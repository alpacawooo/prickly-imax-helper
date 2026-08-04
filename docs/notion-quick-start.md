# Prickly IMAX Helper 비공개 베타 — 3분 시작

## 준비

- macOS
- Google Chrome
- 본인 CGV 계정
- CGV 계정에 등록된 IMAX 관람권 2매
- Apple Mail에 로그인된 이메일 계정

Python이나 개발 도구는 미리 설치하지 않아도 됩니다. 필요한 경우 설치기가 검증된 관리형 Python을 사용자 폴더 안에 준비합니다.

비밀번호와 결제정보는 Prickly AI에 입력하지 않습니다. 전용 Chrome 창에서 사용자가 직접 로그인합니다.

CGV 비밀번호, 관람권 번호, 카드번호, 이메일 비밀번호는 Prickly AI나 설치 페이지에 입력하지 않습니다.

## 1. 설치

비공개 GitHub 초대를 수락하고 Releases에서 아래 파일 두 개를 다운로드합니다.

- `prickly-imax-helper-0.1.0.tar.gz`
- `prickly-imax-helper-0.1.0.tar.gz.sha256`

터미널을 열어 이 한 줄을 붙여넣습니다.

```bash
cd "$HOME/Downloads" && shasum -a 256 -c prickly-imax-helper-0.1.0.tar.gz.sha256 && tar -xzf prickly-imax-helper-0.1.0.tar.gz && open prickly-imax-helper-0.1.0/scripts/Install.command
```

`OK`가 나오지 않으면 설치하지 말고 받은 파일을 삭제합니다. macOS가 처음 실행을 막으면 Finder에서 `Install.command`를 Control-클릭한 뒤 `열기`를 선택합니다.

## 2. 로그인과 조건 확인

설정 페이지가 자동으로 열립니다.

1. `전용 Chrome 열기`를 누릅니다.
2. 열린 Chrome에서 CGV에 직접 로그인합니다.
3. 설정 페이지로 돌아와 결과를 받을 자기 이메일을 입력합니다.
4. 표시된 좌석·시간·관람권 조건을 확인합니다.
5. 자동 예매 사전동의에 체크하고 `설정 저장`을 누릅니다.

CGV 허용량은 공인 IP당 초당 1회입니다. 같은 집·회사 Wi-Fi에서 Prickly IMAX Helper를 여러 대 동시에 실행하지 마세요. 설정 페이지에서 동일 공인 IP에 한 대만 실행한다는 항목도 확인합니다.

저장할 때 Apple Mail 테스트 메일을 한 번 보냅니다. macOS가 `Install.command` 또는 Python이 Mail을 제어하도록 허용할지 물으면 `허용`을 누릅니다. 테스트 발송에 실패하면 설정은 저장되지 않습니다.

설정 저장 후 설치기가 CGV 조회 연결을 한 번 확인합니다. 이 검사는 좌석, 관람권, 결제 버튼을 누르지 않습니다. 검사가 실패하면 상주 감시는 시작되지 않습니다.

기본 조건은 다음과 같습니다.

- 오디세이 · 용산아이파크몰 · IMAX
- 현재와 앞으로 열리는 모든 예매일
- 2명 같은 행 연속 좌석
- D~J열, 양 끝 각각 20% 제외, 중앙 우선
- 평일 19:00 이후, 토요일 전체, 일요일 22:00 이전 시작
- 등록된 IMAX 관람권 2매, 남은 결제금액 0원
- 중복 예매, 기존 예매 취소, 좌석 변경 금지

## 3. 상태 확인

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

## 중지

```bash
~/.local/bin/prickly-imax stop
```

## 삭제

다운로드해 둔 릴리스 폴더에서 `scripts/Uninstall.command`를 엽니다. 프로그램만 지울지 CGV 로그인 프로필까지 지울지 삭제 전에 다시 묻습니다.

## 업데이트

새 릴리스와 SHA-256 파일을 내려받아 체크섬을 확인한 뒤 새 폴더의 `scripts/Update.command`를 엽니다. 기존 CGV 로그인 프로필과 설정은 유지되고 실행 코드만 새 버전으로 교체됩니다.

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
