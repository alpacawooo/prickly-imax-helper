# Prickly IMAX Helper

Prickly IMAX Helper is a macOS-local CGV IMAX availability monitor and fail-closed voucher booking runtime. The standalone runtime is the product; the Codex plugin is an optional conversational setup and diagnostics layer.

The repository contains no CGV credentials, customer identifiers, cookies, voucher numbers, email credentials, or developer-specific paths.

## Private beta flow

1. Accept the private GitHub repository invitation and download the pinned release plus its SHA-256 file.
2. Verify the checksum, extract the release, and open `scripts/Install.command`.
3. In the localhost-only setup page, open the dedicated Chrome profile and log in to CGV personally.
4. Confirm the Odyssey preset, notification email, and one-time automatic voucher-submission consent.
5. The LaunchAgent starts the resident monitor. Check it with `~/.local/bin/prickly-imax status`.

No password or payment credential is entered into Prickly AI, Codex, Notion, GitHub, or the helper.
Python is not a user prerequisite; the installer bootstraps a checksum-verified, pinned `uv` binary and managed Python when no suitable local interpreter exists.

## Repository layout

- `.agents/plugins/marketplace.json`: Codex marketplace manifest
- `plugins/prickly-imax-helper/`: plugin package
- `runtime/`: independent local runtime
- `scripts/`: installer, uninstaller, and gated release builder
- `docs/notion-quick-start.md`: copy-ready private-beta guide
- `docs/beta-readiness.md`: evidence-backed release and pilot gate
- `tests/`: deterministic policy tests

## Privacy

CGV login and browser data remain under the user's local profile. Runtime state must never be committed to this repository.

## Safety contract

- All explicit CGV availability requests share a cross-process one-request-per-second budget.
- HTTP 429 stops traffic and applies a shared cooldown.
- Only an exact same-row consecutive block satisfying the configured policy can proceed.
- The runtime submits once only after duplicate, seat, voucher count, and zero-balance checks.
- A restart or network failure across the submission boundary becomes `unknown_after_submit` and is never retried automatically.

## Development

```bash
PYTHONPATH=runtime python3 -m unittest discover -s tests -v
PYTHONPATH=runtime python3 -m prickly_imax_helper.cli --home /tmp/prickly-test doctor
```

Release generation is blocked unless authorization metadata contains an approval date, approved scope, a `public_ip` request limit no greater than one request per second, and either a public-safe authorization reference or the SHA-256 fingerprint of the privately retained source document. The private source document is never copied into a release.
