# Checkout Stage Audit and Party Render Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover safely from CGV's delayed visitor-count render and make every seat-match attempt traceable from detection to exactly one terminal outcome.

**Architecture:** Add a bounded semantic wait for the exact `일반` party-size control, then keep checkout orchestration fail-closed. Introduce a focused `CheckoutAttemptRecorder` for privacy-safe correlated stage events and a read-only audit script that handles exact future `attempt_id` correlation plus conservative legacy correlation.

**Tech Stack:** Python 3.12, Playwright 1.62, `unittest`, JSON Lines, Ruff 0.14.2, macOS LaunchAgent runtime.

## Global Constraints

- The live diagnostic may click one available showtime only to enter `/cnm/selectVisitorCnt`; it must not click a party-size control, seat, voucher, or payment control.
- Wait at most 10,000 ms for the exact visible, enabled `<party size> 선택` button inside the exact visible `일반` group.
- Click the party-size control once and require `aria-pressed="true"`; never retry an uncertain party click.
- Keep party size, same-row adjacency, row allow-list, edge exclusion, duplicate prevention, exact IMAX voucher count, zero balance, and one-submit rules unchanged.
- Runtime logs must not contain DOM/page text, screenshots, cookies, authorization headers, account numbers, email addresses, customer numbers, voucher numbers, ticket identifiers, or payment details.
- Historical missing evidence remains `legacy_unknown`; never invent a cause for `D28-D29`.
- Audit commands are read-only and must not launch Chrome, call CGV, or alter booking state.
- The three-hour same-day lead-time rule and any new direct-phone-push provider remain outside this plan.

---

### Task 1: Reproduce and fix delayed general-admission rendering

**Files:**
- Modify: `runtime/prickly_imax_helper/checkout.py`
- Modify: `tests/test_checkout_browser.py`

**Interfaces:**
- Consumes: `CheckoutFlow(page, config)` and `config["party_size"]`.
- Produces: `CheckoutFlow._wait_for_general_party_control(party: int, timeout_ms: int = 10_000) -> bool`.
- Produces: `CheckoutFlow._select_general_party(party: int, timeout_ms: int = 10_000) -> None`.
- Preserves: `CheckoutFlow.select_party_and_seats(match: dict[str, Any]) -> None`.

- [ ] **Step 1: Add a failing delayed-render browser test**

Add this shape to `tests/test_checkout_browser.py`; the HTML must insert the groups after 500 ms so the old immediate lookup fails:

```python
def test_waits_for_delayed_general_party_control(self):
    self.page.set_content(
        """<!doctype html><meta charset=utf-8>
        <script>
          setTimeout(() => document.body.insertAdjacentHTML('beforeend', `
            <div role="group"><div>일반</div>
              <button aria-label="1 선택" aria-pressed="false">1</button>
              <button aria-label="2 선택" aria-pressed="false"
                onclick="this.setAttribute('aria-pressed','true')">2</button>
            </div>`), 500);
        </script>"""
    )

    self.flow._select_general_party(2, timeout_ms=2_000)

    self.assertEqual(
        self.page.locator('[role=group]').get_by_role('button', name='2 선택').get_attribute('aria-pressed'),
        'true',
    )
```

- [ ] **Step 2: Add failing wrong-group, timeout, and single-click tests**

Add three tests:

