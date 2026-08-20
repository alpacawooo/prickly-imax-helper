from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "0.2.3"
BUILD_SCRIPT = ROOT / "scripts/build_release.py"
BUILD_SPEC = importlib.util.spec_from_file_location("prickly_build_release", BUILD_SCRIPT)
build_release = importlib.util.module_from_spec(BUILD_SPEC)
assert BUILD_SPEC.loader is not None
BUILD_SPEC.loader.exec_module(build_release)


class ReleaseTests(unittest.TestCase):
    def test_release_version_is_aligned_across_runtime_lock_and_installers(self):
        """Every shipped version source must agree before a release is built."""

        expected = RELEASE_VERSION
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        root_package = next(
            package
            for package in lock["package"]
            if package.get("name") == "prickly-imax-helper"
        )
        runtime = (ROOT / "runtime/prickly_imax_helper/__init__.py").read_text(encoding="utf-8")
        mac_installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        windows_installer = (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8-sig")

        versions = {
            "pyproject.toml": project["project"]["version"],
            "uv.lock root package": root_package["version"],
            "runtime __version__": re.search(r'^__version__ = "([^"]+)"$', runtime, re.MULTILINE).group(1),
            "Install.command APP_VERSION": re.search(r"^APP_VERSION=([^\s]+)$", mac_installer, re.MULTILINE).group(1),
            "Install.ps1 AppVersion": re.search(r'^\$AppVersion = "([^"]+)"$', windows_installer, re.MULTILINE).group(1),
        }
        self.assertEqual(
            versions,
            {name: expected for name in versions},
            "all executable/installable version sources must equal the release version",
        )

    def test_release_builder_rejects_runtime_and_lock_version_drift(self):
        shipped = (
            "pyproject.toml",
            "uv.lock",
            "runtime/prickly_imax_helper/__init__.py",
            "scripts/Install.command",
            "scripts/Install.ps1",
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in shipped:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((ROOT / relative).read_bytes())

            build_release.validate_release_versions(root, RELEASE_VERSION)

            runtime = root / "runtime/prickly_imax_helper/__init__.py"
            runtime.write_text('__version__ = "0.0.0"\n', encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "runtime __version__"):
                build_release.validate_release_versions(root, RELEASE_VERSION)
            runtime.write_bytes((ROOT / "runtime/prickly_imax_helper/__init__.py").read_bytes())

            lock = root / "uv.lock"
            lock.write_text(
                lock.read_text(encoding="utf-8").replace(
                    'name = "prickly-imax-helper"\nversion = "0.2.3"',
                    'name = "prickly-imax-helper"\nversion = "0.0.0"',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "uv.lock root package"):
                build_release.validate_release_versions(root, RELEASE_VERSION)

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
        self.assertIn("Smoke-test macOS installer", workflow)
        self.assertIn("Smoke-test Windows installer", workflow)
        self.assertIn("PRICKLY_INSTALL_DRY_RUN", workflow)
        self.assertIn("scripts/Update.command", workflow)
        self.assertIn("scripts\\Update.ps1", workflow)
        self.assertIn("scripts/Uninstall.command", workflow)
        self.assertIn("scripts\\Uninstall.ps1", workflow)

    def test_installer_avoids_unlocked_project_build_backend(self):
        installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        self.assertIn("--no-install-project", installer)
        self.assertNotIn("--no-editable", installer)
        self.assertIn('"${VENV_DIR}/bin/prickly-imax"', installer)
        self.assertIn("PLIST_PATH=${APP_HOME}/ai.prickly.imax-helper.plist", installer)
        self.assertIn("dry-run 설치가 완료됐습니다", installer)

    def test_user_and_plugin_docs_disclose_midnight_only_discovery(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runtime_contract = (
            ROOT
            / "plugins/prickly-imax-helper/skills/prickly-imax-booking/references/runtime-contract.md"
        ).read_text(encoding="utf-8")

        for document in (readme, runtime_contract):
            self.assertIn("startup", document)
            self.assertIn("Korea Standard Time midnight", document)
            self.assertIn("no daytime schedule-discovery requests", document)
            self.assertIn("serially", document)

    def test_windows_quick_start_stops_before_hashing_when_zip_is_missing(self):
        guide = (ROOT / "docs/notion-quick-start.md").read_text(encoding="utf-8")
        zip_guard = "if(-not $zip)"
        hash_check = "Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256"

        self.assertIn(zip_guard, guide)
        self.assertIn(hash_check, guide)
        self.assertLess(guide.index(zip_guard), guide.index(hash_check))
        self.assertIn("설치 ZIP 파일을 찾을 수 없습니다.", guide)
        self.assertIn("압축을 풀지 않은 원본 ZIP", guide)
        self.assertIn("파일이 손상되었거나 다른 버전의 설치 파일입니다.", guide)
        self.assertNotIn("Get-FileHash $f -Algorithm SHA256", guide)

    def test_windows_quick_start_finds_zip_in_custom_desktop_download_folder(self):
        guide = (ROOT / "docs/notion-quick-start.md").read_text(encoding="utf-8")

        self.assertIn("[Environment]::GetFolderPath('Desktop')", guide)
        self.assertIn("Get-ChildItem", guide)
        self.assertIn("-Filter $f", guide)
        self.assertIn("-File -Recurse", guide)
        self.assertIn("Sort-Object LastWriteTime -Descending", guide)
        self.assertIn("Select-Object -First 1", guide)
        self.assertNotIn('cd "$HOME\\Downloads"', guide)

    def test_public_github_docs_explain_the_windows_zip_discovery_guard(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        release_notes = (ROOT / "docs/release-notes-0.2.2.md").read_text(encoding="utf-8")

        self.assertIn("docs/notion-quick-start.md", readme)
        self.assertIn("Desktop subfolders", readme)
        self.assertIn("stops before hashing", readme)
        self.assertIn("다운로드 폴더와 바탕화면 아래의 하위 폴더", release_notes)
        self.assertIn("ZIP이 없으면 체크섬을 검사하지 않고", release_notes)
        self.assertIn("거리 표기가 함께 있는 실제 극장 행", release_notes)

    def test_install_and_uninstall_restrict_app_home_to_user_home(self):
        for name in ("Install.command", "Uninstall.command"):
            script = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn('[[ ${APP_HOME} != "${USER_HOME}/"* ]]', script)

    def test_dry_run_lifecycle_cannot_stop_real_resident_service(self):
        mac_installer = (ROOT / "scripts" / "Install.command").read_text(encoding="utf-8")
        mac_uninstaller = (ROOT / "scripts" / "Uninstall.command").read_text(encoding="utf-8")
        windows_installer = (ROOT / "scripts" / "Install.ps1").read_text(encoding="utf-8-sig")
        windows_uninstaller = (ROOT / "scripts" / "Uninstall.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('if [[ ${DRY_RUN} != 1 ]]; then\n  /bin/launchctl bootout', mac_installer)
        self.assertIn('if [[ ${DRY_RUN} != 1 ]]; then\n  /bin/launchctl bootout', mac_uninstaller)
        self.assertIn('PLIST_PATH=${APP_HOME}/ai.prickly.imax-helper.plist', mac_uninstaller)
        self.assertIn('if (-not $DryRun) {\n    $ExistingTask = Get-ScheduledTask', windows_installer)
        self.assertIn('if (-not $DryRun) {\n    Stop-ScheduledTask', windows_uninstaller)

    def test_macos_update_replaces_only_the_versioned_runtime(self):
        installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        self.assertIn("RUNTIME_TARGET=${APP_DIR}/runtime", installer)
        self.assertIn('/bin/rm -rf -- "${RUNTIME_TARGET}"', installer)
        self.assertNotIn('/bin/rm -rf -- "${APP_HOME}"', installer)

    def test_installers_clear_the_stop_request_before_starting_service(self):
        mac_installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        windows_installer = (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8-sig")
        self.assertLess(mac_installer.index('/bin/mv -- "${STOP_REQUEST}"'), mac_installer.index('prickly-imax" --home "${APP_HOME}" dry-run'))
        self.assertIn('/bin/mv -- "${STOP_REQUEST_BACKUP}" "${STOP_REQUEST}"', mac_installer)
        self.assertLess(windows_installer.index('Move-Item -LiteralPath $StopRequest -Destination $StopRequestBackup'), windows_installer.index('& $LauncherCmd --home $AppHome dry-run'))
        self.assertIn('Move-Item -LiteralPath $StopRequestBackup -Destination $StopRequest', windows_installer)

    def test_windows_installer_is_pinned_and_user_scoped(self):
        installer = (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8")
        uninstaller = (ROOT / "scripts/Uninstall.ps1").read_text(encoding="utf-8")
        self.assertIn('$UvVersion = "0.11.15"', installer)
        self.assertIn('$ManagedPythonVersion = "3.12.12"', installer)
        self.assertIn("--no-install-project", installer)
        self.assertIn("-DestinationPath $UvExtractDir", installer)
        self.assertIn("Register-ScheduledTask", installer)
        self.assertIn("Stop-ScheduledTask", installer)
        self.assertIn("-RunLevel Limited", installer)
        self.assertIn("$ExpectedPrefix", installer)
        self.assertIn("%~dp0..\\venv\\Scripts\\python.exe", installer)
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
                [sys.executable, str(ROOT / "scripts/build_release.py"), "--version", RELEASE_VERSION, "--authorization", str(authorization), "--output", str(output)],
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
                [sys.executable, str(ROOT / "scripts/build_release.py"), "--version", RELEASE_VERSION, "--authorization", str(authorization), "--output", str(root / "dist")],
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
                    RELEASE_VERSION,
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
                    RELEASE_VERSION,
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

    def test_release_rejects_unknown_authorization_fields(self):
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
                        "document_sha256": "d" * 64,
                        "source_path": "/private/approval.pdf",
                        "private_note": "confidential correspondence",
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release.py"),
                    "--version",
                    RELEASE_VERSION,
                    "--authorization",
                    str(authorization),
                    "--output",
                    str(root / "dist"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("non-public or unknown fields", process.stderr)
            self.assertFalse((root / "dist" / f"prickly-imax-helper-{RELEASE_VERSION}.tar.gz").exists())

    def test_release_rejects_placeholder_authorization_reference(self):
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
                        "authorization_reference": "OPTIONAL_PUBLIC_APPROVAL_OR_CONTRACT_REFERENCE",
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release.py"),
                    "--version",
                    RELEASE_VERSION,
                    "--authorization",
                    str(authorization),
                    "--output",
                    str(root / "dist"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("still a placeholder", process.stderr)


if __name__ == "__main__":
    unittest.main()
