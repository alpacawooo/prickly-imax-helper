# Prickly IMAX Two-Motion Carousel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an eight-item Instagram carousel with six 1080×1350 PNGs and exactly two muted H.264 MP4s—Card 5 for the Helper workflow and Card 7 for the outcome flow.

**Architecture:** Keep the existing offline HTML-to-PNG renderer and manifest, but make media type explicit per card. Render all eight PNG covers for QA, copy six covers into the publishable mixed-media sequence, and encode only Cards 5 and 7 from staged offline frames. Card 7 visualizes the product's result path without fabricating a CGV mobile ticket, booking identifier, or completed transaction.

**Tech Stack:** Python 3, Pillow, Playwright/Chrome screenshot capture, FFmpeg/FFprobe, pytest/unittest, HTML/CSS.

## Global Constraints

- Publish order is exactly `01.png`, `02.png`, `03.png`, `04.png`, `05.mp4`, `06.png`, `07.mp4`, `08.png`.
- Only Cards 5 and 7 may contain motion; no ornamental slow pushes on static cards.
- Card 5 shows `조건 설정 → 감시 시작 → 연속 좌석 후보 발견 → 중복·관람권·잔액 검증`.
- Card 7 shows `조건 일치 → 안전검증 통과 → 최종 제출 1회 → 결과 이메일 전송`.
- Do not create a CGV mobile ticket, booking number, QR code, barcode, or fake completed-transaction screenshot.
- Do not browse CGV or create any CGV request while building or verifying the content.
- Do not expose email addresses, cookies, voucher numbers, profile paths, attempt IDs, or unredacted logs.
- Card 2 preserves The Direct attribution and states that the IMAX 70mm comparison example is not Yongsan's IMAX LASER 2D format.

---

### Task 1: Lock the mixed-media contract

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json`
- Modify: `tests/test_carousel_visuals.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py`

**Interfaces:**
- Produces: manifest fields `media_type: "png" | "mp4"`, `duration: null | int`, and `motion: "none" | "workflow-sequence" | "outcome-sequence"`.

- [ ] Add failing tests asserting PNG cards `{1,2,3,4,6,8}`, MP4 cards `{5,7}`, exact publish filenames, honest Card 7 copy, and no fake-ticket source types.
- [ ] Run the focused tests and confirm failure against the eight-MP4 implementation.
- [ ] Update manifest validation and card copy. Card 2 receives the IMAX comparison source and format disclaimer; Card 7 receives outcome-flow copy without a completed-booking claim.
- [ ] Run the focused tests and confirm the manifest contract passes.
- [ ] Commit the contract change.

### Task 2: Build the two staged motion sequences

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`
- Modify: `tests/test_carousel_visuals.py`

**Interfaces:**
- Produces: `card_five_scene_htmls(setup_png, monitor_png) -> list[str]` with four stages.
- Produces: `card_seven_scene_htmls(monitor_png) -> list[str]` with four stages.

- [ ] Add failing tests for exact stage count, stage order, privacy-safe copy, and absence of `모바일티켓`, `예매번호`, `QR`, and `barcode` in Card 7 HTML.
- [ ] Run focused tests and confirm failure because the new stage functions do not exist.
- [ ] Implement Card 5 stages using the actual setup preview, redacted monitor preview, and restrained Prickly stage typography.
- [ ] Implement Card 7 stages as an outcome path using Prickly-branded state panels and the real notification subject supported by the product, without imitating CGV UI.
- [ ] Render representative stage PNGs and inspect them at 1080×1350.
- [ ] Run focused tests and commit the staged-motion implementation.

### Task 3: Render a mixed publishable sequence

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py`

**Interfaces:**
- Produces: `render_video_carousel_cards(cards, covers) -> list[Path]` containing six PNGs and two MP4s in numeric order.
- Produces: `verify_video_carousel(cards, covers, media) -> dict[str, object]` validating mixed media.

- [ ] Add a failing output test asserting six PNGs, two MP4s, exact filenames, 1080×1350 PNGs, and muted H.264/yuv420p/30fps videos.
- [ ] Run the output test and confirm failure while stale eight-MP4 output exists.
- [ ] Clean only the known `video-carousel/cards` build directory and copy static covers as PNG cards.
- [ ] Encode Card 5 and Card 7 with 220ms or shorter fades and no decorative zoom.
- [ ] Update verification to validate PNG and MP4 contracts independently.
- [ ] Run focused tests and commit the mixed-media renderer.

### Task 4: Package, source, and verify

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/README.md`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/sources-and-claim-notes.md`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/cards/`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/contact-sheet.png`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/SHA256SUMS`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip`

**Interfaces:**
- Produces: a publishable ZIP containing the exact eight-item mixed sequence, README, QA report, source ledger, and checksums.

- [ ] Rebuild all covers and the two videos without making network requests.
- [ ] Inspect the eight-card contact sheet plus first/middle/last frames for Cards 5 and 7.
- [ ] Verify Card 2 attribution/format disclaimer, Card 3 claim accuracy, Card 5 step order, Card 7 non-transactional result flow, mobile legibility, and safe-zone clipping.
- [ ] Run the focused carousel tests, then the full product suite.
- [ ] Run `shasum -a 256 -c SHA256SUMS` and ZIP integrity verification.
- [ ] Commit generated outputs and report the final paths and verification evidence.
