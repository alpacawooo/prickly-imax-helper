# Prickly IMAX Carousel Readability Revision Plan

**Goal:** Preserve the approved eight-card story while making Card 4 immediately understandable to a first-time viewer and repairing Card 6's clipped composition.

## Locked output

- Upload order: `01.png`, `02.png`, `03.png`, `04.mp4`, `05.mp4`, `06.png`, `07.mp4`, `08.png`.
- Card 4: seven-second continuous downward scroll through the real offline Helper setup page.
- Card 5: eight-second Helper workflow sequence.
- Card 6: static field-focused view of `연속 2석`, `D–J열`, `양끝 20% 제외`, and `3시간 이상`.
- Card 7: eight-second product outcome sequence.
- No CGV browsing, booking-state changes, fake ticket, booking identifier, QR code, or barcode.

## Implementation

1. Change the manifest contract from two videos to Cards 4, 5, and 7.
2. Capture the local setup page at full height without network access.
3. Render Card 4 as a continuous 30fps scroll inside a fixed 1080×1350 frame.
4. Replace Card 6's asymmetric clipped layout with one full-width real form crop and four large value labels.
5. Rebuild covers, mixed media, contact sheet, checksums, QA notes, and ZIP.
6. Verify motion, dimensions, codec, duration, upload order, checksum integrity, and the full product test suite.
