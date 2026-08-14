# Balanced Hot Scan Queue Design

**Date:** 2026-08-12  
**Branch:** `feat/balanced-hot-scan-queue`  
**Status:** Approved design awaiting implementation plan

## Context

The resident monitor currently rotates through every open date, fetches that date's schedule, and probes a seat map when the free-seat count changes or the prior seat-map probe is at least 60 seconds old. With 15–17 open dates and an approved public-IP limit of one explicit CGV availability request per second, a cancellation for an already known eligible show can wait behind unrelated date discovery work.

Local browser measurements show that already-rendered DOM work is not the main bottleneck: current-date recognition, general-party selection, and zero-balance proof plus a local fake submission together had a 15.3 ms median and 37.8 ms maximum over 30 offline samples. The material delay is reaching the relevant seat map and waiting for CGV page/network transitions.

The previously observed 2.86-second `E25-E26` attempt was not proof that another customer won a three-second race. That attempt stopped on the now-fixed `target date is no longer open` error. A later real attempt reached the seat stage in about 3.35 seconds, but the target seat was already unavailable when the live seat page rendered. No design can guarantee a win against a seat already held by another customer.

## Goals

- Give already known, eligible shows most of the one-request-per-second availability budget.
- Preserve dynamic discovery of newly opened dates and newly added showtimes.
- Revisit two known eligible shows in an estimated two to three request-start seconds during normal, low-latency operation.
- Report when the number of hot targets makes a three-second revisit physically impossible under the approved rate limit.
- Preserve all checkout, duplicate, voucher, zero-balance, one-submit, login, rate-limit, and privacy safeguards.

## Non-goals

- Do not exceed one explicit CGV availability request per public IP per second.
- Do not parallelize CGV availability requests.
- Do not remove either duplicate-ticket guard or any checkout proof to save time.
- Do not promise a booking or a three-second end-to-end checkout.
- Do not persist a schedule or seat cache across process restarts; a restart rebuilds trusted state from CGV.
- Do not add a new notification provider or collect credentials.
- Do not solve the parent PR's Windows `tzdata` dependency failure inside this feature. The parent dependency fix must be present before this branch can be called cross-platform green.

## Considered approaches

### 1. Keep the current full date rotation

This gives simple fairness to all dates but makes a known cancellation wait behind schedule requests for unrelated dates. It does not meet the speed goal.

### 2. Spend every request on known seat maps

This minimizes known-show revisit time but can miss new dates and newly added showtimes indefinitely. It violates the dynamic-discovery requirement.

### 3. Four hot requests followed by one discovery request — selected

This spends 80% of steady-state availability requests on known eligible seat maps and 20% on discovery. It keeps discovery alive while bounding the normal request-position revisit for two hot targets to about three seconds.

## Architecture

The monitor gains three small, independently testable scheduling units.

### Discovery cache

An in-memory cache maps each open date to its latest schedule response and refresh time. It also tracks dates that have never had a schedule fetched.

- The open-date list becomes due for refresh every 30 seconds and is served by the next discovery slot, at most one four-hot block later.
- A newly discovered or never-loaded date has priority over ordinary stale schedule refreshes.
- Otherwise the discovery queue refreshes the date whose schedule is oldest.
- Schedule results are filtered through the existing movie format, weekday/weekend time rules, and Korea-time minimum-lead policy before becoming hot targets.
- Cache contents are discarded on process restart.

### Hot queue

The hot queue contains only known shows that currently satisfy every non-seat scheduling condition. It round-robins exact seat-map requests fairly across those shows.

- A hot probe calls the existing seat-map endpoint even when the schedule's free-seat count is unchanged; this removes the current 60-second unchanged-probe delay for known eligible shows.
- A target is removed when it is no longer in an authoritative refreshed schedule, its date closes, it falls below the configured 180–1,440 minute lead, its format/time policy no longer passes, or the seat endpoint proves the target stale.
- Newly eligible shows are appended without resetting the cursor, so an existing target cannot be starved.
- When the queue is empty, all request opportunities go to discovery until at least one eligible target is known.

### Request planner

The request planner emits exactly one next availability action at a time.

Steady-state sequence:

```text
hot → hot → hot → hot → discovery → repeat
```

Every emitted action still passes through the existing cross-process `RequestBudget` immediately before the request starts. The planner does not sleep independently to emulate rate limiting and cannot create parallel requests.

Discovery action selection is:

1. refresh open dates when the 30-second deadline is due;
2. fetch a newly discovered or never-loaded date's schedule;
3. otherwise refresh the stalest cached date schedule.

When a seat map yields an eligible consecutive block, the planner stops issuing availability actions and immediately enters the existing checkout flow under the browser lock.

## Timing model

For `N` hot targets, the displayed estimated revisit time is:

```text
ceil(N × 5 / 4) × configured minimum request interval
```

This is a request-position estimate, not a service-level guarantee. CGV response time, browser rendering, a discovery request already in flight, host sleep, login loss, and rate-limit cooldown can make the observed interval longer.

