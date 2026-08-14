# Prickly IMAX Six-Card Monitoring Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve cards 1–4, replace the former cards 5–7 with one eight-second video made from redacted local monitor state, and move the CTA to card 6.

**Architecture:** Keep `carousel_manifest.json` as the six-card publishing contract and keep `build_visuals.py` as the single renderer. Split the renderer’s monitoring work into read-only local state sampling, five HTML stages, and a generic scene-sequence encoder. The build may call only `prickly-imax diagnose`; it must not browse CGV or trigger a booking action.

**Tech Stack:** Python 3.12, Pillow, Playwright with installed Google Chrome, FFmpeg/FFprobe, HTML/CSS, pytest, unittest.

## Global Constraints

- Cards 1–4 retain their approved copy, source images, compositions, and media.
- The final sequence is `01.png`, `02.png`, `03.png`, `04.mp4`, `05.mp4`, `06.png`.
- Card 4 remains a three-second setup-scroll video.
- Card 5 is an eight-second muted H.264 video at 1080×1350, 30fps, yuv420p.
- Card 5 starts after setup: `감시 시작 → 열린 날짜·회차 확인 → 연속 좌석 감시 → 후보가 없으면 계속 순환 → 좌석 발견 시 안전검증·한 번 제출·이메일 알림`.
- Card 5 uses only redacted local `prickly-imax diagnose` state and must not fabricate a seat match.
- Card 6 is the approved CTA: `용아맥 새로고침에 지쳤다면.` and `댓글에 아이맥스`.
- Preserve the existing black background, white type, Prickly red accent, typography, and page-number placement.
- Do not add rounded cards, fake browser chrome, phone mockups, decorative icons, QR codes, tickets, booking numbers, or fake completed transactions.
- Building the content must not create additional CGV requests or click a showtime, party size, seat, voucher, or payment control.

---

### Task 1: Lock the six-card publishing contract

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json`
- Modify: `tests/test_carousel_visuals.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`

**Interfaces:**
- Consumes: the approved cards 1–4 manifest entries without modification.
- Produces: a six-entry manifest and validators expecting `[None, None, None, 3, 8, None]`.

- [ ] **Step 1: Write failing six-card contract tests**

```python
def test_manifest_locks_six_card_sequence() -> None:
    cards = load_builder().load_carousel_manifest()
    assert [card["number"] for card in cards] == [1, 2, 3, 4, 5, 6]
    assert [card["media_type"] for card in cards] == ["png", "png", "png", "mp4", "mp4", "png"]
    assert [card["duration"] for card in cards] == [None, None, None, 3, 8, None]
    assert cards[4]["composition"] == "monitoring-process"
    assert cards[5]["composition"] == "black-note-cta"
```

Update output tests to require exactly `01.png` through `06.png`, four PNGs, and two MP4s. Assert generated cover HTML contains `05 / 06` and `06 / 06` and no `/8` page number.

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q tests/test_carousel_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
```

Expected: failures report eight manifest entries, the old three-video sequence, or `/8` page numbering.

- [ ] **Step 3: Reduce the manifest and validator to six cards**

Keep entries 1–4. Replace entry 5 with:

```json
{
  "number": 5,
  "media_type": "mp4",
  "duration": 8,
  "source_type": "local-monitor",
  "source": "generated_assets/prickly_imax_helper_launch/visuals/assets/helper-monitor-preview.png",
  "headline": "설정이 끝나면\n그다음은 이렇게 돌아간다.",
  "supporting": "실제 로컬 감시 상태",
  "footer": "개인정보를 제외한 로컬 상태 · 추가 CGV 요청 없음",
  "composition": "monitoring-process",
  "text_anchor": "top-left",
  "motion": "workflow-sequence"
}
```

Renumber the existing CTA entry to 6 and delete the old condition and outcome entries. Change `validate_manifest()` to require six entries, media `png,png,png,mp4,mp4,png`, and durations `[None,None,None,3,8,None]`.

- [ ] **Step 4: Make page numbering accept the six-card total**

Change hard-coded page numbers in `video_carousel_covers()`, `flow_stage_html()`, and card-three stages to derive `page_total = len(cards)` or accept `page_total: int` explicitly. Do not alter the visual placement or font sizes.

- [ ] **Step 5: Run focused tests and commit**

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q tests/test_carousel_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
git add generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py \
  tests/test_carousel_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
git commit -m "content: reduce IMAX carousel to six cards"
```

Expected: manifest and HTML contract tests pass; output tests may remain red until Task 4 rerenders files.

---

### Task 2: Capture real redacted local monitor states without CGV activity

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`
- Modify: `tests/test_carousel_visuals.py`

