from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
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
    def test_release_version_inputs_are_aligned_at_0_2_4(self):
        """A release must not mix runtime, installer, or lockfile versions."""

        version = "0.2.4"
        self.assertEqual(
            tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
            version,
        )
        runtime = (ROOT / "runtime/prickly_imax_helper/__init__.py").read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{version}"', runtime)
        self.assertIn(f"APP_VERSION={version}", (ROOT / "scripts/Install.command").read_text(encoding="utf-8"))
        self.assertIn(
            f'$AppVersion = "{version}"',
            (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8-sig"),
        )
        lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
        self.assertIn('name = "prickly-imax-helper"\nversion = "0.2.4"', lock)

    def test_version_alignment_rejects_each_mismatched_release_input(self):
        """Changing any release version input must stop the builder before archive creation."""

        version = "0.2.4"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime/prickly_imax_helper").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "pyproject.toml").write_text('[project]\nversion = "0.2.4"\n', encoding="utf-8")
            (root / "runtime/prickly_imax_helper/__init__.py").write_text(
                '"""Runtime version metadata."""\n\n__version__ = "0.2.4"\n', encoding="utf-8"
            )
            (root / "scripts/Install.command").write_text(
                'APP_VERSION=0.2.4\nprint "${APP_VERSION}"\n', encoding="utf-8"
            )
            (root / "scripts/Install.ps1").write_text('$AppVersion = "0.2.4"\n', encoding="utf-8")
            (root / "uv.lock").write_text(
                '[[package]]\nname = "prickly-imax-helper"\nversion = "0.2.4"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            build_release.validate_version_alignment(root, version)

            paths = (
                root / "pyproject.toml",
                root / "runtime/prickly_imax_helper/__init__.py",
                root / "scripts/Install.command",
                root / "scripts/Install.ps1",
                root / "uv.lock",
            )
            for path in paths:
                original = path.read_text(encoding="utf-8")
                path.write_text(original.replace(version, "0.2.1"), encoding="utf-8")
                with self.subTest(path=path):
                    with self.assertRaisesRegex(SystemExit, "version alignment"):
                        build_release.validate_version_alignment(root, version)
                path.write_text(original, encoding="utf-8")

    def test_version_alignment_rejects_trailing_duplicate_release_assignments(self):
        """A later assignment must not silently override a release version."""

        version = "0.2.4"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime/prickly_imax_helper").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "pyproject.toml").write_text('[project]\nversion = "0.2.4"\n', encoding="utf-8")
            (root / "runtime/prickly_imax_helper/__init__.py").write_text(
                '"""Runtime version metadata."""\n\n__version__ = "0.2.4"\n', encoding="utf-8"
            )
            (root / "scripts/Install.command").write_text("APP_VERSION=0.2.4\n", encoding="utf-8")
            (root / "scripts/Install.ps1").write_text('$AppVersion = "0.2.4"\n', encoding="utf-8")
            (root / "uv.lock").write_text(
                '[[package]]\nname = "prickly-imax-helper"\nversion = "0.2.4"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )

            duplicates = {
                root / "runtime/prickly_imax_helper/__init__.py": '__version__ = "{version}"\n',
                root / "scripts/Install.command": "APP_VERSION={version}\n",
                root / "scripts/Install.ps1": '$AppVersion = "{version}"\n',
                root / "uv.lock": '[[package]]\nname = "prickly-imax-helper"\nversion = "{version}"\n',
            }
            for path, template in duplicates.items():
                original = path.read_text(encoding="utf-8")
                for duplicate_version in (version, "0.2.1"):
                    path.write_text(original + template.format(version=duplicate_version), encoding="utf-8")
                    with self.subTest(path=path, duplicate_version=duplicate_version):
                        with self.assertRaisesRegex(SystemExit, "version alignment"):
                            build_release.validate_version_alignment(root, version)
                path.write_text(original, encoding="utf-8")

    def test_version_alignment_rejects_alternate_syntax_and_ignores_comments_and_near_names(self):
        """Static parsing must catch executable alternate declarations without false positives."""

        version = "0.2.4"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime/prickly_imax_helper").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "pyproject.toml").write_text('[project]\nversion = "0.2.4"\n', encoding="utf-8")
            (root / "runtime/prickly_imax_helper/__init__.py").write_text(
                '"""Runtime version metadata."""\n\n__version__ = "0.2.4"\n# __version__helper = "0.2.1"\n',
                encoding="utf-8",
            )
            (root / "scripts/Install.command").write_text(
                'APP_VERSION=0.2.4\n# APP_VERSION="0.2.1"\nAPP_VERSION_BACKUP=0.2.1\n',
                encoding="utf-8",
            )
            (root / "scripts/Install.ps1").write_text(
                '$AppVersion = "0.2.4"\n# $AppVersion="0.2.1"\n$AppVersionBackup = "0.2.1"\n',
                encoding="utf-8",
            )
            (root / "uv.lock").write_text(
                '[[package]]\nname = "prickly-imax-helper"\nversion = "0.2.4"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            build_release.validate_version_alignment(root, version)

            alternate_assignments = {
                root / "runtime/prickly_imax_helper/__init__.py": (
                    '__version__="0.2.1"\n',
                    "__version__ = '0.2.1'\n",
                    "__version__ = version_value\n",
                ),
                root / "scripts/Install.command": (
                    'APP_VERSION="0.2.1"\n',
                    "APP_VERSION='0.2.1'\n",
                    "  APP_VERSION=0.2.1\n",
                    "export APP_VERSION='0.2.1'\n",
                    "APP_VERSION=$VERSION_VALUE\n",
                ),
                root / "scripts/Install.ps1": (
                    '$AppVersion="0.2.1"\n',
                    "$AppVersion = '0.2.1'\n",
                    "  $appversion = $VersionValue\n",
                    '$AppVersion = "0.2.4" + "-ambiguous"\n',
                ),
            }
            for path, assignments in alternate_assignments.items():
                original = path.read_text(encoding="utf-8")
                for assignment in assignments:
                    path.write_text(original + assignment, encoding="utf-8")
                    with self.subTest(path=path, assignment=assignment.strip()):
                        with self.assertRaisesRegex(SystemExit, "version alignment"):
                            build_release.validate_version_alignment(root, version)
                path.write_text(original, encoding="utf-8")

            powershell = root / "scripts/Install.ps1"
            original_powershell = powershell.read_text(encoding="utf-8")
            powershell.write_text('$AppVersion = "0.2.4" + "-ambiguous"\n', encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "version alignment"):
                build_release.validate_version_alignment(root, version)
            powershell.write_text(original_powershell, encoding="utf-8")

    def test_version_alignment_rejects_dynamic_mutations_and_ignores_powershell_block_comments(self):
        """Only a static runtime declaration and literal installer declarations are permitted."""

        version = "0.2.4"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime/prickly_imax_helper").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "pyproject.toml").write_text('[project]\nversion = "0.2.4"\n', encoding="utf-8")
            (root / "runtime/prickly_imax_helper/__init__.py").write_text(
                '"""Runtime version metadata."""\n\n__version__ = "0.2.4"\n', encoding="utf-8"
            )
            (root / "scripts/Install.command").write_text("APP_VERSION=0.2.4\n", encoding="utf-8")
            (root / "scripts/Install.ps1").write_text(
                '$AppVersion = "0.2.4"\n<#\n$AppVersion = "0.2.1"\n#>\n', encoding="utf-8"
            )
            (root / "uv.lock").write_text(
                '[[package]]\nname = "prickly-imax-helper"\nversion = "0.2.4"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            build_release.validate_version_alignment(root, version)

            mutations = {
                root / "runtime/prickly_imax_helper/__init__.py": (
                    'globals()["__version__"] = "0.2.1"\n',
                    'exec("__version__ = \'0.2.1\'")\n',
                ),
                root / "scripts/Install.command": ("APP_VERSION+=0.2.1\n",),
                root / "scripts/Install.ps1": ('$AppVersion += "0.2.1"\n',),
            }
            for path, source_mutations in mutations.items():
                original = path.read_text(encoding="utf-8")
                for mutation in source_mutations:
                    path.write_text(original + mutation, encoding="utf-8")
                    with self.subTest(path=path, mutation=mutation.strip()):
                        with self.assertRaisesRegex(SystemExit, "version alignment"):
                            build_release.validate_version_alignment(root, version)
                path.write_text(original, encoding="utf-8")

    def test_version_alignment_rejects_braced_and_scoped_powershell_version_writes(self):
        """Alternative references must not bypass the one canonical AppVersion declaration."""

        version = "0.2.4"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime/prickly_imax_helper").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "pyproject.toml").write_text('[project]\nversion = "0.2.4"\n', encoding="utf-8")
            (root / "runtime/prickly_imax_helper/__init__.py").write_text(
                '"""Runtime version metadata."""\n\n__version__ = "0.2.4"\n', encoding="utf-8"
            )
            (root / "scripts/Install.command").write_text("APP_VERSION=0.2.4\n", encoding="utf-8")
            powershell = root / "scripts/Install.ps1"
            source = '$AppVersion = "0.2.4"\nWrite-Host ${AppVersion}\nWrite-Host $script:AppVersion\n'
            powershell.write_text(source, encoding="utf-8")
            (root / "uv.lock").write_text(
                '[[package]]\nname = "prickly-imax-helper"\nversion = "0.2.4"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            build_release.validate_version_alignment(root, version)

            writes = (
                '${AppVersion} = "0.2.1"\n',
                '$script:AppVersion = "0.2.1"\n',
                '$global:AppVersion = "0.2.1"\n',
                '$local:AppVersion = "0.2.1"\n',
                '$private:AppVersion = "0.2.1"\n',
                '${script:AppVersion} = "0.2.1"\n',
            )
            for write in writes:
                powershell.write_text(source + write, encoding="utf-8")
                with self.subTest(write=write.strip()):
                    with self.assertRaisesRegex(SystemExit, "version alignment"):
                        build_release.validate_version_alignment(root, version)

    def test_version_alignment_rejects_dynamic_installer_apis_and_ignores_mentions(self):
        """Installer sources must not contain dynamic execution or variable-mutation commands."""

        version = "0.2.4"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime/prickly_imax_helper").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "pyproject.toml").write_text('[project]\nversion = "0.2.4"\n', encoding="utf-8")
            (root / "runtime/prickly_imax_helper/__init__.py").write_text(
                '"""Runtime version metadata."""\n\n__version__ = "0.2.4"\n', encoding="utf-8"
            )
            shell = root / "scripts/Install.command"
            shell_source = (
                "APP_VERSION=0.2.4\n"
                "print \"${APP_VERSION}\"\n"
                "# eval 'APP_VERSION=0.2.1'\n"
                "print 'eval source read vared APP_VERSION=0.2.1'\n"
                "# command eval 'APP_VERSION=0.2.1'\n"
                "print 'command eval APP_VERSION=0.2.1'\n"
            )
            shell.write_text(shell_source, encoding="utf-8")
            powershell = root / "scripts/Install.ps1"
            powershell_source = (
                '$AppVersion = "0.2.4"\n'
                'Write-Host ${AppVersion}\n'
                'Write-Host $script:AppVersion\n'
                '# Set-Variable -Name AppVersion -Value "0.2.1"\n'
                '<# Invoke-Expression \'$AppVersion = "0.2.1"\' #>\n'
                'Write-Host \'Set-Variable Invoke-Expression AppVersion\'\n'
                '# Set-Item -Path Variable:AppVersion -Value "0.2.1"\n'
                'Write-Host \'Set-Content Variable:AppVersion\'\n'
                'Set-Item -Path safe-item -Value \'Variable:AppVersion\'\n'
                'Set-Content -LiteralPath safe.txt -Value \'Variable:script:AppVersion\'\n'
            )
            powershell.write_text(powershell_source, encoding="utf-8")
            (root / "uv.lock").write_text(
                '[[package]]\nname = "prickly-imax-helper"\nversion = "0.2.4"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            build_release.validate_version_alignment(root, version)

            shell_commands = (
                'eval "APP_VERSION=0.2.1"\n',
                "source ./version-override.zsh\n",
                ". ./version-override.zsh\n",
                "read APP_VERSION <<<'0.2.1'\n",
                "vared APP_VERSION\n",
                'command eval "APP_VERSION=0.2.1"\n',
                "command source ./version-override.zsh\n",
                "command . ./version-override.zsh\n",
                "command read APP_VERSION <<<'0.2.1'\n",
                "command vared APP_VERSION\n",
                'builtin eval "APP_VERSION=0.2.1"\n',
            )
            for command in shell_commands:
                shell.write_text(shell_source + command, encoding="utf-8")
                with self.subTest(shell_command=command.strip()):
                    with self.assertRaisesRegex(SystemExit, "version alignment"):
                        build_release.validate_version_alignment(root, version)
            shell.write_text(shell_source, encoding="utf-8")

            powershell_commands = (
                'Set-Variable -Name AppVersion -Value "0.2.1"\n',
                'sv -Name AppVersion -Value "0.2.1"\n',
                'Invoke-Expression \'$AppVersion = "0.2.1"\'\n',
                'iex \'$AppVersion = "0.2.1"\'\n',
                'New-Variable -Name AppVersion -Value "0.2.1" -Force\n',
                '[scriptblock]::Create(\'$AppVersion = "0.2.1"\').Invoke()\n',
                'Set-Item -Path Variable:AppVersion -Value "0.2.1"\n',
                'si VARIABLE:script:APPVERSION "0.2.1"\n',
                'Set-Content -LiteralPath \'Variable:${global:AppVersion}\' -Value "0.2.1"\n',
                'sc \'variable:private:appversion\' "0.2.1"\n',
            )
            for command in powershell_commands:
                powershell.write_text(powershell_source + command, encoding="utf-8")
                with self.subTest(powershell_command=command.strip()):
                    with self.assertRaisesRegex(SystemExit, "version alignment"):
                        build_release.validate_version_alignment(root, version)

    def test_release_main_aborts_before_creating_output_for_version_mismatch(self):
        """Version validation must run before output, archives, and checksums can be created."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "scripts").mkdir()
            shutil.copy2(BUILD_SCRIPT, root / "scripts/build_release.py")
            (root / "runtime/prickly_imax_helper").mkdir(parents=True)
            (root / "pyproject.toml").write_text('[project]\nversion = "0.2.4"\n', encoding="utf-8")
            (root / "runtime/prickly_imax_helper/__init__.py").write_text(
                '__version__ = "0.2.1"\n', encoding="utf-8"
            )
            (root / "scripts/Install.command").write_text("APP_VERSION=0.2.4\n", encoding="utf-8")
            (root / "scripts/Install.ps1").write_text('$AppVersion = "0.2.4"\n', encoding="utf-8")
            (root / "uv.lock").write_text(
                '[[package]]\nname = "prickly-imax-helper"\nversion = "0.2.4"\nsource = { editable = "." }\n',
                encoding="utf-8",
            )
            authorization = root / "authorization.json"
            authorization.write_text(
                json.dumps(
                    {
                        "approved_at": "2026-08-05",
                        "scope": sorted(build_release.REQUIRED_AUTHORIZATION_SCOPES),
                        "request_limit_scope": "public_ip",
                        "max_requests_per_ip_per_second": 1.0,
                        "document_sha256": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )
            output = root / "sentinel-output"
            process = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/build_release.py"),
                    "--version",
                    "0.2.4",
                    "--authorization",
                    str(authorization),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(process.returncode, 0)
            self.assertIn("version alignment", process.stderr)
            self.assertFalse(output.exists())
            for suffix in (".tar.gz", ".tar.gz.sha256", ".zip", ".zip.sha256"):
                self.assertFalse((output / f"prickly-imax-helper-0.2.4{suffix}").exists())

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
        self.assertIn("Preserve existing install in dry-run (macOS)", workflow)
        self.assertIn("Preserve existing install in dry-run (Windows)", workflow)
        self.assertIn("PRICKLY_INSTALL_DRY_RUN", workflow)
        self.assertIn("scripts/Update.command", workflow)
        self.assertIn("scripts\\Update.ps1", workflow)
        self.assertIn("scripts/Uninstall.command", workflow)
        self.assertIn("scripts\\Uninstall.ps1", workflow)
        self.assertIn("Exercise Windows installer safety harness", workflow)
        self.assertIn("tests\\test_install_safety.ps1", workflow)
        self.assertIn("Preserve existing install in dry-run", workflow)
        self.assertIn("Exercise isolated update lifecycle", workflow)
        self.assertIn("uv==0.11.15", workflow)
        self.assertIn("uv lock --check", workflow)
        self.assertIn("$PSVersionTable.PSVersion.Major -eq 5", workflow)
        self.assertIn("Test (Windows PowerShell 5.1)", workflow)
        self.assertLess(
            workflow.index("Assert Windows PowerShell 5.1"),
            workflow.index("Exercise Windows installer safety harness"),
        )
        self.assertLess(
            workflow.index("Exercise Windows installer safety harness"),
            workflow.index("Test (Windows PowerShell 5.1)"),
        )

    def test_windows_powershell_5_harness_is_ascii_or_has_a_utf8_bom(self):
        """Windows PowerShell 5.1 must not decode UTF-8 harness text through an ANSI code page."""

        source = (ROOT / "tests/test_install_safety.ps1").read_bytes()
        if source.startswith(b"\xef\xbb\xbf"):
            source.decode("utf-8-sig")
        else:
            self.assertTrue(source.isascii(), "BOM-less Windows PowerShell 5.1 harness must be ASCII-only")

    def test_windows_safety_harness_emits_executable_child_environment_assignments(self):
        """Single-quoted child-script lines must not retain a literal PowerShell escape."""

        source = (ROOT / "tests/test_install_safety.ps1").read_text(encoding="ascii")
        self.assertIn("'$env:PRICKLY_INSTALL_SAFETY_LIBRARY = \"1\"'", source)
        self.assertNotIn("'`$env:PRICKLY_INSTALL_SAFETY_LIBRARY", source)

    def test_windows_old_cli_json_uses_powershell_5_compatible_key_checks(self):
        """JavaScriptSerializer dictionaries must not use an ambiguous generic Contains overload."""

        installer = (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8-sig")
        parser = installer.split("function ConvertFrom-StrictOldCliJson {", 1)[1].split(
            "function Get-ExistingTaskInspection {", 1
        )[0]
        self.assertIn('$Payload.Keys -contains "ok"', parser)
        self.assertIn('$Payload.Keys -contains "status"', parser)
        self.assertNotIn('$Payload.Contains(', parser)

    def test_powershell_cmdlet_composite_arguments_are_parenthesized(self):
        """PowerShell command argument mode must not split composite expressions."""

        unsafe_argument = re.compile(
            r"""(?mx)
            ^[ \t]*[A-Za-z][A-Za-z0-9]*-[A-Za-z][A-Za-z0-9]*\b
            [^\r\n]*?
            -[A-Za-z][A-Za-z0-9]*[ \t]+
            (?:
                \$[A-Za-z_][A-Za-z0-9_:]*
                |
                '(?:''|[^'\r\n])*'
                |
                "(?:`.|[^"\r\n])*"
            )
            [ \t]+(?:\+|-f|-join|-replace|-split|-and|-or|-eq|-ne)[ \t]+
            """
        )
        failures = []
        paths = (*ROOT.glob("scripts/*.ps1"), *ROOT.glob("tests/*.ps1"))
        for path in sorted(paths):
            source = path.read_text(encoding="utf-8-sig")
            for match in unsafe_argument.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0).strip()}")

        self.assertEqual(
            [],
            failures,
            "parenthesize composite expressions passed as cmdlet arguments:\n" + "\n".join(failures),
        )

    def test_powershell_variables_are_braced_before_non_ascii_text(self):
        """PowerShell treats adjacent Unicode letters as part of an unbraced variable name."""

        unsafe_variable = re.compile(r"\$[A-Za-z_][A-Za-z0-9_:]*(?=[^\x00-\x7f])")
        failures = []
        paths = (*ROOT.glob("scripts/*.ps1"), *ROOT.glob("tests/*.ps1"))
        for path in sorted(paths):
            source = path.read_text(encoding="utf-8-sig")
            for line_number, line in enumerate(source.splitlines(), 1):
                for match in unsafe_variable.finditer(line):
                    failures.append(f"{path.relative_to(ROOT)}:{line_number}: {match.group(0)}")

        self.assertEqual([], failures, "brace PowerShell variables before adjacent Unicode text")

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
        self.assertIn("체크섬이 일치하지 않습니다.", guide)
        self.assertNotIn("Get-FileHash $f -Algorithm SHA256", guide)

    def test_release_docs_pin_audited_0_2_4_artifact_hashes(self):
        guide = (ROOT / "docs/notion-quick-start.md").read_text(encoding="utf-8")
        notes = (ROOT / "docs/release-notes-0.2.4.md").read_text(encoding="utf-8")
        mac_hash = "18a37b78f05a40118df73db7d04d61e4d25de1840a8fd6e70a2de11a3ca1eb64"
        windows_hash = "432caab792f69f2ccc3ea57be748c22755dd6a3df2c6356f1224d14a75bff3d2"

        for document in (guide, notes):
            self.assertIn(mac_hash, document)
            self.assertIn(windows_hash, document)
            self.assertNotIn("RELEASE_NOT_PUBLISHED", document)
        self.assertIn(
            "https://github.com/alpacawooo/prickly-imax-helper/releases/download/0.2.4/"
            "prickly-imax-helper-0.2.4.tar.gz",
            guide,
        )
        self.assertIn(
            "https://github.com/alpacawooo/prickly-imax-helper/releases/download/0.2.4/"
            "prickly-imax-helper-0.2.4.zip",
            guide,
        )

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
        release_notes = (ROOT / "docs/release-notes-0.2.4.md").read_text(encoding="utf-8")

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
        self.assertIn('if dry_run_would_mutate_existing_install; then', mac_installer)
        self.assertIn('Dry-run: 기존 runtime/venv는 변경하지 않습니다.', mac_installer)
        self.assertIn('if [[ ${DRY_RUN} != 1 ]]; then\n  /bin/launchctl bootout', mac_uninstaller)
        self.assertIn('PLIST_PATH=${APP_HOME}/ai.prickly.imax-helper.plist', mac_uninstaller)
        self.assertIn('if ($DryRun -and ((Test-Path -LiteralPath (Join-Path $AppDir "runtime"))', windows_installer)
        self.assertIn('if (-not $DryRun) {\n    Stop-ScheduledTask', windows_uninstaller)

    def test_macos_update_replaces_only_the_versioned_runtime(self):
        installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        self.assertIn("RUNTIME_TARGET=${APP_DIR}/runtime", installer)
        self.assertIn("existing_install_needs_maintenance", installer)
        self.assertIn("[[ -x ${VENV_DIR}/bin/prickly-imax || -e ${RUNTIME_TARGET} ]]", installer)
        self.assertIn('--source "${REPO_DIR}/runtime" --target "${RUNTIME_TARGET}"', installer)
        self.assertNotIn('/bin/rm -rf -- "${APP_HOME}"', installer)

    def test_windows_partial_runtime_without_launcher_uses_atomic_update_maintenance(self):
        installer = (ROOT / "scripts" / "Install.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Test-ExistingInstallNeedsMaintenance", installer)
        self.assertIn("(Test-Path -LiteralPath $RuntimeTarget -PathType Container)", installer)
        self.assertIn('"replace-runtime", "--token", $MaintenanceToken', installer)

    def test_installers_bootstrap_managed_python_before_committing_the_final_runtime(self):
        mac_installer = (ROOT / "scripts" / "Install.command").read_text(encoding="utf-8")
        windows_installer = (ROOT / "scripts" / "Install.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("prepare_runtime_replacement()", mac_installer)
        self.assertIn("prove_service_absent_for_bootstrap", mac_installer)
        self.assertIn('--project "${REPO_DIR}"', mac_installer)
        mac_replacement = mac_installer.split("prepare_runtime_replacement() {", 1)[1].split(
            "dry_run_would_mutate_existing_install() {", 1
        )[0]
        self.assertLess(mac_replacement.rindex("prepare_managed_environment"), mac_replacement.index("run_update_maintenance replace-runtime"))
        self.assertNotIn('/usr/bin/ditto "${REPO_DIR}/runtime"', mac_installer)

        self.assertIn("function Prepare-RuntimeReplacement", windows_installer)
        self.assertIn("Assert-ServiceAbsentForBootstrap", windows_installer)
        self.assertIn("--project $RepoDir", windows_installer)
        windows_replacement = windows_installer.split("function Prepare-RuntimeReplacement {", 1)[1].split(
            'if ($env:PRICKLY_INSTALL_SAFETY_LIBRARY -eq "1")', 1
        )[0]
        self.assertLess(windows_replacement.rindex("Sync-ManagedEnvironment"), windows_replacement.index('"replace-runtime", "--token"'))
        self.assertNotIn('Copy-Item -Recurse -Force (Join-Path $RepoDir "runtime") $RuntimeTarget', windows_installer)

    def test_installers_own_an_outer_lock_before_any_bootstrap_or_runtime_mutation(self):
        mac_installer = (ROOT / "scripts" / "Install.command").read_text(encoding="utf-8")
        windows_installer = (ROOT / "scripts" / "Install.ps1").read_text(encoding="utf-8-sig")

        mac_main = mac_installer.split("if dry_run_would_mutate_existing_install; then", 1)[1]
        self.assertIn("acquire_installer_lock", mac_main)
        self.assertIn("installer_lock_exit", mac_main)
        self.assertLess(mac_main.index("trap 'installer_lock_exit' EXIT"), mac_main.index("acquire_installer_lock"))
        self.assertLess(mac_main.index("acquire_installer_lock"), mac_main.index("prepare_runtime_replacement"))

        windows_main = windows_installer.split('if ($DryRun -and ((Test-Path -LiteralPath', 1)[1]
        self.assertIn("Enter-InstallerLock", windows_main)
        self.assertIn("finally", windows_main)
        self.assertIn("Exit-InstallerLock", windows_main)
        self.assertLess(windows_main.index("try {"), windows_main.index("Enter-InstallerLock"))
        self.assertLess(windows_main.index("Enter-InstallerLock"), windows_main.index("Prepare-RuntimeReplacement"))

    def test_windows_installer_lock_uses_atomic_publication_and_revalidates_moved_owner(self):
        windows_installer = (ROOT / "scripts" / "Install.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("[IO.FileShare]::None", windows_installer)
        self.assertIn("function New-InstallerLockCandidate", windows_installer)
        self.assertIn("function Publish-InstallerLockCandidate", windows_installer)
        enter_lock = windows_installer.split("function Enter-InstallerLock {", 1)[1].split("function Exit-InstallerLock {", 1)[0]
        self.assertLess(enter_lock.index("New-InstallerLockCandidate"), enter_lock.index("Publish-InstallerLockCandidate"))
        self.assertIn("$MovedOwner.Pid -ne $ObservedOwner.Pid", enter_lock)
        self.assertIn("$MovedOwner.Token -ne $ObservedOwner.Token", enter_lock)
        self.assertGreaterEqual(enter_lock.count("Get-InstallerOwnerState"), 2)

    def test_installers_fail_closed_before_replacing_an_unsafe_resident_monitor(self):
        mac_installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        windows_installer = (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('parse_old_status()', mac_installer)
        self.assertIn('prickly_imax_helper.maintenance', mac_installer)
        self.assertIn('cooperative_stop_existing_monitor "${VENV_DIR}/bin/prickly-imax"', mac_installer)
        mac_replacement = mac_installer.split("prepare_runtime_replacement() {", 1)[1].split(
            "dry_run_would_mutate_existing_install() {", 1
        )[0]
        self.assertIn(
            'begin_update_maintenance || return 1\n    cooperative_stop_existing_monitor "${VENV_DIR}/bin/prickly-imax" || return 1',
            mac_replacement,
        )
        self.assertLess(
            mac_replacement.index('cooperative_stop_existing_monitor "${VENV_DIR}/bin/prickly-imax"'),
            mac_replacement.index('run_update_maintenance replace-runtime'),
        )

        self.assertIn('ConvertFrom-StrictOldCliJson', windows_installer)
        self.assertIn('System.Web.Script.Serialization.JavaScriptSerializer', windows_installer)
        self.assertNotIn('ConvertFrom-Json -AsHashtable', windows_installer)
        self.assertIn('Test-StrictJsonObjectSyntax', windows_installer)
        self.assertIn('Stop-ExistingMonitorSafely -OldCli $ExistingLauncherCmd', windows_installer)
        self.assertLess(
            windows_installer.index('        Start-UpdateMaintenance'),
            windows_installer.index('    Stop-ExistingMonitorSafely -OldCli $ExistingLauncherCmd'),
        )
        self.assertLess(
            windows_installer.index('Stop-ExistingMonitorSafely -OldCli $ExistingLauncherCmd'),
            windows_installer.index('        "replace-runtime", "--token"'),
        )
        self.assertLess(mac_installer.index('/bin/launchctl bootstrap'), mac_installer.index('run_update_maintenance end'))
        self.assertLess(mac_installer.index('run_update_maintenance end'), mac_installer.index('/bin/launchctl kickstart -p'))
        self.assertLess(windows_installer.index('Register-ScheduledTask'), windows_installer.index('@("end", "--token"'))
        self.assertLess(windows_installer.index('@("end", "--token"'), windows_installer.index('Start-ScheduledTask -TaskName $TaskName'))

    def test_normal_lifecycle_paths_never_use_destructive_launchctl_kickstart(self):
        offenders = []
        for base in (ROOT / "runtime", ROOT / "scripts"):
            for path in base.rglob("*"):
                if path.is_file() and "launchctl kickstart -k" in path.read_text(encoding="utf-8", errors="ignore"):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_installers_stop_and_wait_for_resident_exit_before_service_teardown_or_replacement(self):
        mac_installer = (ROOT / "scripts/Install.command").read_text(encoding="utf-8")
        windows_installer = (ROOT / "scripts/Install.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('"${old_cli}" --home "${APP_HOME}" stop', mac_installer)
        self.assertIn('"${SLEEP_BIN}" 0.25', mac_installer)
        self.assertIn('EXIT_TIMEOUT_SECONDS=${PRICKLY_EXIT_TIMEOUT_SECONDS:-60}', mac_installer)
        self.assertIn('query_launchctl_state()', mac_installer)
        self.assertLess(
            mac_installer.index('"${old_cli}" --home "${APP_HOME}" stop'),
            mac_installer.index('"${LAUNCHCTL_BIN}" bootout'),
        )
        self.assertLess(
            mac_installer.index('상주 감시가 ${EXIT_TIMEOUT_SECONDS}초 안에 종료되지 않아 업데이트를 중단합니다.'),
            mac_installer.index('run_update_maintenance replace-runtime'),
        )

        self.assertIn('$OldStopOutput = & $OldCli --home $AppHome stop', windows_installer)
        self.assertIn('Get-ExistingTaskInspection', windows_installer)
        self.assertIn('Start-Sleep -Milliseconds 250', windows_installer)
        self.assertIn('AddSeconds($ExitTimeoutSeconds)', windows_installer)
        self.assertIn('상주 감시가 ${ExitTimeoutSeconds}초 안에 종료되지 않아 업데이트를 중단합니다.', windows_installer)
        self.assertLess(
            windows_installer.index('$OldStopOutput = & $OldCli --home $AppHome stop'),
            windows_installer.index('Stop-ScheduledTask -TaskName $TaskName'),
        )
        self.assertLess(
            windows_installer.index('상주 감시가 ${ExitTimeoutSeconds}초 안에 종료되지 않아 업데이트를 중단합니다.'),
            windows_installer.index('        "replace-runtime", "--token"'),
        )

    def test_plugin_doctor_requires_a_trusted_apple_mail_location(self):
        doctor = (
            ROOT / "plugins/prickly-imax-helper/skills/prickly-imax-booking/scripts/doctor.py"
        ).read_text(encoding="utf-8")
        self.assertIn('/System/Applications/Mail.app', doctor)
        self.assertIn('/Applications/Mail.app', doctor)
        self.assertIn('mail_path', doctor)

    def test_update_wrappers_cannot_bypass_cooperative_stop(self):
        mac_update = (ROOT / "scripts/Update.command").read_text(encoding="utf-8")
        windows_update = (ROOT / "scripts/Update.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('exec "${SCRIPT_DIR}/Install.command"', mac_update)
        self.assertNotIn('launchctl bootout', mac_update)
        self.assertNotIn('rm -rf', mac_update)
        self.assertIn('& (Join-Path $ScriptDir "Install.ps1")', windows_update)
        self.assertNotIn('Stop-ScheduledTask', windows_update)
        self.assertNotIn('Remove-Item', windows_update)

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
                [sys.executable, str(ROOT / "scripts/build_release.py"), "--version", "0.2.4", "--authorization", str(authorization), "--output", str(output)],
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
                [sys.executable, str(ROOT / "scripts/build_release.py"), "--version", "0.2.4", "--authorization", str(authorization), "--output", str(root / "dist")],
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
                    "0.2.4",
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
                    "0.2.4",
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
                    "0.2.4",
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
            self.assertFalse((root / "dist" / "prickly-imax-helper-0.2.4.tar.gz").exists())

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
                    "0.2.4",
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
