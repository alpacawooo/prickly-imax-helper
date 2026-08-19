# Prickly IMAX Helper

Prickly IMAX Helper is a local-first CGV IMAX availability monitor and fail-closed voucher booking runtime for macOS and Windows 10/11. The standalone runtime is the product; the Codex plugin is an optional conversational setup and diagnostics layer.

The repository contains no CGV credentials, customer identifiers, cookies, voucher numbers, email credentials, or developer-specific paths.

## Public release flow

1. Open the public [0.2.1 release](https://github.com/alpacawooo/prickly-imax-helper/releases/tag/0.2.1) and download the installer for your operating system plus its SHA-256 file. No repository invitation or GitHub sign-in is required.
2. Verify the checksum, extract the release, and run `scripts/Install.command` on macOS or `scripts/Install.ps1` on Windows.
3. In the localhost-only setup page, open the dedicated Chrome profile and log in to CGV personally.
4. Keep or edit the Odyssey preset (movie, CGV theater, IMAX format, time windows, minimum lead time, party size, rows, edge exclusion, and seat priority), then confirm the notification email and one-time automatic voucher-submission consent.
5. The macOS LaunchAgent or Windows Scheduled Task starts the resident monitor. Check it with the OS-specific launcher described in the onboarding guide.

### Windows 10/11 one-line install

Download only `prickly-imax-helper-0.2.1.zip` and leave the original ZIP unextracted. Use the current PowerShell command in [docs/notion-quick-start.md](docs/notion-quick-start.md). It searches the default Downloads folder, the Desktop, and Desktop subfolders such as a custom Chrome download folder. If the ZIP is missing, the command stops before hashing and prints only the download instruction. If the ZIP exists but the SHA-256 differs, it stops with a separate wrong-version or damaged-file message. Only a matching ZIP is extracted and installed.

No password or payment credential is entered into Prickly AI, Codex, Notion, GitHub, or the helper.
Python is not a user prerequisite; the installer bootstraps a checksum-verified, pinned `uv` binary and managed Python. It installs only the locked runtime dependencies and generates a local launcher without resolving a separate project build backend.

Users choose a Gmail, Naver Mail, iCloud Mail, or other recipient address during setup. Email delivery uses the account already signed in to Apple Mail on macOS or classic Outlook desktop on Windows, so the helper never asks for an email or app password. New Outlook for Windows does not expose the classic Outlook COM interface and is not yet supported as the local sending bridge; Windows desktop notifications still work independently.

The configured recipient account can also be added to the iPhone Mail app. The helper sends ordinary email rather than direct mobile push, so delivery can be delayed and it cannot bypass the iPhone's silent mode or Focus settings.

## Repository layout

- `.agents/plugins/marketplace.json`: Codex marketplace manifest
- `plugins/prickly-imax-helper/`: plugin package
- `runtime/`: independent local runtime
- `scripts/`: installer, uninstaller, and gated release builder
- `docs/notion-quick-start.md`: copy-ready public installation guide
- `docs/dm-operator-pack.md`: copy-ready DM recruitment, waitlist, invite, and completion replies
- `docs/pilot-runbook.md`: three-person operator checklist and privacy-safe evidence workflow
- `docs/beta-readiness.md`: evidence-backed release and pilot gate
- `tests/`: deterministic policy tests

## Privacy

CGV login and browser data remain under the user's local profile. Runtime state must never be committed to this repository.

## Safety contract

- All explicit CGV availability requests share a cross-process one-request-per-second budget.
- The monitor discovers open dates and their schedules serially at process startup and once at Korea Standard Time midnight. Between those events it makes no daytime schedule-discovery requests and rotates only through known eligible seat maps.
- If the computer sleeps through midnight, the first loop after wake runs the missed daily discovery once. A process restart also performs startup discovery; a show added later in the day is intentionally not discovered until the next midnight or restart.
- HTTP 429 stops traffic for at least five minutes; repeated limits double the shared cooldown up to one hour, while a longer server `Retry-After` always wins.
- Only an exact same-row consecutive block of the configured size satisfying the configured rows and edge exclusion can proceed.
- Shows must start at least three hours after the current Korea time by default. This 180-minute safety floor cannot be lowered, but it can be increased up to 1,440 minutes.
- CGV extended clock values from `24:00` through `29:59` are normalized to the following calendar day before the minimum-lead check.
- Odyssey at Yongsan IMAX, weekday 19:00+, all Saturday, Sunday before 22:00, two seats, D-J rows, 20% edge exclusion, and center priority are editable defaults rather than locked values.
- Shipped presets keep duplicate-booking prevention enabled, so the runtime checks existing tickets before booking preparation and again after the seat, voucher-count, and zero-balance checks.
- An advanced local `prevent_duplicate_booking: false` policy skips only those two existing-ticket page lookups. It is intended for a voucher-exhaustive one-transaction setup; exact consecutive seats, voucher count, zero balance, one submission, mobile-ticket proof, and terminal stop behavior remain mandatory.
- A restart or network failure across the submission boundary becomes `unknown_after_submit` and is never retried automatically.

## Development

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -v
PYTHONPATH=runtime python3 -m prickly_imax_helper.cli --home /tmp/prickly-test doctor
```

Release generation is blocked unless authorization metadata contains an approval date, approved scope, a `public_ip` request limit no greater than one request per second, and either a public-safe authorization reference or the SHA-256 fingerprint of the privately retained source document. The private source document is never copied into a release.

To change conditions after installation, stop the resident monitor before reopening setup. This avoids competing for the dedicated browser lock:

```bash
~/.local/bin/prickly-imax stop
~/.local/bin/prickly-imax setup
~/.local/bin/prickly-imax start
```
