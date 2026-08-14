# Balanced Hot Scan Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spend four of every five steady-state availability requests on fair known-show seat probes while preserving dynamic date and schedule discovery.

**Architecture:** Add a pure in-memory `BalancedScanPlanner` to `scheduler.py`. It owns open-date/schedule cache topology, a fair hot-target cursor, the deterministic 4:1 lane sequence, discovery priority, and privacy-safe timing metrics. `monitor.py` remains the only component issuing CGV requests and continues routing every request through `CgvSession` and its shared `RequestBudget`; checkout remains unchanged.

**Tech Stack:** Python 3.10+, dataclasses, unittest, existing Playwright-backed CGV session.

## Global Constraints

- Never exceed one explicit CGV availability request per public IP per second or issue parallel requests.
- Preserve the 30-second open-date refresh, login handling, 429 cooldown, duplicate guards, voucher count, zero balance, one-submit boundary, and mobile-ticket proof.
- Do not persist the discovery cache across restarts.
- Tests use fake data only and click no CGV control.

---

### Task 1: Pure balanced request planner

**Files:**
- Modify: `runtime/prickly_imax_helper/scheduler.py`
- Test: `tests/test_scheduler_and_cgv.py`

**Interfaces:**
- Produces: `ScanAction(lane, kind, ymd=None, show=None)` and `BalancedScanPlanner` methods `replace_dates`, `update_schedule`, `next_action`, `remove_hot_target`, and `metrics`.

- [ ] Write failing tests for `hot, hot, hot, hot, discovery`, two-target fairness across the discovery slot, all-discovery empty-hot behavior, new-date priority, stalest-date priority, target pruning, cursor preservation, and timing estimates.
- [ ] Run the focused scheduler suite and verify the new tests fail because the planner does not exist.
- [ ] Implement the smallest pure planner satisfying those tests, using stable show keys and a monotonic-time argument supplied by the caller.
- [ ] Run the focused suite and commit the planner.

### Task 2: Resident monitor integration

**Files:**
- Modify: `runtime/prickly_imax_helper/monitor.py`
- Test: `tests/test_monitor_safety.py`

**Interfaces:**
- Consumes: `BalancedScanPlanner.next_action(now, open_dates_due)`.
- Produces: one serialized API call per loop and heartbeat fields `hot_target_count`, `estimated_hot_revisit_seconds`, `discovery_queue_count`, `oldest_schedule_age_seconds`, and `last_scan_lane`.

- [ ] Write a fake-session monitor test proving the first populated steady-state actions are four fair seat calls then one schedule discovery, and that a match enters checkout once.
- [ ] Verify the tests fail against the old full-date loop.
- [ ] Replace the full-date scan loop with planner actions while keeping `require_login`, `RateLimited`, recovery, checkout, notification, and submission code unchanged.
- [ ] Log only topology changes, not every successful hot probe; heartbeat after every completed action with privacy-safe metrics and `errors=0`.
- [ ] Run monitor, scheduler, rate-limit, checkout, and audit tests and commit.

### Task 3: Cross-platform and installed-runtime verification

**Files:**
- Modify only if exact evidence warrants: `docs/beta-readiness.md`

- [ ] Run the full unit suite, Ruff, compileall, shell/PowerShell syntax checks, lock validation, and `git diff --check`.
- [ ] Push the feature branch and require macOS and Windows CI to pass.
- [ ] Confirm the resident is `armed` with `match:null`, then stop and install the verified runtime without deleting config, profile, logs, or request-budget state.
- [ ] Confirm source/installed hashes match, `doctor` passes, one monitor and one Playwright driver exist, Hermes CGV processes remain zero, and heartbeat exposes the new lane metrics.
- [ ] Do not click a showtime, party, seat, voucher, or payment control during verification.
