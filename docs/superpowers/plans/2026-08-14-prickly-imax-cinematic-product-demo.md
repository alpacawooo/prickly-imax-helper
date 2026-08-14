# Prickly IMAX Cinematic Product Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the approved eight-card Prickly IMAX carousel as 1080×1350 PNG covers and MP4 cards that preserve the current claims and flow while removing repeated AI-template composition, fake interface chrome, and decorative motion.

**Architecture:** Keep the existing offline asset pipeline and eight-card manifest. Extend the manifest with explicit composition and motion contracts, render each card from its own art-directed HTML composition, and encode either a restrained still-image move or a real offline product-screen move with FFmpeg. The build must not browse CGV or mutate booking state; product evidence comes from the local setup page, redacted diagnose output, local event history, and local installation guide.

**Tech Stack:** Python 3.12, HTML/CSS, Playwright with local Chrome, Pillow, FFmpeg/FFprobe, pytest, SHA-256 packaging.

## Global Constraints

- Preserve exactly eight cards in this order: problem, sold-out evidence, repeated failure, Helper setup, monitoring, conditions, result/guide, comment CTA.
- Preserve the approved claims and the keyword `아이맥스`; do not introduce seat guarantees, CGV partnership claims, fake booking success, or card-payment automation.
- Every output is 1080×1350, H.264, yuv420p, 30fps, muted, with durations `6 / 6 / 7 / 9 / 8 / 7 / 9 / 6` seconds.
- Use only approved Odyssey stills and real offline Prickly surfaces. Do not create fake browser, terminal, phone, ticket, or success UI.
- Do not browse CGV, create CGV requests, select showtimes or seats, apply vouchers, or change booking state during production or verification.
- Do not expose account names, email addresses, cookies, voucher numbers, booking identifiers, profile paths, or unredacted logs.
- Apply `/content/DESIGN.md`: one focal scene per card, imagery or product surface occupying at least 60% of the canvas, no repeated 66/34 template, no decorative pills/badges/kickers, and no equal-weight card grids inside a slide.
- Apply `emil-design-eng`, `find-animation-opportunities`, `animation-vocabulary`, and `review-animations` only to meaningful motion; the static frame must remain understandable.

---

## File Map

- Modify `generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json` — approved copy, per-card composition, evidence source, and motion recipe.
- Modify `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py` — offline evidence capture, eight distinct HTML compositions, motion encoding, QA, and packaging.
- Create `tests/test_carousel_visuals.py` — manifest contract, anti-template assertions, privacy boundaries, output metadata, and package checks.
- Modify `generated_assets/prickly_imax_helper_launch/visuals/README.md` — build and upload instructions for the cinematic eight-card package.
- Modify `generated_assets/prickly_imax_helper_launch/visuals/qa-report.md` — final mechanical and human-review evidence.
- Modify `generated_assets/prickly_imax_helper_launch/visuals/sources-and-claim-notes.md` — precise source and redaction ledger.
- Generate `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/` — covers, cards, contact sheet, QA report, and checksums.
- Generate `generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip` — publishable package.