**Interfaces:**
- Produces: `read_redacted_monitor_state(command: Path) -> dict[str, object]`.
- Produces: `sample_monitor_states(read_state, *, count: int, interval_seconds: float, sleeper) -> list[dict[str, object]]`.
- Consumed by: Task 3’s five monitoring stages.

- [ ] **Step 1: Write failing read-only sampling tests**

```python
def test_monitor_sampling_reads_local_state_only() -> None:
    states = iter([
        {"status": "armed", "open_dates": 12, "eligible_shows": 35, "match": None, "last_scan_lane": "discovery"},
        {"status": "armed", "open_dates": 12, "eligible_shows": 35, "match": None, "last_scan_lane": "hot"},
    ])
    sleeps: list[float] = []
    sampled = load_builder().sample_monitor_states(
        lambda: next(states), count=2, interval_seconds=0.4, sleeper=sleeps.append
    )
    assert sampled[0]["last_scan_lane"] == "discovery"
    assert sampled[1]["last_scan_lane"] == "hot"
    assert sleeps == [0.4]
```

Add a subprocess test that patches `subprocess.run`, calls `read_redacted_monitor_state(Path("/tmp/prickly-imax"))`, and asserts the only command is `[/tmp/prickly-imax, diagnose]`. Assert email addresses, `/Users/...` paths, cookie, voucher, and profile values do not survive.

- [ ] **Step 2: Run the focused tests and verify failure**

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q tests/test_carousel_visuals.py -k 'monitor_sampling or redacted_monitor_state'
```

Expected: missing function failures.

- [ ] **Step 3: Extract the diagnose reader**

Implement `read_redacted_monitor_state()` by moving the existing `prickly-imax diagnose` parsing out of `redacted_monitor_preview()`. Return only:

```python
{
    key: status.get(key)
    for key in ("status", "detail", "open_dates", "eligible_shows", "match", "errors", "last_scan_lane")
}
```

Run `redact_visual_evidence()` before JSON decoding, preserve the 20-second timeout, and raise on a non-zero local CLI result. Do not add browser or network calls.

- [ ] **Step 4: Implement bounded local sampling**

```python
def sample_monitor_states(read_state, *, count, interval_seconds, sleeper=time.sleep):
    if count < 1 or interval_seconds < 0:
        raise ValueError("monitor sampling requires a positive count and non-negative interval")
    states = []
    for index in range(count):
        states.append(read_state())
        if index + 1 < count:
            sleeper(interval_seconds)
    return states
```

Use five samples at 0.4-second intervals only when building card 5. If the state remains unchanged, keep the authentic values and change only the explanatory focus; never synthesize a match.

- [ ] **Step 5: Run tests and commit**

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q tests/test_carousel_visuals.py -k 'monitor or redaction'
git add generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py tests/test_carousel_visuals.py
git commit -m "content: sample redacted local monitor state"
```

---

### Task 3: Build the five-stage actual monitoring video

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`
- Modify: `tests/test_carousel_visuals.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py`

**Interfaces:**
- Consumes: Task 2’s five redacted state dictionaries.
- Produces: `card_five_monitor_scene_htmls(states: list[dict[str, object]]) -> list[str]` with exactly five pages.
- Produces: `render_scene_sequence(frames: list[Path], output: Path, *, duration: int, fps: int = 30) -> None`.

- [ ] **Step 1: Write failing stage-content tests**

```python
def test_card_five_uses_actual_monitoring_stages_without_fake_match() -> None:
    states = [{"status": "armed", "open_dates": 12, "eligible_shows": 35,
               "match": None, "errors": 0, "last_scan_lane": "hot"}] * 5
    pages = load_builder().card_five_monitor_scene_htmls(states)
    assert len(pages) == 5
    assert "감시 시작" in pages[0] and "armed" in pages[0]
    assert "열린 날짜·회차 확인" in pages[1]
    assert "연속 좌석 감시" in pages[2] and "hot" in pages[2]
    assert "후보가 없으면 계속 순환" in pages[3] and "null" in pages[3]
    assert "좌석 발견 시" in pages[4]
    assert "match&quot;: true" not in "\n".join(pages)
```

Add a renderer test with five temporary frame paths and assert generated FFmpeg arguments contain five inputs, four `xfade` transitions, `-t 8`, `30fps`, and `yuv420p`.

- [ ] **Step 2: Run the focused tests and verify failure**

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q tests/test_carousel_visuals.py -k 'card_five or scene_sequence'
```

