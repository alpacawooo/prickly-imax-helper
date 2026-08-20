# Prickly IMAX Helper 0.2.4

0.2.4 is the immutable release version for the login-required restart and safe-update hardening port. Download only the operating-system archives attached to this GitHub Release and verify their SHA-256 values before installation.

- macOS `prickly-imax-helper-0.2.4.tar.gz`: `18a37b78f05a40118df73db7d04d61e4d25de1840a8fd6e70a2de11a3ca1eb64`
- Windows `prickly-imax-helper-0.2.4.zip`: `432caab792f69f2ccc3ea57be748c22755dd6a3df2c6356f1224d14a75bff3d2`

## 0.2.3 결제 팝업 안전 유지

- 0.2.3에서 추가된 `결제 전 확인해 주세요` 팝업 처리를 그대로 유지합니다. 팝업 내부의 정확한 활성 `결제하기` 버튼 하나만 허용하고, 팝업 상태가 중복·지연·불명확하면 결제 전에 중단합니다.
- 결제 팝업 유무, 지연 표시, 팝업 밖 동명 버튼, 비활성 버튼, 관람권 화면 지연과 거리 표기가 함께 있는 실제 극장 행 선택을 회귀 검사합니다.
- 고객 배포 파일에는 실제 제출 경로를 부르는 QA probe를 포함하지 않습니다.

## 로그인 필요 상태와 시작 안전

- `login_required`에서 `start`를 실행하면 상주 감시를 다시 요청할 수 있습니다. 제출 이후 결과가 확정되지 않은 상태나 검토가 필요한 종료 상태는 계속 fail-closed입니다.
- 동시에 여러 `start`가 들어와도 서비스 제어 잠금과 실제 `monitor.lock` 확인 안에서 하나의 시작 요청만 진행합니다.
- 업데이트 유지보수 장벽이 존재하면 CLI와 직접 서비스 실행 모두 시작하지 않습니다.
- macOS의 일반 설치·업데이트·시작 경로는 기존 프로세스를 강제로 재시작하는 `launchctl kickstart -k`를 사용하지 않습니다.

## 원자적 설치·업데이트

- macOS와 Windows 설치기는 관리형 Python, 공유 가상환경, 런타임 또는 launcher를 바꾸기 전에 프로세스 간 installer lock을 획득합니다.
- lock 메타데이터는 sibling 임시 디렉터리에 완전히 기록한 뒤 원자적으로 게시합니다. stale lock 회수 시 이동한 소유자의 PID와 임의 토큰을 다시 검증하며, 다른 live owner나 모호한 생존 상태를 만나면 공유 파일을 바꾸지 않습니다.
- 유지보수 장벽은 동일한 Python 서비스 제어 잠금 아래 원자적으로 생성됩니다. 설치기는 기존 monitor의 안전한 종료를 증명하고 `monitor.lock`을 런타임 교체 직전에 다시 확인합니다.
- 새 런타임은 staging에서 완성한 뒤 버전별 최종 경로로 원자 교체합니다. launcher가 없거나 설치가 중간에 끊긴 경우에도 stale 파일 병합이나 중첩 `runtime/runtime`을 만들지 않습니다.
- 첫 설치와 부분 설치는 pinned uv와 관리형 Python을 준비한 뒤 최종 런타임 경로를 커밋합니다. 기존 활성 설치는 installer lock과 유지보수 장벽을 얻기 전에 공유 가상환경을 바꾸지 않습니다.
- 설치기 실패나 비정상 종료로 유지보수 장벽이 남으면 `start`는 계속 차단됩니다. 같은 검증된 0.2.4 설치 파일로 복구를 다시 시도하고 상태 파일을 임의로 삭제하지 마세요.

## 데이터 보존

업데이트는 아래 사용자 데이터를 버전별 코드 교체 대상에서 제외합니다.

- 좌석·상영 조건과 이메일 설정이 든 `config.json`
- CGV 로그인용 `browser-profile/`
- 개인정보를 제거한 상태·감사 로그

기존 프로그램을 먼저 삭제하지 말고, 최종 0.2.4 아티팩트의 SHA-256을 확인한 뒤 운영체제에 맞는 `Update.command` 또는 `Update.ps1`을 실행하세요.

## 알림 호환성

- macOS는 지원되는 신뢰 경로인 `/System/Applications/Mail.app` 또는 `/Applications/Mail.app`에서만 Apple Mail을 찾습니다.
- `doctor`의 `notification_backend`가 실패하면 Mail 앱 위치와 로그인된 발송 계정을 확인하세요. 사용자 입력은 AppleScript 소스에 삽입하지 않고 별도 인자로 전달합니다.
- Windows는 클래식 Outlook 데스크톱만 로컬 이메일 발송 통로로 지원합니다.

## Windows ZIP 검색

PowerShell 안내는 다운로드 폴더와 바탕화면 아래의 하위 폴더를 검색해 가장 최근의 원본 ZIP을 찾습니다. ZIP이 없으면 체크섬을 검사하지 않고 다운로드 안내만 표시합니다. 압축을 푼 폴더가 아니라 압축을 풀지 않은 원본 ZIP이 필요합니다.

## 검증 범위

자동 검증은 겹치는 start, 업데이트 단계별 경합, 부분 설치 복구, macOS 2~3개 프로세스 installer-lock 경합, Windows PowerShell 5.1 harness, lock 게시 중 쓰기 실패, stale owner와 PID/token 불일치, strict JSON, Apple Mail 스크립트 컴파일, 릴리스 버전 정렬을 다룹니다. CI는 pinned uv로 `uv lock --check`를 실행하고 Windows harness와 전체 테스트 전에 PowerShell 5.1을 명시적으로 확인합니다.

실제 CGV 좌석·결제, 실제 브라우저 제출, 실제 이메일 발송, 실제 서비스 변경은 이 포트 작업의 검증 범위에 포함하지 않습니다.
