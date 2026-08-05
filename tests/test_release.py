from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts/build_release.py"
BUILD_SPEC = importlib.util.spec_from_file_location("prickly_build_release", BUILD_SCRIPT)
build_release = importlib.util.module_from_spec(BUILD_SPEC)
assert BUILD_SPEC.loader is not None
BUILD_SPEC.loader.exec_module(build_release)


class ReleaseTests(unittest.TestCase):
    def test_release_privacy_scan_rejects_state_secrets_and_absolute_user_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            (stage / "safe.txt").write_text("portable content", encoding="utf-8")
            build_release.validate_stage(stage)
            (stage / "config.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "forbidden runtime file"):
                build_release.validate_stage(stage)
            (stage / "config.json").unlink()
            (stage / "unsafe.py").write_text("ROOT = '/Users/private/project'", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "developer-specific absolute path"):
                build_release.validate_stage(stage)

    def test_ci_runs_on_macos_and_windows_with_read_only_contents(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
        self.assertIn("macos-latest", workflow)
        self.assertIn("windows-latest", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("Management.Automation.Language.Parser", workflow)
        self.assertIn("zsh -n scripts/Install.command", workflow)

    def test_installer_avoids_unlocked_project_build_backend(self):
        installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        self.assertIn("--no-install-project", installer)
        self.assertNotIn("--no-editable", installer)
        self.assertIn('"${VENV_DIR}/bin/prickly-imax"', installer)

    def test_install_and_uninstall_restrict_app_home_to_user_home(self):
        for name in ("Install.command", "Uninstall.command"):
            script = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn('[[ ${APP_HOME} != "${USER_HOME}/"* ]]', script)

    def test_macos_update_replaces_only_the_versioned_runtime(self):
        installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        self.assertIn("RUNTIME_TARGET=${APP_DIR}/runtime", installer)
        self.assertIn('/bin/rm -rf -- "${RUNTIME_TARGET}"', installer)
        self.assertNotIn('/bin/rm -rf -- "${APP_HOME}"', installer)

    def test_windows_installer_is_pinned_and_user_scoped(self):
        installer = (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8")
        uninstaller = (ROOT / "scripts/Uninstall.ps1").read_text(encoding="utf-8")
        self.assertIn('$UvVersion = "0.11.15"', installer)
        self.assertIn('$ManagedPythonVersion = "3.12.12"', installer)
        self.assertIn("--no-install-project", installer)
        self.assertIn("Register-ScheduledTask", installer)
        self.assertIn("Stop-ScheduledTask", installer)
        self.assertIn("-RunLevel Limited", installer)
        self.assertIn("$ExpectedPrefix", installer)
        self.assertIn("$ExpectedPrefix", uninstaller)
        self.assertNotIn("password", installer.lower())

    def test_fingerprint_keeps_source_private(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "private-approval.txt"
            source.write_text("private approval body", encoding="utf-8")
            metadata = root / "authorization.json"
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/fingerprint_authorization.py"),
                    str(source),
                    "--approved-at",
                    "2026-08-05",
                    "--reference",
                    "CGV-APPROVAL-2026-001",
                    "--output",
                    str(metadata),
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            result = json.loads(process.stdout)
            self.assertFalse(result["source_copied"])
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(payload["document_sha256"], hashlib.sha256(b"private approval body").hexdigest())
            self.assertEqual(payload["authorization_reference"], "CGV-APPROVAL-2026-001")
            self.assertEqual(payload["request_limit_scope"], "public_ip")
            self.assertNotIn("private approval body", metadata.read_text(encoding="utf-8"))

    def test_release_requires_authorization_and_emits_matching_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            authorization = root / "authorization.json"
            authorization.write_text(
                json.dumps(
                    {
                        "approved_at": "2026-08-05",
                        "scope": [
                            "automated_availability_query",
                            "automated_seat_selection",
                            "voucher_submission",
                            "private_beta_distribution",
                        ],
                        "request_limit_scope": "public_ip",
                        "max_requests_per_ip_per_second": 1.0,
                        "document_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )
            output = root / "dist"
            process = subprocess.run(
                [sys.executable, str(ROOT / "scripts/build_release.py"), "--version", "0.1.0", "--authorization", str(authorization), "--output", str(output)],
                text=True,
                capture_output=True,
                check=True,
            )
            result = json.loads(process.stdout)
            archive = Path(result["archive"])
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), result["sha256"])
            with tarfile.open(archive) as bundle:
                names = bundle.getnames()
                self.assertTrue(any(name.endswith("scripts/Install.command") for name in names))
                self.assertTrue(any(name.endswith("scripts/Update.command") for name in names))
                self.assertTrue(any(name.endswith("uv.lock") for name in names))
                self.assertTrue(any(name.endswith("AUTHORIZATION.json") for name in names))
                self.assertFalse(any(".egg-info" in name or "__pycache__" in name for name in names))
            windows = next(item for item in result["artifacts"] if item["operating_system"] == "windows")
            windows_archive = Path(windows["archive"])
            self.assertEqual(hashlib.sha256(windows_archive.read_bytes()).hexdigest(), windows["sha256"])
            with zipfile.ZipFile(windows_archive) as bundle:
                names = bundle.namelist()
                self.assertTrue(any(name.endswith("scripts/Install.ps1") for name in names))
                self.assertTrue(any(name.endswith("scripts/Update.ps1") for name in names))
                self.assertTrue(any(name.endswith("scripts/Uninstall.ps1") for name in names))
                self.assertTrue(any(name.endswith("AUTHORIZATION.json") for name in names))

    def test_release_rejects_rate_above_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            authorization = root / "authorization.json"
            authorization.write_text(
                json.dumps(
                    {
                        "approved_at": "2026-08-05",
                        "scope": [
                            "automated_availability_query",
                            "automated_seat_selection",
                            "voucher_submission",
                            "private_beta_distribution",
                        ],
                        "request_limit_scope": "public_ip",
                        "max_requests_per_ip_per_second": 2.0,
                        "document_sha256": "b" * 64,
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                [sys.executable, str(ROOT / "scripts/build_release.py"), "--version", "0.1.0", "--authorization", str(authorization), "--output", str(root / "dist")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("exceeds", process.stderr)

    def test_release_accepts_public_reference_without_document_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            authorization = root / "authorization.json"
            authorization.write_text(
                json.dumps(
                    {
                        "approved_at": "2026-08-05",
                        "scope": [
                            "automated_availability_query",
                            "automated_seat_selection",
                            "voucher_submission",
                            "private_beta_distribution",
                        ],
                        "request_limit_scope": "public_ip",
                        "max_requests_per_ip_per_second": 1.0,
                        "authorization_reference": "CGV-APPROVAL-2026-001",
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release.py"),
                    "--version",
                    "0.1.0",
                    "--authorization",
                    str(authorization),
                    "--output",
                    str(root / "dist"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)

    def test_release_rejects_wrong_limit_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            authorization = root / "authorization.json"
            authorization.write_text(
                json.dumps(
                    {
                        "approved_at": "2026-08-05",
                        "scope": [
                            "automated_availability_query",
                            "automated_seat_selection",
                            "voucher_submission",
                            "private_beta_distribution",
                        ],
                        "request_limit_scope": "device",
                        "max_requests_per_ip_per_second": 1.0,
                        "document_sha256": "c" * 64,
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release.py"),
                    "--version",
                    "0.1.0",
                    "--authorization",
                    str(authorization),
                    "--output",
                    str(root / "dist"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("public_ip", process.stderr)


if __name__ == "__main__":
    unittest.main()