```python
def test_selects_two_only_inside_exact_general_group(self):
    self.page.set_content("""<!doctype html><meta charset=utf-8>
      <div role=group><div>일반</div><button aria-label="2 선택" aria-pressed=false
        onclick="window.general=(window.general||0)+1;this.setAttribute('aria-pressed','true')">2</button></div>
      <div role=group><div>청소년</div><button aria-label="2 선택" aria-pressed=false
        onclick="window.youth=(window.youth||0)+1;this.setAttribute('aria-pressed','true')">2</button></div>
      <div role=group><div>우대</div><button aria-label="2 선택" aria-pressed=false
        onclick="window.priority=(window.priority||0)+1;this.setAttribute('aria-pressed','true')">2</button></div>""")
    self.flow._select_general_party(2, timeout_ms=500)
    self.assertEqual(self.page.evaluate("() => window.general"), 1)
    self.assertIsNone(self.page.evaluate("() => window.youth"))
    self.assertIsNone(self.page.evaluate("() => window.priority"))

def test_missing_general_party_control_times_out_without_click(self):
    self.page.set_content("""<!doctype html><meta charset=utf-8>
      <div role=group><div>청소년</div><button aria-label="2 선택"
        onclick="window.youth=(window.youth||0)+1">2</button></div>
      <div role=group><div>우대</div><button aria-label="2 선택"
        onclick="window.priority=(window.priority||0)+1">2</button></div>""")
    with self.assertRaises(CheckoutError):
        self.flow._select_general_party(2, timeout_ms=100)
    self.assertIsNone(self.page.evaluate("() => window.youth"))
    self.assertIsNone(self.page.evaluate("() => window.priority"))

def test_unproven_general_selection_is_not_clicked_twice(self):
    self.page.set_content("""<!doctype html><meta charset=utf-8>
      <div role=group><div>일반</div><button aria-label="2 선택" aria-pressed=false
        onclick="window.general=(window.general||0)+1">2</button></div>""")
    with self.assertRaises(CheckoutError):
        self.flow._select_general_party(2, timeout_ms=100)
    self.assertEqual(self.page.evaluate("() => window.general"), 1)
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_checkout_browser -v
```

Expected: the new tests fail because `_wait_for_general_party_control` and `_select_general_party` do not exist.

- [ ] **Step 4: Implement the bounded semantic wait**

Add `_wait_for_general_party_control` to `CheckoutFlow`. Its Playwright predicate must require one visible `role=group` with an exact visible child label `일반`, then require one visible, enabled button in that group with exact `aria-label="<party> 선택"`. Poll through `page.wait_for_function` and return `False` only on timeout.

The method must not search the whole document for a number button and must not use a fixed sleep.

- [ ] **Step 5: Implement one-click selection and proof**

Add `_select_general_party`. It calls the readiness helper, clicks the exact button once, then waits for that same button to become `aria-pressed="true"`. Raise these bounded errors:

```python
raise CheckoutError("general admission count control not ready")
raise CheckoutError("general admission count selection not proven")
```

Update `select_party_and_seats` to call `_select_general_party(party)` before any seat lookup.

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_checkout_browser -v
```

Expected: all browser tests pass; delayed render succeeds, wrong groups remain untouched, and an unproven click occurs once.

- [ ] **Step 7: Commit the party-control fix**

```bash
git add runtime/prickly_imax_helper/checkout.py tests/test_checkout_browser.py
git commit -m "fix: wait for general admission controls"
```

### Task 2: Add a privacy-safe checkout-attempt recorder

**Files:**
- Create: `runtime/prickly_imax_helper/checkout_attempt.py`
- Create: `tests/test_checkout_attempt.py`
- Modify: `runtime/prickly_imax_helper/checkout.py`
- Modify: `runtime/prickly_imax_helper/monitor.py`
- Modify: `tests/test_monitor_safety.py`

**Interfaces:**
- Produces: `STAGE_ORDER: tuple[str, ...]`.
- Produces: `TERMINAL_OUTCOMES: frozenset[str]`.
- Produces: `CheckoutAttemptRecorder.start(log_dir: Path, match: dict[str, Any]) -> CheckoutAttemptRecorder`.
- Produces: `CheckoutAttemptRecorder.stage(name: str) -> ContextManager[None]`.
- Produces: `CheckoutAttemptRecorder.mark(name: str, outcome: str = "passed") -> None`.
- Produces: `CheckoutAttemptRecorder.terminal(name: str, *, error: str | None = None) -> None`.
- Produces: `CheckoutFlow._require_match_date(match: dict[str, Any]) -> None`.
- Changes: `_checkout(paths, config, session, match, recorder) -> str`.

- [ ] **Step 1: Add failing recorder tests**

Create `tests/test_checkout_attempt.py` with tests that patch `write_event` and execute:

```python
from unittest.mock import ANY

