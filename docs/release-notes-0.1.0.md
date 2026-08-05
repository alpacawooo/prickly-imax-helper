# Prickly IMAX Helper 0.1.0 — Private Beta

Prickly IMAX Helper는 사용자의 PC에서만 실행되는 CGV 용산아이파크몰 오디세이 IMAX 감시·사전동의형 1회 관람권 예매 도우미다. CGV 로그인, 전용 Chrome 프로필, 이메일 주소, 관람권 상태는 로컬에만 저장된다.

## 다운로드

운영체제에 맞는 아카이브와 같은 이름의 SHA-256 파일을 함께 받는다.

- macOS: `prickly-imax-helper-0.1.0.tar.gz`, `prickly-imax-helper-0.1.0.tar.gz.sha256`
- Windows 10/11: `prickly-imax-helper-0.1.0.zip`, `prickly-imax-helper-0.1.0.zip.sha256`

Notion 안내의 버전 고정 명령은 체크섬이 일치할 때만 설치기를 실행한다. `main` 브랜치의 파일을 직접 실행하지 않는다.

## 고정된 예매 정책

- 오디세이 · 용산아이파크몰 · IMAX
- 현재 및 앞으로 열리는 모든 예매일
- 2명, 같은 행 연속 2석
- D~J열, 각 행 양 끝 각각 20% 제외, 중앙 우선
- 평일 19:00 이후, 토요일 전체, 일요일 22:00 이전 시작
- 등록된 IMAX 영화관람권 정확히 2매와 남은 결제금액 0원
- 중복 예매, 기존 예매 취소, 좌석 변경 금지
- 조건이 모두 증명될 때 최종 제출 한 번만 실행
- 모바일티켓 확인 실패 시 `unknown_after_submit`으로 중단하고 자동 재시도 금지

## 요청 제한과 복구

- 모든 명시적 CGV 조회는 로컬 공유 요청 예산을 통과하며 시작 간격이 최소 1초다.
- HTTP 429는 전체 조회를 최소 5분 쿨다운한다.
- 날짜 목록은 고정하지 않고 계속 다시 발견한다.
- 로그인 만료, 중복 예매, 관람권 부족, 잔액 발생, 좌석 소실은 fail-closed 상태로 멈춘다.

## 설치 전 요구사항

- Google Chrome
- 본인 CGV 계정과 등록된 IMAX 관람권 2매
- macOS Apple Mail 또는 Windows 클래식 Outlook 데스크톱
- 운영체제와 상관없이 Gmail·네이버 메일·iCloud Mail·기타 수신 주소 선택
- 동일 공인 IP에서 Prickly IMAX Helper 한 대만 실행

Python, Codex, Prickly AI 플러그인은 필수 설치 항목이 아니다. Codex 플러그인은 상태 확인과 진단을 돕는 선택 기능이다.

## 개인정보

CGV 비밀번호, 관람권 번호, 카드번호, 이메일 비밀번호를 설치 페이지나 프롬프트에 입력하지 않는다. 오류 보고에는 `prickly-imax diagnose`의 개인정보 제거 JSON만 사용한다.

## 0.1.0 검증 게이트

이 릴리스는 다음 조건이 모두 완료된 뒤에만 첨부 파일을 게시한다.

- 승인 범위와 공개 가능한 참조값 또는 비공개 승인 원문의 SHA-256 지문
- macOS/Windows 단위·통합·설치·업데이트·삭제 CI
- 로그인된 macOS 무클릭 dry-run
- 24시간 단일 인스턴스 soak
- 실제 비공개 GitHub release 링크가 반영된 Notion 온보딩
