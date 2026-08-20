from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAC_INSTALLER = ROOT / "scripts" / "Install.command"
MAC_UPDATE = ROOT / "scripts" / "Update.command"


@unittest.skipUnless(
    platform.system() == "Darwin" and shutil.which("zsh") is not None,
    "macOS zsh installer behavior is macOS-only",
)
class MacInstallSafetyBehaviorTests(unittest.TestCase):
    def run_safety(self, status: str, stop: str, launchctl: str = "stopped", *, status_code: int = 0, stop_code: int = 0, old_cli: bool = True) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cli = root / "old-cli"
            launchctl_bin = root / "launchctl"
            cli.write_text(
                "#!/bin/sh\n"
                "if [ \"$3\" = status ]; then printf '%s' \"${FAKE_STATUS}\"; exit \"${FAKE_STATUS_CODE}\"; fi\n"
                "printf '%s' \"${FAKE_STOP}\"; exit \"${FAKE_STOP_CODE}\"\n",
                encoding="utf-8",
            )
            launchctl_bin.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = print ]; then\n"
                "  case \"${FAKE_LAUNCHCTL}\" in error) exit 1;; missing) exit 113;; running) printf 'pid = 123\\n';; *) printf 'state = waiting\\n';; esac\n"
                "  exit 0\n"
                "fi\n"
                "[ \"${FAKE_LAUNCHCTL}\" = bootout-error ] && exit 1\n"
                "exit 0\n",
                encoding="utf-8",
            )
            for path in (cli, launchctl_bin):
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={root / 'home'}",
                    f"export PRICKLY_LAUNCHCTL_BIN={launchctl_bin}",
                    f"export PRICKLY_MAINTENANCE_PYTHON={sys.executable}",
                    "export PRICKLY_EXIT_TIMEOUT_SECONDS=0",
                    f"export FAKE_STATUS='{status}'",
                    f"export FAKE_STOP='{stop}'",
                    f"export FAKE_STATUS_CODE={status_code}",
                    f"export FAKE_STOP_CODE={stop_code}",
                    f"export FAKE_LAUNCHCTL={launchctl}",
                    f"source {MAC_INSTALLER}",
                    f"cooperative_stop_existing_monitor {cli if old_cli else root / 'missing-cli'}",
                ]
            )
            return subprocess.run(["zsh", "-c", script], text=True, capture_output=True)

    def test_rejects_unprovable_old_cli_payloads_without_teardown(self):
        for status, code in (
            ("not-json", 0),
            ("{}", 0),
            ("{status:'armed'}", 0),
            ("{'status':'armed'}", 0),
            ('{"status":"submitting","status":"armed"}', 0),
            ('{"stat\\u0075s":"submitting","status":"armed"}', 0),
            ('[{"status":"armed"}]', 0),
            ('{"status":"armed"}{"status":"armed"}', 0),
            ('{"status":"armed"} trailing', 0),
            ('{"status":"future"}', 0),
            ('{"status":"armed"}', 1),
            ('{"status":"submitting"}', 0),
        ):
            with self.subTest(status=status, code=code):
                result = self.run_safety(status, '{"ok":true,"status":"stopped"}', status_code=code)
                self.assertNotEqual(result.returncode, 0)

    def test_rejects_stop_race_and_invalid_stop_payloads(self):
        for stop, code in (
            ("not-json", 0),
            ('{"ok":true,"ok":false,"status":"stopped"}', 0),
            ('{"ok":true,"status":"unknown_after_submit","status":"stopped"}', 0),
            ('{"ok":true,"st\\u0061tus":"unknown_after_submit","status":"stopped"}', 0),
            ('[{"ok":true,"status":"stopped"}]', 0),
            ('{"ok":false,"status":"stopped"}', 0),
            ('{"ok":true,"status":"unknown_after_submit"}', 0),
            ('{"ok":true,"status":"stopped","extra":1}', 0),
            ('{"ok":true,"status":"stopped"}', 1),
        ):
            with self.subTest(stop=stop, code=code):
                result = self.run_safety('{"status":"armed"}', stop, stop_code=code)
                self.assertNotEqual(result.returncode, 0)

    def test_rejects_query_error_and_timeout_before_teardown(self):
        query_error = self.run_safety('{"status":"armed"}', '{"ok":true,"status":"stopped"}', "error")
        timeout = self.run_safety('{"status":"armed"}', '{"ok":true,"status":"stopped"}', "running")
        self.assertNotEqual(query_error.returncode, 0)
        self.assertNotEqual(timeout.returncode, 0)

    def test_allows_clean_install_when_launchagent_is_missing(self):
        result = self.run_safety("{}", "{}", "missing", old_cli=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_update_dry_run_with_existing_runtime_does_not_mutate_it(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            runtime = home / "app" / "0.2.4" / "runtime"
            runtime.mkdir(parents=True)
            marker = runtime / "keep.txt"
            marker.write_text("unchanged", encoding="utf-8")
            result = subprocess.run(
                ["zsh", str(MAC_UPDATE)],
                text=True,
                capture_output=True,
                env={**os.environ, "PRICKLY_INSTALL_DRY_RUN": "1", "PRICKLY_IMAX_HOME": str(home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")

    def test_partial_runtime_without_launcher_requires_atomic_update_maintenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            runtime = home / "app" / "0.2.4" / "runtime"
            runtime.mkdir(parents=True)
            stale = runtime / "stale-sentinel.txt"
            stale.write_text("must disappear", encoding="utf-8")
            config = home / "config.json"
            config.write_text("preserve config", encoding="utf-8")
            profile = home / "browser-profile"
            profile.mkdir()
            (profile / "profile-marker").write_text("preserve profile", encoding="utf-8")
            uv_marker = root / "fake-uv-ran"
            fake_uv = root / "uv"
            fake_uv.write_text(
                "#!/bin/sh\n"
                f'printf ran > "{uv_marker}"\n'
                f'exec "{sys.executable}" -m venv "$UV_PROJECT_ENVIRONMENT"\n',
                encoding="utf-8",
            )
            fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)
            launchctl_bin = root / "launchctl"
            launchctl_bin.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = print ]; then\n"
                "  case \"${FAKE_LAUNCHCTL}\" in error) exit 1;; missing) exit 113;; *) printf 'state = waiting\\n'; exit 0;; esac\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            launchctl_bin.chmod(launchctl_bin.stat().st_mode | stat.S_IXUSR)
            script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_LAUNCHCTL_BIN={launchctl_bin}",
                    f"source {MAC_INSTALLER}",
                    f"prepare_pinned_uv() {{ UV_BIN={fake_uv}; }}",
                    "export FAKE_LAUNCHCTL=error",
                    "if prepare_runtime_replacement; then return 91; fi",
                    f"[[ ! -e {uv_marker} && -e ${{RUNTIME_TARGET}}/stale-sentinel.txt && ! -e ${{APP_HOME}}/state/update-in-progress ]]",
                    "export FAKE_LAUNCHCTL=stopped",
                    "if prepare_runtime_replacement; then return 92; fi",
                    f"[[ ! -e {uv_marker} && -e ${{RUNTIME_TARGET}}/stale-sentinel.txt && ! -e ${{APP_HOME}}/state/update-in-progress ]]",
                    "export FAKE_LAUNCHCTL=missing",
                    "prepare_runtime_replacement",
                    f"[[ -e {uv_marker} && -x ${{VENV_DIR}}/bin/python ]]",
                    "[[ -n ${MAINTENANCE_TOKEN} && -f ${APP_HOME}/state/update-in-progress ]]",
                    "[[ ! -e ${RUNTIME_TARGET}/stale-sentinel.txt && ! -e ${RUNTIME_TARGET}/runtime ]]",
                    "[[ -f ${RUNTIME_TARGET}/prickly_imax_helper/__init__.py ]]",
                    f"[[ \"$(< {config})\" = 'preserve config' && \"$(< {profile / 'profile-marker'})\" = 'preserve profile' ]]",
                    "run_update_maintenance end --token ${MAINTENANCE_TOKEN}",
                ]
            )
            result = subprocess.run(["zsh", "-c", script], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_launcher_without_managed_python_never_bootstraps_shared_venv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            launcher = home / "venv" / "bin" / "prickly-imax"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("old launcher", encoding="utf-8")
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
            uv_marker = root / "fake-uv-ran"
            fake_uv = root / "uv"
            fake_uv.write_text(
                "#!/bin/sh\n"
                f'printf ran > "{uv_marker}"\n'
                f'exec "{sys.executable}" -m venv "$UV_PROJECT_ENVIRONMENT"\n',
                encoding="utf-8",
            )
            fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)
            launchctl_bin = root / "launchctl"
            launchctl_bin.write_text("#!/bin/sh\n[ \"$1\" = print ] && exit 113\nexit 0\n", encoding="utf-8")
            launchctl_bin.chmod(launchctl_bin.stat().st_mode | stat.S_IXUSR)
            script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_LAUNCHCTL_BIN={launchctl_bin}",
                    f"source {MAC_INSTALLER}",
                    f"prepare_pinned_uv() {{ UV_BIN={fake_uv}; }}",
                    "if prepare_runtime_replacement; then return 93; fi",
                    f"[[ ! -e {uv_marker} ]]",
                ]
            )
            result = subprocess.run(["zsh", "-c", script], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(launcher.read_text(encoding="utf-8"), "old launcher")

    def test_wrong_pinned_uv_digest_never_extracts_or_executes_archive_in_production_context(self):
        installer_source = MAC_INSTALLER.read_text(encoding="utf-8")
        self.assertIn("PRICKLY_CURL_BIN", installer_source, "installer needs a hermetic curl boundary for this security regression")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            uv_target = "aarch64-apple-darwin" if platform.machine() == "arm64" else "x86_64-apple-darwin"
            archive_root = root / "archive"
            archived_uv = archive_root / f"uv-{uv_target}" / "uv"
            archived_uv.parent.mkdir(parents=True)
            uv_marker = root / "unverified-uv-ran"
            archived_uv.write_text(f"#!/bin/sh\nprintf ran > '{uv_marker}'\nexit 0\n", encoding="utf-8")
            archived_uv.chmod(archived_uv.stat().st_mode | stat.S_IXUSR)
            archive = root / "wrong-digest.tar.gz"
            subprocess.run(
                ["/usr/bin/tar", "-czf", str(archive), "-C", str(archive_root), f"uv-{uv_target}"],
                check=True,
                capture_output=True,
                text=True,
            )
            fake_curl_marker = root / "fake-curl-ran"
            fake_curl = root / "curl"
            fake_curl.write_text(
                "#!/bin/sh\n"
                "destination=\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = -o ]; then destination=$2; shift 2; else shift; fi\n"
                "done\n"
                "[ -n \"$destination\" ] || exit 2\n"
                f"printf ran > '{fake_curl_marker}'\n"
                f"exec /bin/cp '{archive}' \"$destination\"\n",
                encoding="utf-8",
            )
            fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)
            launchctl_bin = root / "launchctl"
            launchctl_bin.write_text("#!/bin/sh\n[ \"$1\" = print ] && exit 113\nexit 0\n", encoding="utf-8")
            launchctl_bin.chmod(launchctl_bin.stat().st_mode | stat.S_IXUSR)
            script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_LAUNCHCTL_BIN={launchctl_bin}",
                    f"export PRICKLY_CURL_BIN={fake_curl}",
                    f"source {MAC_INSTALLER}",
                    "if ! prepare_runtime_replacement; then exit 41; fi",
                    "exit 0",
                ]
            )
            result = subprocess.run(["zsh", "-c", script], text=True, capture_output=True)
            extracted_uv = home / "bootstrap" / "uv-0.11.15" / f"uv-{uv_target}" / "uv"
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(fake_curl_marker.exists(), result.stderr)
            self.assertFalse(extracted_uv.exists(), result.stderr)
            self.assertFalse(uv_marker.exists(), result.stderr)

    def test_installer_lock_rejects_overlapping_process_before_shared_mutation(self):
        installer_source = MAC_INSTALLER.read_text(encoding="utf-8")
        self.assertIn("acquire_installer_lock()", installer_source)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            ready = root / "owner-ready"
            release = root / "release-owner"
            second_mutation = home / "venv" / "second-installer-ran"
            owner_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"source {MAC_INSTALLER}",
                    "mkdir -p ${APP_HOME}/state",
                    "acquire_installer_lock",
                    f"print -r -- ready > {ready}",
                    f"while [[ ! -e {release} ]]; do /bin/sleep 0.02; done",
                    "release_installer_lock",
                ]
            )
            owner = subprocess.Popen(["zsh", "-c", owner_script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not ready.exists():
                    owner_error = owner.communicate(timeout=1)[1] if owner.poll() is not None else "owner timeout"
                    self.fail(owner_error)
                contender_script = "\n".join(
                    [
                        "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                        f"export PRICKLY_IMAX_HOME={home}",
                        f"source {MAC_INSTALLER}",
                        "mkdir -p ${APP_HOME}/state",
                        "acquire_installer_lock",
                        f"mkdir -p {second_mutation.parent}",
                        f"print -r -- mutated > {second_mutation}",
                        "release_installer_lock",
                    ]
                )
                contender = subprocess.run(["zsh", "-c", contender_script], text=True, capture_output=True)
                self.assertNotEqual(contender.returncode, 0)
                self.assertFalse(second_mutation.exists(), contender.stderr)
            finally:
                release.write_text("release", encoding="utf-8")
                owner_stdout, owner_stderr = owner.communicate(timeout=5)
            self.assertEqual(owner.returncode, 0, owner_stderr or owner_stdout)

    def test_installer_lock_serializes_two_stale_reclaimers_before_shared_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            lock_dir = home / "state" / "installer.lock"
            lock_dir.mkdir(parents=True)
            (lock_dir / "owner").write_text("99999999\naaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\n", encoding="utf-8")
            classified = root / "first-classified-stale"
            resume = root / "resume-first"
            first_mutation = root / "first-mutated"
            second_mutation = root / "second-mutated"
            dead_kill = root / "dead-kill"
            paused_ps = root / "paused-ps"
            immediate_ps = root / "immediate-ps"
            dead_kill.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            paused_ps.write_text(
                "#!/bin/sh\n"
                f"printf classified > '{classified}'\n"
                f"while [ ! -e '{resume}' ]; do /bin/sleep 0.02; done\n"
                "exit 1\n",
                encoding="utf-8",
            )
            immediate_ps.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            for path in (dead_kill, paused_ps, immediate_ps):
                path.chmod(path.stat().st_mode | stat.S_IXUSR)

            first_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_INSTALLER_KILL_BIN={dead_kill}",
                    f"export PRICKLY_INSTALLER_PS_BIN={paused_ps}",
                    f"source {MAC_INSTALLER}",
                    "acquire_installer_lock",
                    f"print -r -- mutated > {first_mutation}",
                    "release_installer_lock",
                ]
            )
            first = subprocess.Popen(["zsh", "-c", first_script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not classified.exists() and first.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not classified.exists():
                    first_error = first.communicate(timeout=1)[1] if first.poll() is not None else "first classifier timeout"
                    self.fail(first_error)
                second_script = "\n".join(
                    [
                        "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                        f"export PRICKLY_IMAX_HOME={home}",
                        f"export PRICKLY_INSTALLER_KILL_BIN={dead_kill}",
                        f"export PRICKLY_INSTALLER_PS_BIN={immediate_ps}",
                        f"source {MAC_INSTALLER}",
                        "acquire_installer_lock",
                        f"print -r -- mutated > {second_mutation}",
                        "release_installer_lock",
                    ]
                )
                second = subprocess.run(["zsh", "-c", second_script], text=True, capture_output=True, timeout=5)
                self.assertNotEqual(second.returncode, 0, second.stderr)
                self.assertFalse(second_mutation.exists(), second.stderr)
            finally:
                resume.write_text("resume", encoding="utf-8")
                first_stdout, first_stderr = first.communicate(timeout=5)
            self.assertEqual(first.returncode, 0, first_stderr or first_stdout)
            self.assertTrue(first_mutation.exists())

    def test_stale_reclaimer_restores_a_different_live_owner_without_mutating(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            lock_dir = home / "state" / "installer.lock"
            lock_dir.mkdir(parents=True)
            (lock_dir / "owner").write_text("99999999\naaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\n", encoding="utf-8")
            classified = root / "classified-stale"
            resume = root / "resume-reclaimer"
            mutation = root / "reclaimer-mutated"
            dead_kill = root / "dead-kill"
            paused_ps = root / "paused-ps"
            dead_kill.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            paused_ps.write_text(
                "#!/bin/sh\n"
                f"printf classified > '{classified}'\n"
                f"while [ ! -e '{resume}' ]; do /bin/sleep 0.02; done\n"
                "exit 1\n",
                encoding="utf-8",
            )
            for path in (dead_kill, paused_ps):
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            reclaimer_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_INSTALLER_KILL_BIN={dead_kill}",
                    f"export PRICKLY_INSTALLER_PS_BIN={paused_ps}",
                    f"source {MAC_INSTALLER}",
                    "acquire_installer_lock",
                    f"print -r -- mutated > {mutation}",
                    "release_installer_lock",
                ]
            )
            reclaimer = subprocess.Popen(["zsh", "-c", reclaimer_script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            replacement_token = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            displaced = root / "classified-owner"
            try:
                deadline = time.monotonic() + 5
                while not classified.exists() and reclaimer.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not classified.exists():
                    reclaimer_error = reclaimer.communicate(timeout=1)[1] if reclaimer.poll() is not None else "reclaimer timeout"
                    self.fail(reclaimer_error)
                lock_dir.rename(displaced)
                lock_dir.mkdir()
                (lock_dir / "owner").write_text(f"{os.getpid()}\n{replacement_token}\n", encoding="utf-8")
            finally:
                resume.write_text("resume", encoding="utf-8")
                reclaimer_stdout, reclaimer_stderr = reclaimer.communicate(timeout=5)
            self.assertNotEqual(reclaimer.returncode, 0, reclaimer_stdout or reclaimer_stderr)
            self.assertFalse(mutation.exists(), reclaimer_stderr)
            self.assertEqual((lock_dir / "owner").read_text(encoding="utf-8"), f"{os.getpid()}\n{replacement_token}\n")

    def test_installer_lock_owner_write_failure_never_publishes_and_rerun_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            config = home / "config.json"
            profile = home / "browser-profile" / "profile-marker"
            profile.parent.mkdir(parents=True)
            config.write_text("preserve config", encoding="utf-8")
            profile.write_text("preserve profile", encoding="utf-8")
            failed_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"source {MAC_INSTALLER}",
                    "write_installer_lock_owner() { print -rn -- partial > \"$1/owner\"; return 1; }",
                    "if acquire_installer_lock; then release_installer_lock; exit 91; fi",
                    "[[ ! -e ${INSTALLER_LOCK_DIR} ]] || exit 92",
                    "exit 42",
                ]
            )
            failed = subprocess.run(["zsh", "-c", failed_script], text=True, capture_output=True)
            self.assertEqual(failed.returncode, 42, failed.stderr)
            self.assertFalse((home / "state" / "installer.lock").exists())
            self.assertEqual(list((home / "state").glob("installer.lock.candidate.*")), [])

            recovery_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"source {MAC_INSTALLER}",
                    "acquire_installer_lock",
                    "release_installer_lock",
                ]
            )
            recovery = subprocess.run(["zsh", "-c", recovery_script], text=True, capture_output=True)
            self.assertEqual(recovery.returncode, 0, recovery.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), "preserve config")
            self.assertEqual(profile.read_text(encoding="utf-8"), "preserve profile")

    def test_installer_lock_recovers_after_exit_between_publication_and_local_token_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            abrupt_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"source {MAC_INSTALLER}",
                    "mkdir -p ${APP_HOME}/state",
                    "acquire_installer_gate",
                    "candidate_token=$(${INSTALLER_UUIDGEN_BIN})",
                    "prepare_installer_lock_candidate \"${candidate_token}\"",
                    "publish_installer_lock_candidate",
                    "exit 72",
                ]
            )
            abrupt = subprocess.run(["zsh", "-c", abrupt_script], text=True, capture_output=True)
            self.assertEqual(abrupt.returncode, 72, abrupt.stderr)
            self.assertTrue((home / "state" / "installer.lock" / "owner").is_file())

            dead_kill = root / "dead-kill"
            dead_ps = root / "dead-ps"
            dead_kill.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            dead_ps.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            for path in (dead_kill, dead_ps):
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            recovery_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_INSTALLER_KILL_BIN={dead_kill}",
                    f"export PRICKLY_INSTALLER_PS_BIN={dead_ps}",
                    f"source {MAC_INSTALLER}",
                    "acquire_installer_lock",
                    "release_installer_lock",
                ]
            )
            recovery = subprocess.run(["zsh", "-c", recovery_script], text=True, capture_output=True)
            self.assertEqual(recovery.returncode, 0, recovery.stderr)
            self.assertFalse((home / "state" / "installer.lock").exists())

    def test_installer_lock_bounded_recovery_removes_a_dead_partial_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            token = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            partial_candidate = home / "state" / f"installer.lock.candidate.99999999.{token}"
            partial_candidate.mkdir(parents=True)
            (partial_candidate / "owner").write_text("partial", encoding="utf-8")
            dead_kill = root / "dead-kill"
            dead_ps = root / "dead-ps"
            dead_kill.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            dead_ps.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            for path in (dead_kill, dead_ps):
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_INSTALLER_KILL_BIN={dead_kill}",
                    f"export PRICKLY_INSTALLER_PS_BIN={dead_ps}",
                    f"source {MAC_INSTALLER}",
                    "acquire_installer_lock",
                    "release_installer_lock",
                ]
            )
            result = subprocess.run(["zsh", "-c", script], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(partial_candidate.exists(), result.stderr)

    def test_installer_lock_adopts_confirmed_dead_owner_but_not_ambiguous_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            dead_kill = root / "dead-kill"
            dead_ps = root / "dead-ps"
            dead_kill.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            dead_ps.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            for path in (dead_kill, dead_ps):
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            stale_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_INSTALLER_KILL_BIN={dead_kill}",
                    f"export PRICKLY_INSTALLER_PS_BIN={dead_ps}",
                    f"source {MAC_INSTALLER}",
                    "mkdir -p ${INSTALLER_LOCK_DIR}",
                    "printf '%s\\n%s\\n' 99999999 aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa > ${INSTALLER_LOCK_OWNER_FILE}",
                    "acquire_installer_lock",
                    "[[ -n ${INSTALLER_LOCK_TOKEN} ]]",
                    "release_installer_lock",
                ]
            )
            stale = subprocess.run(["zsh", "-c", stale_script], text=True, capture_output=True)
            self.assertEqual(stale.returncode, 0, stale.stderr)
            self.assertFalse((home / "state" / "installer.lock").exists())

            ambiguous_ps = root / "ambiguous-ps"
            ambiguous_ps.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
            ambiguous_ps.chmod(ambiguous_ps.stat().st_mode | stat.S_IXUSR)
            ambiguous_script = "\n".join(
                [
                    "export PRICKLY_INSTALL_SAFETY_LIBRARY=1",
                    f"export PRICKLY_IMAX_HOME={home}",
                    f"export PRICKLY_INSTALLER_KILL_BIN={dead_kill}",
                    f"export PRICKLY_INSTALLER_PS_BIN={ambiguous_ps}",
                    f"source {MAC_INSTALLER}",
                    "mkdir -p ${INSTALLER_LOCK_DIR}",
                    "printf '%s\\n%s\\n' 99999999 bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb > ${INSTALLER_LOCK_OWNER_FILE}",
                    "acquire_installer_lock",
                ]
            )
            ambiguous = subprocess.run(["zsh", "-c", ambiguous_script], text=True, capture_output=True)
            self.assertNotEqual(ambiguous.returncode, 0)
            self.assertTrue((home / "state" / "installer.lock").exists(), ambiguous.stderr)
