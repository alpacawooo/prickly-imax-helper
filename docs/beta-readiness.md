# Private Beta Readiness

This checklist is the release gate. A checked implementation item is not equivalent to a completed pilot.

## Implemented and locally verified

- [x] Standalone Python package installs in a clean virtual environment.
- [x] A Python-free clean install bootstraps checksum-pinned `uv 0.11.15`, managed Python 3.12.12, and only the locked runtime dependency graph; no project build backend is resolved during installation.
- [x] Local setup server binds only to `127.0.0.1` and requires an unguessable request token.
- [x] Configuration is not saved until the dedicated Chrome session is logged in.
- [x] Setup records automatic-submission and one-device-per-public-IP consent.
- [x] Apple Mail and classic Outlook desktop adapters keep user values out of script source; setup requires a successful test message.
- [x] Dedicated system Chrome launches with an isolated profile and accepts a Playwright CDP connection.
- [x] Explicit availability requests share a cross-process minimum one-second interval.
- [x] HTTP 429 applies a shared cooldown; HTTP 401/403 becomes `login_required`.
- [x] Open dates refresh dynamically and schedule checks rotate across dates.
- [x] Seat ranking enforces same-row adjacency, allowed rows, edge exclusion, and center priority.
- [x] Duplicate checks run before staging and again immediately before submission.
- [x] Exact selected voucher count, requested seats, zero remaining balance, and one final button are required.
- [x] Submission is single-use; restart across the submission boundary becomes `unknown_after_submit`.
- [x] macOS and Windows installer/updater/uninstaller, LaunchAgent/Scheduled Task registration, diagnostic output, and redacted event logs exist.
- [x] Release builder emits macOS tar.gz and Windows zip artifacts with SHA-256 files and rejects missing authorization evidence, a non-public-IP limit scope, or an invalid request rate.
- [x] Codex marketplace and optional plugin install successfully on the development Mac.

## Required before inviting pilot users

- [x] Create the private Notion onboarding draft: `https://app.notion.com/p/3b24fb8e6f4d81168194f4f4a4b68bef` (explicitly marked not ready to share).
- [ ] Generate authorization metadata from the retained CGV approval document and its SHA-256 fingerprint.
- [ ] Complete a logged-in, no-click `dry-run` with the new dedicated public runtime profile.
- [ ] Capture current CGV checkout DOM fixtures without submitting an order and confirm selectors against them.
- [ ] Confirm the Apple Mail test message from the installed LaunchAgent environment, not only an interactive shell.
- [ ] Complete a clean Windows 10/11 install and confirm the Scheduled Task, dedicated Chrome profile, toast, and classic Outlook test message under a standard non-admin user.
- [ ] Run the full automated test suite on an actual Windows runner; local macOS tests currently validate Windows branches by simulation only.
- [ ] Run a 24-hour monitor soak with no 429, duplicate process, memory growth, or login-profile loss.
- [ ] Create the private GitHub repository, publish tag `0.1.0`, and attach the gated archive and checksum.
- [ ] Replace the private-beta guide's generic GitHub wording with the exact repository/release link.

## Required before calling the beta successful

- [ ] Three invited non-developer users complete install, login, dry-run, status, stop, update, and uninstall from the Notion guide alone.
- [ ] Each pilot confirms that credentials stayed local and that the email notification reached the intended address.
- [ ] Any pilot failure produces a sufficient redacted `diagnose` result without screenshots containing private data.
- [ ] No pilot network runs more than one helper instance behind the same public IP.

## Commands used for evidence

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -v
zsh -n scripts/Install.command scripts/Update.command scripts/Uninstall.command
uv lock --check
PYTHONPATH=runtime python -m unittest discover -s tests -v  # Windows runner
python3 scripts/build_release.py --version 0.1.0 --authorization <private-metadata.json> --output dist
```

The release metadata may include a public-safe `authorization_reference`, such as an approval letter, contract, or support-ticket number. It must never contain credentials or private approval text. When no public reference exists, the SHA-256 fingerprint of the privately retained source document is sufficient; the source document itself is never copied into a release.
