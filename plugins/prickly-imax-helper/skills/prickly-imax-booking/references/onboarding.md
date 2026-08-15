# Onboarding

Ask for the booking policy in one message. Do not ask for a CGV password or payment credentials.

Required fields:

- movie and theater
- screen format and party size
- allowed dates or all open dates
- weekday/time rules
- minimum lead time before the show starts
- allowed rows and edge exclusion ratio
- center preference
- payment method and maximum payable balance
- duplicate-booking behavior
- notification recipient provider (Gmail, Naver Mail, iCloud Mail, or other) and address

Default Odyssey profile:

- theater: 용산아이파크몰
- format: IMAX
- party size: 2
- dates: every currently open date, refreshed continuously
- weekday: start at or after 19:00
- Saturday: no time restriction
- Sunday: start before 22:00
- minimum lead: 180 minutes
- rows: D through J
- exclude: 20% at each row edge
- preference: consecutive same-row seats closest to center
- duplicate booking, cancellation, and seat changes: forbidden

Movie, CGV theater, IMAX display format, party size, time windows, rows, edge exclusion, and center preference are user-editable defaults. The minimum lead time can be increased as high as 1,440 minutes, but the default 180-minute safety floor cannot be lowered. CGV extended clocks from `24:00` through `29:59` are normalized to the following calendar day before this check. Same-row adjacency, all-open-date refresh, no cancellation/change, voucher-only zero-balance submission, and the request budget remain enforced safety boundaries.

Duplicate prevention is enabled in every shipped preset. An advanced operator may explicitly set `prevent_duplicate_booking` to `false` only for a voucher-exhaustive one-transaction setup where the configured account has exactly the registered IMAX voucher count required for the selected party. This skips only the two existing-ticket page lookups; it does not skip seat validation, voucher-count proof, zero-balance proof, the one-submit guard, mobile-ticket verification, or the terminal stop.

The user logs in personally in the dedicated Chrome window. Confirm login by visible account state, not by reading credentials.
The recipient provider is independent of the operating system. Use Apple Mail on macOS or classic Outlook desktop on Windows only as the local sending bridge, and never request an email password or app password.
The configured recipient account may also be used in the iPhone Mail app. This is ordinary email notification, not direct mobile push: delivery can be delayed, and the helper cannot bypass silent mode or Focus on the iPhone.
