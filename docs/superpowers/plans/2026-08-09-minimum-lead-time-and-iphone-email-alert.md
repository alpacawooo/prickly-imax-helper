# Minimum Lead Time and iPhone Email Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude every CGV show starting in less than 180 minutes before any seat-map request and make the existing email-to-iPhone notification path explicit without adding a push provider or credential.

**Architecture:** Add Korea-time show-start arithmetic as a focused policy boundary, then call it from schedule eligibility before seat probing. Preserve legacy configuration by defaulting a missing `minimum_lead_minutes` to 180, expose only values from 180 through 1,440 in localhost setup, and retain the existing desktop/email notification fan-out unchanged.

**Tech Stack:** Python 3.12, standard-library `datetime`/`zoneinfo`, local HTML setup server, `unittest`, Ruff 0.14.2, macOS LaunchAgent, Windows Scheduled Task.

## Global Constraints

- The effective minimum lead time is 180 minutes for an existing configuration that lacks the new field.
- An explicitly configured value must be an integer from 180 through 1,440; `bool` is not accepted as an integer.
- Exactly 180 minutes remaining is eligible; any smaller duration is ineligible.
- CGV start hours 24 through 29 roll into the next calendar day in `Asia/Seoul`.
- The filter runs before `changed_seat_targets` and before every seat-map request.
- Existing weekday/weekend time windows, dynamic dates, seat ranking, duplicate guards, vouchers, zero-balance proof, and one-submit behavior remain unchanged.
- Existing desktop and Apple Mail/classic Outlook email delivery remain the only notification transports.
- Do not add Pushover, ntfy, APNs, SMS, a token, an email password, or a cloud service.
- Do not claim email can bypass iPhone Focus, silent mode, Mail fetch delay, or notification settings.
- Installation may proceed only from `armed` with `match: null`; no live showtime, party, seat, voucher, or payment click is required.

---

### Task 1: Add Korea-time minimum-lead policy before seat probing

**Files:**
- Modify: `runtime/prickly_imax_helper/policy.py`
- Modify: `runtime/prickly_imax_helper/scheduler.py`
- Modify: `tests/test_scheduler_and_cgv.py`

**Interfaces:**
- Produces: `show_start_at(ymd: str, start: str) -> datetime`.
- Produces: `has_minimum_lead(ymd: str, start: str, minimum_lead_minutes: int, *, now: datetime | None = None) -> bool`.
- Changes: `eligible_shows(ymd: str, schedules: list[dict[str, Any]], config: dict[str, Any], *, now: datetime | None = None) -> list[dict[str, Any]]`.
- Preserves: production monitor calls may omit `now`.

- [ ] **Step 1: Add failing exact-boundary and too-soon tests**

Extend `SchedulerTests` in `tests/test_scheduler_and_cgv.py` with an aware Korea clock and schedules whose `scnsrtTm` values straddle 180 minutes:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

def test_minimum_lead_accepts_exactly_180_minutes_and_rejects_less(self):
    config = odyssey()
    schedules = [
        {"scnsrtTm": "2100", "movkndDsplNm": "IMAX", "scnsNo": "1", "scnSseq": "1"},
        {"scnsrtTm": "2059", "movkndDsplNm": "IMAX", "scnsNo": "1", "scnSseq": "2"},
    ]
    now = datetime(2026, 8, 10, 18, 0, tzinfo=KST)

    result = eligible_shows("20260810", schedules, config, now=now)

    self.assertEqual([show["time"] for show in result], ["21:00"])
```

Use a Monday so the preset's weekday 19:00 lower bound does not hide either lead-time assertion.

- [ ] **Step 2: Add failing rollover, later-date, and host-timezone tests**

Add three cases:

```python
def test_2430_rolls_into_the_next_calendar_day(self):
    config = odyssey()
    config["time_rules"]["sunday"] = {"any_time": True}
    schedules = [{"scnsrtTm": "2430", "movkndDsplNm": "IMAX"}]
    accepted = eligible_shows(
        "20260809", schedules, config,
        now=datetime(2026, 8, 9, 21, 30, tzinfo=KST),
    )
    rejected = eligible_shows(
        "20260809", schedules, config,
        now=datetime(2026, 8, 9, 21, 31, tzinfo=KST),
    )
    self.assertEqual([show["time"] for show in accepted], ["24:30"])
    self.assertEqual(rejected, [])

def test_later_date_remains_eligible(self):
    config = odyssey()
    schedules = [{"scnsrtTm": "1900", "movkndDsplNm": "IMAX"}]
    result = eligible_shows(
        "20260811", schedules, config,
        now=datetime(2026, 8, 10, 23, 0, tzinfo=KST),
    )
    self.assertEqual([show["time"] for show in result], ["19:00"])