recorder = CheckoutAttemptRecorder.start(log_dir, match)
with recorder.stage("theater"):
    pass
recorder.terminal("checkout_pre_submit_error", error="safe bounded error")
```

Assert these event shapes in order:

```python
("seat_match", {"attempt_id": recorder.attempt_id, "match": match})
("checkout_stage", {"attempt_id": recorder.attempt_id, "stage": "theater", "outcome": "started"})
("checkout_stage", {"attempt_id": recorder.attempt_id, "stage": "theater", "outcome": "passed", "elapsed_ms": ANY})
("checkout_pre_submit_error", {"attempt_id": recorder.attempt_id, "match": match, "error": "safe bounded error"})
```

Also assert that an exception inside `stage("party")` writes `outcome="failed"` and re-raises, an unknown stage is rejected before writing, and a second terminal outcome raises without writing.

- [ ] **Step 2: Run recorder tests and verify RED**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_checkout_attempt -v
```

Expected: import failure because `checkout_attempt.py` does not exist.

- [ ] **Step 3: Implement the recorder minimally**

Use `secrets.token_hex(8)` for a local non-personal attempt ID. Define this exact order:

```python
STAGE_ORDER = (
    "duplicate_guard_before", "theater", "date", "showtime", "party", "seats",
    "vouchers", "zero_balance", "duplicate_guard_final", "submission_ready",
    "submission", "mobile_ticket",
)
```

Define terminal outcomes:

```python
TERMINAL_OUTCOMES = frozenset({
    "completed", "seat_vanished", "checkout_pre_submit_error", "blocked_duplicate",
    "blocked_payment", "unknown_after_submit", "checkout_attempt_interrupted",
})
```

The context manager writes `started`, then `passed` with monotonic elapsed milliseconds, or `failed` with the exception class name and redacted message before re-raising. Do not catch write failures.

- [ ] **Step 4: Add failing orchestration tests**

Extend `tests/test_monitor_safety.py` with a recorder spy and flow doubles. Assert `_checkout` records the existing operations in exact order, uses one terminal outcome, and does not advance after the first failed stage. Add a write-failure test proving that a recorder failure before submission prevents the next booking action.

- [ ] **Step 5: Split combined browser operations only where stage proof requires it**

In `CheckoutFlow` preserve public behavior while extracting:

`_open_match_showtime(self, match: dict[str, Any]) -> None` receives the existing exact-showtime wait, exact-showtime click, and `/cnm/selectVisitorCnt` route wait from `open_match`. `_select_seats(self, match: dict[str, Any]) -> None` receives the existing configured-seat lookup, click, and selected-count proof from `select_party_and_seats`.

`open_match` remains a compatibility wrapper that calls `_click_match_date` then `_open_match_showtime`. `select_party_and_seats` remains a compatibility wrapper that calls `_select_general_party` then `_select_seats`. The monitor may call the atomic helpers so `date`, `showtime`, `party`, and `seats` each receive separate stage evidence.

- [ ] **Step 6: Wire recorder stages and terminal outcomes into `_checkout`**

Wrap each action in this exact order:

```python
with recorder.stage("duplicate_guard_before"):
    flow.ensure_no_existing_ticket(match, separate_tab=True)
with recorder.stage("theater"):
    flow.open_movie_and_theater()
with recorder.stage("date"):
    flow._require_match_date(match)
with recorder.stage("showtime"):
    flow._open_match_showtime(match)
with recorder.stage("party"):
    flow._select_general_party(int(config["party_size"]))
with recorder.stage("seats"):
    flow._select_seats(match)
with recorder.stage("vouchers"):
    flow.open_payment_and_apply_vouchers()
with recorder.stage("zero_balance"):
    flow.prove_ready(match)
with recorder.stage("duplicate_guard_final"):
    flow.ensure_no_existing_ticket(match, separate_tab=True)
recorder.mark("submission_ready")
```

