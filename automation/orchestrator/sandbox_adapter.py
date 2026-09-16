from __future__ import annotations

import os
import selectors
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Protocol

from .sandbox_schema import SandboxRequest, SandboxResult


class SandboxAdapter(Protocol):
    """Provider-independent execution surface for an isolated local runtime."""

    def execute(self, request: SandboxRequest) -> SandboxResult:
        """Execute one bounded workload inside the adapter's isolation boundary."""
        ...


class LocalBubblewrapSandbox:
    """Run workloads through bubblewrap with project-only write access.

    The adapter fails closed when bubblewrap is unavailable. It never invokes a
    shell and does not expose the host user's home directory to the workload.
    """

    _ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "TZ")

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise ValueError("sandbox root must be an existing directory")

    def execute(self, request: SandboxRequest) -> SandboxResult:
        try:
            cwd = self._confined_cwd(request.cwd)
        except ValueError as exc:
            return self._rejected(request, str(exc))

        bwrap = shutil.which("bwrap")
        if bwrap is None:
            return self._rejected(request, "No supported local sandbox runtime is installed.")

        command = [
            bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--clearenv",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(self.root),
            "/workspace",
            "--tmpfs",
            "/home",
            "--tmpfs",
            "/root",
            "--tmpfs",
            "/run",
            "--tmpfs",
            "/tmp",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--chdir",
            f"/workspace/{request.cwd}" if request.cwd != "." else "/workspace",
            "--setenv",
            "PATH",
            os.environ.get("PATH", os.defpath),
            "--setenv",
            "LANG",
            os.environ.get("LANG", "C"),
            "--setenv",
            "LC_ALL",
            os.environ.get("LC_ALL", "C"),
            "--setenv",
            "TZ",
            os.environ.get("TZ", "UTC"),
            "--",
            *request.argv,
        ]

        try:
            return self._run(request, command, cwd)
        except OSError as exc:
            return SandboxResult(
                request_id=request.request_id,
                task_id=request.task_id,
                step_id=request.step_id,
                status="failed",
                error=f"Sandbox runtime failed to start: {exc}",
            )

    def _run(
        self,
        request: SandboxRequest,
        command: list[str],
        cwd: Path,
    ) -> SandboxResult:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        output = {"stdout": bytearray(), "stderr": bytearray()}
        truncated = False
        deadline = __import__("time").monotonic() + request.timeout_seconds

        try:
            while selector.get_map():
                remaining = deadline - __import__("time").monotonic()
                if remaining <= 0:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    return SandboxResult(
                        request_id=request.request_id,
                        task_id=request.task_id,
                        step_id=request.step_id,
                        status="failed",
                        return_code=process.returncode,
                        stdout=output["stdout"].decode(errors="replace"),
                        stderr=output["stderr"].decode(errors="replace"),
                        error="Sandbox workload timed out.",
                    )

                for key, _ in selector.select(min(0.1, remaining)):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    stream = key.data
                    output[stream].extend(chunk)
                    if len(output[stream]) > request.max_output_bytes:
                        truncated = True
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        return SandboxResult(
                            request_id=request.request_id,
                            task_id=request.task_id,
                            step_id=request.step_id,
                            status="failed",
                            return_code=process.returncode,
                            stdout=output["stdout"][: request.max_output_bytes].decode(errors="replace"),
                            stderr=output["stderr"][: request.max_output_bytes].decode(errors="replace"),
                            error="Sandbox workload exceeded the output limit.",
                            metadata={"output_limit_exceeded": "true"},
                        )

            process.wait(timeout=max(0.1, deadline - __import__("time").monotonic()))
        finally:
            selector.close()

        return SandboxResult(
            request_id=request.request_id,
            task_id=request.task_id,
            step_id=request.step_id,
            status="executed" if process.returncode == 0 else "failed",
            return_code=process.returncode,
            stdout=output["stdout"].decode(errors="replace"),
            stderr=output["stderr"].decode(errors="replace"),
            error=None if process.returncode == 0 else "Sandbox workload exited non-zero.",
            metadata={"output_truncated": str(truncated).lower()},
        )

    def _confined_cwd(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("sandbox cwd escapes the configured root")
        if not candidate.is_dir():
            raise ValueError("sandbox cwd must be an existing directory")
        return candidate

    @staticmethod
    def _rejected(request: SandboxRequest, error: str) -> SandboxResult:
        return SandboxResult(
            request_id=request.request_id,
            task_id=request.task_id,
            step_id=request.step_id,
            status="rejected",
            error=error,
        )
