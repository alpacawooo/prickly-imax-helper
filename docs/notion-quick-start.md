# Prickly IMAX Helper 0.2.1 공개 배포 — 3분 시작

## 먼저 운영체제를 확인하세요

- macOS 또는 Windows 10/11
- Google Chrome
- 본인 CGV 계정
- CGV 계정에 등록된, 선택한 연속 좌석 수와 같은 수의 IMAX 관람권
- macOS: Apple Mail에 로그인된 이메일 계정
- Windows: 클래식 Outlook 데스크톱에 로그인된 이메일 계정

Python이나 개발 도구는 미리 설치하지 않아도 됩니다. 필요한 경우 설치기가 검증된 관리형 Python을 사용자 폴더 안에 준비합니다.

비밀번호와 결제정보는 Prickly AI에 입력하지 않습니다. 전용 Chrome 창에서 사용자가 직접 로그인합니다.

CGV 비밀번호, 관람권 번호, 카드번호, 이메일 비밀번호는 Prickly AI나 설치 페이지에 입력하지 않습니다. Windows의 새 Outlook은 아직 이메일 발송을 지원하지 않습니다. 클래식 Outlook 데스크톱을 사용하세요.

## 1. 설치 — macOS

공개 GitHub 릴리스에서 **macOS 전용 설치 파일 하나만** 다운로드합니다. 저장소 초대나 GitHub 로그인이 필요하지 않습니다.

