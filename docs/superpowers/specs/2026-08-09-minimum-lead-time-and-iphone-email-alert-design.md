# Minimum Lead Time and iPhone Email Alert Design

## Goal

Prevent the helper from attempting an IMAX booking when the actual show start is less than three hours away, while keeping the existing locally sent email as the user's iPhone notification path.

## Scope

This change adds a configurable minimum lead-time policy with a default of 180 minutes. It also makes the setup and onboarding copy explicit that the configured recipient address can be added to iPhone Mail and used for mobile notification delivery.

This change does not add Pushover, ntfy, APNs, SMS, a new cloud service, a new credential, or a background acknowledgement protocol. It cannot bypass iPhone silent mode, Focus, Mail fetch delay, or notification settings.

## Lead-Time Policy

Every schedule receives one actual start timestamp in the `Asia/Seoul` timezone. The helper combines the CGV schedule date (`YYYYMMDD`) with the CGV start clock (`HHMM`). Hours from 24 through 29 roll into the following calendar day, so a schedule clock of `24:30` becomes `00:30` on the next day.

A show is eligible only when:

```text
actual_start_at - current_korea_time >= minimum_lead_minutes
```

The Odyssey preset and backward-compatible runtime default are 180 minutes. Exactly 180 minutes is eligible; 179 minutes and 59 seconds is not. Applying the calculation to every show avoids ambiguous business-date cases around midnight. Shows on later dates naturally remain eligible because they are more than three hours away.

The lead-time filter runs inside schedule eligibility before `changed_seat_targets` and before any seat-map request. An ineligible imminent show therefore cannot produce a seat match, enter checkout, select a seat, apply a voucher, or submit an order. It also does not consume a seat-map request.

## Configuration and Setup

Add optional top-level configuration field:

```json
"minimum_lead_minutes": 180
```

The preset includes the field. Existing installations that do not yet contain it use 180 at runtime, so the installed personal monitor gains the protection without reopening setup. If present, the field must be an integer from 180 through 1,440.

The localhost setup form exposes `상영 시작 최소 여유(분)` with a default and minimum of 180. Users may increase it but cannot weaken it below three hours. The user's existing installation remains at the 180-minute default unless they later increase it. Saving setup persists the field with the other non-secret booking policy.

No email password, Apple ID password, CGV credential, voucher number, or new push token is requested or stored.

## iPhone Notification Path

The runtime keeps the current notification fan-out:

1. local desktop notification;
2. local Apple Mail or classic Outlook email delivery;
3. privacy-safe `notification_result` evidence for a correlated checkout attempt.

The booking-result events remain unchanged:

- verified booking completion;
- unknown result after the submission boundary;
- payment guard block;
- duplicate-booking guard block.

Existing rate-limit operational email also remains unchanged. An email failure never changes a verified booking outcome and never authorizes a retry.

The setup page explains that the recipient mailbox should be added to iPhone Mail and that Mail notifications must be enabled to receive the same result on the phone. Setup continues to send one test email before saving. The helper makes no claim that delivery is immediate or that it can wake a sleeping user.

## Components

### `policy.py`

Add focused helpers that parse CGV schedule clocks and calculate the actual Korea start timestamp. Keep date arithmetic out of `eligible_start`, whose existing responsibility remains weekday time-window policy.

### `scheduler.py`

Extend `eligible_shows` with an injectable aware `now` value for deterministic tests. It first checks format and clock validity, then the existing weekday window, then the minimum lead time. Production callers omit `now` and receive the current `Asia/Seoul` time.

### `config.py` and `presets.py`

Validate an explicitly supplied lead-time value and provide the 180-minute preset. Missing legacy values remain valid and resolve to 180 at the policy boundary.

### `setup_server.py`

Render, parse, and persist the lead-time field. Add concise iPhone Mail instructions near the recipient address without changing the local sender bridge or asking for mail credentials.

### Documentation

Update the repository onboarding/README copy to distinguish email-to-iPhone notification from direct push and to state the Focus, silent-mode, and delivery-delay limitations.

## Failure Handling

- Invalid CGV date or clock data remains ineligible and produces no booking action.
- A naive or incorrectly zoned injected test clock is rejected by the time helper rather than silently interpreted.
- A malformed configured lead time prevents configuration save; a missing legacy value safely defaults to 180.
- A system clock that is wrong can produce a wrong lead-time decision. Diagnostics may report the effective configured minutes but must not expose the recipient address.
- Email delivery failures remain redacted operational events and do not alter checkout state.

## Verification

Add deterministic tests for:

- exactly 180 minutes remaining;
- less than 180 minutes remaining;
- a later-date show;
- `24:30` rollover;
- Korea-time behavior when the host clock uses another timezone;
- missing legacy configuration defaulting to 180;
- valid and invalid configured minute values;
- setup form rendering and persistence;
- iPhone Mail limitation copy;
- preservation of existing booking-result email calls.

Run the complete unit suite, Ruff, compile checks, macOS/Windows script parsing, and diff checks. Install only from an `armed` state with `match: null`, preserve the dedicated Chrome profile and configuration, compare repository/installed hashes, then restore exactly one monitor and one Playwright driver. No live showtime, party, seat, voucher, or payment click is needed for this policy change.
