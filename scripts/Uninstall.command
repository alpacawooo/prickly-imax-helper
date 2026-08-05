#!/bin/zsh
set -euo pipefail

USER_HOME=${HOME:A}
APP_HOME=${PRICKLY_IMAX_HOME:-${USER_HOME}/.prickly-imax-helper}
APP_HOME=${APP_HOME:A}
PLIST_PATH=${HOME}/Library/LaunchAgents/ai.prickly.imax-helper.plist
CLI_LINK=${HOME}/.local/bin/prickly-imax
LABEL=ai.prickly.imax-helper

if [[ ${APP_HOME} != "${USER_HOME}/"* ]]; then
  print -u2 "삭제 경로는 현재 사용자 홈의 하위 폴더여야 합니다: ${APP_HOME}"
  exit 1
fi

print "다음 항목을 제거합니다:"
print -r -- "- 감시 서비스: ${PLIST_PATH}"
print -r -- "- 설치된 실행 파일: ${APP_HOME}/app, ${APP_HOME}/venv"
print -r -- "- 명령 링크: ${CLI_LINK}"
print ""
if [[ ${PRICKLY_UNINSTALL_KEEP_DATA:-0} == 1 ]]; then
  answer=n
else
  read "answer?설정·로그·CGV 로그인 프로필까지 모두 삭제할까요? [y/N] "
fi

/bin/launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
[[ ! -f "${PLIST_PATH}" ]] || /bin/rm "${PLIST_PATH}"
[[ ! -L "${CLI_LINK}" ]] || /bin/rm "${CLI_LINK}"

if [[ ${answer:l} == y || ${answer:l} == yes ]]; then
  if [[ "${APP_HOME}" != "${USER_HOME}/.prickly-imax-helper" ]]; then
    print -u2 "안전을 위해 기본 설치 경로가 아닌 전체 삭제는 자동 실행하지 않습니다: ${APP_HOME}"
    exit 2
  fi
  /bin/rm -rf "${USER_HOME}/.prickly-imax-helper"
  print "설정, 로그, 전용 CGV 로그인 프로필을 모두 삭제했습니다. 복구할 수 없습니다."
else
  /bin/rm -rf "${APP_HOME}/app" "${APP_HOME}/venv"
  print "프로그램만 제거했습니다. 설정과 CGV 로그인 프로필은 ${APP_HOME}에 보존했습니다."
fi
