# Midnight-only CGV discovery design

## Goal

Use the entire permitted request budget for known-show seat monitoring outside the
daily CGV schedule publication window. Replace the current four seat requests to
one discovery request ratio with one Korean-calendar-day discovery cycle.

## User-approved assumptions

- CGV adds the relevant booking date and show schedule at 00:00 Korea Standard
  Time, not at arbitrary times during the day.
- Missing a date or show added after the midnight discovery is an accepted trade-off.
- Requests remain serial. The public-IP limit is still one explicit CGV
  availability request per second.
- The existing seat, duplicate-booking, voucher, zero-balance, one-submit, 429,
  and notification guards do not change.

## Selected approach

Use a time-gated discovery cycle and a continuously rotating hot-seat queue.

1. At monitor startup, rebuild the in-memory queue once:
   - fetch the currently open booking dates;
   - fetch the schedule for each open date serially;
   - filter the schedules through the configured movie, theater, format, time,
     minimum-lead, and party-size policies;
   - install the eligible shows into the hot-seat queue.
2. After bootstrap, issue only seat-map requests for known eligible shows. Rotate
   fairly through the queue with one request at a time.
3. When the local Korean date changes at 00:00, run one discovery cycle:
   - refresh the open-date list once;
   - refresh each open date's schedule serially so newly added shows on an existing
     date are also detectable;
   - atomically replace the hot-seat queue while preserving the next fair cursor
     where possible.
4. If the computer sleeps across 00:00, the first iteration after wake observes the
   Korean date change and runs the missed discovery cycle once.
5. If the process restarts at any time, startup bootstrap replaces the missed-cycle
   recovery; it does not wait until the next midnight.
6. A show that expires, violates the minimum lead time, or returns an empty seat map
   is removed from the hot queue. It is not rediscovered during the day.
7. If no hot targets remain, the monitor stays armed and idle without making CGV
   availability requests until the next midnight cycle or process restart.

## Explicit exclusions

- No `four hot requests : one discovery request` ratio.
- No ten-minute, thirty-minute, or arbitrary daytime discovery polling.
- No parallel show requests and no burst requests at midnight.
- No movie or theater UI reselection for each seat check.
- No change to checkout selection, voucher use, final submission, or ticket checks.

## Request and state flow

```text
startup
  -> open dates
  -> each date schedule (serial, >=1s apart)
  -> build hot queue
  -> seat A -> seat B -> seat C -> ... (serial, >=1s apart)
  -> KST date changes
  -> one full discovery cycle
  -> replace hot queue
  -> seat rotation resumes
```

The dedicated logged-in Chrome session and shared request budget remain the only
browser and request owners. A seat match pauses scanning and enters the existing
locked staging and checkout guard path.

## Planner changes

- Remove `hot_actions_since_discovery` and ratio-based scheduling from
  `BalancedScanPlanner`.
- Represent discovery as an explicit daily refresh cycle controlled by the monitor,
  not as every fifth planner action.
- Keep fair hot cursor preservation when schedules are replaced.
- Change estimated hot revisit time from `ceil(count * 5 / 4) * interval` to
  `count * interval` outside the midnight refresh window.
- Report whether bootstrap or the daily refresh cycle is in progress without
  storing personal data.

## Failure handling

- HTTP 429 still stops all CGV traffic for at least five minutes and uses the
  existing increasing cooldown.
- Login loss, browser closure, and request failures keep their current recovery
  behavior.
- A failed midnight discovery does not weaken the request budget. Recovery retries
  the incomplete discovery serially after the existing error backoff; it does not
  launch parallel requests.
- Checkout and notification failures follow the existing terminal-state rules.

## Test contract

Automated tests must prove:

1. Startup performs one complete serial bootstrap before seat rotation.
2. Known targets rotate continuously without ratio-based discovery.
3. A Korean date change triggers exactly one complete discovery cycle.
4. Waking or resuming after midnight triggers the missed cycle once.
5. Restarting during the day bootstraps immediately.
6. Newly discovered shows join the hot queue after the midnight cycle.
7. Empty or expired targets are removed without daytime rediscovery.
8. Revisit metrics use `target_count * minimum_interval_seconds`.
9. All requests remain subject to the shared one-second budget and 429 cooldown.
10. Existing duplicate, voucher, zero-balance, one-submit, and ticket-verification
    tests remain green.

## Acceptance criteria

- Outside bootstrap and the Korean-midnight refresh, diagnose reports the last scan
  lane as `hot` while targets exist.
- With 35 targets and a one-second minimum interval, estimated revisit time is about
  35 seconds rather than about 44 seconds.
- Exactly one Prickly monitor and one Playwright driver own the dedicated profile.
- Installation validation does not click a showtime, party count, seat, voucher, or
  payment control.
