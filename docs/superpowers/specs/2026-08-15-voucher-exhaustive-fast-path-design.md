# Voucher-exhaustive checkout fast path

## Goal

Reduce the time from a detected seat block to selecting those seats for the
owner's voucher-only setup. The public default remains duplicate-safe. The
owner can explicitly enable a fast path that omits both mobile-ticket duplicate
lookups and relies on the existing exact voucher, zero-balance, one-submit, and
terminal-stop guards.

## Evidence and expected latency impact

Redacted local stage logs contain two completed `duplicate_guard_before`
measurements:

- 0.733 seconds on 2026-08-10;
- 3.495 seconds on 2026-08-15.

Removing the first lookup therefore saves approximately 0.7–3.5 seconds before
the theater/date/showtime/party/seat path. The final duplicate lookup has no
completed local timing sample. If it has similar latency, the total path to the
single final submission should improve by approximately 1.5–7 seconds. That
second range is an estimate, not a measured guarantee.

The same logs show that theater preparation took 1.773 seconds in one attempt
and 10.654 seconds in another. Duplicate removal improves the requested path but
does not eliminate the separate theater-preparation bottleneck.

## Selected design

Keep `prevent_duplicate_booking: true` as the public/setup default. Accept an
explicit `false` value as an advanced local policy. The checkout flow reads the
policy once:

- `true`: run `duplicate_guard_before` and `duplicate_guard_final` exactly as
  today;
- `false`: omit both duplicate stages and proceed directly from match detection
  to theater preparation, then from zero-balance proof to `submission_ready`.

The owner's installed configuration will be changed to `false` only after the
new runtime passes tests and the resident state is `armed` with `match: null`.

## Guards that remain mandatory

The fast path does not weaken any of these checks:

- exactly the configured same-row consecutive seats;
- configured party size and exact seat labels;
- registered IMAX voucher count equal to party size;
- remaining payment balance exactly zero;
- exactly one enabled final purchase button;
- one submission attempt per checkout flow;
- no automatic retry after an uncertain submission;
- mobile-ticket proof before reporting completion;
- terminal stop after completed, blocked-payment, or unknown-after-submit.

The configuration validator continues to require a Boolean
`prevent_duplicate_booking`; missing values retain the safe `true` default.

## Failure behavior

- A vanished seat returns to monitoring without applying a different seat.
- Missing vouchers, an unproven zero balance, or an ambiguous purchase button
  stops before submission.
- Any uncertainty after the one final click becomes `unknown_after_submit` and
  is never retried.
- Re-enabling `prevent_duplicate_booking` restores both duplicate checks without
  reinstalling the runtime.

## Tests

Add regression coverage that proves:

1. the safe default still executes both duplicate guards;
2. explicit `false` executes neither duplicate guard;
3. the fast path preserves theater, date, showtime, party, seat, voucher,
   zero-balance, submission, and mobile-ticket stage order;
4. configuration accepts only Boolean values;
5. all existing payment, single-submit, and unknown-after-submit tests remain
   green.

No test or installation verification will click a live CGV showtime, party,
seat, voucher, or payment control.
