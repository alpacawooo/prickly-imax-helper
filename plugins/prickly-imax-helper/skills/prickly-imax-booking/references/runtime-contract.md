# Runtime Contract

The public runtime must be configuration-driven and contain no developer-specific absolute paths, customer numbers, cookies, tokens, or payment data.

State machine:

`unconfigured -> login_required -> armed -> staging -> submitting -> completed`

Failure states:

`recovering`, `rate_limited`, `blocked_duplicate`, `blocked_payment`, `unknown_after_submit`, `fatal`.

Runtime files live below `~/.prickly-imax-helper/` on macOS or `%LOCALAPPDATA%\PricklyIMAXHelper\` on Windows:

- `config.json`: non-secret booking policy
- `browser-profile/`: dedicated Chrome state; never committed
- `state/heartbeat.json`: health and scan telemetry
- `state/checkout.json`: current transaction state
- `logs/`: redacted operational logs

The monitor must discover open dates and every open date's schedule serially at process startup and once at Korea Standard Time midnight. It makes no daytime schedule-discovery requests between those events and rotates only through known eligible seat maps. If the host sleeps through midnight, the first loop after wake performs the missed discovery once; a process restart performs startup discovery again. A show added after the daily discovery is intentionally deferred until the next midnight or restart.

The monitor must keep the booking page pre-positioned, use a bounded request budget, lock the browser through submission, revalidate the pair and duplicate guard, and stop after one completed or uncertain transaction.
