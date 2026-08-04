from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Callable, Iterator


class LockUnavailable(BlockingIOError):
    pass


@contextmanager
def locked_file(path: str | Path, *, blocking: bool = True) -> Iterator[BinaryIO]:
    """Hold a one-byte interprocess lock on macOS, Linux, or Windows."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stream = target.open("a+b")
    try:
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            try:
                msvcrt.locking(stream.fileno(), mode, 1)
            except OSError as exc:
                raise LockUnavailable(str(exc)) from exc
            def unlock() -> None:
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
            try:
                fcntl.flock(stream, flags)
            except BlockingIOError as exc:
                raise LockUnavailable(str(exc)) from exc
            def unlock() -> None:
                fcntl.flock(stream, fcntl.LOCK_UN)

        unlock_callback: Callable[[], None] = unlock
        try:
            yield stream
        finally:
            stream.seek(0)
            unlock_callback()
    finally:
        stream.close()
