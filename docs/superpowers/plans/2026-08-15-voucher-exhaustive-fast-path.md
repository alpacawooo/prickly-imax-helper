# Voucher-Exhaustive Fast Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow an explicitly configured voucher-exhaustive personal runtime to skip both duplicate-booking page checks while preserving the public safe default and every seat, voucher, zero-balance, one-submit, and uncertain-result guard.

**Architecture:** `prevent_duplicate_booking` remains `true` in every shipped preset and setup path. Runtime and plugin validation accept either Boolean value, default a missing value to `true`, and reject non-Booleans. Checkout branches only around the two remote duplicate-ticket checks; all other stages and terminal-state behavior remain unchanged.

**Tech Stack:** Python 3.13, `unittest`, Playwright runtime fakes, JSON configuration, shell installers.

## Global Constraints

- Public presets and setup output keep `prevent_duplicate_booking: true`.
- Only explicit Boolean `false` enables the fast path; missing values behave as `true`.
- Exact same-row consecutive seats, configured party size, registered IMAX voucher count equal to party size, and remaining balance `0` remain mandatory.
- Submission remains exactly once; `unknown_after_submit` is never retried automatically.
- Existing booking cancellation and seat changes remain forbidden.
- Verification must not browse CGV or click a showtime, party, seat, voucher, or payment control.
- The personal installed configuration may be changed only while the monitor is stopped and its state is `armed` with `match: null`.

---

### Task 1: Configuration Contract

**Files:**
- Modify: `tests/test_runtime_core.py`
- Modify: `tests/test_policy.py`
- Modify: `runtime/prickly_imax_helper/config.py`
- Modify: `plugins/prickly-imax-helper/skills/prickly-imax-booking/scripts/policy.py`

**Interfaces:**
- Consumes: `validate_config(value: dict) -> list[str]` and plugin `validate(config: dict) -> dict`.
- Produces: a Boolean policy contract where `true`, `false`, and omission are valid, while strings, numbers, and null are invalid.

- [ ] **Step 1: Write failing runtime and plugin validation tests**

```python
def test_duplicate_policy_accepts_explicit_false_and_legacy_default(self):
    disabled = copy.deepcopy(VALID_CONFIG)
    disabled["prevent_duplicate_booking"] = False
    self.assertEqual(validate_config(disabled), [])
    legacy = copy.deepcopy(VALID_CONFIG)
    legacy.pop("prevent_duplicate_booking")
    self.assertEqual(validate_config(legacy), [])

def test_duplicate_policy_rejects_non_boolean_values(self):
    for invalid in (0, 1, None, "false"):
        value = copy.deepcopy(VALID_CONFIG)
        value["prevent_duplicate_booking"] = invalid
        self.assertTrue(any("prevent_duplicate_booking" in error for error in validate_config(value)))
```

Mirror the same behavior through `policy.validate()` using `CONFIG`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=runtime python -m unittest \
  tests.test_runtime_core.ConfigTests.test_duplicate_policy_accepts_explicit_false_and_legacy_default \
  tests.test_runtime_core.ConfigTests.test_duplicate_policy_rejects_non_boolean_values \
  tests.test_policy.PolicyTests.test_duplicate_policy_accepts_explicit_false_and_legacy_default \
  tests.test_policy.PolicyTests.test_duplicate_policy_rejects_non_boolean_values
```

Expected: explicit `false` is rejected by the current fixed-true validators.

- [ ] **Step 3: Implement the minimal Boolean validation**

Use this contract in both validators:

```python
duplicate_policy = value.get("prevent_duplicate_booking", True)
if not isinstance(duplicate_policy, bool):
    errors.append("prevent_duplicate_booking must be a boolean")
```

Remove `prevent_duplicate_booking` from the plugin's fixed-value `LOCKED_SAFETY` mapping, but leave every default JSON/preset value set to `true`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all four tests pass.

- [ ] **Step 5: Commit the configuration contract**

```bash
git add tests/test_runtime_core.py tests/test_policy.py runtime/prickly_imax_helper/config.py plugins/prickly-imax-helper/skills/prickly-imax-booking/scripts/policy.py
git commit -m "feat: allow explicit duplicate-check policy"
```

### Task 2: Checkout Fast Path

**Files:**
- Modify: `tests/test_monitor_safety.py`
- Modify: `runtime/prickly_imax_helper/monitor.py`

**Interfaces:**
- Consumes: validated `config["prevent_duplicate_booking"]: bool`, defaulting to `True` when absent.
- Produces: `_checkout(...) -> str` with unchanged terminal outcomes and optional omission of the two duplicate-guard stages.

- [ ] **Step 1: Write a failing checkout behavior test**

Add a successful flow whose `ensure_no_existing_ticket()` raises `AssertionError` if called. Invoke `_checkout` with `prevent_duplicate_booking = False` and assert:

```python
self.assertEqual(result, Status.COMPLETED.value)
self.assertEqual(actions, [
    "theater", "date", "showtime", "party:2", "seats",
    "vouchers", "zero_balance", "submission", "mobile_ticket",
])
self.assertEqual(passed, [
    "theater", "date", "showtime", "party", "seats", "vouchers",
    "zero_balance", "submission_ready", "submission", "mobile_ticket",
])
```

Keep the existing default-path test unchanged so it continues to prove that both duplicate checks run when the policy is `true`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTHONPATH=runtime python -m unittest tests.test_monitor_safety.MonitorSafetyTests.test_checkout_skips_duplicate_guards_only_when_explicitly_disabled
```

