# Prickly IMAX Final Video Carousel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy nine-image carousel with an eight-card, upload-ready Instagram video carousel that uses the approved Odyssey stills, real offline Helper UI, privacy-safe status proof, and a sanitized installation-guide preview.

**Architecture:** Keep the existing HTML/CSS renderer as the single visual source of truth, but model each carousel card as structured metadata and render one PNG cover plus one H.264 MP4 per card. Authentic Odyssey stills are used only for the problem and recognition cards; product and guide proof are generated locally from repository content without CGV browsing or private Notion UI.

**Tech Stack:** Python 3.12, Pillow, HTML/CSS, Playwright with local Chrome, FFmpeg/FFprobe, SHA-256, unittest

## Global Constraints

- Exactly eight cards in posting order, each with a 1080×1350 PNG cover and 1080×1350 MP4.
- MP4 output is H.264, yuv420p, 30 fps, with durations `6, 6, 7, 9, 8, 7, 9, 6` seconds.
- Use `odyssey-agamemnon-fullbody-1080x1350.jpg` and `odyssey-giants-forest-1080x1350.jpg` without generative modification.
- The user-provided `ScreenRecording_08-14-2026 17-39-23_1.MP4` is a benchmark only; it must not appear in the final package.
- Do not capture the logged-in Notion sidebar. Render a sanitized local guide preview from `docs/notion-quick-start.md` and label it `설치 안내 미리보기`.
- Do not browse CGV, click a showtime, select party size or seats, apply vouchers, or submit a booking.
- Do not claim a successful booking, guaranteed ticket, CGV endorsement, public Notion availability, or direct push notification.
- Preserve the Prickly near-black layout, red top rule, restrained typography, page counter, and final CTA spacing.
- The removed brand sentence `Prickly AI는 사람이 반복하던 일을 실제로 작동하는 자동화로 바꾼다.` must not reappear.

---

### Task 1: Add deterministic carousel inputs and validation

**Files:**
- Create: `generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json`
- Create: `generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`

**Interfaces:**
- Consumes: approved Odyssey still paths, offline Helper setup renderer, `docs/notion-quick-start.md`.
- Produces: `load_carousel_manifest() -> list[dict[str, object]]` and `validate_manifest(cards) -> None`.

- [ ] **Step 1: Write failing manifest tests**

Assert that the manifest contains exactly eight numbered cards, the required duration sequence, one headline per card, valid motion presets, and no benchmark-video path or banned sentence.

- [ ] **Step 2: Run the focused test and confirm failure**

Run:

```bash
PYTHONPATH=runtime /tmp/prickly-imax-final-carousel-verify/bin/python \
  -m unittest generated_assets.prickly_imax_helper_launch.visuals.tests.test_video_carousel -v
```

Expected: failure because the manifest and loader do not exist.

- [ ] **Step 3: Add the eight-card manifest and loader**

Encode card numbers, durations, source type, source path, eyebrow, headline, supporting copy, footer, and motion preset. Reject missing files, unsupported presets, duplicate numbers, and copy containing banned claims.

- [ ] **Step 4: Run the focused test and confirm success**

Run the command from Step 2. Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py
git commit -m "content: define final IMAX video carousel"
```

### Task 2: Render eight branded cover frames

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`
- Create: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/covers/01.png` through `08.png`
- Create: `generated_assets/prickly_imax_helper_launch/visuals/assets/install-guide-preview.png`

**Interfaces:**
- Consumes: `load_carousel_manifest()`, the two approved Odyssey stills, offline setup screenshot, and sanitized guide copy.
- Produces: `render_video_carousel_covers(cards) -> list[Path]`.

- [ ] **Step 1: Extend focused tests for cover dimensions and privacy**

Assert 1080×1350 output, exactly eight covers, no overflow marker, no email address, no Notion workspace name, and no text from the benchmark account.

- [ ] **Step 2: Confirm the new assertions fail**

Run the focused unittest module. Expected: cover-rendering functions or outputs are missing.

- [ ] **Step 3: Implement cover templates**

Use the orange full-body still on Card 1 and fog-giants still on Card 2. Use dark Prickly panels for Cards 3–8, the real offline Helper setup screenshot on Card 4, a redacted synthetic status panel on Card 5, safety tiles on Card 6, and the sanitized guide preview on Card 7. Card 8 must preserve large negative space and restrained final-statement scale.

- [ ] **Step 4: Render and inspect contact sheet**

Generate `video-carousel/contact-sheet.png` and verify one clear idea per card at thumbnail size.

- [ ] **Step 5: Run focused tests and commit**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/assets/install-guide-preview.png \
  generated_assets/prickly_imax_helper_launch/visuals/video-carousel
git commit -m "content: render final IMAX carousel covers"
```

### Task 3: Produce one motion MP4 per carousel card

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`
- Create: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/cards/01.mp4` through `08.mp4`

**Interfaces:**
- Consumes: eight PNG covers and the manifest duration/motion fields.
- Produces: `render_video_carousel_cards(cards, covers) -> list[Path]`.

- [ ] **Step 1: Add failing media-contract tests**

Probe every MP4 with FFprobe and assert H.264, yuv420p, 1080×1350, 30 fps, and duration within 0.10 seconds of the manifest.

- [ ] **Step 2: Confirm media tests fail before MP4 generation**

Run the focused unittest module. Expected: missing card files.

- [ ] **Step 3: Implement restrained motion**

Use a maximum 3% Ken Burns zoom for Odyssey stills, subtle red light drift for static dark cards, and readable vertical pan within the setup and guide proof panels. Render without audio and add `+faststart`.

- [ ] **Step 4: Generate all eight MP4 cards**

Run `build_visuals.py --video-carousel` and verify FFmpeg exits successfully for every card.

- [ ] **Step 5: Run focused tests and commit**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/video-carousel/cards
git commit -m "content: build final IMAX video carousel"
```

### Task 4: Package, document, and verify the final deliverable

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/README.md`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/sources-and-claim-notes.md`
- Create: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/SHA256SUMS`
- Create: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/qa-report.md`
- Create: `generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip`

**Interfaces:**
- Consumes: eight MP4 cards, eight PNG covers, contact sheet, source and claim notes.
- Produces: one publish-ready ZIP and a reproducible verification record.

- [ ] **Step 1: Add packaging assertions**

Assert that the ZIP contains only the eight cards, eight covers, contact sheet, README/source notes, QA report, and checksums in posting order.

- [ ] **Step 2: Generate checksums, QA report, and ZIP**

Record the media contract, privacy review, source credits, benchmark-video exclusion, and the local-guide-preview disclosure.

- [ ] **Step 3: Run all verification**

```bash
PYTHONPATH=runtime /tmp/prickly-imax-final-carousel-verify/bin/python -m unittest discover -s tests
PYTHONPATH=runtime /tmp/prickly-imax-final-carousel-verify/bin/python \
  -m unittest generated_assets.prickly_imax_helper_launch.visuals.tests.test_video_carousel -v
```

Expected: repository suite and focused visual suite both pass with zero failures.

- [ ] **Step 4: Perform final visual review**

Inspect the 8-up contact sheet, Card 1 at full size, Card 4 setup proof, Card 7 guide preview, and Card 8 CTA. Confirm legibility, crop safety, privacy, and absence of banned claims.

- [ ] **Step 5: Commit**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals
git commit -m "content: package final IMAX video carousel"
```