def test_aware_utc_now_is_converted_to_korea_time(self):
    config = odyssey()
    schedules = [{"scnsrtTm": "2100", "movkndDsplNm": "IMAX"}]
    result = eligible_shows(
        "20260810", schedules, config,
        now=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
    )
    self.assertEqual([show["time"] for show in result], ["21:00"])
```

Add a direct helper test that a naive `datetime` raises `ValueError("now must include timezone information")`.

- [ ] **Step 3: Run focused tests and verify RED**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_scheduler_and_cgv.py' -v
```

Expected: new calls fail because `eligible_shows` does not accept `now` and the time helpers do not exist.

- [ ] **Step 4: Implement Korea-time show-start parsing**

In `runtime/prickly_imax_helper/policy.py`, add:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")

def show_start_at(ymd: str, start: str) -> datetime:
    if len(ymd) != 8 or not ymd.isdigit():
        raise ValueError("show date must be YYYYMMDD")
    hour, minute = map(int, start.split(":"))
    if not 0 <= hour <= 29 or not 0 <= minute <= 59:
        raise ValueError("show start must be HH:MM with hour 00 through 29")
    base = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=KOREA_TIMEZONE)
    return base + timedelta(hours=hour, minutes=minute)

def has_minimum_lead(
    ymd: str,
    start: str,
    minimum_lead_minutes: int,
    *,
    now: datetime | None = None,
) -> bool:
    current = datetime.now(KOREA_TIMEZONE) if now is None else now
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must include timezone information")
    current_korea = current.astimezone(KOREA_TIMEZONE)
    return show_start_at(ymd, start) - current_korea >= timedelta(minutes=minimum_lead_minutes)
```

Catch malformed start strings by raising the bounded `ValueError` rather than leaking a raw split/unpack error. Do not change `eligible_start`.

- [ ] **Step 5: Filter schedules before they become seat targets**

In `runtime/prickly_imax_helper/scheduler.py`, import `datetime` and `has_minimum_lead`, add keyword-only `now`, and append a show only after both policies pass:

```python
minimum_lead = int(config.get("minimum_lead_minutes", 180))
if eligible_start(day, start, config) and has_minimum_lead(
    ymd,
    start,
    minimum_lead,
    now=now,
):
    result.append({**show, "ymd": ymd, "time": start})
```

Keep the existing invalid `scnsrtTm` skip before parsing. Because `monitor.py` already calls `changed_seat_targets` only with the returned list, do not add a second filter or any new CGV request.

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_scheduler_and_cgv.py' -v
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_monitor_safety.py' -v
```

Expected: all scheduler/CGV tests pass, and monitor orchestration remains unchanged.

- [ ] **Step 7: Commit the policy boundary**

```bash
git add runtime/prickly_imax_helper/policy.py runtime/prickly_imax_helper/scheduler.py tests/test_scheduler_and_cgv.py
git commit -m "feat: enforce minimum showtime lead"
```

### Task 2: Add backward-compatible configuration and setup control

**Files:**
- Modify: `runtime/prickly_imax_helper/config.py`
- Modify: `runtime/prickly_imax_helper/presets.py`
- Modify: `runtime/prickly_imax_helper/setup_server.py`
- Modify: `plugins/prickly-imax-helper/assets/default-odyssey.json`
- Modify: `plugins/prickly-imax-helper/skills/prickly-imax-booking/scripts/policy.py`
- Modify: `tests/test_runtime_core.py`
- Modify: `tests/test_setup_server.py`
- Modify: `tests/test_policy.py`

**Interfaces:**
- Consumes: runtime default `config.get("minimum_lead_minutes", 180)` from Task 1.
- Produces: optional config field `minimum_lead_minutes: int` constrained to `180..1440` when present.
- Produces: setup form field `minimum_lead_minutes` with HTML `min="180"`, `max="1440"`, and default `180`.

- [ ] **Step 1: Add failing runtime configuration tests**

In `tests/test_runtime_core.py`, add:

```python
def test_legacy_config_without_minimum_lead_remains_valid(self):
    legacy = copy.deepcopy(VALID_CONFIG)
    legacy.pop("minimum_lead_minutes", None)
    self.assertEqual(validate_config(legacy), [])

def test_minimum_lead_accepts_180_to_1440_only(self):
    for value in (180, 181, 1440):
        config = copy.deepcopy(VALID_CONFIG)
        config["minimum_lead_minutes"] = value
        self.assertEqual(validate_config(config), [])
    for value in (179, 1441, True, 180.5, "180"):
        config = copy.deepcopy(VALID_CONFIG)
        config["minimum_lead_minutes"] = value
        self.assertTrue(any("minimum_lead_minutes" in error for error in validate_config(config)))
```

