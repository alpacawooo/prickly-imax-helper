from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

from .locks import LockUnavailable, locked_file
from .paths import RuntimePaths


SAFE_OLD_STATUSES = {
    "unconfigured",
    "login_required",
    "armed",
    "staging",
    "completed",
    "recovering",
    "rate_limited",
    "blocked_duplicate",
    "blocked_payment",
    "fatal",
    "stopped",
}
SAFE_STOP_STATUSES = {"completed", "blocked_duplicate", "blocked_payment", "fatal", "stopped"}


class MaintenanceError(RuntimeError):
    pass


def _control_lock(paths: RuntimePaths) -> Path:
    return paths.state_dir / "service-control.lock"


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MaintenanceError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def parse_old_cli_json(raw: str, *, stop_payload: bool = False) -> str:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=lambda value: (_ for _ in ()).throw(MaintenanceError(f"invalid JSON constant: {value}")),
        )
    except (json.JSONDecodeError, MaintenanceError) as exc:
        raise MaintenanceError("old CLI response is not one strict JSON object") from exc
    if not isinstance(value, dict):
        raise MaintenanceError("old CLI response is not one strict JSON object")
    status = value.get("status")
    if not isinstance(status, str):
        raise MaintenanceError("old CLI response has no status")
    if stop_payload:
        if set(value) != {"ok", "status"} or value.get("ok") is not True or status not in SAFE_STOP_STATUSES:
            raise MaintenanceError("old CLI stop response is unsafe")
    elif status not in SAFE_OLD_STATUSES:
        raise MaintenanceError("old CLI status is unsafe")
    return status


def _read_barrier(paths: RuntimePaths) -> tuple[str, int]:
    try:
        payload = json.loads(paths.maintenance_barrier.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaintenanceError("update barrier is missing or unreadable") from exc
    token = payload.get("token") if isinstance(payload, dict) else None
    owner_pid = payload.get("owner_pid") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token or not isinstance(owner_pid, int) or owner_pid <= 0:
        raise MaintenanceError("update barrier owner is invalid")
    return token, owner_pid


def _require_owner(paths: RuntimePaths, token: str) -> None:
    current_token, _ = _read_barrier(paths)
    if not secrets.compare_digest(current_token, token):
        raise MaintenanceError("update barrier belongs to another installer")


def _is_windows() -> bool:
    return os.name == "nt"


class _WindowsProcessApi:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    ERROR_INVALID_PARAMETER = 87
    STILL_ACTIVE = 259

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = kernel32

    def open_process(self, pid: int) -> int:
        return self._kernel32.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)

    def get_last_error(self) -> int:
        return self._ctypes.get_last_error()

    def get_exit_code(self, handle: int) -> int | None:
        exit_code = self._wintypes.DWORD()
        if not self._kernel32.GetExitCodeProcess(handle, self._ctypes.byref(exit_code)):
            return None
        return exit_code.value

    def close_handle(self, handle: int) -> None:
        self._kernel32.CloseHandle(handle)


def _windows_process_is_running(pid: int) -> bool:
    api = _WindowsProcessApi()
    handle = api.open_process(pid)
    if not handle:
        error = api.get_last_error()
        if error == api.ERROR_INVALID_PARAMETER:
            return False
        if error == api.ERROR_ACCESS_DENIED:
            return True
        # Unknown query failures are also treated as live so stale-barrier
        # adoption can never replace an owner that Windows did not let us inspect.
        return True
    try:
        exit_code = api.get_exit_code(handle)
        return exit_code is None or exit_code == api.STILL_ACTIVE
    finally:
        api.close_handle(handle)