- `N = 1`: estimated 2 seconds or less in the repeating plan.
- `N = 2`: estimated 3 seconds or less in the repeating plan.
- `N >= 3`: the status must make the longer estimate visible rather than claiming three-second monitoring.

The status/diagnostic output adds only privacy-safe fields:

- `hot_target_count`
- `estimated_hot_revisit_seconds`
- `discovery_queue_count`
- `oldest_schedule_age_seconds`
- `last_scan_lane` (`hot` or `discovery`)

It must not expose customer data, cookies, voucher data, recipient addresses, or raw CGV identifiers.

## Data flow

```text
open dates
  → prioritized discovery queue
  → schedule cache
  → existing eligibility policies
  → fair hot queue
  → exact seat map
  → existing seat ranking
  → existing checkout safety flow
```

The discovery schedule's free-seat count may help diagnostics, but it must not be used as the sole reason to suppress hot seat-map polling. Exact available-seat labels remain authoritative for a candidate block.

## Error handling

- **HTTP 429:** preserve the shared global cooldown, exponential extension, and longer `Retry-After`; clear no cache merely to hide the event and issue no request during cooldown.
- **HTTP 401/403 or missing login:** enter `login_required`; do not keep advancing either queue.
- **Transient request/browser error:** use the existing bounded recovery behavior. The failed action is not immediately repeated in a tight loop.
- **Stale seat target:** remove it from the hot queue and prioritize its date for discovery refresh.
- **Seat vanished during checkout:** return to `armed`; retain the show only if its cached schedule remains eligible, then let fair rotation probe it again.
- **Checkout guard unavailable:** preserve the existing five-minute deferred retry and do not spend the fast lane retrying the guarded checkout.
- **Restart:** rebuild open dates, schedules, and hot targets from CGV before issuing hot probes.

## Safety invariants

- All CGV availability calls remain serialized through the shared request budget.
- The existing browser lock covers monitoring and checkout.
- The pair is re-ranked from the latest exact seat map.
- Existing tickets are checked before staging and immediately before submission.
- The configured number of vouchers, every selected seat, a zero remaining balance, and exactly one final action remain mandatory.
- Submission remains single-use; an uncertain post-submit result is never retried automatically.
- No existing time, row, adjacency, edge-exclusion, center-priority, or minimum-lead condition is weakened.

## Logging and observability

Do not write one log event per successful hot probe; that would create unnecessary local log growth. Update the heartbeat summary after each action and log only meaningful topology changes:

- hot queue built or materially changed;
- target pruned with a bounded, non-sensitive reason;
- new date discovered;
- rate-limit, login, or monitor error through the existing event types;
- seat match and correlated checkout stages through the existing attempt recorder.

## Test design

All new scheduler tests use fake clocks and fake CGV responses. They make no real CGV request and click no browser control.

Required tests:

1. Two hot targets produce four fair hot actions followed by one discovery action.
2. Two targets are each revisited within three request positions, including across the discovery slot.
3. With no hot targets, every action is discovery until an eligible schedule is cached.
4. A newly opened date receives the next available schedule-discovery priority.
5. Otherwise the stalest schedule date is refreshed first.
6. New targets join without starving existing targets.
7. Closed, removed, stale, wrong-format, wrong-time, and below-minimum-lead targets are pruned.
8. A seat match stops planning and enters checkout once.
9. HTTP 429 prevents every subsequent fake request until the shared cooldown expires.
10. Login loss advances neither queue.
11. Status estimates match the queue size and never claim a guarantee.
12. Existing monitor, duplicate, payment, notification, and audit regression suites remain green.

## Rollout and verification

1. Implement in the isolated feature branch with test-first changes.
2. Run the full unit suite, Ruff, compileall, installer shell/PowerShell checks, lock validation, and diff checks.
3. Require macOS and Windows hosted CI to pass; the known parent `tzdata` dependency issue must be fixed first or incorporated from its reviewed fix.
4. Install only when the resident is `armed` with `match: null`.
5. Preserve config, browser profile, request-budget state, and logs.
6. Verify repository/installed hashes, `doctor`, one monitor, one Playwright driver, and zero Hermes CGV-profile processes.
7. Validate lane scheduling from redacted telemetry. Do not click a showtime, party, seat, voucher, or payment control merely to test this feature.

## Acceptance criteria

- The planner produces a deterministic 4:1 hot/discovery request sequence whenever hot targets exist.
- Two hot targets have an estimated revisit of no more than three seconds at the configured one-second minimum interval.
- Open-date refresh becomes due every 30 seconds and starts by the next discovery slot (normally near 30 seconds and no later than about 35 request-position seconds for two hot targets); a new date's schedule is prioritized at the following discovery opportunity.
- Existing-date schedule refresh remains fair and completes in roughly one to two minutes for the current 15–17-date range under normal response latency.
- The runtime never exceeds the approved rate, never requests in a 429 cooldown, and never weakens checkout safety.
- Diagnostics disclose when the target count makes a three-second revisit impossible.
- All offline tests and both hosted operating-system checks pass before integration.