Add `_require_match_date(match: dict[str, Any]) -> None` as a fail-closed wrapper around `_click_match_date`. Keep the final duplicate guard after voucher and zero-balance proof exactly as shown. Submission and mobile-ticket proof are recorded only after heartbeat crosses to `submitting`.

Map each existing return path to one terminal name: `DuplicateBlocked -> blocked_duplicate`, `PaymentBlocked -> blocked_payment`, `SeatVanished -> seat_vanished`, pre-submit `CheckoutError -> checkout_pre_submit_error`, `UnknownAfterSubmit -> unknown_after_submit`, and verified mobile ticket -> `completed`. Transition heartbeat `staging` and `submitting` with both `attempt_id` and `match` so restart recovery can correlate the attempt.

- [ ] **Step 7: Start the recorder at seat detection**

Replace the direct `write_event(paths.logs, "seat_match", match=match)` call with:

```python
recorder = CheckoutAttemptRecorder.start(paths.logs, match)
result = _checkout(paths, config, session, match, recorder)
```

Dry-run matches remain `dry_run_match_not_selected` and do not create checkout attempts.

- [ ] **Step 8: Run focused tests and verify GREEN**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_checkout_attempt tests.test_monitor_safety tests.test_checkout_browser -v
```

Expected: all focused tests pass and the recorded stage order matches `STAGE_ORDER`.

- [ ] **Step 9: Commit the recorder and orchestration changes**

```bash
git add runtime/prickly_imax_helper/checkout_attempt.py runtime/prickly_imax_helper/checkout.py runtime/prickly_imax_helper/monitor.py tests/test_checkout_attempt.py tests/test_monitor_safety.py
git commit -m "feat: correlate checkout stage outcomes"
```

### Task 3: Record interruption and notification follow-up evidence

**Files:**
- Modify: `runtime/prickly_imax_helper/monitor.py`
- Modify: `tests/test_monitor_safety.py`
- Modify: `tests/test_notify.py`

**Interfaces:**
- Changes: `_notify(paths, config, subject, body, *, attempt_id: str | None = None) -> None`.
- Consumes: heartbeat `attempt_id` and `match` set by Task 2.
- Produces events: `checkout_attempt_interrupted` and `notification_result`.

- [ ] **Step 1: Add failing pre-submit restart correlation test**

Create a configured temporary runtime whose heartbeat is `staging` with `attempt_id="attempt-a"` and a redacted match. Start `run` with browser launch patched. Assert it writes:

```python
write_event(paths.logs, "checkout_attempt_interrupted", attempt_id="attempt-a", match=match)
```

before changing to `recovering`. Assert a `submitting` restart still becomes `unknown_after_submit` and never records a pre-submit interruption.

- [ ] **Step 2: Add failing notification-result tests**

Patch desktop and email delivery independently. Assert an attempt-linked notification writes one `notification_result` per channel with only `attempt_id`, `channel`, and `outcome`. On failure, preserve the existing `desktop_notification_failed` or `email_failed` compatibility event without logging the recipient.

- [ ] **Step 3: Run focused tests and verify RED**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_monitor_safety tests.test_notify -v
```

Expected: failures because restart correlation and successful notification-result events are absent.

- [ ] **Step 4: Implement restart correlation and notification follow-up**

When startup sees `staging`, read the stored `attempt_id` and `match`, write `checkout_attempt_interrupted`, then transition to `recovering`. Pass the attempt ID only for booking-result notifications. Record success or failure separately for desktop and email, after the booking terminal outcome.

