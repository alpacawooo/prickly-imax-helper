# Theater Picker Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent qualifying seats from being lost when CGV renders theater controls late, already has the configured theater selected, or requires separate search-suggestion, theater-row, and confirmation actions.

**Architecture:** Keep `CheckoutFlow` fail-closed and extract two small browser-state operations: one proves the configured theater/format/showtimes are already ready, and one opens the theater picker through ordered semantic selectors. `open_movie_and_theater()` uses those operations without changing seat selection, duplicate checks, voucher checks, or submission.

**Tech Stack:** Python 3.12, Playwright 1.62, `unittest`, GitHub Actions on macOS and Windows.

## Global Constraints

- A controlled live test may navigate only through configured movie and theater preparation; do not click a showtime, real seat, voucher, or submission control.
- Never accept a different theater, movie, or format as ready.
- Keep exact same-row seats, duplicate prevention, exact IMAX voucher count, zero balance, and one-submit rules unchanged.
- Continue to fail before seat selection when the configured booking state cannot be proven.

---

### Task 1: Reproduce the already-selected-theater regression

**Files:**
- Modify: `tests/test_checkout_browser.py`
- Modify: `tests/test_checkout_navigation.py`

**Interfaces:**
- Consumes: `CheckoutFlow(page, config)` and `CheckoutFlow.open_movie_and_theater()`.
- Produces: regression coverage for `_booking_page_state(theater, format_name)` and `_open_theater_picker()`.

- [ ] **Step 1: Write failing browser-state tests**

Add tests that render local HTML and assert that the configured theater plus visible showtime and format yields `target_ready=True`, a different theater yields `False`, the legacy launcher clicks, and a visible semantic `극장 선택` launcher clicks.

- [ ] **Step 2: Write a failing navigation test**

Use a scripted page whose movie click succeeds and whose booking state is `{"picker": false, "target_ready": true}`. Assert that `open_movie_and_theater()` returns without requesting a launcher.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
PYTHONPATH=runtime python3 -m unittest tests.test_checkout_browser tests.test_checkout_navigation -v
```

Expected: failure because the browser-state helpers do not exist and the current flow still searches for the legacy launcher.

### Task 2: Implement fail-closed theater-state recovery

**Files:**
- Modify: `runtime/prickly_imax_helper/checkout.py`
- Test: `tests/test_checkout_browser.py`
- Test: `tests/test_checkout_navigation.py`

**Interfaces:**
- Produces: `CheckoutFlow._booking_page_state(theater: str, format_name: str) -> dict[str, bool]`.
- Produces: `CheckoutFlow._open_theater_picker() -> bool`.
- Preserves: `CheckoutFlow.open_movie_and_theater() -> None`.

- [ ] **Step 1: Implement `_booking_page_state` minimally**

Return `picker=True` only for a visible region-search input. Return `target_ready=True` only when the exact configured theater is visible in a selected/active control, at least one visible `HH:MM-HH:MM` showtime exists, and the configured format text is visible.

- [ ] **Step 2: Implement `_open_theater_picker` minimally**

Try visible buttons in this order: the legacy `.voice-only` label `자주가는 CGV 목록 수정`, exact visible text `극장 선택`, and accessible labels/titles containing both `극장` and `선택` or `수정`. Click exactly one enabled visible control and return whether it was found.

- [ ] **Step 3: Wire the helpers into `open_movie_and_theater`**

Poll for a picker or proven ready target for at most 10 seconds after the route changes. Return immediately when `target_ready` is proven. Otherwise reuse an already-open picker or call `_open_theater_picker()`. Preserve `CheckoutError("theater picker launcher not found")` when neither state is available after the bounded wait.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same focused command and require all tests to pass.

- [ ] **Step 5: Commit the code and regression tests**

```bash
git add runtime/prickly_imax_helper/checkout.py tests/test_checkout_browser.py tests/test_checkout_navigation.py
git commit -m "fix: recover configured theater booking state"
```

### Task 3: Verify, install, and publish the patch

**Files:**
- Modify only if required by verification: `docs/beta-readiness.md`

**Interfaces:**
- Consumes: patched runtime and installers.
- Produces: verified local runtime and a GitHub pull request.

- [ ] **Step 1: Run full local verification**

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -v
ruff check runtime tests scripts plugins/prickly-imax-helper
python3 -m compileall -q runtime tests scripts plugins/prickly-imax-helper
zsh -n scripts/Install.command scripts/Update.command scripts/Uninstall.command
```

- [ ] **Step 2: Install without overlapping the resident monitor**

Stop the service, run the repository updater/installer against the patched checkout, and restart only after `doctor` passes. Preserve the dedicated Chrome profile and configuration.

- [ ] **Step 3: Verify local runtime state without a manual CGV request**

Confirm exactly one monitor and one Playwright driver, `browser_state_present=true`, and no Hermes CGV profile process. A current `match` must be either `null` or handled only by the resident monitor.

- [ ] **Step 4: Push the branch and open a pull request**

Publish the branch, open a PR describing the ten identical failures and the regression test, and wait for macOS/Windows CI.

- [ ] **Step 5: Report honestly**

Claim the deterministic regression fixed only after focused and full tests pass. Do not claim a real booking succeeded until the resident monitor completes one under the unchanged safety guards.

### Task 4: Reproduce and fix the staged theater-result flow

**Files:**
- Modify: `tests/test_checkout_browser.py`
- Modify: `runtime/prickly_imax_helper/checkout.py`

- [x] **Step 1: Reproduce the live sequence without selecting a showtime or seat**

The live picker showed two exact `용산아이파크몰` buttons. The first click reduced them to one actual theater row. Clicking that row exposed an enabled `극장선택` button; it did not close the picker by itself.

- [x] **Step 2: Write and verify a failing browser regression**

The regression models suggestion removal, actual-row selection, confirmation, and the final configured theater/format/showtime proof. It failed before production changes because `_select_theater_from_picker` did not exist.

- [x] **Step 3: Implement the minimum three-stage flow**

Click the duplicate suggestion, wait for one exact actual row, click it, require and click the enabled confirmation button, then fail closed unless the configured booking state becomes ready.

- [x] **Step 4: Run focused and full local verification**

The focused regression and all 115 unit tests pass. Ruff, compile, macOS script parsing, and `git diff --check` pass.

- [x] **Step 5: Install and repeat the controlled live no-seat test**

Require the picker to close and the configured theater, format, and showtimes to be proven. Do not click a showtime or proceed to seats.

The first installed-runtime verification passed with `theater_ready=true` and `picker_closed=true`; showtime, seat, voucher, and submission clicks all remained false.

### Task 5: Remove ordering and transient-click assumptions

- [x] **Step 1: Add RED tests for reversed DOM order and an ignored first row click**
- [x] **Step 2: Select the suggestion outside `li` and the actual row inside visible `li`**
- [x] **Step 3: Retry once only when no selected chip or confirmation is visible**
- [x] **Step 4: Pass all 116 tests, Ruff, compile, script parsing, and diff checks**
- [x] **Step 5: Install and pass a controlled live theater-preparation test**
