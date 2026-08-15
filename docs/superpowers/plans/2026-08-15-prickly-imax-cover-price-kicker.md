# Prickly IMAX Cover Price Kicker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing Odyssey still and add `30만 원까지 오른 용아맥 표.` as a restrained red kicker above the existing persona question.

**Architecture:** Store the approved copy in the carousel manifest, render it through a dedicated first-card kicker element, and leave cards 2–8 untouched. Rebuild the deterministic carousel package and compare cards 2–8 hashes before and after rendering.

**Tech Stack:** Python 3.12, HTML/CSS, Pillow, Playwright, ffmpeg, unittest

## Global Constraints

- Card 1 background remains `odyssey-agamemnon-fullbody-1080x1350.jpg`.
- Kicker copy is exactly `30만 원까지 오른 용아맥 표.` in Prickly red.
- Main headline is exactly `며칠째 새로고침 중인 사람?` at 86px.
- Supporting copy remains exactly `나도 그랬음.`.
- Cards 2–8 must not change.
- Output remains 1080×1350 and the ZIP checksum is regenerated.

---

### Task 1: Add and render the approved price kicker

**Files:**
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py`
- Modify: `generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py`
- Modify: `docs/superpowers/specs/2026-08-15-prickly-imax-resale-evidence-cover-design.html`

**Interfaces:**
- Consumes: card 1 manifest fields and the existing `cinematic_page()` renderer.
- Produces: card 1 `kicker: str`, `.cover-kicker` markup, `cards/01.png`, and a rebuilt carousel ZIP.

- [ ] **Step 1: Record cards 2–8 hashes and write the failing test**

```python
def test_cover_uses_approved_price_kicker_copy():
    card = self.load_cards()[0]
    self.assertEqual(card["kicker"], "30만 원까지 오른 용아맥 표.")
    self.assertEqual(card["headline"], "며칠째 새로고침 중인 사람?")
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    self.assertIn('class="cover-kicker"', source)
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python3 -m unittest generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py`

Expected: FAIL because card 1 has no `kicker` and still contains the old two-line headline.

- [ ] **Step 3: Implement the manifest and renderer change**

Add this manifest field and headline:

```json
"kicker": "30만 원까지 오른 용아맥 표.",
"headline": "며칠째 새로고침 중인 사람?"
```

Render the kicker immediately before card 1 `<h1>` and style it at 44px, red, left aligned, with an 18px bottom gap. Do not change the first-card background, 86px headline, supporting copy, or cards 2–8 renderers.

- [ ] **Step 4: Update the HTML visual spec to the approved text-only direction**

Remove the proposed resale screenshot layer from the target mockup. Show the original Odyssey still with the red kicker, white headline, supporting copy, and existing footer hierarchy.

- [ ] **Step 5: Run tests and rebuild**

Run:

```bash
python3 -m unittest generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py
PYTHONPATH=/Users/woojinyoung/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages \
  .venv/bin/python generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py --video-carousel
```

Expected: all tests pass and eight publishable cards plus the ZIP are regenerated.

- [ ] **Step 6: Verify visual and regression boundaries**

Confirm card 1 is 1080×1350, the kicker and headline do not clip, cards 2–8 hashes match the recorded values, `git diff --check` passes, and a new ZIP SHA-256 is printed.

- [ ] **Step 7: Commit the focused change**

```bash
git add generated_assets/prickly_imax_helper_launch/visuals/carousel_manifest.json \
  generated_assets/prickly_imax_helper_launch/visuals/build_visuals.py \
  generated_assets/prickly_imax_helper_launch/visuals/tests/test_video_carousel.py \
  generated_assets/prickly_imax_helper_launch/visuals/video-carousel \
  generated_assets/prickly_imax_helper_launch/visuals/prickly-imax-helper-video-carousel.zip \
  docs/superpowers/specs/2026-08-15-prickly-imax-resale-evidence-cover-design.html
git commit -m "content: add resale price kicker to cover"
```