Expected: missing five-stage builder and generic sequence renderer.

- [ ] **Step 3: Render five honest monitoring stages**

Each stage uses the same actual redacted local state screen, changing only the crop/focus and one large overlay line:

1. `감시 시작` — emphasize `status: armed`.
2. `열린 날짜·회차 확인` — emphasize `open_dates` and `eligible_shows`.
3. `연속 좌석 감시` — emphasize `last_scan_lane` and explain hot/discovery rotation.
4. `후보가 없으면 계속 순환` — emphasize `match: null`.
5. `좌석 발견 시 안전검증 → 한 번 제출 → 이메일 알림` — transition rule only; do not change the actual `match` value.

Use full-bleed black, actual diagnose typography, white stage text, and one Prickly red index/rail. Do not wrap stages in cards.

- [ ] **Step 4: Generalize video encoding for five frames**

Construct FFmpeg inputs from the frame list and generate four 180ms crossfades at offsets `1.42`, `3.02`, `4.62`, and `6.22`. Finish with `fps=30,format=yuv420p`, muted H.264, CRF 18, and `+faststart`. Reject fewer than two frames.

- [ ] **Step 5: Remove obsolete outcome rendering**

Delete `card_seven_scene_htmls()`, the old condition card HTML, the old outcome card HTML, and their frame-generation loops. Keep cards 1–4 byte-identical unless page numbering requires rerendered covers.

- [ ] **Step 6: Run tests and commit**

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q tests/test_carousel_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
git add generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py \
  tests/test_carousel_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
git commit -m "content: render actual IMAX monitoring flow"
```

---

### Task 4: Render, visually inspect, checksum, and package the six cards

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/README.md`
- Regenerate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/cards/`
- Regenerate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/covers/`
- Regenerate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/contact-sheet.png`
- Regenerate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/SHA256SUMS`
- Regenerate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/README.md`
- Regenerate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/qa-report.md`
- Regenerate: `generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip`

**Interfaces:**
- Consumes: the six-card manifest and rendered card 5 stages.
- Produces: a verified six-file Instagram package and review artifacts.

- [ ] **Step 1: Update verification and package-count tests**

Require six covers, four PNG cards, two MP4 cards, a 6-card contact sheet, and a ZIP containing only:

```text
cards/01.png
cards/02.png
cards/03.png
cards/04.mp4
cards/05.mp4
cards/06.png
```

Assert card 4 is 3.0±0.1 seconds and card 5 is 8.0±0.1 seconds. Assert no `07.*` or `08.*` file appears in the archive.

- [ ] **Step 2: Run output tests and verify they fail against the old package**

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
```

Expected: old eight-card files and counts fail.

- [ ] **Step 3: Update verification, README, and QA copy**

Change `verify_video_carousel()` and `package_video_carousel()` to six-card counts. Document four PNGs, two MP4s, card 4 at three seconds, card 5 at eight seconds, and card 5’s actual redacted local monitoring source. Remove references to cards 7–8 and the removed condition/outcome slides.

- [ ] **Step 4: Render the six-card package**

```bash
PYTHONPATH=runtime \
  /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv \
  run --locked --with pillow python \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py --video-carousel
```

The render may read `prickly-imax diagnose`; it must not open or control CGV.

- [ ] **Step 5: Inspect motion and layout**

Extract a 4fps contact sheet from card 5 and verify:

- each stage is legible on a phone-sized preview;
- the actual diagnose screen remains visible rather than becoming a decorative background;
- stage copy does not overlap state values or page numbering;
- transitions feel continuous and not like five separate cards;
- the final stage describes the transition rule without showing a fake match.

- [ ] **Step 6: Run full verification**

```bash
PYTHONPATH=runtime /Users/woojinyoung/.prickly-imax-helper/bootstrap/uv-0.11.15/uv-aarch64-apple-darwin/uv run --locked --with pillow --with pytest \
  pytest -q tests/test_carousel_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
PYTHONPATH=runtime ./.venv/bin/python -m unittest discover -s tests -q
(cd generated_assets/prickly_imax_helper_launch/visuals/video-carousel && shasum -a 256 -c SHA256SUMS)
git diff --check
```

Expected: all visual tests pass, all 167 product tests pass, every checksum reports `OK`, and `git diff --check` is silent.

- [ ] **Step 7: Commit the final six-card output**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals/README.md \
  generated_assets/prickly_imax_helper_launch/visuals/video-carousel \
  generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip
git commit -m "content: publish six-card IMAX carousel"
```
