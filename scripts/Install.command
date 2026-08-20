#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=${0:A:h}
REPO_DIR=${SCRIPT_DIR:h}
USER_HOME=${HOME:A}
APP_HOME=${PRICKLY_IMAX_HOME:-${USER_HOME}/.prickly-imax-helper}
APP_HOME=${APP_HOME:A}
APP_VERSION=0.2.4
APP_DIR=${APP_HOME}/app/${APP_VERSION}
VENV_DIR=${APP_HOME}/venv
RUNTIME_TARGET=${APP_DIR}/runtime
LABEL=ai.prickly.imax-helper
DRY_RUN=${PRICKLY_INSTALL_DRY_RUN:-0}
if [[ ${DRY_RUN} == 1 ]]; then
  PLIST_PATH=${APP_HOME}/ai.prickly.imax-helper.plist
else
  PLIST_PATH=${HOME}/Library/LaunchAgents/ai.prickly.imax-helper.plist
fi
UV_VERSION=0.11.15
MANAGED_PYTHON_VERSION=3.12.12
LAUNCHCTL_BIN=${PRICKLY_LAUNCHCTL_BIN:-/bin/launchctl}
CURL_BIN=${PRICKLY_CURL_BIN:-/usr/bin/curl}
SLEEP_BIN=${PRICKLY_SLEEP_BIN:-/bin/sleep}
EXIT_TIMEOUT_SECONDS=${PRICKLY_EXIT_TIMEOUT_SECONDS:-60}
MAINTENANCE_PYTHON=${PRICKLY_MAINTENANCE_PYTHON:-${VENV_DIR}/bin/python}
MAINTENANCE_TOKEN=""
INSTALLER_LOCK_DIR=${APP_HOME}/state/installer.lock
INSTALLER_LOCK_OWNER_FILE=${INSTALLER_LOCK_DIR}/owner
INSTALLER_LOCK_TOKEN=""
INSTALLER_GATE_PATH=${APP_HOME}/state/installer.gate
INSTALLER_GATE_FD=""
INSTALLER_LOCK_CANDIDATE_DIR=""
INSTALLER_LOCK_CANDIDATE_TOKEN=""
INSTALLER_KILL_BIN=${PRICKLY_INSTALLER_KILL_BIN:-/bin/kill}
INSTALLER_PS_BIN=${PRICKLY_INSTALLER_PS_BIN:-/bin/ps}
INSTALLER_UUIDGEN_BIN=${PRICKLY_INSTALLER_UUIDGEN_BIN:-/usr/bin/uuidgen}

