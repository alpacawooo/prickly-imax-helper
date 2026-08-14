# Checkout Stage Audit and Party Render Recovery Design

## Objective

Prevent the confirmed `general admission count control not found` failure and make every future seat-match attempt auditable from detection through a terminal result without recording credentials, customer identifiers, voucher identifiers, payment data, cookies, or page contents.

This change covers three connected outcomes:

1. Wait for the delayed CGV visitor-count UI before locating the configured general-admission party-size control.
2. Add privacy-safe, correlated checkout-stage events so no attempt can silently disappear between `seat_match` and its result.
3. Audit the fourteen historical seat matches and provide a reusable verifier for future attempts.

The previously requested three-hour same-day lead-time rule and any new direct phone-push provider are separate changes and are not included here.

## Confirmed Root Cause

The live diagnostic used the dedicated logged-in Chrome profile while the resident monitor was stopped. It selected an available showtime, entered `/cnm/selectVisitorCnt`, inspected structure only, returned to the booking page, and restarted the monitor. It did not click a party-size button, seat, voucher, or payment control.

Observed timing:

- At 0, 100, and 250 ms after the route changed, the page contained no visible `일반` group and no `N 선택` controls.
- By 500 ms, the page contained a visible `role=group` with an exact `일반` label and enabled buttons with `aria-label="1 선택"` through `aria-label="8 선택"`.
- The current code waits only for the pathname and immediately evaluates the selector. The selector is structurally correct after render, but it runs too early.

The fix must therefore wait for a precise condition. A fixed sleep is not acceptable because it is slower than necessary on a fast render and can still fail on a slow render.

## Party-Control Recovery

`CheckoutFlow` will expose a narrowly scoped helper that waits up to ten seconds for all of these conditions:

- The page remains on `/cnm/selectVisitorCnt`.
- A visible `role=group` contains a visible child whose normalized text is exactly `일반`.
- That same group contains one visible, enabled button whose `aria-label` is exactly `<configured party size> 선택`.

Once the helper proves the target, `select_party_and_seats` clicks it once. It then waits for that exact button to report `aria-pressed="true"`. If the control never appears or the selected state cannot be proven, checkout stops before any seat click and records a pre-submit failure.

The implementation must not:

- select a same-number button from `청소년`, `우대`, or another group;
- use a broad page-wide `2 선택` lookup;
- use a fixed sleep as the readiness test;
- click a party-size button a second time when selected state is uncertain, because a second click could toggle the selection off;
- weaken party size, row, seat adjacency, edge exclusion, duplicate-booking, voucher-count, or zero-balance rules.

## Correlated Checkout Events

Each `seat_match` starts one checkout attempt with a locally generated, non-personal `attempt_id`. Every event for that attempt carries the same identifier.

The event stream records only:

- `attempt_id`;
- stage name;
- `started`, `passed`, or `failed` outcome;
- elapsed milliseconds where available;
- the existing redacted match summary where already permitted;
- a bounded error code or redacted error message.

No DOM snapshots, page body text, screenshots, cookies, authorization headers, account numbers, email addresses, customer numbers, voucher numbers, ticket identifiers, or payment details may enter the logs.

The checkout stage sequence is:

1. `seat_match`
2. `duplicate_guard_before`
3. `theater`
4. `date`
5. `showtime`
6. `party`
7. `seats`
8. `vouchers`
9. `zero_balance`
10. `duplicate_guard_final`
11. `submission_ready`
12. `submission`
13. `mobile_ticket`

After the attempt reaches its terminal outcome, a separate `notification` follow-up event records whether desktop and email delivery succeeded. Notification is intentionally outside the booking-stage order: a failed alert cannot turn an already verified mobile ticket into a failed booking or authorize another submission.

The stage instrumentation must wrap existing behavior without changing the order or safety boundary. It is observability, not permission to advance further during diagnostics.

Every attempt must end with exactly one terminal outcome:

- `completed`;
- `seat_vanished`;
- `checkout_pre_submit_error`;
- `blocked_duplicate`;
- `blocked_payment`;
- `unknown_after_submit`; or
- `checkout_attempt_interrupted` when the process stops before submission without recording another result.

If the process restarts from `staging`, it records the interrupted pre-submit attempt before returning to recovery. If the process restarts from or after `submitting`, existing fail-closed `unknown_after_submit` behavior remains unchanged and automatic resubmission remains forbidden.

## Historical and Future Audit

Add a local audit command under `scripts/` with two modes:

- `report`: summarize historical and current attempts without changing runtime state;
- `verify`: fail when an instrumented attempt has no terminal result, more than one terminal result, invalid stage ordering, a post-submit retry, or prohibited sensitive fields.

For legacy records without `attempt_id`, the report correlates a `seat_match` with the immediately following checkout outcome for the same date, time, and pair when one exists. It marks unprovable gaps as `legacy_unknown`; it must never invent a cause.

The first historical report must account for all fourteen recorded pairs:

- ten `theater picker launcher not found` pre-submit failures;
- two `target date is no longer open` failures caused by the CGV `오늘` label mismatch;
- one `general admission count control not found` pre-submit failure;
- one `legacy_unknown` attempt for `D28-D29`, whose result is absent from retained logs.

The audit also reports, separately from checkout attempts:

- `rate_limited`;
- `login_required`;
- browser/page closure errors;
- transport/HTTP errors;
- desktop-notification failures;
- email failures.

Historical unknowns remain visible but do not masquerade as newly passing evidence. For newly instrumented attempts, `verify` requires complete correlation.

## Testing

### Party-control tests

- The visitor-count route appears first and the `일반` group renders 500 ms later; the helper waits and succeeds.
- `일반`, `청소년`, and `우대` groups all contain `2 선택`; only the `일반` control is clicked.
- The configured control never appears; the function times out without clicking any party or seat control.
- The control appears disabled and later becomes enabled; the helper waits.
- The party control is clicked exactly once and `aria-pressed="true"` is required.
- Selected state is not proven; checkout stops without a second click or seat click.

### Audit tests

- A complete synthetic attempt passes `verify`.
- A missing terminal result fails.
- Two terminal results fail.
- A stage-order regression fails.
- A submission retry fails.
- Sensitive keys or values fail privacy validation.
- A legacy fixture representing the fourteen current matches produces the expected 10/2/1/1 classification.

### Regression and live checks

- Run the full automated suite, static checks, compile checks, and shell-script parsing checks.
- Perform a controlled live recognition check with the installed runtime: stop the monitor, enter the visitor-count route, wait until the exact configured general-admission control is found, do not click it, return to the booking page, and restart the monitor.
- Do not click a party-size control, seat, voucher, or payment control in the live diagnostic.
- Confirm repository and installed runtime hashes match after installation.
- Confirm exactly one Prickly monitor and one Playwright driver, `armed` with `match: null`, and no process using the Hermes CGV profile.

## Failure Handling

- A render timeout remains a pre-submit error and cannot cross the submission boundary.
- Logging failure must not authorize checkout to continue without a trace. Before submission, fail closed if the correlated stage result cannot be persisted.
- Notification failure is recorded but must not be interpreted as booking failure after a verified mobile ticket.
- Audit tools are read-only and must not start a browser, call CGV, select a showtime, change seats, or alter booking state.

## Completion Criteria

The work is complete only when:

- the confirmed delayed-render regression test fails on the old code and passes on the fix;
- all automated tests and checks pass;
- the historical report accounts for all fourteen seat matches without inventing the missing `D28-D29` cause;
- the future-attempt verifier rejects incomplete and unsafe histories;
- the live no-party-click recognition check passes;
- the patched runtime is installed with matching hashes;
- the resident monitor is restored to one monitor, one driver, no Hermes conflict, `armed`, and `match: null`;
- no real party-size, seat, voucher, or payment click occurs during verification.
