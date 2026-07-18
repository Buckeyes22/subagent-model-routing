"""Process-group supervision with streamed and retained output."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Callable, Mapping

from .run_store import FILE_MODE


OutputCallback = Callable[[str, int], None]


@dataclass(slots=True)
class ProcessResult:
    exit_code: int
    signal: int | None
    timed_out: bool
    cancelled: bool
    wall_ms: int
    stdout_bytes: int
    stderr_bytes: int


@dataclass(slots=True)
class BoundedCaptureResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        try:
            written = os.write(descriptor, view)
            view = view[written:]
        except (BrokenPipeError, OSError):
            return


def _pump(
    pipe: object,
    log_path: Path,
    terminal_fd: int,
    channel: str,
    callback: OutputCallback | None,
    counts: dict[str, int],
) -> None:
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    try:
        while True:
            chunk = pipe.read(65536)  # type: ignore[attr-defined]
            if not chunk:
                break
            _write_all(descriptor, chunk)
            _write_all(terminal_fd, chunk)
            counts[channel] += len(chunk)
            if callback is not None:
                try:
                    callback(channel, len(chunk))
                except (OSError, RuntimeError, TypeError, ValueError):
                    # Output events are additive observability and must never
                    # stop pipe drainage or deadlock the provider process.
                    pass
    finally:
        os.close(descriptor)
        pipe.close()  # type: ignore[attr-defined]


def _feed(pipe: object, content: bytes) -> None:
    try:
        pipe.write(content)  # type: ignore[attr-defined]
        pipe.flush()  # type: ignore[attr-defined]
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            pipe.close()  # type: ignore[attr-defined]
        except (BrokenPipeError, OSError):
            pass


def _capture_bounded(
    pipe: object,
    buffer: bytearray,
    maximum: int,
    counts: dict[str, int],
    channel: str,
) -> None:
    try:
        while True:
            chunk = pipe.read(65536)  # type: ignore[attr-defined]
            if not chunk:
                break
            counts[channel] += len(chunk)
            remaining = maximum - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
    finally:
        pipe.close()  # type: ignore[attr-defined]


def _terminate_group(process: subprocess.Popen[bytes], grace_seconds: float = 2.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _terminate_remaining_group(process_group: int, grace_seconds: float = 2.0) -> None:
    """Reap grandchildren that outlive a normally exiting group leader."""
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_bounded_capture(
    argv: list[str],
    *,
    env: Mapping[str, str],
    timeout_seconds: float,
    max_bytes: int,
    cwd: Path | None = None,
    stdin: bytes | None = None,
) -> BoundedCaptureResult:
    """Run a command while draining both streams and retaining at most ``max_bytes`` each."""

    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        cwd=None if cwd is None else str(cwd),
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    stdout = bytearray()
    stderr = bytearray()
    counts = {"stdout": 0, "stderr": 0}
    threads = [
        threading.Thread(
            target=_capture_bounded,
            args=(process.stdout, stdout, max_bytes, counts, "stdout"),
            daemon=True,
        ),
        threading.Thread(
            target=_capture_bounded,
            args=(process.stderr, stderr, max_bytes, counts, "stderr"),
            daemon=True,
        ),
    ]
    if stdin is not None:
        assert process.stdin is not None
        threads.append(
            threading.Thread(
                target=_feed,
                args=(process.stdin, stdin),
                daemon=True,
            )
        )
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_group(process)
        process.wait()
    _terminate_remaining_group(process.pid)
    for thread in threads:
        thread.join(timeout=5)
    return BoundedCaptureResult(
        returncode=process.returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
        stdout_bytes=counts["stdout"],
        stderr_bytes=counts["stderr"],
        stdout_truncated=counts["stdout"] > len(stdout),
        stderr_truncated=counts["stderr"] > len(stderr),
        timed_out=timed_out,
    )


def run_process(
    argv: list[str],
    *,
    env: Mapping[str, str],
    stdin: bytes | None,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
    cwd: Path,
    output_callback: OutputCallback | None = None,
    terminal_stdout_fd: int = 1,
    terminal_stderr_fd: int = 2,
) -> ProcessResult:
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        cwd=cwd,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    counts = {"stdout": 0, "stderr": 0}
    threads = [
        threading.Thread(target=_pump, args=(process.stdout, stdout_path, terminal_stdout_fd, "stdout", output_callback, counts)),
        threading.Thread(target=_pump, args=(process.stderr, stderr_path, terminal_stderr_fd, "stderr", output_callback, counts)),
    ]
    if stdin is not None:
        assert process.stdin is not None
        threads.append(threading.Thread(target=_feed, args=(process.stdin, stdin)))
    for thread in threads:
        thread.daemon = True
        thread.start()
    timed_out = False
    cancelled = False
    try:
        while process.poll() is None:
            if time.monotonic() - started >= timeout_seconds:
                timed_out = True
                _terminate_group(process)
                break
            time.sleep(0.02)
    except KeyboardInterrupt:
        cancelled = True
        _terminate_group(process)
    return_code = process.wait()
    _terminate_remaining_group(process.pid)
    for thread in threads:
        thread.join(timeout=5)
    child_signal = -return_code if return_code < 0 else None
    exit_code = 124 if timed_out else 130 if cancelled else (128 + child_signal if child_signal else return_code)
    return ProcessResult(
        exit_code=max(0, min(255, exit_code)),
        signal=child_signal,
        timed_out=timed_out,
        cancelled=cancelled,
        wall_ms=max(0, int((time.monotonic() - started) * 1000)),
        stdout_bytes=counts["stdout"],
        stderr_bytes=counts["stderr"],
    )