- [ ] **Step 5: Run focused tests and verify GREEN**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_monitor_safety tests.test_notify -v
```

- [ ] **Step 6: Commit interruption and notification evidence**

```bash
git add runtime/prickly_imax_helper/monitor.py tests/test_monitor_safety.py tests/test_notify.py
git commit -m "feat: record interrupted checkout attempts"
```

### Task 4: Build the read-only checkout audit

**Files:**
- Create: `scripts/checkout_audit.py`
- Create: `tests/test_checkout_audit.py`
- Create: `tests/fixtures/checkout-audit-legacy-14.jsonl`

**Interfaces:**
- Produces: `load_events(input_path: Path) -> list[dict[str, Any]]`.
- Produces: `build_report(events: list[dict[str, Any]]) -> dict[str, Any]`.
- Produces: `verify_report(report: dict[str, Any]) -> list[str]`.
- Produces CLI: `python3 scripts/checkout_audit.py report --input PATH`.
- Produces CLI: `python3 scripts/checkout_audit.py verify --input PATH`.

- [ ] **Step 1: Create the fourteen-match legacy fixture**

Write minimal redacted JSON Lines containing fourteen `seat_match` events and the retained outcomes:

- ten matching `checkout_pre_submit_error` events with `theater picker launcher not found`;
- two matching `seat_vanished` events with `target date is no longer open`;
- one matching `checkout_pre_submit_error` with `general admission count control not found`;
- one `D28-D29` match with no retained outcome.

The fixture may contain date, time, and seat pair but no email, absolute home path, customer number, voucher number, ticket ID, cookie, authorization header, or payment detail.

- [ ] **Step 2: Add failing legacy-report test**

```python
def test_legacy_fourteen_match_report_is_10_2_1_1(self):
    events = checkout_audit.load_events(FIXTURE)
    report = checkout_audit.build_report(events)
    self.assertEqual(report["attempts_total"], 14)
    self.assertEqual(report["legacy_classification"], {
        "theater_picker": 10,
        "today_label": 2,
        "general_party": 1,
        "legacy_unknown": 1,
    })
```

- [ ] **Step 3: Add failing future-attempt verifier tests**

Test one valid instrumented attempt and these failures:

- missing terminal outcome;
- two terminal outcomes;
- stage order moves backward;
- two `submission` started events;
- prohibited key such as `cookie`, `authorization`, `voucher_number`, or `ticket_id`;
- prohibited value containing an email address or a 12-or-more-digit customer-like number.

Also assert a legacy unknown is reported honestly but does not count as future passing evidence.

- [ ] **Step 4: Run audit tests and verify RED**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_checkout_audit -v
```

Expected: import failure because `scripts/checkout_audit.py` does not exist.

- [ ] **Step 5: Implement input loading and conservative correlation**

Accept one JSONL file or a directory of `*.jsonl`. Sort events by parsed `at`. Group instrumented events exactly by `attempt_id`. For legacy events, associate only an immediately following terminal event whose match date, time, and pair equal the `seat_match`; otherwise classify it as `legacy_unknown`.

Do not call runtime browser, network, service, setup, or monitor modules.

- [ ] **Step 6: Implement verification and JSON CLI output**

`report` exits zero and prints the complete JSON report. `verify` prints a success object such as `{"ok": true, "attempts_total": 1, "errors": []}` and exits zero only when all instrumented attempts have one terminal outcome, valid monotonic stage order, no duplicate submission start, and no prohibited fields. It prints a failure object such as `{"ok": false, "attempts_total": 1, "errors": ["attempt abc has no terminal outcome"]}` and exits one otherwise.

Keep operational error counts separate: `rate_limited`, `login_required`, browser closure, transport/HTTP, desktop notification, and email.

