# Failure Playbook

## Browser not ready

Check Chrome, the dedicated profile, CDP port ownership, login state, managed Python environment, and Playwright package. LaunchAgents and Windows Scheduled Tasks use installer-resolved absolute paths and must not depend on an interactive shell PATH.

## Theater modal timeout

Detect whether the modal is already open before clicking its launcher. Search results may render two identical theater labels: a suggestion and the actual theater row. Select the actual row and require the enabled confirmation button.

## Date not found

Do not compare flattened `textContent` with a guessed space. Read the weekday and day-number child spans separately.

## Browser state changes unexpectedly

Use one shared file lock for read-only polling, status checks, staging, and submission.

## HTTP 429

Stop concurrent all-date bursts. Enter a cooldown, lower the request budget, and stagger date checks. Repeated short retries extend the block. Report monitoring gaps honestly.

## Final result unknown

Never submit again. Mark `unknown_after_submit`, notify the user, and verify the mobile-ticket list before any further action.