### Task 1: Lock the eight-card visual contract

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py:37-59`
- Create: `tests/test_carousel_visuals.py`

**Interfaces:**
- Consumes: the existing `load_carousel_manifest() -> list[dict[str, object]]` entry point.
- Produces: validated card dictionaries with `number`, `duration`, `source_type`, `source`, `headline`, `supporting`, `footer`, `composition`, `text_anchor`, and `motion`.

- [x] **Step 1: Write failing manifest-contract tests**

```python
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("prickly_visual_builder", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_locks_eight_distinct_compositions():
    cards = load_builder().load_carousel_manifest()
    assert [card["number"] for card in cards] == list(range(1, 9))
    assert [card["duration"] for card in cards] == [6, 6, 7, 9, 8, 7, 9, 6]
    assert len({card["composition"] for card in cards}) >= 6
    assert all(card["text_anchor"] in {"bottom-left", "top-left", "bottom", "right", "center-left"} for card in cards)


def test_manifest_rejects_fake_ui_sources():
    cards = load_builder().load_carousel_manifest()
    banned = {"fake-browser", "fake-terminal", "phone-mockup", "fake-ticket"}
    assert not ({card["source_type"] for card in cards} & banned)
```

- [x] **Step 2: Run the focused tests and verify failure**

Run:

```bash
UV_CACHE_DIR=/Users/woojinyoung/.prickly-imax-helper/cache/uv uv run --locked pytest tests/test_carousel_visuals.py -v
```

Expected: FAIL because `composition` and `text_anchor` do not exist.

- [x] **Step 3: Add the approved composition values to the manifest**

Use these exact values, keeping the existing durations and approved Korean copy:

```json
[
  [1, "full-bleed-still", "bottom-left", "slow-push"],
  [2, "evidence-overlay", "top-left", "slow-push"],
  [3, "single-seat-evidence", "bottom", "evidence-pan"],
  [4, "setup-full-frame", "bottom-left", "guided-focus"],
  [5, "monitor-full-frame", "bottom-left", "proof-pan"],
  [6, "conditions-asymmetric", "right", "guided-scroll"],
  [7, "setup-monitor-guide", "bottom-left", "three-scene-sequence"],
  [8, "black-note-cta", "center-left", "text-reveal"]
]
```

Card 3 uses the user-provided real CGV screenshot already stored locally. It supports only the claim that a displayed single seat is not an adjacent pair; it must not be used to claim that a seat disappeared. Cards 4–7 use real offline local surfaces.

- [x] **Step 4: Strengthen `validate_manifest()`**

Add assertions for required keys, approved text anchors, at least six distinct compositions, allowed motion names, existing source files where a source path is present, and forbidden source types. Raise `ValueError` with the card number and missing or invalid field.

- [x] **Step 5: Run the focused tests**

Run the Task 1 pytest command again. Expected: PASS.

- [x] **Step 6: Commit the contract**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py \
  tests/test_carousel_visuals.py
git commit -m "test: lock cinematic carousel contract"
```

### Task 2: Replace repeated templates with eight art-directed covers

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py:95-278`
- Modify: `tests/test_carousel_visuals.py`

**Interfaces:**
- Consumes: validated cards from `load_carousel_manifest()` and real local asset paths returned by `setup_preview()`, `install_guide_preview()`, and the new `redacted_monitor_preview()`.
- Produces: `video_carousel_covers(setup_png, monitor_png, guide_png, cards) -> list[str]` with eight distinct 1080×1350 HTML documents.

- [x] **Step 1: Write failing anti-template HTML tests**

```python
def test_cover_html_has_eight_distinct_compositions_and_no_fake_chrome():
    builder = load_builder()
    cards = builder.load_carousel_manifest()
    html = builder.video_carousel_covers(
        Path("/tmp/setup.png"),
        Path("/tmp/monitor.png"),
        Path("/tmp/guide.png"),
        cards,
    )
    assert len(html) == 8
    joined = "\n".join(html)
    for banned in ("browserbar", "status-grid", "phone", "pill", "eyebrow"):
        assert banned not in joined
    for composition in {card["composition"] for card in cards}:
        assert any(f'data-composition="{composition}"' in page for page in html)
```

- [x] **Step 2: Run the test and verify failure**

Run the focused pytest command. Expected: FAIL because the old renderer uses repeated `header`, `footer`, `eyebrow`, `card`, and fake status/browser components.

- [x] **Step 3: Implement shared typography and minimal chrome**

Keep only canvas size, Korean type family, Prickly red, text-safe insets, page number, full-bleed media, and accessible contrast utilities in `base_css()`. Remove reusable pill, card-grid, fake browser bar, fake terminal/status card, and repeated footer-label CSS from the video-carousel path. Legacy reel functions may remain untouched.

- [x] **Step 4: Implement each approved card composition**

Implement all eight branches inside `video_carousel_covers()`:

1. Full-bleed Agamemnon still, dark lower edge, bottom-left copy.
2. Full-bleed giants still, left evidence line and sold-out claim, no detached white copy panel.
3. User-provided CGV seat screen as one full evidence field. Hold on `1석/624석`, pan to the isolated seat, then state that an adjacent pair is unavailable; no claim that the seat disappeared.
4. Actual setup page filling the canvas with only thin labels for movie, time, and adjacent seats.
5. Actual redacted monitor output filling the canvas, with the claim in natural negative space.
6. Actual setup page cropped left with condition copy in the right negative space; no chips or feature cards.
7. A cover frame based on the real installation guide, reserved for the three-scene video in Task 3.
8. Black note CTA with restrained type scale based on `assets/signature-ending-reference.png`; no phone mockup.

- [x] **Step 5: Render covers and inspect the contact sheet**

Run:

```bash
/Users/woojinyoung/.prickly-imax-helper/venv/bin/python \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py --video-carousel
```

Open `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/contact-sheet.png` with `view_image`. Check focal order, image/copy ratio, text clipping, repeated geometry, and whether each card still reads at 216×270.

- [x] **Step 6: Run the focused tests and commit**

```bash
UV_CACHE_DIR=/Users/woojinyoung/.prickly-imax-helper/cache/uv uv run --locked pytest tests/test_carousel_visuals.py -v
git add generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py tests/test_carousel_visuals.py
git commit -m "content: art direct cinematic carousel covers"
```

### Task 3: Capture real offline product evidence and apply restrained motion

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py:145-333`
- Modify: `tests/test_carousel_visuals.py`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/assets/helper-monitor-preview.png`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/build/scene-frames/`

**Interfaces:**
- Consumes: local setup HTML, redacted `prickly-imax diagnose`, the user-provided single-seat CGV screenshot, local guide HTML, cover PNGs, and manifest motion names.
- Produces: `redacted_monitor_preview() -> Path`, `render_motion_frames(card, cover) -> list[Path]`, and eight final MP4 files.

- [x] **Step 1: Write failing privacy and motion tests**

```python
def test_motion_recipes_are_restrained():
    builder = load_builder()
    recipes = builder.motion_recipes()
    assert recipes["slow-push"]["max_scale"] <= 1.05
    assert recipes["guided-focus"]["transition_ms"] <= 300
    assert recipes["guided-scroll"]["transition_ms"] <= 300
    assert recipes["text-reveal"]["transition_ms"] <= 300


def test_redaction_blocks_private_fields():
    builder = load_builder()
    sample = "email=a@example.com cookie=secret voucher=1234 profile=/Users/name/private"
    redacted = builder.redact_visual_evidence(sample)
    assert "a@example.com" not in redacted
    assert "secret" not in redacted
    assert "1234" not in redacted
    assert "/Users/name/private" not in redacted
```

- [x] **Step 2: Run the tests and verify failure**

Run the focused pytest command. Expected: FAIL because the recipe and visual-redaction functions do not exist.

- [x] **Step 3: Add exact motion recipes**

Implement `motion_recipes()` with these caps:

```python
{
    "slow-push": {"max_scale": 1.04, "transition_ms": 0},
    "staged-reveal": {"max_scale": 1.00, "transition_ms": 220},
    "guided-focus": {"max_scale": 1.02, "transition_ms": 220},
    "proof-pan": {"max_scale": 1.01, "transition_ms": 0},
    "guided-scroll": {"max_scale": 1.00, "transition_ms": 240},
    "three-scene-sequence": {"max_scale": 1.00, "transition_ms": 220},
    "text-reveal": {"max_scale": 1.00, "transition_ms": 200},
}
```

Use `ease-out` for entrances, transform and opacity for overlays, and no perpetual loops. Each final second must hold a stable readable frame.

- [x] **Step 4: Capture real offline evidence**

Render the setup page and installation guide through the existing offline functions. Run the installed CLI's redacted diagnose command without opening Chrome or contacting CGV, pass its output through `redact_visual_evidence()`, and render it as plain actual output rather than invented dashboard tiles. Use the saved Card 3 screenshot only as offline evidence for `one isolated seat / no adjacent pair`; do not browse CGV or infer that the seat disappeared.

- [x] **Step 5: Implement card-specific video assembly**

Use FFmpeg for Cards 1–2 slow pushes. Render timed HTML frames for Cards 3–6 and 8. Build Card 7 as `setup completed → armed/match:null → installation guide` with 220ms opacity transitions and a stable final guide frame. Keep all cards muted and use H.264/yuv420p/30fps.

- [x] **Step 6: Review animations with the installed motion skills**

Run `find-animation-opportunities` against the card sequence, apply only suggestions that explain state or reading order, use `animation-vocabulary` to name each accepted transition, and run `review-animations` on the final motion code. Reject ambient motion, simultaneous competing moves, bounce, elastic easing, glow, and decorative parallax.

- [x] **Step 7: Run tests and commit**

```bash
UV_CACHE_DIR=/Users/woojinyoung/.prickly-imax-helper/cache/uv uv run --locked pytest tests/test_carousel_visuals.py -v
git add generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py tests/test_carousel_visuals.py
git commit -m "content: add restrained real-screen carousel motion"
```

### Task 4: Add mechanical QA and human visual review gates

**Files:**
- Modify: `tests/test_carousel_visuals.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py:334-397`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/qa-report.md`

**Interfaces:**
- Consumes: eight cover PNGs, eight MP4s, contact sheet, manifest, and `content/DESIGN.md`.
- Produces: `verify_video_carousel(cards, covers, videos) -> dict[str, object]` and a complete QA report.

- [x] **Step 1: Write failing output-metadata tests**

```python
def test_verify_video_carousel_rejects_wrong_count(tmp_path):
    builder = load_builder()
    try:
        builder.verify_video_carousel([], [], [])
    except ValueError as exc:
        assert "eight" in str(exc).lower()
    else:
        raise AssertionError("wrong card count must fail")


def test_design_contract_has_no_template_smell():
    text = (ROOT / "content/DESIGN.md").read_text(encoding="utf-8")
    assert "동일한 크기의 카드와 박스를 반복" in text
    assert "가짜 브라우저" in text
    assert "사람이 편집한 장면처럼 보이는가" in text
```

- [x] **Step 2: Run the tests and verify failure**

Run the focused pytest command. Expected: FAIL because `verify_video_carousel()` does not exist.

- [x] **Step 3: Implement exact verification**

For each MP4, use FFprobe to assert 1080×1350, H.264, yuv420p, 30fps, no audio stream, and manifest duration within ±0.10 seconds. For each PNG, assert 1080×1350 and nonempty file size. Verify cover/video counts, filenames `01`–`08`, contact sheet presence, README, source ledger, QA report, and SHA256SUMS coverage.

- [x] **Step 4: Run the complete build and automated tests**

```bash
/Users/woojinyoung/.prickly-imax-helper/venv/bin/python \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py --video-carousel
UV_CACHE_DIR=/Users/woojinyoung/.prickly-imax-helper/cache/uv uv run --locked pytest tests/test_carousel_visuals.py -v
UV_CACHE_DIR=/Users/woojinyoung/.prickly-imax-helper/cache/uv uv run --locked pytest -q
```

Expected: eight covers, eight MP4s, full focused suite PASS, full product suite PASS.

- [x] **Step 5: Perform human visual QA**

Use `view_image` on the approved design preview and the generated contact sheet in the same pass. Inspect at least: slide count, focal point, mobile legibility, claim-to-image match, image crop, no repeated 66/34 split, no fake UI chrome, red-accent frequency, CTA negative space, and safe-zone clipping. Extract representative first/middle/last MP4 frames and compare them to their cover compositions.

- [x] **Step 6: Commit QA changes**

```bash
git add tests/test_carousel_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/qa-report.md
git commit -m "test: enforce cinematic carousel QA"
```

### Task 5: Package the final publishable carousel

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/README.md`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/sources-and-claim-notes.md`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/covers/01.png` through `08.png`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/cards/01.mp4` through `08.mp4`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/contact-sheet.png`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/video-carousel/SHA256SUMS`
- Generate: `generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip`

**Interfaces:**
- Consumes: all verified Task 4 outputs.
- Produces: one ordered, checksummed ZIP ready for Instagram carousel upload.

- [x] **Step 1: Update the source and safety ledger**

Record the two approved Odyssey still sources, the user-provided single-seat CGV screenshot, local setup renderer, redacted diagnose source, local guide renderer, excluded benchmark recordings, no-CGV-request production boundary, and the exact reason no fake browser/terminal/phone UI appears.

- [x] **Step 2: Update operator instructions**

Document upload order `01.mp4`–`08.mp4`, cover order, muted-first behavior, optional Instagram music addition, keyword `아이맥스`, and checksum verification:

```bash
cd generated_assets/prickly_imax_helper_launch/visuals/video-carousel
shasum -a 256 -c SHA256SUMS
```

- [x] **Step 3: Rebuild from a clean generated directory**

Move the current generated `video-carousel` directory to a timestamped temporary backup outside the repository, run the approved build once, and verify the new package. Do not delete the previous output until the new ZIP and checksums pass.

- [x] **Step 4: Verify the package and repository diff**

```bash
cd generated_assets/prickly_imax_helper_launch/visuals/video-carousel
shasum -a 256 -c SHA256SUMS
cd /Users/woojinyoung/Documents/Playground/prickly-imax-helper
git diff --check
git status --short
```

Expected: every checksum reports `OK`; only planned content, test, documentation, and generated carousel files are changed.

- [x] **Step 5: Commit the package**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals/README.md \
  generated_assets/prickly_imax_helper_launch/visuals/sources-and-claim-notes.md \
  generated_assets/prickly_imax_helper_launch/visuals/video-carousel \
  generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip
git commit -m "content: package cinematic IMAX carousel"
```

## Final Review Checklist

- The result contains eight cards, not nine.
- Existing approved claims, safety language, and CTA remain intact.
- Cards 1–2 use approved Odyssey stills without generative edits.
- Cards 3–7 show actual redacted local evidence, not invented interface chrome.
- Card 8 matches the restrained Prickly ending scale and negative space.
- The eight cards do not repeat one image/copy template.
- Motion is restrained, purposeful, and understandable when paused.
- No CGV request or booking-state mutation occurred during the build.
- Automated visual tests and the full product test suite pass.
- Contact sheet and representative video frames pass human visual review.
- ZIP and SHA-256 verification pass.