- [ ] **Step 7: Run audit tests and verify GREEN**

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_checkout_audit -v
python3 scripts/checkout_audit.py report --input tests/fixtures/checkout-audit-legacy-14.jsonl
```

Expected report: `attempts_total=14` with classification `10/2/1/1` and no invented D28-D29 cause.

- [ ] **Step 8: Run the report against local historical logs**

```bash
python3 scripts/checkout_audit.py report --input /Users/woojinyoung/.prickly-imax-helper/logs
```

Expected: all fourteen historical seat matches are accounted for. This command must not change files or contact CGV.

- [ ] **Step 9: Commit the audit tool and fixtures**

```bash
git add scripts/checkout_audit.py tests/test_checkout_audit.py tests/fixtures/checkout-audit-legacy-14.jsonl
git commit -m "feat: audit checkout attempt histories"
```

### Task 5: Full verification, installation, and controlled live recognition

**Files:**
- Modify only when exact evidence is available: `docs/beta-readiness.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: installed patched runtime, verified local state, and exact audit evidence.

- [ ] **Step 1: Run the complete local verification suite**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -v
ruff check runtime tests scripts plugins/prickly-imax-helper
python3 -m compileall -q runtime tests scripts plugins/prickly-imax-helper
zsh -n scripts/Install.command scripts/Update.command scripts/Uninstall.command
git diff --check
```

Require every command to exit zero. Record the exact test count; do not reuse the previous 117-test count.

- [ ] **Step 2: Stop the resident monitor without crossing submission**

Run `~/.local/bin/prickly-imax status`. Proceed only from `armed` with `match: null`. Run `~/.local/bin/prickly-imax stop` and wait until this exact process pattern disappears:

```text
^/Users/woojinyoung/.prickly-imax-helper/venv/bin/python /Users/woojinyoung/.prickly-imax-helper/venv/bin/prickly-imax --home /Users/woojinyoung/.prickly-imax-helper run$
```

- [ ] **Step 3: Install the patched runtime and verify hashes**

```bash
zsh scripts/Update.command
shasum -a 256 runtime/prickly_imax_helper/checkout.py /Users/woojinyoung/.prickly-imax-helper/app/0.1.0/runtime/prickly_imax_helper/checkout.py
shasum -a 256 runtime/prickly_imax_helper/checkout_attempt.py /Users/woojinyoung/.prickly-imax-helper/app/0.1.0/runtime/prickly_imax_helper/checkout_attempt.py
```

Require matching repository/installed hashes and `~/.local/bin/prickly-imax doctor` success. Preserve config and the dedicated Chrome profile.

- [ ] **Step 4: Perform the approved no-party-click live recognition check**

With the monitor stopped and one browser lock held, connect to the dedicated Chrome profile. Select one available showtime, enter `/cnm/selectVisitorCnt`, call only `_wait_for_general_party_control(configured_party_size)`, and require `True`. Do not call `_select_general_party`, `select_party_and_seats`, seat selection, voucher application, or submission. Return to `/cnm/movieBook/movie`.

- [ ] **Step 5: Restart and verify resident state**

Run `~/.local/bin/prickly-imax start`, then require:

- status `armed`;
- `match: null`;
- exactly one exact-pattern Prickly monitor;
- exactly one Playwright driver;
- no process using `/Users/woojinyoung/.hermes/browser-profiles/cgv`.

- [ ] **Step 6: Run audit verification without CGV traffic**

```bash
python3 scripts/checkout_audit.py report --input /Users/woojinyoung/.prickly-imax-helper/logs
python3 scripts/checkout_audit.py verify --input /Users/woojinyoung/.prickly-imax-helper/logs
```

The report must retain the historical `legacy_unknown`. The verifier applies strict completeness only to newly instrumented attempts and must explain that legacy unknown separately rather than claiming it passed.

- [ ] **Step 7: Commit exact verification evidence only if documentation changes**

If `docs/beta-readiness.md` receives exact test, hash, live-recognition, or audit evidence:

```bash
git add docs/beta-readiness.md
git commit -m "docs: record checkout audit verification"
```

Do not create an empty documentation commit.

- [ ] **Step 8: Report completion precisely**

Report the confirmed 500 ms root cause, new test count, historical 10/2/1/1 audit, repository/installed hashes, live recognition result, and final process state. Do not claim a real booking or payment succeeded; only a verified mobile ticket from a future resident attempt can prove that.
