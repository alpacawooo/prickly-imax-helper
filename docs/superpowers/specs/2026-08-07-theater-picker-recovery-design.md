# Theater Picker Recovery Design

## Problem

The monitor detected qualifying seat pairs, but every recent checkout attempt stopped before seat selection with `theater picker launcher not found`. The checkout flow currently recognizes only a visible region-search input or one exact legacy launcher label. It no longer recognizes the valid state where the configured theater and schedules are already loaded.

## Root Cause

`CheckoutFlow.open_movie_and_theater()` removed the previous "selected theater and schedules are ready" short-circuit when configurable targets were introduced. When CGV opens the booking page with the configured theater already selected and the picker closed, the runtime unnecessarily searches for the legacy `자주가는 CGV 목록 수정` launcher. If that exact control is absent or its accessible markup has changed, the flow fails closed.

## Design

After selecting the configured movie, the runtime will inspect the visible booking state in this order:

1. If the configured theater is visibly selected, at least one showtime is present, and the configured format is present, continue without reopening the picker.
2. If the region-search input is already visible, use it.
3. Otherwise, open the theater picker using a small ordered set of semantic signals, including the legacy accessible label and visible theater-selection controls.
4. Require the region-search input to appear before typing the configured theater.
5. Require the exact configured theater row and enabled confirmation button before continuing.

No fallback may silently select a different theater, movie, format, date, showtime, or seat.

## Safety Boundaries

- The fix changes only pre-seat navigation.
- Tests and verification must not click a real CGV seat or submit a booking.
- Same-row adjacency, configured seat policy, duplicate checks, exact IMAX voucher count, zero remaining balance, single submission, and `unknown_after_submit` behavior remain unchanged.
- If neither an already-ready state nor a supported picker launcher can be proven, the flow must still stop before seat selection.

## Tests

Add deterministic browser-flow tests for:

- configured theater and schedules already ready: no picker click and navigation continues;
- picker input already visible: no launcher click;
- legacy launcher available: it opens the picker;
- semantic theater-selection launcher available: it opens the picker;
- no ready state and no launcher: fail closed with the existing error;
- a different theater displayed: never treat it as the configured theater.

Run the full unit suite, lint, compile checks, and platform script parsing. Install the patched runtime locally only after all checks pass. Confirm one monitor and one Playwright driver, `armed`, and `match: null`; do not generate a manual CGV request or test booking.

## Release Handling

Publish the change through a pull request. The existing personal monitor may receive the patched local runtime after verification. The public-distribution gate and private-beta authorization metadata are unrelated and remain unchanged.
