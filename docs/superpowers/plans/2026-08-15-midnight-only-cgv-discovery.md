# Midnight-only CGV Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `4 hot : 1 discovery` request ratio with one serial startup bootstrap and one serial Korea-midnight discovery cycle, using all other permitted requests for known-show seat monitoring.

**Architecture:** `BalancedScanPlanner` becomes a hot-target rotation planner with atomic discovery replacement and no internal discovery cadence. `monitor.run` owns the Korean-calendar-day gate: it performs a full serial discovery at startup and after a KST date change, then requests only known seat maps until the next date change. The existing `CgvSession` request budget remains the single rate-limiting authority.

**Tech Stack:** Python 3.12, `unittest`, `zoneinfo`, Playwright-backed CGV session, macOS LaunchAgent, zsh installer.

## Global Constraints

- CGV date and show discovery runs once at startup and once when the Korea Standard Time calendar date changes at 00:00.
- A wake after midnight runs the missed daily discovery once; a process restart always bootstraps immediately.
- Outside bootstrap and midnight discovery, issue only serial known-show seat-map requests.
- Never add ten-minute or arbitrary daytime discovery polling.
- Never parallelize CGV availability requests; preserve the public-IP minimum interval of one second.
- Preserve 429 cooldown, duplicate-booking, voucher-count, zero-balance, one-submit, ticket-verification, privacy, and browser-lock behavior.
- Installation verification must not click a showtime, party count, seat, voucher, or payment control.

---

## File map

- `runtime/prickly_imax_helper/scheduler.py`: fair hot-target rotation, atomic daily discovery replacement, revisit metrics.
- `runtime/prickly_imax_helper/monitor.py`: KST day gate, startup/midnight discovery orchestration, idle behavior.
- `tests/test_scheduler_and_cgv.py`: planner contract and metrics.
- `tests/test_monitor_safety.py`: startup, same-day, wake-after-midnight, sequential discovery, checkout-safety regressions.
- `README.md`: user-visible monitoring cadence.
- `plugins/prickly-imax-helper/skills/prickly-imax-booking/references/runtime-contract.md`: plugin runtime contract matching the implemented cadence.
- `docs/beta-readiness.md`: exact local verification evidence only if the repository already records current runtime evidence there.

---

### Task 1: Convert the planner to continuous hot-seat rotation

**Files:**
- Modify: `runtime/prickly_imax_helper/scheduler.py`
- Modify: `tests/test_scheduler_and_cgv.py`

**Interfaces:**
- Produces: `BalancedScanPlanner.replace_discovery(dates: list[str], schedules: dict[str, list[dict[str, Any]]], *, now: float) -> None`
- Produces: `BalancedScanPlanner.next_hot_action() -> ScanAction | None`
- Preserves: `BalancedScanPlanner.complete(action: ScanAction) -> None`, `remove_hot_target`, `metrics`, and fair cursor behavior.
- Removes: ratio scheduling through `hot_actions_since_discovery`, `_next_discovery`, and `next_action(self, *, now: float, open_dates_due: bool)`.

- [ ] **Step 1: Replace ratio tests with failing continuous-rotation tests**

In `tests/test_scheduler_and_cgv.py`, replace the ratio/discovery planner tests with tests equivalent to:

```python
def test_planner_rotates_known_shows_without_inserting_discovery(self):
    planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
    shows = {
        "20260820": [
            {"scnsNo": "18", "scnSseq": "1", "time": "19:00"},
            {"scnsNo": "18", "scnSseq": "2", "time": "22:00"},
        ]
    }
    planner.replace_discovery(["20260820"], shows, now=10.0)
    actions = []
    for _ in range(6):
        action = planner.next_hot_action()
        actions.append(action)
        planner.complete(action)
    assert [action.show["scnSseq"] for action in actions] == ["1", "2", "1", "2", "1", "2"]
    assert {action.lane for action in actions} == {"hot"}

def test_planner_returns_none_when_no_hot_targets_exist():
    planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
    planner.replace_discovery(["20260820"], {"20260820": []}, now=1.0)
    assert planner.next_hot_action() is None

def test_atomic_discovery_replacement_preserves_next_fair_target():
    planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
    first = {"scnsNo": "18", "scnSseq": "1", "time": "19:00"}
    second = {"scnsNo": "18", "scnSseq": "2", "time": "22:00"}
    third = {"scnsNo": "18", "scnSseq": "3", "time": "24:30"}
    planner.replace_discovery(["20260820"], {"20260820": [first, second]}, now=1.0)
    action = planner.next_hot_action()
    planner.complete(action)
    planner.replace_discovery(["20260820"], {"20260820": [first, second, third]}, now=2.0)
    assert planner.next_hot_action().show["scnSseq"] == "2"

def test_revisit_metric_uses_only_hot_target_count():
    planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
    planner.replace_discovery(
        ["20260820"],
        {"20260820": [
            {"scnsNo": "18", "scnSseq": str(index), "time": "19:00"}
            for index in range(35)
        ]},
        now=10.0,
    )
    assert planner.metrics(now=20.0)["estimated_hot_revisit_seconds"] == 35.0
```

