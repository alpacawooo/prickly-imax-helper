# Prickly IMAX Helper 소셜 배포 에셋

## 완성본

### 최종 혼합 캐러셀

- `video-carousel/cards/01.png`, `02.png`, `03.png`, `06.png`: 정지 카드 4개
- `video-carousel/cards/04.mp4`, `05.mp4`: 설정 스크롤·실제 감시 과정 영상 2개
- `video-carousel/covers/01.png`~`06.png`: 전체 구도 검수용 PNG 표지
- `video-carousel/contact-sheet.png`: 6장 전체 검수판
- `video-carousel/SHA256SUMS`: 카드·표지 체크섬
- `prickly-imax-helper-video-carousel.zip`: 최종 업로드 묶음

모든 게시 파일은 1080×1350이다. Card 4는 실제 설정 화면을 빠르게 스크롤하는 3초 영상이고, Card 5는 개인정보가 제거된 실제 로컬 `diagnose` 상태를 연결한 8초 감시 과정 영상이다. 두 영상 모두 H.264, yuv420p, 30fps, 무음이다. Card 3은 사용자가 제공한 실제 CGV 한 자리 화면을 사용하며 `한 자리는 연속 2석이 아니다`라는 사실만 표현한다. Card 5는 현재 `match:null`을 그대로 유지하고 후보 발견 뒤의 안전 절차만 설명한다. Card 6은 댓글 CTA다.

### 기존 정적 캐러셀·릴스 마스터

- `carousel/01.png`~`carousel/09.png`: 인스타그램 캐러셀 9장, 각 1080×1350
- `carousel/contact-sheet.png`: 캐러셀 전체 검수판
- `reel/prickly-imax-helper-reel-visual-master.mp4`: 30초 무음 비주얼 마스터, 1080×1920
- `reel/frames/01.png`~`07.png`: 릴스 장면별 원본 프레임
- `reel/contact-sheet.png`: 릴스 전체 검수판
- `prickly-imax-helper-social-assets.zip`: 전달용 묶음

음악은 저작권 문제를 피하기 위해 포함하지 않았다. 인스타그램 게시 단계에서 음원이나 직접 녹음한 내레이션을 붙이면 된다.

## 메시지 구조

1. 문제 정의: 원하는 회차는 매진이고, 한 자리가 보여도 붙어 있는 2석은 없음
2. 문제 해결: 사용자 본인의 컴퓨터가 설정한 조건에 맞는 취소표를 확인
3. 작동 방식: 설치 → 사용자 직접 CGV 로그인 → 영화·극장·시간·인원·좌석 조건 설정
4. 안전 경계: 중복 예매 차단, 관람권 수 확인, 남은 금액 0원, 최종 제출 1회, 카드 결제 자동화 없음
5. 행동 요청: 댓글에 `아이맥스`

## 다시 만들기

```bash
/Users/woojinyoung/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py
```

최종 영상 캐러셀만 다시 만들려면:

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv \
  run --locked --with pillow python \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py --video-carousel
```

제품 설정 화면은 실제 로컬 UI를 오프라인으로 렌더링한다. CGV 접속, 회차 조회, 좌석 선택, 관람권 적용, 결제는 실행하지 않는다.

체크섬 확인:

```bash
cd generated_assets/prickly_imax_helper_launch/visuals/video-carousel
shasum -a 256 -c SHA256SUMS
```
