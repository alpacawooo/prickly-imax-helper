# Prickly IMAX Helper 소셜 배포 에셋

## 완성본

- `carousel/01.png`~`carousel/09.png`: 인스타그램 캐러셀 9장, 각 1080×1350
- `carousel/contact-sheet.png`: 캐러셀 전체 검수판
- `reel/prickly-imax-helper-reel-visual-master.mp4`: 30초 무음 비주얼 마스터, 1080×1920
- `reel/frames/01.png`~`07.png`: 릴스 장면별 원본 프레임
- `reel/contact-sheet.png`: 릴스 전체 검수판
- `prickly-imax-helper-social-assets.zip`: 전달용 묶음

음악은 저작권 문제를 피하기 위해 포함하지 않았다. 인스타그램 게시 단계에서 음원이나 직접 녹음한 내레이션을 붙이면 된다.

## 메시지 구조

1. 문제 정의: 일부 리셀 게시물에 30만 원 사례가 등장하고, 원하는 회차는 반복해서 매진됨
2. 문제 해결: 사람 대신 사용자 본인의 컴퓨터가 조건에 맞는 취소표를 기다림
3. 작동 방식: 설치 → 사용자 직접 CGV 로그인 → 영화·극장·시간·인원·좌석 조건 설정
4. 안전 경계: 중복 예매 차단, 관람권 수 확인, 남은 금액 0원, 최종 제출 1회, 카드 결제 자동화 없음
5. 행동 요청: 댓글에 `아이맥스`

## 다시 만들기

```bash
/Users/woojinyoung/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py
```

제품 설정 화면은 실제 로컬 UI를 오프라인으로 렌더링한다. CGV 접속, 회차 조회, 좌석 선택, 관람권 적용, 결제는 실행하지 않는다.