- [ ] **Step 2: Run the focused tests and confirm the intended RED state**

Run:

```bash
PYTHONPATH=runtime .venv/bin/python -m unittest tests.test_scheduler_and_cgv.SchedulerTests -v
```

Expected: failures because `replace_discovery` and `next_hot_action` do not exist and the current metric still includes the 5/4 discovery factor.

- [ ] **Step 3: Implement the minimal hot-only planner**

In `scheduler.py`:

```python
def replace_discovery(
    self,
    dates: list[str],
    schedules: dict[str, list[dict[str, Any]]],
    *,
    now: float,
) -> None:
    normalized_dates = list(dict.fromkeys(dates))
    normalized_schedules = {
        ymd: [{**show, "ymd": ymd} for show in schedules.get(ymd, [])]
        for ymd in normalized_dates
    }
    self.open_dates = normalized_dates
    self.schedules = normalized_schedules
    self.schedule_refreshed_at = {ymd: now for ymd in normalized_dates}
    self.invalidated_hot_keys.clear()
    self._replace_hot_targets([
        show
        for ymd in normalized_dates
        for show in normalized_schedules[ymd]
    ])

def next_hot_action(self) -> ScanAction | None:
    if not self.hot_targets:
        return None
    show = self.hot_targets[self.hot_cursor]
    return ScanAction("hot", "seats", ymd=str(show["ymd"]), show=show)
```

Remove the ratio-only fields and methods. Simplify `complete` so it advances only completed hot actions. Change the revisit estimate to:

```python
"estimated_hot_revisit_seconds": float(count * self.minimum_interval_seconds)
```

Keep removed targets excluded until the next successful `replace_discovery`; remove the obsolete `prioritize_discovery` argument.

- [ ] **Step 4: Run focused planner tests**

Run:

```bash
PYTHONPATH=runtime .venv/bin/python -m unittest tests.test_scheduler_and_cgv.SchedulerTests -v
```

Expected: planner, eligibility, and seat-ranking tests pass with no discovery action emitted by the planner.

- [ ] **Step 5: Commit the planner change**

```bash
git add runtime/prickly_imax_helper/scheduler.py tests/test_scheduler_and_cgv.py
git commit -m "feat: rotate IMAX seat targets without daytime discovery"
```

---

### Task 2: Gate full discovery on startup and Korean midnight

**Files:**
- Modify: `runtime/prickly_imax_helper/monitor.py`
- Modify: `tests/test_monitor_safety.py`

**Interfaces:**
- Consumes: `BalancedScanPlanner.replace_discovery(dates, schedules, *, now)` and `next_hot_action()` from Task 1.
- Produces: `_kst_day(now: datetime | None = None) -> date`.
- Produces: `_refresh_discovery(paths: RuntimePaths, session: CgvSession, planner: BalancedScanPlanner, config: dict[str, Any], *, now: float) -> int` returning the eligible hot-target count.
- Preserves: `run(paths, *, max_cycles=None, allow_checkout=True) -> int` public signature.

- [ ] **Step 1: Add failing day-gate and serial-refresh tests**

Add tests that directly prove the time boundary and staged replacement:

```python
def test_kst_day_changes_at_korean_midnight():
    before = datetime(2026, 8, 15, 14, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 15, 15, 0, 0, tzinfo=timezone.utc)
    self.assertEqual(_kst_day(before).isoformat(), "2026-08-15")
    self.assertEqual(_kst_day(after).isoformat(), "2026-08-16")

def test_refresh_discovery_fetches_open_dates_and_each_schedule_serially():
    calls = []
    class FakeSession:
        def open_dates(self):
            calls.append("open_dates")
            return ["20260820", "20260821"]
        def schedules(self, ymd):
            calls.append(f"schedule:{ymd}")
            return [{"movkndDsplNm": "IMAX", "scnsrtTm": "1900", "scnsNo": "18", "scnSseq": ymd}]
    count = _refresh_discovery(paths, FakeSession(), planner, config, now=10.0)
    self.assertEqual(calls, ["open_dates", "schedule:20260820", "schedule:20260821"])
    self.assertEqual(count, 2)
```

