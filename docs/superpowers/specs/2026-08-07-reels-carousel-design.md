# Prickly IMAX Helper Reels and Carousel Design

## Goal

Create a ready-to-publish Instagram content package that demonstrates what Prickly IMAX Helper does within the first three seconds and converts viewers through the comment keyword `아이맥스` into an automated DM containing the Notion installation guide.

The creative direction is **B: product demo**. The content shows the product instead of leading with scalping claims or fear. It must never imply that a transaction occurred unless a verified mobile ticket exists.

## Deliverables

### Reel

- One 1080×1920, 30 fps, H.264 MP4, 25–30 seconds.
- No face or voiceover; screen recording, kinetic type, restrained interface motion, and platform-safe music placeholder only.
- Burned-in Korean captions inside Reels safe areas.
- Opening frame: `IMAX 취소표, 컴퓨터가 대신 기다리게 했어`.
- Closing CTA: `댓글에 “아이맥스”라고 남기면 설치 링크를 보내줄게`.

Timeline:

1. `0:00–0:03` — Hook and Prickly wordmark.
2. `0:03–0:07` — Dedicated Chrome and direct CGV login; credentials stay local.
3. `0:07–0:12` — Configurable movie, theater, format, time, party size, rows, edge exclusion, and seat priority.
4. `0:12–0:16` — `armed`, dynamic open-date monitoring, and `match:null` as a truthful waiting state.
5. `0:16–0:21` — Stylized adjacent-seat demonstration clearly labeled `DEMO`; no fabricated CGV completion screen.
6. `0:21–0:25` — Same-row adjacency, duplicate prevention, exact IMAX voucher count, zero remaining balance, and one-submit safety.
7. `0:25–0:28` — Comment-to-DM CTA.

### Carousel

- Ten 1080×1350 PNG slides, contact sheet, and ZIP.
- Reuse the approved Prickly black/graphite/red master, centered `prickly.ai` header, restrained typography, source/footer line, and fixed signature ending scale.
- Slides:
  1. Cover: `취소표 새로고침을 내 컴퓨터에게 넘겼다`.
  2. The problem: manual refresh requires constant attention.
  3. The product: a local monitor running on the user’s own Mac or Windows PC.
  4. Login and privacy: user logs in directly in dedicated Chrome; no password entry into Prickly.
  5. Editable policy: movie, theater, format, times, adjacent count, rows, edge exclusion, and priority.
  6. Monitoring: current and newly opened dates, one shared request budget, and 429 cooldown.
  7. Booking guard: same-row seats, duplicate recheck, exact IMAX vouchers, zero balance, one submission.
  8. Why IMAX vouchers are required: the helper does not automate card payment.
  9. CTA: comment `아이맥스` to receive the Notion installation guide.
  10. Fixed Prickly signature ending with restrained type and negative space.

### Publishing packet

- Reel caption, carousel caption, cover copy, alt text, pinned comment, and ten natural reply variants.
- Auto-DM copy with one button linking to the existing Notion guide; configuration is prepared but not activated or posted automatically.
- Shot list, source manifest, privacy checklist, and QA report.

## Visual and Source Rules

- Use existing Prickly logos and the fixed ending reference under `generated_assets/prickly_master`.
- Capture only redacted local Helper UI and status. Never show CGV credentials, cookies, voucher numbers, email addresses, ticket identifiers, or payment details.
- Use a stylized seat diagram for the match demonstration. Do not present a simulated booking as a real success.
- Avoid unverified resale-price claims, CGV endorsement language, and guarantees that future CGV UI changes can never break automation.
- State that the Helper runs locally, supports macOS and Windows 10/11, and requires the configured number of registered IMAX vouchers with zero remaining balance.

## Launch Gate

The current GitHub repository and Notion copy still describe a private beta. The creative assets may be completed now, but the public CTA must not be posted until all of these are true:

- the intended GitHub release is accessible to the general audience;
- the Notion guide no longer instructs users to accept a private-repository invitation;
- public-distribution authorization language matches the actual approved scope;
- the DM button resolves without authentication or permission errors.

No repository visibility change, Instagram post, or automated DM activation is part of asset production without a separate action-time confirmation.

## QA and Acceptance

- Reel opens, lasts 25–30 seconds, is 1080×1920 at 30 fps, and has readable captions at 360 px preview width.
- Every carousel slide is 1080×1350; no overflow, clipping, missing images, or low-contrast body copy.
- Contact sheet confirms consistent hierarchy and limited red accents; the last slide matches the fixed ending type scale.
- No secret, credential, personal identifier, voucher number, ticket information, or private browser state appears in source or export.
- Product claims match the local runtime and current documentation.
- The CTA and captions consistently use the keyword `아이맥스` and the same Notion destination.
- Outputs are delivered under `generated_assets/prickly_imax_helper_launch/` with separate `reel`, `carousel`, `copy`, `sources`, and `qa` folders.