- [Prickly IMAX Helper 0.2.1 공개 릴리스 전체 보기](https://github.com/alpacawooo/prickly-imax-helper/releases/tag/0.2.1)

- [🍎 macOS 전용 설치 파일 받기](https://github.com/alpacawooo/prickly-imax-helper/releases/download/0.2.1/prickly-imax-helper-0.2.1.tar.gz) — `prickly-imax-helper-0.2.1.tar.gz`
- [macOS 체크섬 보기](https://github.com/alpacawooo/prickly-imax-helper/releases/download/0.2.1/prickly-imax-helper-0.2.1.tar.gz.sha256) — 설치 파일이 공식 배포본인지 확인하는 검증값이며, 별도 설치 파일이 아닙니다.

별도의 `.sha256` 파일은 받지 않아도 됩니다. 아래 명령에 검증된 SHA-256이 고정되어 있습니다. GitHub가 자동으로 표시하는 `Source code (zip)`과 `Source code (tar.gz)`도 설치 파일이 아니므로 다운로드하지 않습니다.

터미널을 열어 이 한 줄을 붙여넣습니다.

```bash
cd "$HOME/Downloads"; f='prickly-imax-helper-0.2.1.tar.gz'; expected='aa8cf1b5d47c64ba9f8940bf7a65fb56d5f78cb53c441770cebed8bed185527b'; actual="$(shasum -a 256 "$f" | awk '{print $1}')"; if [ "$actual" = "$expected" ]; then tar -xzf "$f" && open prickly-imax-helper-0.2.1/scripts/Install.command; else echo '체크섬 불일치: 설치 중단'; fi
```

설정 페이지가 열리면 검증과 압축 해제가 완료된 것입니다. `체크섬 불일치: 설치 중단`이 나오면 설치하지 말고 받은 파일을 삭제합니다. macOS가 처음 실행을 막으면 Finder에서 `Install.command`를 Control-클릭한 뒤 `열기`를 선택합니다.

## 1. 설치 — Windows 10/11

**Windows 전용 설치 파일 하나만** 다운로드합니다.

- [🪟 Windows 10/11 전용 설치 파일 받기](https://github.com/alpacawooo/prickly-imax-helper/releases/download/0.2.1/prickly-imax-helper-0.2.1.zip) — `prickly-imax-helper-0.2.1.zip`
- [Windows 체크섬 보기](https://github.com/alpacawooo/prickly-imax-helper/releases/download/0.2.1/prickly-imax-helper-0.2.1.zip.sha256) — 설치 파일이 공식 배포본인지 확인하는 검증값이며, 별도 설치 파일이 아닙니다.

별도의 `.sha256` 파일은 받지 않아도 됩니다. 아래 명령에 검증된 SHA-256이 고정되어 있습니다. GitHub가 자동으로 표시하는 `Source code (zip)`과 `Source code (tar.gz)`도 설치 파일이 아니므로 다운로드하지 않습니다.

시작 메뉴에서 `Windows PowerShell`을 열고 아래 한 줄을 붙여넣습니다.

```powershell
$v='0.2.1'; $f="prickly-imax-helper-$v.zip"; $expected='0067fc3919f551de64748551c925d50addadc3b8681c20cdd660a0999dfd5fa7'; cd "$HOME\Downloads"; $actual=(Get-FileHash $f -Algorithm SHA256).Hash.ToLower(); if($actual -ne $expected){throw '체크섬 불일치: 설치 중단'}; Expand-Archive -Force $f .; powershell -ExecutionPolicy RemoteSigned -File ".\prickly-imax-helper-$v\scripts\Install.ps1"
```

체크섬이 다르면 설치가 즉시 중단됩니다. 관리자 PowerShell은 필요하지 않습니다. Windows가 실행 여부를 물으면 다운로드한 공식 GitHub 공개 릴리스가 맞는지 확인한 뒤 실행합니다.

## 2. 로그인과 조건 확인

설정 페이지가 자동으로 열립니다.

1. `전용 Chrome 열기`를 누릅니다.
2. 열린 Chrome에서 CGV에 직접 로그인합니다.
3. 설정 페이지로 돌아와 알림을 받을 메일 서비스를 `Gmail / 네이버 메일 / iCloud Mail / 기타` 중에서 선택하고 자기 수신 주소를 입력합니다.
4. 영화·CGV 극장·IMAX 형식·요일별 시간·같은 행 연속 좌석 수·허용 열·양끝 제외율·좌석 우선순위를 확인하거나 본인 조건으로 바꿉니다.
5. 자동 예매 사전동의에 체크하고 `설정 저장`을 누릅니다.

CGV 허용량은 공인 IP당 초당 1회입니다. 같은 집·회사 Wi-Fi에서 Prickly IMAX Helper를 여러 대 동시에 실행하지 마세요. 설정 페이지에서 동일 공인 IP에 한 대만 실행한다는 항목도 확인합니다.

수신 주소는 운영체제와 상관없이 Gmail·네이버·iCloud·기타 주소를 사용할 수 있습니다. 저장할 때 macOS는 Apple Mail, Windows는 클래식 Outlook 데스크톱을 로컬 발송 통로로 사용해 선택한 주소로 테스트 메일을 한 번 보냅니다. macOS가 Mail 제어 권한을 물으면 `허용`을 누릅니다. Windows에서는 Outlook에 발신 계정 하나를 미리 연결해 두고 프로그램 액세스 경고가 나오면 내용을 확인한 뒤 허용합니다. 테스트 발송에 실패하면 설정은 저장되지 않습니다. 이메일 비밀번호나 앱 비밀번호는 Helper에 입력하지 않습니다.

설정 저장 후 설치기가 CGV 조회 연결을 한 번 확인합니다. 이 검사는 좌석, 관람권, 결제 버튼을 누르지 않습니다. 검사가 실패하면 상주 감시는 시작되지 않습니다.

처음 표시되는 직장인용 기본값은 다음과 같으며, 설정 화면에서 변경할 수 있습니다.

- 오디세이 · 용산아이파크몰 · IMAX
- 현재와 앞으로 열리는 모든 예매일
- 2명 같은 행 연속 좌석
- D~J열, 양 끝 각각 20% 제외, 중앙 우선
- 평일 19:00 이후, 토요일 전체, 일요일 22:00 이전 시작
- 등록된 IMAX 관람권 2매, 남은 결제금액 0원
- 중복 예매, 기존 예매 취소, 좌석 변경 금지

시간 입력란을 비우면 그 방향의 시간 제한이 없습니다. 같은 행 연속 조건, 현재 열린 모든 날짜와 새로 열리는 날짜 포함, 중복 예매 금지, 기존 예매 취소·좌석 변경 금지, IMAX 관람권 수량 일치·잔액 0원 조건은 안전장치로 유지됩니다. 저장할 때 선택한 영화와 극장의 CGV 내부 식별자를 전용 Chrome에서 자동 확인하며 좌석·관람권·결제 버튼은 누르지 않습니다.

## 3. 상태 확인 — macOS

```bash
~/.local/bin/prickly-imax status
```

주요 상태:

- `login_required`: 전용 Chrome에서 CGV 로그인 필요
- `armed`: 정상 감시 중
- `rate_limited`: CGV 요청 제한으로 자동 중지·대기 중
- `completed`: 모바일티켓까지 확인된 예매 완료
- `unknown_after_submit`: 최종 제출 결과를 증명하지 못해 재시도 금지
- `blocked_duplicate`, `blocked_payment`: 중복 또는 결제 조건 때문에 중단

Windows PowerShell에서는 아래 명령을 사용합니다.

```powershell
& "$env:LOCALAPPDATA\PricklyIMAXHelper\bin\prickly-imax.cmd" status
```

## 중지

```bash
~/.local/bin/prickly-imax stop
```

Windows:

```powershell
& "$env:LOCALAPPDATA\PricklyIMAXHelper\bin\prickly-imax.cmd" stop
```

## 조건 다시 설정

감시 중에는 전용 Chrome 잠금을 보호하기 위해 설정 페이지를 동시에 열지 않습니다. 먼저 감시를 중지하고 `setup`을 실행한 뒤, 저장이 끝나면 다시 시작합니다.

macOS:

```bash
~/.local/bin/prickly-imax stop
~/.local/bin/prickly-imax setup
~/.local/bin/prickly-imax start
```

Windows PowerShell:

```powershell
& "$env:LOCALAPPDATA\PricklyIMAXHelper\bin\prickly-imax.cmd" stop
& "$env:LOCALAPPDATA\PricklyIMAXHelper\bin\prickly-imax.cmd" setup
& "$env:LOCALAPPDATA\PricklyIMAXHelper\bin\prickly-imax.cmd" start
```

## 삭제

다운로드해 둔 릴리스 폴더에서 macOS는 `scripts/Uninstall.command`, Windows는 `scripts/Uninstall.ps1`을 실행합니다. 프로그램만 지울지 CGV 로그인 프로필까지 지울지 삭제 전에 다시 묻습니다.

## 업데이트

새 릴리스와 SHA-256 파일을 내려받아 체크섬을 확인한 뒤 macOS는 `scripts/Update.command`, Windows는 `scripts/Update.ps1`을 실행합니다. 기존 CGV 로그인 프로필과 설정은 유지되고 실행 코드만 새 버전으로 교체됩니다.

## Codex를 사용하는 경우

Codex 플러그인은 선택 사항입니다. 설치되어 있다면 다음처럼 말할 수 있습니다.

- `Prickly IMAX Helper 상태와 최근 오류를 알려줘.`
- `CGV 로그인 창을 열어줘.`
- `IMAX 감시를 중단해줘.`

## 문제가 생기면

비밀번호나 화면 전체를 보내지 말고 아래 두 결과만 전달합니다.

```bash
~/.local/bin/prickly-imax doctor
~/.local/bin/prickly-imax diagnose
```

Windows에서는 위 두 명령의 앞부분을 `%LOCALAPPDATA%\PricklyIMAXHelper\bin\prickly-imax.cmd`로 바꿉니다.