def _process_is_running(pid: int) -> bool:
    if _is_windows():
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_barrier(paths: RuntimePaths, token: str, owner_pid: int, *, replace: bool) -> None:
    payload = {"owner_pid": owner_pid, "schema": 1, "token": token}
    if replace:
        temporary = paths.maintenance_barrier.with_name(f".{paths.maintenance_barrier.name}.{secrets.token_hex(8)}")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, paths.maintenance_barrier)
        finally:
            temporary.unlink(missing_ok=True)
        return
    descriptor = os.open(paths.maintenance_barrier, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        paths.maintenance_barrier.unlink(missing_ok=True)
        raise


def _begin_update_locked(paths: RuntimePaths, token: str, owner_pid: int) -> None:
    if paths.maintenance_barrier.exists():
        _, existing_pid = _read_barrier(paths)
        if _process_is_running(existing_pid):
            raise MaintenanceError("another installer still owns the update barrier")
        _write_barrier(paths, token, owner_pid, replace=True)
        return
    try:
        _write_barrier(paths, token, owner_pid, replace=False)
    except FileExistsError as exc:
        raise MaintenanceError("another installer created the update barrier") from exc


def _validated_owner_pid(owner_pid: int | None) -> int:
    result = os.getpid() if owner_pid is None else owner_pid
    if result <= 0:
        raise MaintenanceError("update owner process is invalid")
    return result


def begin_update(paths: RuntimePaths, *, owner_pid: int | None = None) -> str:
    paths.prepare()
    token = secrets.token_hex(32)
    owner_pid = _validated_owner_pid(owner_pid)
    with locked_file(_control_lock(paths)):
        _begin_update_locked(paths, token, owner_pid)
    return token


def verify_monitor_stopped(paths: RuntimePaths, token: str) -> None:
    with locked_file(_control_lock(paths)):
        _require_owner(paths, token)
        try:
            with locked_file(paths.state_dir / "monitor.lock", blocking=False):
                pass
        except LockUnavailable as exc:
            raise MaintenanceError("resident monitor still owns monitor.lock") from exc


def end_update(paths: RuntimePaths, token: str) -> None:
    with locked_file(_control_lock(paths)):
        _require_owner(paths, token)
        paths.maintenance_barrier.unlink()


def install_launcher(target: Path, runtime: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.update-{secrets.token_hex(8)}")
    source = (
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.path.insert(0, {str(runtime)!r})\n"
        "from prickly_imax_helper.cli import main\n"
        "raise SystemExit(main())\n"
    )
    try:
        temporary.write_text(source, encoding="utf-8")
        os.chmod(temporary, 0o755)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def arm_update(
    paths: RuntimePaths,
    launcher: Path,
    runtime: Path,
    *,
    owner_pid: int | None = None,
) -> str:
    if not runtime.is_dir():
        raise MaintenanceError(f"release runtime is missing: {runtime}")
    paths.prepare()
    token = secrets.token_hex(32)
    owner_pid = _validated_owner_pid(owner_pid)
    with locked_file(_control_lock(paths)):
        _begin_update_locked(paths, token, owner_pid)
        install_launcher(launcher, runtime)
    return token


def replace_runtime(paths: RuntimePaths, token: str, source: Path, target: Path) -> None:
    if not source.is_dir():
        raise MaintenanceError(f"release runtime is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = secrets.token_hex(8)
    staged = target.with_name(f".{target.name}.update-{suffix}")
    backup = target.with_name(f".{target.name}.backup-{suffix}")
    try:
        shutil.copytree(source, staged)
        with locked_file(_control_lock(paths)):
            _require_owner(paths, token)
            try:
                with locked_file(paths.state_dir / "monitor.lock", blocking=False):
                    if target.exists():
                        os.replace(target, backup)
                    try:
                        os.replace(staged, target)
                    except BaseException:
                        if backup.exists() and not target.exists():
                            os.replace(backup, target)
                        raise
            except LockUnavailable as exc:
                raise MaintenanceError("resident monitor restarted before runtime replacement") from exc
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prickly-update-maintenance")
    parser.add_argument("--home", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("begin")
    begin.add_argument("--owner-pid", type=int)
    arm = commands.add_parser("arm")
    arm.add_argument("--launcher", type=Path, required=True)
    arm.add_argument("--runtime", type=Path, required=True)
    arm.add_argument("--owner-pid", type=int)
    verify = commands.add_parser("verify")
    verify.add_argument("--token", required=True)
    end = commands.add_parser("end")
    end.add_argument("--token", required=True)
    replace = commands.add_parser("replace-runtime")
    replace.add_argument("--token", required=True)
    replace.add_argument("--source", type=Path, required=True)
    replace.add_argument("--target", type=Path, required=True)
    strict_json = commands.add_parser("parse-json")
    strict_json.add_argument("--mode", choices=("status", "stop"), required=True)
    args = parser.parse_args(argv)
    paths = RuntimePaths(args.home.expanduser() if args.home else RuntimePaths.default().root)
    try:
        if args.command == "begin":
            print(begin_update(paths, owner_pid=args.owner_pid or os.getppid()))
        elif args.command == "arm":
            print(arm_update(paths, args.launcher, args.runtime, owner_pid=args.owner_pid or os.getppid()))
        elif args.command == "verify":
            verify_monitor_stopped(paths, args.token)
        elif args.command == "end":
            end_update(paths, args.token)
        elif args.command == "replace-runtime":
            replace_runtime(paths, args.token, args.source, args.target)
        elif args.command == "parse-json":
            print(parse_old_cli_json(sys.stdin.read(), stop_payload=args.mode == "stop"))
    except MaintenanceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