Add two `run` integration tests with a fake session:

- Same KST day for several cycles: `open_dates` and each `schedules` method are called once during bootstrap; all later calls are `seats`.
- `_kst_day` side effect changes from `2026-08-15` to `2026-08-16`: a second complete discovery occurs exactly once, followed by hot-seat rotation.

Patch `_checkout` to fail the test if invoked and return seat maps with no configured pair.

- [ ] **Step 2: Run the focused monitor tests and confirm RED**

Run:

```bash
PYTHONPATH=runtime .venv/bin/python -m unittest tests.test_monitor_safety -v
```

Expected: failures for missing `_kst_day`, `_refresh_discovery`, and the current recurring 4:1 discovery calls.

- [ ] **Step 3: Implement KST date and atomic discovery helpers**

Add imports and helpers in `monitor.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

def _kst_day(now: datetime | None = None) -> date:
    value = now or datetime.now(tz=KST)
    return value.astimezone(KST).date()

def _refresh_discovery(paths, session, planner, config, *, now):
    previous_dates = set(planner.open_dates)
    previous_keys = {show_key(show) for show in planner.hot_targets}
    dates = session.open_dates()
    schedules = {
        ymd: eligible_shows(ymd, session.schedules(ymd), config)
        for ymd in dates
    }
    planner.replace_discovery(dates, schedules, now=now)
    next_keys = {show_key(show) for show in planner.hot_targets}
    if set(dates) != previous_dates:
        write_event(paths.logs, "open_dates_refreshed", count=len(dates))
    for discovered in sorted(set(dates) - previous_dates):
        write_event(paths.logs, "booking_date_discovered", ymd=discovered)
    if next_keys != previous_keys:
        write_event(paths.logs, "hot_queue_changed", count=len(next_keys))
    return len(planner.hot_targets)
```

Import `show_key` from `scheduler`. The event payloads remain limited to counts and date identifiers; do not add seats, cookies, customer data, or credentials.

- [ ] **Step 4: Replace ratio loop with daily gating**

At monitor startup initialize:

```python
last_discovery_day: date | None = None
```

Inside the locked loop:

```python
today = _kst_day()
if last_discovery_day != today:
    eligible_count = _refresh_discovery(
        paths, session, planner, config, now=time.monotonic()
    )
    last_discovery_day = today
    last_scan_lane = "discovery"
else:
    action = planner.next_hot_action()
    if action is None:
        metrics = planner.metrics(now=time.monotonic())
        _heartbeat(
            paths,
            Status.ARMED,
            "no eligible shows; waiting for KST midnight",
            open_dates=len(planner.open_dates),
            eligible_shows=0,
            match=None,
            errors=0,
            last_scan_lane="idle",
            **metrics,
        )
        completed_cycles += 1
        if max_cycles is not None and completed_cycles >= max_cycles:
            return 0
        time.sleep(float(config["request_policy"]["minimum_interval_seconds"]))
        continue
    # Preserve the existing eligibility recheck, seat-map request, match, checkout,
    # recorder, and terminal-state logic.
```

Only assign `last_discovery_day` after `_refresh_discovery` returns successfully, so a failed midnight cycle retries after existing error backoff. Remove `OPEN_DATE_REFRESH_SECONDS` and any monotonic 30-second discovery gate.

- [ ] **Step 5: Run focused scheduler and monitor suites**

Run:

```bash
PYTHONPATH=runtime .venv/bin/python -m unittest tests.test_scheduler_and_cgv tests.test_monitor_safety -v
```

Expected: startup bootstrap, same-day hot-only rotation, KST midnight refresh, wake recovery, match stop, 429, and checkout safety tests all pass.

- [ ] **Step 6: Commit the monitor change**

```bash
git add runtime/prickly_imax_helper/monitor.py tests/test_monitor_safety.py
git commit -m "feat: discover CGV schedules at Korean midnight"
```

---

### Task 3: Align public runtime documentation

**Files:**
- Modify: `README.md`
- Modify: `plugins/prickly-imax-helper/skills/prickly-imax-booking/references/runtime-contract.md`
- Test: `tests/test_release.py`

**Interfaces:**
- Documents the Task 2 cadence without changing configuration or checkout behavior.

- [ ] **Step 1: Add a failing release-documentation assertion**