Expected: FAIL because the first duplicate-ticket check is still called.

- [ ] **Step 3: Implement the minimal checkout branch**

```python
prevent_duplicates = config.get("prevent_duplicate_booking", True)
if prevent_duplicates:
    with recorder.stage("duplicate_guard_before"):
        flow.ensure_no_existing_ticket(match, separate_tab=True)
```

Apply the same conditional around `duplicate_guard_final` only. Do not alter any other stage, exception handler, submit call, or mobile-ticket proof.

- [ ] **Step 4: Run focused checkout tests and verify GREEN**

Run:

```bash
PYTHONPATH=runtime python -m unittest \
  tests.test_monitor_safety.MonitorSafetyTests.test_checkout_skips_duplicate_guards_only_when_explicitly_disabled \
  tests.test_monitor_safety.MonitorSafetyTests.test_checkout_records_ordered_stages_and_one_terminal_outcome \
  tests.test_monitor_safety.MonitorSafetyTests.test_unavailable_duplicate_guard_recovers_before_any_booking_click
```

Expected: fast path passes without duplicate calls; default path and unavailable-guard fail-closed behavior remain green.

- [ ] **Step 5: Commit the checkout behavior**

```bash
git add tests/test_monitor_safety.py runtime/prickly_imax_helper/monitor.py
git commit -m "feat: add voucher-exhaustive checkout fast path"
```

### Task 3: Public Documentation

**Files:**
- Modify: `README.md`
- Modify: `plugins/prickly-imax-helper/skills/prickly-imax-booking/references/runtime-contract.md`
- Modify: `plugins/prickly-imax-helper/skills/prickly-imax-booking/references/onboarding.md`

**Interfaces:**
- Consumes: the Boolean policy implemented in Tasks 1 and 2.
- Produces: honest operator guidance that keeps duplicate prevention as the shipped default and explains the advanced voucher-exhaustive exception.

- [ ] **Step 1: Update safety documentation**

State that duplicate checks run before and after seat/voucher preparation by default. Document that explicit local `false` skips only those two checks and is suitable only when the configured account has exactly the voucher count needed for one transaction and terminal stop behavior is preserved.

- [ ] **Step 2: Verify documentation consistency**

Run:

```bash
rg -n "prevent_duplicate_booking|duplicate|중복" README.md plugins/prickly-imax-helper
```

Expected: no statement falsely claims duplicate checks are unconditional, and shipped defaults remain `true`.

- [ ] **Step 3: Commit documentation**

```bash
git add README.md plugins/prickly-imax-helper/skills/prickly-imax-booking/references/runtime-contract.md plugins/prickly-imax-helper/skills/prickly-imax-booking/references/onboarding.md
git commit -m "docs: explain voucher-exhaustive fast path"
```

### Task 4: Full Verification and Personal Installation

**Files:**
- Modify after verified stop: `/Users/woojinyoung/.prickly-imax-helper/config.json`
- Install from: `scripts/Update.command`

**Interfaces:**
- Consumes: verified source tree and the existing installed runtime.
- Produces: one armed personal monitor with explicit fast-path configuration and no duplicate process.

- [ ] **Step 1: Run the complete source verification**

```bash
PYTHONPATH=runtime /Users/woojinyoung/Documents/Playground/prickly-imax-helper/.venv/bin/python -m unittest discover -s tests
/Users/woojinyoung/.cache/uv/archive-v0/m2snfKWiNq-OkyeP/bin/ruff check runtime tests scripts plugins/prickly-imax-helper
/Users/woojinyoung/Documents/Playground/prickly-imax-helper/.venv/bin/python -m compileall -q runtime tests scripts
zsh -n scripts/*.command
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 2: Record and validate the resident pre-install state**

Check `prickly-imax status` and redacted `diagnose`. Require `armed`, `match: null`, `errors: 0`, one Prickly monitor, one Playwright driver, and no Hermes process. Record config hash and browser-profile/log file counts without printing secrets.

- [ ] **Step 3: Stop and switch the personal policy**

Stop the resident monitor. Apply only this JSON value change:

```json
"prevent_duplicate_booking": false
```

Validate the resulting config with the newly verified runtime before installation.

- [ ] **Step 4: Install and restore the resident monitor**

Run `zsh scripts/Update.command`, then start the runtime if the updater does not restore it. Do not manually browse CGV or interact with any booking control.

- [ ] **Step 5: Verify post-install identity and health**

Require installed/source hashes to match, `armed`, `match: null`, `errors: 0`, one monitor, one Playwright driver, no Hermes, the same browser profile, and explicit `prevent_duplicate_booking: false`. Confirm the public preset still contains `true`.

- [ ] **Step 6: Commit any installation-evidence documentation required by the repository**

If the repository has an established evidence file for local installations, append only redacted hashes, test counts, and process/state results; otherwise leave local runtime evidence uncommitted and report it directly.