read_installer_lock_owner() {
  local lock_dir=${1:-${INSTALLER_LOCK_DIR}}
  local owner_file=${lock_dir}/owner contents
  local -a lines
  if [[ ! -f ${owner_file} ]]; then
    print -u2 "기존 설치 잠금의 소유자 정보가 없어 안전하게 계속할 수 없습니다."
    return 1
  fi
  if ! contents=$(/bin/cat -- "${owner_file}"); then
    print -u2 "기존 설치 잠금의 소유자 정보를 읽지 못했습니다."
    return 1
  fi
  lines=("${(@f)contents}")
  if (( ${#lines} != 2 )) || [[ ${lines[1]} != <-> ]] || (( lines[1] <= 0 )); then
    print -u2 "기존 설치 잠금의 소유자 정보가 잘못되어 안전하게 계속할 수 없습니다."
    return 1
  fi
  if ! print -r -- "${lines[2]}" | /usr/bin/grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'; then
    print -u2 "기존 설치 잠금의 소유자 토큰이 잘못되어 안전하게 계속할 수 없습니다."
    return 1
  fi
  INSTALLER_LOCK_OWNER_PID=${lines[1]}
  INSTALLER_LOCK_OWNER_TOKEN=${lines[2]}
}

acquire_installer_gate() {
  if [[ -n ${INSTALLER_GATE_FD} ]]; then
    print -u2 "이 설치 프로세스가 이미 운영체제 잠금을 소유하고 있습니다."
    return 1
  fi
  if ! zmodload zsh/system; then
    print -u2 "설치 잠금에 필요한 zsh 시스템 모듈을 준비하지 못했습니다."
    return 1
  fi
  if ! : >> "${INSTALLER_GATE_PATH}"; then
    print -u2 "운영체제 설치 잠금 파일을 준비하지 못했습니다."
    return 1
  fi
  if ! zsystem flock -t 0 -f INSTALLER_GATE_FD "${INSTALLER_GATE_PATH}"; then
    INSTALLER_GATE_FD=""
    print -u2 "다른 설치 프로세스가 진행 중이라 중단합니다."
    return 1
  fi
}

release_installer_gate() {
  if [[ -z ${INSTALLER_GATE_FD} ]]; then
    return 0
  fi
  local gate_fd=${INSTALLER_GATE_FD}
  INSTALLER_GATE_FD=""
  if ! zsystem flock -u "${gate_fd}"; then
    print -u2 "운영체제 설치 잠금을 해제하지 못했습니다."
    return 1
  fi
}

restore_moved_installer_lock() {
  local moved_path=$1
  if [[ -e ${INSTALLER_LOCK_DIR} || -L ${INSTALLER_LOCK_DIR} ]]; then
    print -u2 "변경된 설치 잠금을 원위치로 복원할 수 없어 중단합니다."
    return 1
  fi
  if ! /bin/mv "${moved_path}" "${INSTALLER_LOCK_DIR}"; then
    print -u2 "변경된 설치 잠금 복원에 실패해 중단합니다."
    return 1
  fi
}

write_installer_lock_owner() {
  local lock_dir=$1 owner_pid=$2 owner_token=$3
  printf '%s\n%s\n' "${owner_pid}" "${owner_token}" > "${lock_dir}/owner"
}

cleanup_current_installer_candidate() {
  local expected_dir
  if [[ -z ${INSTALLER_LOCK_CANDIDATE_DIR} ]]; then
    return 0
  fi
  expected_dir=${APP_HOME}/state/installer.lock.candidate.$$.${INSTALLER_LOCK_CANDIDATE_TOKEN}
  if [[ ${INSTALLER_LOCK_CANDIDATE_DIR} != ${expected_dir} ]]; then
    print -u2 "임시 설치 잠금 경로의 소유권을 확인할 수 없어 정리하지 않습니다."
    return 1
  fi
  if [[ -e ${INSTALLER_LOCK_CANDIDATE_DIR}/owner || -L ${INSTALLER_LOCK_CANDIDATE_DIR}/owner ]]; then
    /bin/rm -f -- "${INSTALLER_LOCK_CANDIDATE_DIR}/owner" || return 1
  fi
  if [[ -d ${INSTALLER_LOCK_CANDIDATE_DIR} ]]; then
    /bin/rmdir "${INSTALLER_LOCK_CANDIDATE_DIR}" || return 1
  elif [[ -e ${INSTALLER_LOCK_CANDIDATE_DIR} || -L ${INSTALLER_LOCK_CANDIDATE_DIR} ]]; then
    print -u2 "임시 설치 잠금 경로가 폴더가 아니어 정리하지 않습니다."
    return 1
  fi
  INSTALLER_LOCK_CANDIDATE_DIR=""
  INSTALLER_LOCK_CANDIDATE_TOKEN=""
}

prepare_installer_lock_candidate() {
  local candidate_token=$1
  INSTALLER_LOCK_CANDIDATE_TOKEN=${candidate_token}
  INSTALLER_LOCK_CANDIDATE_DIR=${APP_HOME}/state/installer.lock.candidate.$$.${candidate_token}
  if ! /bin/mkdir "${INSTALLER_LOCK_CANDIDATE_DIR}"; then
    print -u2 "임시 설치 잠금 폴더를 만들지 못했습니다."
    return 1
  fi
  if ! write_installer_lock_owner "${INSTALLER_LOCK_CANDIDATE_DIR}" "$$" "${candidate_token}"; then
    print -u2 "임시 설치 잠금 소유자 정보를 완전하게 기록하지 못했습니다."
    cleanup_current_installer_candidate || true
    return 1
  fi
  if ! read_installer_lock_owner "${INSTALLER_LOCK_CANDIDATE_DIR}"; then
    cleanup_current_installer_candidate || true
    return 1
  fi
  if [[ ${INSTALLER_LOCK_OWNER_PID} != $$ || ${INSTALLER_LOCK_OWNER_TOKEN} != ${candidate_token} ]]; then
    print -u2 "임시 설치 잠금 소유자 정보가 예상과 달라 중단합니다."
    cleanup_current_installer_candidate || true
    return 1
  fi
}

publish_installer_lock_candidate() {
  if [[ -z ${INSTALLER_GATE_FD} || -z ${INSTALLER_LOCK_CANDIDATE_DIR} ]]; then
    print -u2 "임시 설치 잠금을 게시할 소유권이 없습니다."
    return 1
  fi
  if [[ -e ${INSTALLER_LOCK_DIR} || -L ${INSTALLER_LOCK_DIR} ]]; then
    print -u2 "기존 설치 잠금이 있어 임시 잠금을 게시하지 않습니다."
    return 1
  fi
  if ! /bin/mv "${INSTALLER_LOCK_CANDIDATE_DIR}" "${INSTALLER_LOCK_DIR}"; then
    print -u2 "완성된 설치 잠금을 원자적으로 게시하지 못했습니다."
    return 1
  fi
  INSTALLER_LOCK_CANDIDATE_DIR=""
}

query_installer_owner_state() {
  local owner_pid=$1 output rc normalized
  if "${INSTALLER_KILL_BIN}" -0 "${owner_pid}" >/dev/null 2>&1; then
    REPLY=live
    return 0
  fi
  if output=$("${INSTALLER_PS_BIN}" -p "${owner_pid}" -o pid= 2>/dev/null); then
    normalized=${output//[[:space:]]/}
    if [[ ${normalized} == "${owner_pid}" ]]; then
      REPLY=live
      return 0
    fi
    print -u2 "설치 잠금 소유자 프로세스 상태가 모호해 중단합니다."
    return 1
  else
    rc=$?
  fi
  if (( rc == 1 )) && [[ -z ${output} ]]; then
    REPLY=dead
    return 0
  fi
  print -u2 "설치 잠금 소유자 프로세스를 안전하게 확인하지 못해 중단합니다."
  return 1
}

cleanup_abandoned_installer_candidates() {
  setopt local_options null_glob
  local candidate basename candidate_pid candidate_token
  local -a candidates
  candidates=("${APP_HOME}/state"/installer.lock.candidate.*(N/))
  if (( ${#candidates} > 32 )); then
    print -u2 "중단된 임시 설치 잠금이 너무 많아 자동 복구를 중단합니다."
    return 1
  fi
  for candidate in "${candidates[@]}"; do
    basename=${candidate:t}
    if [[ ${basename} =~ '^installer\.lock\.candidate\.([1-9][0-9]*)\.([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})$' ]]; then
      candidate_pid=${match[1]}
      candidate_token=${match[2]}
    else
      print -u2 "중단된 임시 설치 잠금 경로가 모호해 자동으로 정리하지 않습니다."
      return 1
    fi
    if ! query_installer_owner_state "${candidate_pid}"; then
      return 1
    fi
    if [[ ${REPLY} != dead ]]; then
      print -u2 "임시 설치 잠금의 소유자가 live일 수 있어 정리하지 않습니다."
      return 1
    fi
    if read_installer_lock_owner "${candidate}" 2>/dev/null; then
      if [[ ${INSTALLER_LOCK_OWNER_PID} != ${candidate_pid} || ${INSTALLER_LOCK_OWNER_TOKEN} != ${candidate_token} ]]; then
        print -u2 "임시 설치 잠금의 경로와 소유자 정보가 달라 정리하지 않습니다."
        return 1
      fi
    fi
    if [[ -e ${candidate}/owner || -L ${candidate}/owner ]]; then
      /bin/rm -f -- "${candidate}/owner" || return 1
    fi
    if ! /bin/rmdir "${candidate}"; then
      print -u2 "중단된 임시 설치 잠금에 예상하지 못한 내용이 있어 정리하지 않습니다."
      return 1
    fi
  done
}

acquire_installer_lock() {
  local candidate_token stale_path observed_pid observed_token
  local -a stale_entries
  if [[ -n ${INSTALLER_LOCK_TOKEN} ]]; then
    print -u2 "이 설치 프로세스가 이미 잠금을 소유하고 있습니다."
    return 1
  fi
  if ! mkdir -p "${APP_HOME}/state"; then
    print -u2 "설치 잠금 폴더를 준비하지 못했습니다."
    return 1
  fi
  if ! acquire_installer_gate; then
    return 1
  fi
  if ! cleanup_abandoned_installer_candidates; then
    release_installer_gate || true
    return 1
  fi
  if ! candidate_token=$("${INSTALLER_UUIDGEN_BIN}"); then
    print -u2 "설치 잠금 소유자 토큰을 만들지 못했습니다."
    release_installer_gate || true
    return 1
  fi
  if ! print -r -- "${candidate_token}" | /usr/bin/grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'; then
    print -u2 "설치 잠금 소유자 토큰이 잘못되어 중단합니다."
    release_installer_gate || true
    return 1
  fi
  if ! prepare_installer_lock_candidate "${candidate_token}"; then
    release_installer_gate || true
    return 1
  fi
  if [[ ! -e ${INSTALLER_LOCK_DIR} && ! -L ${INSTALLER_LOCK_DIR} ]]; then
    if ! publish_installer_lock_candidate; then
      cleanup_current_installer_candidate || true
      release_installer_gate || true
      return 1
    fi
    INSTALLER_LOCK_TOKEN=${candidate_token}
    INSTALLER_LOCK_CANDIDATE_TOKEN=""
    return 0
  fi
  if [[ ! -d ${INSTALLER_LOCK_DIR} ]]; then
    print -u2 "설치 잠금 경로가 모호해 안전하게 계속할 수 없습니다."
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  if ! read_installer_lock_owner; then
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  observed_pid=${INSTALLER_LOCK_OWNER_PID}
  observed_token=${INSTALLER_LOCK_OWNER_TOKEN}
  if ! query_installer_owner_state "${observed_pid}"; then
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  if [[ ${REPLY} == live ]]; then
    print -u2 "다른 설치 프로세스가 진행 중이라 중단합니다."
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  stale_path=${INSTALLER_LOCK_DIR}.stale.${candidate_token}
  if ! /bin/mv "${INSTALLER_LOCK_DIR}" "${stale_path}" 2>/dev/null; then
    print -u2 "검증한 설치 잠금을 독점적으로 이동하지 못해 중단합니다."
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  if ! read_installer_lock_owner "${stale_path}"; then
    restore_moved_installer_lock "${stale_path}" || true
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  if [[ ${INSTALLER_LOCK_OWNER_PID} != ${observed_pid} || ${INSTALLER_LOCK_OWNER_TOKEN} != ${observed_token} ]]; then
    print -u2 "이동된 설치 잠금의 소유자가 최초 검증과 달라 중단합니다."
    restore_moved_installer_lock "${stale_path}" || true
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  if ! query_installer_owner_state "${INSTALLER_LOCK_OWNER_PID}" || [[ ${REPLY} != dead ]]; then
    print -u2 "이동된 설치 잠금의 소유자가 더 이상 dead로 확인되지 않아 중단합니다."
    restore_moved_installer_lock "${stale_path}" || true
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  stale_entries=("${stale_path}"/*(N) "${stale_path}"/.[!.]*(N) "${stale_path}"/..?*(N))
  if (( ${#stale_entries} != 1 )) || [[ ${stale_entries[1]} != ${stale_path}/owner || ! -f ${stale_entries[1]} ]]; then
    print -u2 "중단된 설치 잠금에 예상하지 못한 내용이 있어 중단합니다."
    restore_moved_installer_lock "${stale_path}" || true
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  if ! /bin/rm -f -- "${stale_path}/owner" || ! /bin/rmdir "${stale_path}"; then
    print -u2 "중단된 설치 잠금을 안전하게 정리하지 못했습니다."
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  if ! publish_installer_lock_candidate; then
    cleanup_current_installer_candidate || true
    release_installer_gate || true
    return 1
  fi
  INSTALLER_LOCK_TOKEN=${candidate_token}
  INSTALLER_LOCK_CANDIDATE_TOKEN=""
}

release_installer_lock() {
  local released_path release_status=0
  if [[ -z ${INSTALLER_LOCK_TOKEN} ]]; then
    cleanup_current_installer_candidate || release_status=1
    release_installer_gate || release_status=1
    return ${release_status}
  fi
  if ! read_installer_lock_owner; then
    release_installer_gate || true
    return 1
  fi
  if [[ ${INSTALLER_LOCK_OWNER_PID} != $$ || ${INSTALLER_LOCK_OWNER_TOKEN} != ${INSTALLER_LOCK_TOKEN} ]]; then
    print -u2 "설치 잠금 소유권이 달라 자동으로 해제하지 않습니다."
    release_installer_gate || true
    return 1
  fi
  released_path=${INSTALLER_LOCK_DIR}.released.${INSTALLER_LOCK_TOKEN}
  if ! /bin/mv "${INSTALLER_LOCK_DIR}" "${released_path}"; then
    print -u2 "설치 잠금을 안전하게 해제하지 못했습니다."
    release_installer_gate || true
    return 1
  fi
  INSTALLER_LOCK_TOKEN=""
  /bin/rm -f -- "${released_path}/owner" || release_status=1
  /bin/rmdir "${released_path}" || release_status=1
  release_installer_gate || release_status=1
  return ${release_status}
}

installer_lock_exit() {
  local status=$?
  trap - EXIT
  if ! release_installer_lock; then
    (( status == 0 )) && status=1
  fi
  exit "${status}"
}

run_update_maintenance() {
  PYTHONPATH="${REPO_DIR}/runtime${PYTHONPATH:+:${PYTHONPATH}}" \
    "${MAINTENANCE_PYTHON}" -m prickly_imax_helper.maintenance --home "${APP_HOME}" "$@"
}

parse_old_status() {
  local payload=$1 mode=$2
  print -rn -- "${payload}" | run_update_maintenance parse-json --mode "${mode}"
}

begin_update_maintenance() {
  if [[ ! -x ${MAINTENANCE_PYTHON} ]]; then
    print -u2 "기존 관리형 Python을 찾을 수 없어 안전한 업데이트 장벽을 만들 수 없습니다."
    return 1
  fi
  local -a maintenance_command
  if [[ -x ${VENV_DIR}/bin/prickly-imax ]]; then
    maintenance_command=(arm --launcher "${VENV_DIR}/bin/prickly-imax" --runtime "${REPO_DIR}/runtime")
  else
    maintenance_command=(begin)
  fi
  if ! MAINTENANCE_TOKEN=$(run_update_maintenance "${maintenance_command[@]}"); then
    print -u2 "업데이트 장벽을 만들지 못했습니다. 이전 업데이트가 중단됐다면 지원 절차로 확인해 주세요."
    return 1
  fi
}

existing_install_needs_maintenance() {
  [[ -x ${VENV_DIR}/bin/prickly-imax || -e ${RUNTIME_TARGET} ]]
}

query_launchctl_state() {
  local output rc
  output=$("${LAUNCHCTL_BIN}" print "gui/$(id -u)/${LABEL}" 2>&1)
  rc=$?
  if (( rc == 0 )); then
    if print -r -- "${output}" | /usr/bin/grep -Eq '^[[:space:]]*pid = [1-9][0-9]*'; then
      REPLY=running
    else
      REPLY=stopped
    fi
    return 0
  fi
  if (( rc == 113 )); then
    REPLY=missing
    return 0
  fi
  print -u2 "LaunchAgent 상태를 확인하지 못해 업데이트를 중단합니다: ${output}"
  return 1
}

cooperative_stop_existing_monitor() {
  local old_cli=$1 old_status old_stop_status deadline bootout_rc
  if [[ -x ${old_cli} ]]; then
    if ! old_status=$("${old_cli}" --home "${APP_HOME}" status); then
      print -u2 "기존 설치 상태를 확인하지 못해 업데이트를 중단합니다."
      return 1
    fi
    if ! parse_old_status "${old_status}" status >/dev/null; then
      print -u2 "기존 감시 상태를 안전하게 증명하지 못해 업데이트를 중단합니다."
      return 1
    fi
    if ! old_stop_status=$("${old_cli}" --home "${APP_HOME}" stop); then
      print -u2 "기존 감시에 중지 요청을 전달하지 못해 업데이트를 중단합니다."
      return 1
    fi
    if ! parse_old_status "${old_stop_status}" stop >/dev/null; then
      print -u2 "중지 결과를 안전하게 증명하지 못해 업데이트를 중단합니다."
      return 1
    fi
    deadline=$((SECONDS + EXIT_TIMEOUT_SECONDS))
    while true; do
      if ! query_launchctl_state; then return 1; fi
      [[ ${REPLY} == stopped || ${REPLY} == missing ]] && break
      if (( SECONDS >= deadline )); then
        print -u2 "상주 감시가 ${EXIT_TIMEOUT_SECONDS}초 안에 종료되지 않아 업데이트를 중단합니다."
        return 1
      fi
      "${SLEEP_BIN}" 0.25 || return 1
    done
  else
    if ! query_launchctl_state; then return 1; fi
    if [[ ${REPLY} != missing ]]; then
      print -u2 "기존 감시 서비스의 CLI를 찾을 수 없어 상태를 안전하게 확인하지 못했습니다. 업데이트를 중단합니다."
      return 1
    fi
  fi
  "${LAUNCHCTL_BIN}" bootout "gui/$(id -u)/${LABEL}"
  bootout_rc=$?
  if (( bootout_rc != 0 && bootout_rc != 3 )); then
    print -u2 "LaunchAgent를 안전하게 해제하지 못해 업데이트를 중단합니다."
    return 1
  fi
}

prove_service_absent_for_bootstrap() {
  if ! query_launchctl_state; then
    return 1
  fi
  if [[ ${REPLY} != missing ]]; then
    print -u2 "관리형 Python 준비 전에 기존 LaunchAgent가 없음을 증명하지 못했습니다. 업데이트를 중단합니다."
    return 1
  fi
}

prepare_pinned_uv() {
  local machine
  if ! machine=$(uname -m); then
    print -u2 "Mac 아키텍처를 확인하지 못해 설치를 중단합니다."
    return 1
  fi
  case ${machine} in
    arm64)
      UV_TARGET=aarch64-apple-darwin
      UV_SHA256=7e5b336108f8576eda1939920ca0a805b4a9a3c3d3eb2f6140e38b7092fbe4f3
      ;;
    x86_64)
      UV_TARGET=x86_64-apple-darwin
      UV_SHA256=42bca7cc879d117ed7139a0e26de8cab0b6f033ad439a32144f324d1f8580d8c
      ;;
    *)
      print -u2 "지원하지 않는 Mac 아키텍처입니다: ${machine}"
      return 1
      ;;
  esac
  BOOTSTRAP_DIR=${APP_HOME}/bootstrap/uv-${UV_VERSION}
  UV_ARCHIVE=${BOOTSTRAP_DIR}/uv-${UV_TARGET}.tar.gz
  UV_BIN=${BOOTSTRAP_DIR}/uv-${UV_TARGET}/uv
  if ! mkdir -p "${BOOTSTRAP_DIR}"; then
    print -u2 "uv 부트스트랩 폴더를 준비하지 못해 설치를 중단합니다."
    return 1
  fi
  if [[ ! -x ${UV_BIN} ]]; then
    print "검증된 관리형 Python 실행기를 준비합니다."
    if ! "${CURL_BIN}" --proto '=https' --tlsv1.2 --retry 3 -fsSL \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${UV_TARGET}.tar.gz" \
      -o "${UV_ARCHIVE}"; then
      print -u2 "uv 다운로드에 실패해 설치를 중단합니다."
      return 1
    fi
    if ! print "${UV_SHA256}  ${UV_ARCHIVE}" | /usr/bin/shasum -a 256 -c -; then
      print -u2 "uv 체크섬이 일치하지 않아 설치를 중단합니다."
      return 1
    fi
    if ! /usr/bin/tar -xzf "${UV_ARCHIVE}" -C "${BOOTSTRAP_DIR}"; then
      print -u2 "uv 압축을 풀지 못해 설치를 중단합니다."
      return 1
    fi
  fi
  if [[ ! -x ${UV_BIN} ]]; then
    print -u2 "검증된 uv 실행기를 확인하지 못해 설치를 중단합니다."
    return 1
  fi
}

prepare_managed_environment() {
  prepare_pinned_uv || return 1
  export UV_PYTHON_INSTALL_DIR=${APP_HOME}/python
  export UV_CACHE_DIR=${APP_HOME}/cache/uv
  export UV_PROJECT_ENVIRONMENT=${VENV_DIR}
  if ! "${UV_BIN}" sync --project "${REPO_DIR}" --locked --no-dev --no-install-project \
    --python "${MANAGED_PYTHON_VERSION}" --managed-python --quiet; then
    print -u2 "잠긴 Python 실행 환경 설치에 실패했습니다."
    return 1
  fi
}

prepare_runtime_replacement() {
  if [[ ( -e ${VENV_DIR}/bin/prickly-imax || -L ${VENV_DIR}/bin/prickly-imax ) && ! -x ${MAINTENANCE_PYTHON} ]]; then
    print -u2 "기존 실행기가 있지만 관리형 Python이 없어 활성 설치를 안전하게 갱신할 수 없습니다."
    return 1
  fi
  if [[ -x ${MAINTENANCE_PYTHON} ]]; then
    begin_update_maintenance || return 1
    cooperative_stop_existing_monitor "${VENV_DIR}/bin/prickly-imax" || return 1
    prepare_managed_environment || return 1
  else
    prove_service_absent_for_bootstrap || return 1
    prepare_managed_environment || return 1
    begin_update_maintenance || return 1
    cooperative_stop_existing_monitor "${VENV_DIR}/bin/prickly-imax" || return 1
  fi
  run_update_maintenance replace-runtime --token "${MAINTENANCE_TOKEN}" \
    --source "${REPO_DIR}/runtime" --target "${RUNTIME_TARGET}" || return 1
}

dry_run_would_mutate_existing_install() {
  [[ ${DRY_RUN} == 1 && ( -e ${APP_DIR}/runtime || -e ${VENV_DIR} ) ]]
}

if [[ ${PRICKLY_INSTALL_SAFETY_LIBRARY:-0} == 1 ]]; then
  return 0
fi

if dry_run_would_mutate_existing_install; then
  print "Dry-run: 기존 runtime/venv는 변경하지 않습니다."
  exit 0
fi

if [[ $(uname -s) != Darwin ]]; then
  print -u2 "이 설치기는 macOS 전용입니다."
  exit 1
fi
if [[ ${APP_HOME} != "${USER_HOME}/"* ]]; then
  print -u2 "설치 경로는 현재 사용자 홈의 하위 폴더여야 합니다: ${APP_HOME}"
  exit 1
fi
if [[ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  print -u2 "Google Chrome을 먼저 설치해 주세요."
  exit 1
fi
trap 'installer_lock_exit' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
if ! acquire_installer_lock; then
  exit 1
fi
mkdir -p "${APP_HOME}" "${APP_HOME}/logs" "${HOME}/Library/LaunchAgents" || exit 1
chmod 700 "${APP_HOME}" || exit 1
if ! prepare_runtime_replacement; then
  exit 1
fi
/bin/cp "${REPO_DIR}/pyproject.toml" "${APP_DIR}/pyproject.toml"
/bin/cp "${REPO_DIR}/uv.lock" "${APP_DIR}/uv.lock"

"${VENV_DIR}/bin/python" - "${VENV_DIR}/bin/prickly-imax" "${APP_DIR}/runtime" <<'PY'
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
runtime = sys.argv[2]
python = sys.executable
target.write_text(
    f"#!{python}\n"
    "import sys\n"
    f"sys.path.insert(0, {runtime!r})\n"
    "from prickly_imax_helper.cli import main\n"
    "raise SystemExit(main())\n",
    encoding="utf-8",
)
os.chmod(target, 0o755)
PY

"${VENV_DIR}/bin/python" - "${PLIST_PATH}" "${VENV_DIR}/bin/prickly-imax" "${APP_HOME}" <<'PY'
import plistlib
import sys
from pathlib import Path

target = Path(sys.argv[1])
launcher = sys.argv[2]
home = sys.argv[3]
payload = {
    "Label": "ai.prickly.imax-helper",
    "ProgramArguments": [launcher, "--home", home, "run"],
    "EnvironmentVariables": {"PRICKLY_IMAX_HOME": home},
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ProcessType": "Background",
    "StandardOutPath": str(Path(home) / "logs" / "launchd.out.log"),
    "StandardErrorPath": str(Path(home) / "logs" / "launchd.err.log"),
}
with target.open("wb") as stream:
    plistlib.dump(payload, stream, sort_keys=False)
PY
chmod 600 "${PLIST_PATH}"
/usr/bin/plutil -lint "${PLIST_PATH}" >/dev/null

if [[ ${DRY_RUN} == 1 ]]; then
  print "Dry-run: 설정 페이지와 LaunchAgent 시작을 생략합니다."
elif [[ ! -f "${APP_HOME}/config.json" ]]; then
  print "설정 페이지를 엽니다. CGV 로그인과 자동 예매 조건을 직접 확인해 주세요."
  "${VENV_DIR}/bin/prickly-imax" --home "${APP_HOME}" setup
else
  print "기존 로컬 설정과 CGV 로그인 프로필을 유지합니다."
fi

if [[ ${DRY_RUN} != 1 ]]; then
  print "좌석과 결제를 누르지 않는 연결 검사를 실행합니다."
  STOP_REQUEST=${APP_HOME}/state/stop-requested
  STOP_REQUEST_BACKUP=${APP_HOME}/state/stop-requested.install-backup
  /bin/rm -f -- "${STOP_REQUEST_BACKUP}"
  if [[ -f ${STOP_REQUEST} ]]; then
    /bin/mv -- "${STOP_REQUEST}" "${STOP_REQUEST_BACKUP}"
  fi
  if ! "${VENV_DIR}/bin/prickly-imax" --home "${APP_HOME}" dry-run; then
    if [[ -f ${STOP_REQUEST_BACKUP} ]]; then
      /bin/mv -- "${STOP_REQUEST_BACKUP}" "${STOP_REQUEST}"
    fi
    exit 1
  fi
  /bin/rm -f -- "${STOP_REQUEST_BACKUP}"
fi

if [[ ${DRY_RUN} != 1 ]]; then
  /bin/launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}"
  if [[ -n ${MAINTENANCE_TOKEN} ]]; then
    run_update_maintenance end --token "${MAINTENANCE_TOKEN}"
    MAINTENANCE_TOKEN=""
  fi
  /bin/launchctl kickstart -p "gui/$(id -u)/${LABEL}"
fi

if [[ ${DRY_RUN} == 1 ]]; then
  if [[ -n ${MAINTENANCE_TOKEN} ]]; then
    run_update_maintenance end --token "${MAINTENANCE_TOKEN}"
    MAINTENANCE_TOKEN=""
  fi
  print "Prickly IMAX Helper ${APP_VERSION} dry-run 설치가 완료됐습니다: ${VENV_DIR}/bin/prickly-imax"
else
  mkdir -p "${HOME}/.local/bin"
  ln -sfn "${VENV_DIR}/bin/prickly-imax" "${HOME}/.local/bin/prickly-imax"
  print "Prickly IMAX Helper ${APP_VERSION} 설치가 완료됐습니다. 상태 확인: ${HOME}/.local/bin/prickly-imax status"
fi
