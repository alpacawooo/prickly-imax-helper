# Odyssey Still Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce two clean 1080×1350 Odyssey carousel stills from the user-authorized `@fuckinggoodmovies` source post without generative reconstruction.

**Architecture:** Acquire the original Instagram carousel assets through the already authenticated browser, visually match the two approved Agamemnon frames, and perform deterministic center crops with macOS `sips`. Keep downloaded sources immutable and place only final derivatives in a separate output directory.

**Tech Stack:** Instagram page assets, macOS `sips`, `file`, `shasum`, Git

## Global Constraints

- Source post: `https://www.instagram.com/p/Da0v9PrAJnO/`
- Preserve the film frame, person, armor, lighting, and color exactly.
- Do not use generative fill, inpainting, retouching, or upscaling.
- Remove Instagram/browser UI by using the clean carousel assets, not by editing the screenshots.
- Final output is exactly 1080×1350 pixels.
- Add no text, logo, watermark, arrow, or pagination dot.

---

### Task 1: Acquire and identify the two authorized originals

**Files:**
- Create: `content/assets/source-originals/fuckinggoodmovies/odyssey-agamemnon-fullbody-original.jpg`
- Create: `content/assets/source-originals/fuckinggoodmovies/odyssey-giants-forest-original.jpg`

**Interfaces:**
- Consumes: the authenticated Instagram post and the two approved screenshots in the conversation.
- Produces: two immutable JPEG source files that contain no Instagram/browser UI.

- [ ] **Step 1: Traverse all carousel slides**

Open the source post, move through every slide with the `다음` button, and refresh the page-asset inventory after each move so lazy-loaded originals are observed.

- [ ] **Step 2: Bundle the matching slide on the same page state**

For each approved frame, bundle its current `CAROUSEL_ITEM` image immediately from that inventory. Do not use a CDN URL directly and do not bundle profile images, recommendations, or video thumbnails.

- [ ] **Step 3: Save with stable names**

Copy the two bundled originals into the paths listed above without re-encoding them.

- [ ] **Step 4: Verify source integrity**

Run:

```bash
file content/assets/source-originals/fuckinggoodmovies/*.jpg
shasum -a 256 content/assets/source-originals/fuckinggoodmovies/*.jpg
```

Expected: two valid JPEG images, each with a distinct SHA-256 hash and no zero-byte file.

- [ ] **Step 5: Commit source assets**

```bash
git add content/assets/source-originals/fuckinggoodmovies
git commit -m "content: add authorized Odyssey still originals"
```

### Task 2: Produce and verify the carousel derivatives

**Files:**
- Create: `content/assets/odyssey-clean/odyssey-agamemnon-fullbody-1080x1350.jpg`
- Create: `content/assets/odyssey-clean/odyssey-giants-forest-1080x1350.jpg`

**Interfaces:**
- Consumes: the two immutable source JPEGs from Task 1.
- Produces: two final 4:5 carousel-ready JPEGs.

- [ ] **Step 1: Create the output directory**

```bash
mkdir -p content/assets/odyssey-clean
```

- [ ] **Step 2: Resize and center-crop the full-body frame**

```bash
sips --resampleWidth 1080 \
  content/assets/source-originals/fuckinggoodmovies/odyssey-agamemnon-fullbody-original.jpg \
  --out /tmp/odyssey-agamemnon-fullbody-width1080.jpg
sips --cropToHeightWidth 1350 1080 \
  /tmp/odyssey-agamemnon-fullbody-width1080.jpg \
  --out content/assets/odyssey-clean/odyssey-agamemnon-fullbody-1080x1350.jpg
```

- [ ] **Step 3: Resize and center-crop the giants frame**

```bash
sips --resampleWidth 1080 \
  content/assets/source-originals/fuckinggoodmovies/odyssey-giants-forest-original.jpg \
  --out /tmp/odyssey-giants-forest-width1080.jpg
sips --cropToHeightWidth 1350 1080 \
  /tmp/odyssey-giants-forest-width1080.jpg \
  --out content/assets/odyssey-clean/odyssey-giants-forest-1080x1350.jpg
```

- [ ] **Step 4: Verify exact dimensions**

```bash
sips -g pixelWidth -g pixelHeight content/assets/odyssey-clean/*.jpg
```

Expected for both files:

```text
pixelWidth: 1080
pixelHeight: 1350
```

- [ ] **Step 5: Perform visual invariants review**

Open both sources and derivatives side by side. Confirm that the face, helmet crest, medallions, armor contours, orange lighting, skin tone, and background silhouettes are unchanged; only the outer crop may differ.

- [ ] **Step 6: Commit final derivatives**

```bash
git add content/assets/odyssey-clean
git commit -m "content: prepare clean Odyssey carousel stills"
```