Add `"minimum_lead_minutes": 180` to `VALID_CONFIG` after writing the explicit legacy copy test.

- [ ] **Step 2: Add failing setup render and persistence tests**

In `tests/test_setup_server.py`, require the GET page to contain:

```text
name="minimum_lead_minutes"
min="180"
아이폰
집중 모드
```

Add `"minimum_lead_minutes": "240"` to the successful POST fixture and assert the saved config contains integer `240`.

Add a POST case with `179` that returns HTTP 400, leaves `config.json` absent, and includes `최소 180분` in the response.

- [ ] **Step 3: Add failing plugin policy tests**

In `tests/test_policy.py`, add explicit plugin validation cases for `180`, missing legacy field, `179`, `True`, and `1441`. Assert the same accepted/rejected boundary as runtime configuration.

- [ ] **Step 4: Run focused tests and verify RED**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_runtime_core.py' -v
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_setup_server.py' -v
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_policy.py' -v
```

Expected: missing validation, setup field, persistence, and plugin policy assertions fail.

- [ ] **Step 5: Implement runtime and plugin validation**

In `runtime/prickly_imax_helper/config.py`, validate only when the field is present:

```python
minimum_lead = value.get("minimum_lead_minutes", 180)
if isinstance(minimum_lead, bool) or not isinstance(minimum_lead, int) or not 180 <= minimum_lead <= 1440:
    errors.append("minimum_lead_minutes must be an integer from 180 through 1440")
```

Add the same rule to `plugins/prickly-imax-helper/skills/prickly-imax-booking/scripts/policy.py`, using that file's existing error-list style. Add `"minimum_lead_minutes": 180` to both `runtime/prickly_imax_helper/presets.py` and `plugins/prickly-imax-helper/assets/default-odyssey.json`.

- [ ] **Step 6: Render and save the setup field**

In `runtime/prickly_imax_helper/setup_server.py`:

- Add this label within the time-rule section:

```html
<label>상영 시작 최소 여유(분)
  <input required type=number name=minimum_lead_minutes min=180 max=1440 step=1 value="__MINIMUM_LEAD_MINUTES__">
</label>
```

- Add `minimum_lead_minutes` to `_default_form_values`, `_render_page` replacements, and the posted `values` map.
- Parse it with `int`; on failure raise `ConfigError("상영 시작 최소 여유는 180~1440분의 정수로 입력해 주세요.")`.
- Reject values outside the boundary with `ConfigError("상영 시작 최소 여유는 최소 180분, 최대 1440분입니다.")`.
- Store it in the configuration produced by `_booking_config`.

Do not make the field optional in the browser form. Runtime backward compatibility is only for already-saved configurations.

- [ ] **Step 7: Add honest iPhone Mail copy**

Replace the email hint with copy that states:

```text
이 주소를 아이폰 Mail에 등록하고 iOS 설정에서 Mail 알림을 허용하면 예매 결과를 휴대폰에서도 확인할 수 있습니다. 이메일은 지연될 수 있고 무음 모드·집중 모드를 Helper가 해제할 수 없습니다.
```

Keep the existing local Apple Mail/classic Outlook bridge explanation and test-email-before-save behavior.

- [ ] **Step 8: Run focused tests and verify GREEN**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_runtime_core.py' -v
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_setup_server.py' -v
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_policy.py' -v
```

Expected: legacy configuration, boundary validation, setup persistence, and iPhone limitation copy all pass.

- [ ] **Step 9: Commit configuration and setup**

```bash
git add runtime/prickly_imax_helper/config.py runtime/prickly_imax_helper/presets.py runtime/prickly_imax_helper/setup_server.py plugins/prickly-imax-helper/assets/default-odyssey.json plugins/prickly-imax-helper/skills/prickly-imax-booking/scripts/policy.py tests/test_runtime_core.py tests/test_setup_server.py tests/test_policy.py
git commit -m "feat: configure three-hour booking lead"
```

### Task 3: Freeze booking-result email behavior and update onboarding

**Files:**
- Modify: `tests/test_monitor_safety.py`
- Modify: `README.md`
- Modify: `plugins/prickly-imax-helper/skills/prickly-imax-booking/references/onboarding.md`

**Interfaces:**
- Preserves: `_notify(paths, config, subject, body, *, attempt_id=None) -> None`.
- Preserves booking-result email calls for `completed`, `unknown_after_submit`, `blocked_payment`, and `blocked_duplicate`.
- Produces documentation that describes iPhone Mail delivery without claiming direct push.

- [ ] **Step 1: Add booking-result notification regression assertions**

Extend orchestration tests in `tests/test_monitor_safety.py` so the existing flow doubles assert `_notify` receives the recorder attempt ID for:

