#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=${0:A:h}
REPO_DIR=${SCRIPT_DIR:h}
USER_HOME=${HOME:A}
APP_HOME=${PRICKLY_IMAX_HOME:-${USER_HOME}/.prickly-imax-helper}
APP_HOME=${APP_HOME:A}
APP_VERSION=0.1.0
APP_DIR=${APP_HOME}/app/${APP_VERSION}
VENV_DIR=${APP_HOME}/venv
LABEL=ai.prickly.imax-helper
DRY_RUN=${PRICKLY_INSTALL_DRY_RUN:-0}
if [[ ${DRY_RUN} == 1 ]]; then
  PLIST_PATH=${APP_HOME}/ai.prickly.imax-helper.plist
else
  PLIST_PATH=${HOME}/Library/LaunchAgents/ai.prickly.imax-helper.plist
fi
UV_VERSION=0.11.15
MANAGED_PYTHON_VERSION=3.12.12

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
mkdir -p "${APP_HOME}" "${APP_HOME}/logs" "${HOME}/Library/LaunchAgents"
chmod 700 "${APP_HOME}"
if [[ ${DRY_RUN} != 1 ]]; then
  /bin/launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
fi
RUNTIME_TARGET=${APP_DIR}/runtime
if [[ -e ${RUNTIME_TARGET} ]]; then
  /bin/rm -rf -- "${RUNTIME_TARGET}"
fi
/usr/bin/ditto "${REPO_DIR}/runtime" "${APP_DIR}/runtime"
/bin/cp "${REPO_DIR}/pyproject.toml" "${APP_DIR}/pyproject.toml"
/bin/cp "${REPO_DIR}/uv.lock" "${APP_DIR}/uv.lock"

case $(uname -m) in
  arm64)
    UV_TARGET=aarch64-apple-darwin
    UV_SHA256=7e5b336108f8576eda1939920ca0a805b4a9a3c3d3eb2f6140e38b7092fbe4f3
    ;;
  x86_64)
    UV_TARGET=x86_64-apple-darwin
    UV_SHA256=42bca7cc879d117ed7139a0e26de8cab0b6f033ad439a32144f324d1f8580d8c
    ;;
  *)
    print -u2 "지원하지 않는 Mac 아키텍처입니다: $(uname -m)"
    exit 1
    ;;
esac
BOOTSTRAP_DIR=${APP_HOME}/bootstrap/uv-${UV_VERSION}
UV_ARCHIVE=${BOOTSTRAP_DIR}/uv-${UV_TARGET}.tar.gz
UV_BIN=${BOOTSTRAP_DIR}/uv-${UV_TARGET}/uv
mkdir -p "${BOOTSTRAP_DIR}"
if [[ ! -x ${UV_BIN} ]]; then
  print "검증된 관리형 Python 실행기를 준비합니다."
  /usr/bin/curl --proto '=https' --tlsv1.2 --retry 3 -fsSL \
    "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${UV_TARGET}.tar.gz" \
    -o "${UV_ARCHIVE}"
  print "${UV_SHA256}  ${UV_ARCHIVE}" | /usr/bin/shasum -a 256 -c -
  /usr/bin/tar -xzf "${UV_ARCHIVE}" -C "${BOOTSTRAP_DIR}"
fi
export UV_PYTHON_INSTALL_DIR=${APP_HOME}/python
export UV_CACHE_DIR=${APP_HOME}/cache/uv
export UV_PROJECT_ENVIRONMENT=${VENV_DIR}
"${UV_BIN}" sync --project "${APP_DIR}" --locked --no-dev --no-install-project \
  --python "${MANAGED_PYTHON_VERSION}" --managed-python --quiet

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
  /bin/launchctl kickstart -k "gui/$(id -u)/${LABEL}"
fi

if [[ ${DRY_RUN} == 1 ]]; then
  print "Prickly IMAX Helper ${APP_VERSION} dry-run 설치가 완료됐습니다: ${VENV_DIR}/bin/prickly-imax"
else
  mkdir -p "${HOME}/.local/bin"
  ln -sfn "${VENV_DIR}/bin/prickly-imax" "${HOME}/.local/bin/prickly-imax"
  print "Prickly IMAX Helper ${APP_VERSION} 설치가 완료됐습니다. 상태 확인: ${HOME}/.local/bin/prickly-imax status"
fi
