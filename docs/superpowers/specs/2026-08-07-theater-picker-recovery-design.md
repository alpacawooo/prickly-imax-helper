# Theater Picker Recovery Design

## Problem

The monitor detected qualifying seat pairs, but every recent checkout attempt stopped before seat selection with `theater picker launcher not found`. The checkout flow currently recognizes only a visible region-search input or one exact legacy launcher label. It no longer recognizes the valid state where the configured theater and schedules are already loaded.

## Root Cause

The live no-seat reproduction showed two independent pre-seat failures. First, CGV changes the route to `/cnm/movieBook/movie` before rendering the theater controls. At the first check there was no region input, configured-theater element, or theater launcher. About 500 ms later the region-search input and the rest of the booking UI appeared. `CheckoutFlow.open_movie_and_theater()` checked once immediately after the route change and therefore treated a normal delayed render as a missing launcher. The configurable-target change also removed the previous "selected theater and schedules are ready" short-circuit, so an already-ready screen had no direct success path.

Second, the current picker requires three distinct actions after typing a theater: click the search suggestion, wait for the duplicate exact labels to collapse to the single actual theater row, click that row, then click the enabled `극장선택` confirmation button. The previous code clicked only the last of two exact labels and immediately waited for confirmation. That first click merely applied the search filter, so confirmation could never appear.

The follow-up live test also proved that text order and exact-label counts are not a reliable selector contract. The remaining exact label can be a real `li > button`, yet a click immediately after the search transition may not register. The flow therefore distinguishes the suggestion outside a theater-list item from the actual visible `li` row, and retries the actual row once only when neither a selected-theater chip nor the enabled confirmation button appears.

## Design

After selecting the configured movie, the runtime will inspect the visible booking state in this order:

1. After the route change, poll the booking-page state for at most 10 seconds instead of making a single immediate decision.
2. If the configured theater is visibly selected, at least one showtime is present, and the configured format is present, continue without reopening the picker.
3. If the region-search input becomes visible, use it.
4. Only after the bounded wait expires, try to open the theater picker using a small ordered set of semantic signals, including the legacy accessible label and visible theater-selection controls.
5. Require the region-search input to appear before typing the configured theater.
6. If a search suggestion and actual row share the same exact label, identify the suggestion structurally as an exact button outside a theater-list `li`, click it, and require it to disappear.
7. Identify exactly one visible exact theater button inside a list `li` and click it.
8. If neither the selected-theater chip nor an enabled `극장선택` confirmation appears after 500 ms, retry that same actual row once. Never retry when selection is already proven.
9. Require the enabled confirmation button, click it once, and prove the configured theater, format, and showtimes are ready before continuing.

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
- a region-search input rendered after a short delay: wait and continue instead of raising a missing-launcher error.
- duplicate search-suggestion and theater-row labels: require suggestion, actual row, and confirmation in that order.
- reversed suggestion/row DOM order: use structure instead of array position.
- an ignored first actual-row click: retry once only when no selection state is visible.

Run the full unit suite, lint, compile checks, and platform script parsing. Install the patched runtime locally only after all checks pass. Confirm one monitor and one Playwright driver, `armed`, and `match: null`. A controlled live no-seat test may stop after proving the theater and IMAX showtime list; it must never click a showtime, seat, voucher, or submission control.

## Release Handling

Publish the change through a pull request. The existing personal monitor may receive the patched local runtime after verification. The public-distribution gate and private-beta authorization metadata are unrelated and remain unchanged.