```python
expected_subjects = {
    "Prickly IMAX 예매 완료",
    "Prickly IMAX 결과 확인 필요",
    "Prickly IMAX 결제 중단",
    "Prickly IMAX 예매 중단",
}
```

Use separate terminal-path tests where needed. Assert notifications occur only after the corresponding recorder terminal event; do not weaken the current rule that notification failure cannot authorize another submission.

- [ ] **Step 2: Run notification regression tests**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_monitor_safety.py' -v
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_notify.py' -v
```

Expected: all tests pass without a production notification transport change. If an assertion exposes an existing ordering mismatch, fix only the ordering needed to ensure the terminal outcome is recorded before `_notify`.

- [ ] **Step 3: Update repository and plugin onboarding copy**

Add these points to `README.md` and the plugin onboarding reference:

- the default minimum lead time is three hours and cannot be configured lower;
- CGV clocks through `29:59` are normalized across midnight;
- the configured recipient address may be used in iPhone Mail;
- delivery may be delayed and the helper cannot bypass silent mode or Focus;
- this is email notification, not direct mobile push.

Do not mention Pushover setup because it is intentionally out of scope.

- [ ] **Step 4: Run documentation-sensitive tests and diff checks**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -p 'test_release.py' -v
git diff --check
```

- [ ] **Step 5: Commit notification regression and onboarding**

```bash
git add tests/test_monitor_safety.py README.md plugins/prickly-imax-helper/skills/prickly-imax-booking/references/onboarding.md
git commit -m "docs: explain iPhone email notifications"
```

### Task 4: Full verification, local installation, and monitor restoration

**Files:**
- Modify only with exact evidence: `docs/beta-readiness.md`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: installed runtime with effective `minimum_lead_minutes=180`, preserved local configuration/profile, and one healthy resident monitor.

- [ ] **Step 1: Run the complete verification suite**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -v
ruff check runtime tests scripts plugins/prickly-imax-helper
python3 -m compileall -q runtime tests scripts plugins/prickly-imax-helper
zsh -n scripts/Install.command scripts/Update.command scripts/Uninstall.command
git diff --check
```

Require every command to exit zero and record the new exact test count.

- [ ] **Step 2: Verify the resident is safe to stop**

Run:

```bash
~/.local/bin/prickly-imax status
```

Proceed only when status is `armed` and `match` is `null`. If status is `staging`, `submitting`, `completed`, `unknown_after_submit`, or any block state, stop installation and report the exact state without changing booking data.

- [ ] **Step 3: Stop the monitor and install from the verified worktree**

```bash
~/.local/bin/prickly-imax stop
zsh scripts/Update.command
```

Wait until the exact monitor process disappears before update. Preserve `config.json`, the dedicated Chrome profile, request-budget state, and logs.

- [ ] **Step 4: Verify installed hashes and effective legacy default**

Compare repository and installed copies:

```bash
shasum -a 256 runtime/prickly_imax_helper/policy.py ~/.prickly-imax-helper/app/0.1.0/runtime/prickly_imax_helper/policy.py
shasum -a 256 runtime/prickly_imax_helper/scheduler.py ~/.prickly-imax-helper/app/0.1.0/runtime/prickly_imax_helper/scheduler.py
shasum -a 256 runtime/prickly_imax_helper/config.py ~/.prickly-imax-helper/app/0.1.0/runtime/prickly_imax_helper/config.py
```

Use the installed runtime to load the configuration and print only:

```json
{"effective_minimum_lead_minutes": 180}
```

Resolve the value with `config.get("minimum_lead_minutes", 180)` and never print the notification address, target identifiers, consent timestamp, or any browser data.

- [ ] **Step 5: Run doctor and restore exactly one monitor**

```bash
~/.local/bin/prickly-imax doctor
~/.local/bin/prickly-imax start
~/.local/bin/prickly-imax status
```

Require `armed`, `match: null`, exactly one exact-pattern Prickly monitor, exactly one Playwright driver, and zero processes using `/Users/woojinyoung/.hermes/browser-profiles/cgv`.

- [ ] **Step 6: Record exact evidence only**

If `docs/beta-readiness.md` is updated, include the commit, exact test count, effective 180-minute legacy default, repository/installed hashes, and final process counts. State that no showtime, party, seat, voucher, or payment click was used and that email cannot guarantee waking the user.

- [ ] **Step 7: Commit documentation evidence if changed**

```bash
git add docs/beta-readiness.md
git commit -m "docs: record minimum lead verification"
```

- [ ] **Step 8: Finish the development branch**

Invoke `superpowers:verification-before-completion`, then `superpowers:finishing-a-development-branch`. Do not push, merge, create a PR, or delete the worktree without the user's explicit integration choice.
