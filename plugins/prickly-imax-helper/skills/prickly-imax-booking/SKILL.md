---
name: prickly-imax-booking
description: Set up, configure, diagnose, start, stop, and inspect the Prickly local CGV IMAX seat monitor and authorized booking assistant on macOS or Windows 10/11. Use when a user asks to install the helper, open the CGV login window, configure movie/theater/time/seat rules, monitor cancellations, diagnose browser or rate-limit failures, or check booking results.
---

# Prickly IMAX Booking

Operate the installed standalone runtime. Keep CGV login, customer identifiers,
vouchers, notification address, and payment state on the user's PC.

## Workflow

1. Find the installed CLI at `~/.local/bin/prickly-imax` on macOS or `%LOCALAPPDATA%\PricklyIMAXHelper\bin\prickly-imax.cmd` on Windows. If absent, direct the user to the version-pinned Notion/GitHub release installer; do not invent an unverified download URL.
2. Run the OS-specific CLI with `doctor` and fix required checks.
3. Run the OS-specific CLI with `setup` when configuration is absent. The user logs in personally in the dedicated Chrome window and records consent in the localhost setup page.
4. Never ask for or store a CGV password, voucher number, card number, or email password.
5. Start or inspect the macOS LaunchAgent or Windows Scheduled Task only after the configuration validates.
6. Report status from the OS-specific CLI and redacted local logs, not assumptions.

## Invariants

- Keep credentials and browser data local. Never commit runtime state.
- Use one browser lock for monitoring and checkout.
- Refresh the open-date list dynamically.
- Select only an exact same-row consecutive block of the configured size satisfying the configured rows and edge exclusion.
- Recheck existing tickets immediately before checkout.
- Submit only when the configured payment method covers the full amount and the remaining balance is zero.
- Verify completion from the resulting mobile ticket before reporting success.
- Enforce the documented IP-wide minimum one-second interval for every explicit CGV availability request.
- Treat `429` as a hard rate-limit signal. Stop traffic, honor cooldown, and resume through the shared request budget.
- Never silently weaken the user's seat, time, duplicate-booking, or payment constraints.

## Commands

- Diagnose: `~/.local/bin/prickly-imax doctor`
- Configure: `~/.local/bin/prickly-imax setup`
- Inspect: `~/.local/bin/prickly-imax status`
- Stop: `~/.local/bin/prickly-imax stop`

On Windows, replace `~/.local/bin/prickly-imax` with `%LOCALAPPDATA%\PricklyIMAXHelper\bin\prickly-imax.cmd`.

## References

- Read `references/onboarding.md` for the minimum user interaction.
- Read `references/runtime-contract.md` before implementing or changing the resident monitor.
- Read `references/failure-playbook.md` for browser, modal, selector, login, or rate-limit errors.
- Read `references/authorization.md` before enabling automatic submission for a distribution build.