In `tests/test_release.py`, assert that both public documents contain the meaning of:

```text
startup bootstrap
Korea-time midnight discovery
serial seat-map rotation between discoveries
no parallel availability requests
```

Also assert the documents do not claim ten-minute discovery or the 4:1 ratio.

- [ ] **Step 2: Run the release test and confirm RED**

```bash
PYTHONPATH=runtime .venv/bin/python -m unittest tests.test_release -v
```

Expected: FAIL because the cadence is not yet documented.

- [ ] **Step 3: Update the two public documents**

State plainly that the monitor builds the queue on startup, refreshes dates and schedules once when the Korean calendar day changes, scans known seat maps serially at all other times, and never sends parallel availability requests. Do not promise detection of arbitrary daytime schedule additions.

- [ ] **Step 4: Run release and privacy tests**

```bash
PYTHONPATH=runtime .venv/bin/python -m unittest tests.test_release tests.test_cli_privacy -v
```

Expected: PASS with no absolute customer path, credential, cookie, voucher, or payment data in release files.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md plugins/prickly-imax-helper/skills/prickly-imax-booking/references/runtime-contract.md tests/test_release.py
git commit -m "docs: explain midnight-only schedule discovery"
```

---

### Task 4: Verify, install, and restore the personal monitor

**Files:**
- Verify only: repository tree and `~/.prickly-imax-helper/`
- Optionally modify: `docs/beta-readiness.md` only if it already records current installed-runtime evidence.

**Interfaces:**
- Produces: locally installed runtime matching repository `scheduler.py` and `monitor.py` hashes.
- Produces: one healthy monitor, one Playwright driver, `armed`, `match:null`, and zero current errors.

- [ ] **Step 1: Run the complete clean verification suite**

```bash
PYTHONPATH=runtime .venv/bin/python -m unittest discover -s tests -v
ruff check runtime tests scripts plugins/prickly-imax-helper
python3 -m compileall -q runtime tests scripts plugins/prickly-imax-helper
zsh -n scripts/Install.command scripts/Update.command scripts/Uninstall.command
git diff --check
```

Expected: all tests and static checks pass. If the host shell lacks a dependency, use the repository's pinned environment rather than weakening the checks.

- [ ] **Step 2: Inspect the resident before installation**

```bash
~/.local/bin/prickly-imax --home ~/.prickly-imax-helper doctor
~/.local/bin/prickly-imax --home ~/.prickly-imax-helper diagnose
```

Proceed only when status is `armed`, `match` is `null`, exactly one monitor and one Playwright driver are present, and no process uses `~/.hermes/browser-profiles/cgv`.

- [ ] **Step 3: Preserve local state and install the verified worktree**

Record hashes and counts for `config.json`, browser-profile files, and redacted logs. Then:

```bash
~/.local/bin/prickly-imax --home ~/.prickly-imax-helper stop
zsh scripts/Update.command
```

The installer must preserve the existing config and dedicated browser profile. Its dry-run connection check must not click a showtime, party count, seat, voucher, or payment control.

- [ ] **Step 4: Verify installed source hashes and live state**

Resolve the installed version from the generated CLI wrapper, then compare:

```bash
shasum -a 256 runtime/prickly_imax_helper/scheduler.py \
  ~/.prickly-imax-helper/app/0.2.0/runtime/prickly_imax_helper/scheduler.py
shasum -a 256 runtime/prickly_imax_helper/monitor.py \
  ~/.prickly-imax-helper/app/0.2.0/runtime/prickly_imax_helper/monitor.py
~/.local/bin/prickly-imax --home ~/.prickly-imax-helper diagnose
```

Confirm:

- repository and installed hashes match;
- `armed`, `match:null`, and zero current errors;
- exactly one monitor and one Playwright driver;
- no Hermes CGV profile process;
- configuration and browser-profile counts/hashes are preserved;
- outside discovery the last scan lane becomes `hot`;
- with 35 targets, estimated revisit is approximately 35 seconds.

- [ ] **Step 5: Commit only exact verification evidence if applicable**

If `docs/beta-readiness.md` is the repository's active evidence ledger, record the commit, exact test count, source hashes, final process counts, scan lane, target count, and revisit estimate. Otherwise leave the repository unchanged and report the evidence in the final handoff.

- [ ] **Step 6: Finish the branch through the standard integration gate**

Invoke `superpowers:verification-before-completion`, then `superpowers:finishing-a-development-branch`. Do not merge, push, delete, or force-update a branch without the user's selected integration option.
