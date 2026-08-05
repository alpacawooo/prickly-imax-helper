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
- [x] Repeated HTTP 429 responses exponentially extend the shared cooldown from five minutes up to one hour while honoring longer server `Retry-After` values.
- [x] Open dates refresh dynamically and schedule checks rotate across dates.
- [x] Custom movie/theater identifiers drive open-date, schedule, and seat-map requests without falling back to the Odyssey/Yongsan preset.
- [x] Seat ranking enforces same-row adjacency, allowed rows, edge exclusion, and center priority.
- [x] Duplicate checks run before staging and again immediately before submission.
- [x] The current CGV mobile-ticket empty state and the legacy count state are both recognized; conflicting or unknown markup remains pre-submit `recovering` and is retried no faster than every five minutes.
- [x] Exact selected voucher count, requested seats, zero remaining balance, and one final button are required.
- [x] Submission is single-use; restart across the submission boundary becomes `unknown_after_submit`.
- [x] macOS and Windows installer/updater/uninstaller, LaunchAgent/Scheduled Task registration, diagnostic output, and redacted event logs exist.
- [x] Release builder emits macOS tar.gz and Windows zip artifacts with SHA-256 files and rejects missing authorization evidence, a non-public-IP limit scope, or an invalid request rate.
- [x] Codex marketplace and optional plugin install successfully on the development Mac.
- [x] The private repository exists at `https://github.com/alpacawooo/prickly-imax-helper` and its least-privilege hosted macOS/Windows workflow is active.

## Required before inviting pilot users

- [x] Publish the invited-pilot Notion onboarding guide: `https://app.notion.com/p/3b24fb8e6f4d81168194f4f4a4b68bef` (explicitly marked for approved pilots only; general sharing remains prohibited).
- [x] Generate authorization metadata from the locally retained CGV approval document without copying the confidential source (2026-08-05); only its SHA-256 fingerprint is embedded in the release candidate.
- [x] Complete a logged-in, no-click `dry-run` with the new dedicated runtime profile on macOS (2026-08-05); the installed LaunchAgent then reached `armed` without Hermes running concurrently.
- [x] Capture the current CGV mobile-ticket empty-state structure without submitting an order (2026-08-05); only the sanitized path, heading, tag/class, and empty-state text are retained in `tests/fixtures/cgv-mobile-ticket-empty-2026-08-05.json`.
- [x] Confirm the Apple Mail test message from the installed LaunchAgent environment, not only an interactive shell (2026-08-05; one-shot GUI launchd probe exited successfully and its unique subject token was found in Apple Mail without exposing the configured recipient).
- [ ] Complete a clean Windows 10/11 install and confirm the Scheduled Task, dedicated Chrome profile, toast, and classic Outlook test message under a standard non-admin user.
- [x] Publish the workflow and confirm green hosted macOS and Windows install smoke tests: `https://github.com/alpacawooo/prickly-imax-helper/actions/runs/30974254293`.
- [ ] Run a fresh 24-hour monitor soak with no 429, duplicate process, memory growth, login-profile loss, or checkout-guard failure. The first soak was invalidated on 2026-08-05 when a real seat match exposed a changed CGV mobile-ticket empty-state selector; it stopped before seat selection or payment.
- [x] Create the private GitHub repository.
- [x] Publish tag `0.1.0` as an authorized private prerelease and attach the authorization-gated macOS/Windows archives and checksums: `https://github.com/alpacawooo/prickly-imax-helper/releases/tag/0.1.0` (2026-08-05). Do not call the beta successful until soak and three real pilots pass.
- [x] Verify the private prerelease contains both authorization-gated platform archives and both checksum files; download count remained zero at publication verification (2026-08-05).
- [x] Replace the private-beta guide's draft wording with the exact private repository and published prerelease links (2026-08-05).
- [x] Add a privacy-safe three-pilot evidence generator and validator that requires macOS and Windows, a Windows standard user, distinct recipient providers, all lifecycle steps, local-only credentials, archive/diagnose digests, and no email or absolute user path in evidence.

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
python3 scripts/soak_audit.py start --home ~/.prickly-imax-helper
python3 scripts/soak_audit.py verify --home ~/.prickly-imax-helper
python3 scripts/pilot_audit.py init --output ~/prickly-pilot-evidence
python3 scripts/pilot_audit.py verify --input ~/prickly-pilot-evidence
```

The release metadata may include a public-safe `authorization_reference`, such as an approval letter, contract, or support-ticket number. It must never contain credentials or private approval text. When no public reference exists, the SHA-256 fingerprint of the privately retained source document is sufficient; the source document itself is never copied into a release.
