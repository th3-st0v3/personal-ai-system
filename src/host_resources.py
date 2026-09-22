"""Local host resource observation and explicitly authorized process controls.

Observation is cross-platform where practical. Mutation is intentionally conservative:
Linux cgroup v2 is supported when PASI can create a delegated cgroup; other platforms
report capability gaps instead of falling back to arbitrary shell commands.
"""
from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MIN_MEMORY_MB = 128
_MAX_MEMORY_MB = 1024 * 1024
_MAX_SWAP_MB = 1024 * 1024
_PROFILE_STATE: dict[int, dict[str, object]] = {}


@dataclass(frozen=True)
class ProcessSnapshot:
    pid: int
    name: str
    state: str
    rss_bytes: int
    swap_bytes: int
    memory_percent: float
    threads: int
    command: str

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "name": self.name,
            "state": self.state,
            "rss_bytes": self.rss_bytes,
            "swap_bytes": self.swap_bytes,
            "memory_percent": round(self.memory_percent, 2),
            "threads": self.threads,
            "command": self.command,
        }


def _read_proc_status(pid: int) -> dict[str, str]:
    values: dict[str, str] = {}
    text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key] = value.strip()
    return values


def _kb(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(value.split()[0]) * 1024
    except (ValueError, IndexError):
        return 0


def _linux_process(pid: int, total_memory: int) -> ProcessSnapshot | None:
    try:
        status = _read_proc_status(pid)
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", errors="replace"
        ).strip()
        name = status.get("Name", f"pid-{pid}")
        state = status.get("State", "unknown").split()[0]
        rss = _kb(status.get("VmRSS"))
        swap = _kb(status.get("VmSwap"))
        threads = int(status.get("Threads", "0").split()[0] or "0")
        percent = (rss / total_memory * 100.0) if total_memory else 0.0
        return ProcessSnapshot(pid, name, state, rss, swap, percent, threads, command)
    except (OSError, ValueError):
        return None


def _linux_memory() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        try:
            values[key] = int(raw.strip().split()[0]) * 1024
        except (ValueError, IndexError):
            continue
    return values


def _cgroup_capabilities() -> dict[str, object]:
    root = Path("/sys/fs/cgroup")
    controllers = set()
    try:
        controllers = set(root.joinpath("cgroup.controllers").read_text().split())
        writable = os.access(root, os.W_OK)
    except OSError:
        writable = False
    memory = "memory" in controllers
    swap = "memory" in controllers and "memory.swap.max" in {
        p.name for p in root.glob("memory.swap.max")
    }
    return {
        "linux_cgroup_v2": root.exists() and bool(controllers),
        "cgroup_delegated": bool(writable),
        "memory_limit": memory and writable,
        "swap_limit": swap and writable,
        "cpu_affinity": hasattr(os, "sched_setaffinity"),
    }


def capabilities() -> dict[str, object]:
    system = platform.system().lower()
    cap = {
        "platform": system,
        "hostname": platform.node(),
        "process_observation": True,
        "resource_profiles": False,
        "requires_explicit_grant_for_mutation": True,
        "backend": "procfs+cgroup-v2" if system == "linux" else "observation-only",
        "features": {},
    }
    cap["features"] = _cgroup_capabilities() if system == "linux" else {
        "linux_cgroup_v2": False,
        "cgroup_delegated": False,
        "memory_limit": False,
        "swap_limit": False,
        "cpu_affinity": False,
    }
    return cap


def workload_profiles() -> dict[str, object]:
    """Return hardware-aware workload budgets without claiming to resize the host."""
    snapshot = host_snapshot()
    total_gb = float(snapshot["memory"]["total_bytes"]) / (1024 ** 3)
    cpu_count = int(snapshot["cpu_count"])
    requirements = {
        "Easy": {"min_ram_gb": 4, "min_cpu": 2, "fuzz_max_iterations": 1000},
        "Standard": {"min_ram_gb": 16, "min_cpu": 6, "fuzz_max_iterations": 5000},
        "Performance": {"min_ram_gb": 32, "min_cpu": 8, "fuzz_max_iterations": 25000},
        "Max": {"min_ram_gb": 64, "min_cpu": 16, "fuzz_max_iterations": 100000},
    }
    profiles = {
        name: {**limits, "available": total_gb >= limits["min_ram_gb"] and cpu_count >= limits["min_cpu"]}
        for name, limits in requirements.items()
    }
    detected = "Easy"
    for name in ("Standard", "Performance", "Max"):
        if profiles[name]["available"]:
            detected = name
    return {
        "detected_tier": detected,
        "host_ram_gb": round(total_gb, 2),
        "cpu_count": cpu_count,
        "profiles": profiles,
    }

def host_snapshot() -> dict[str, object]:
    sampled_at = time.time()
    system = platform.system().lower()
    if system == "linux":
        memory = _linux_memory()
        total = memory.get("MemTotal", 0)
        available = memory.get("MemAvailable", memory.get("MemFree", 0))
        swap_total = memory.get("SwapTotal", 0)
        swap_free = memory.get("SwapFree", 0)
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    else:
        total = available = swap_total = swap_free = 0
        load = (0.0, 0.0, 0.0)
    return {
        "sampled_at": sampled_at,
        "platform": system,
        "cpu_count": os.cpu_count() or 1,
        "load_average": [round(float(value), 3) for value in load],
        "memory": {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": max(0, total - available),
            "used_percent": round(((total - available) / total * 100.0), 2) if total else 0.0,
        },
        "swap": {
            "total_bytes": swap_total,
            "free_bytes": swap_free,
            "used_bytes": max(0, swap_total - swap_free),
            "used_percent": round(((swap_total - swap_free) / swap_total * 100.0), 2) if swap_total else 0.0,
        },
        "capabilities": capabilities(),
    }


def process_snapshot(pid: int) -> dict[str, object]:
    if platform.system().lower() != "linux":
        raise ValueError("Detailed process observation is currently available through the Linux host agent.")
    memory = _linux_memory()
    snapshot = _linux_process(int(pid), memory.get("MemTotal", 0))
    if snapshot is None:
        raise ValueError(f"Process {pid} is not available.")
    return snapshot.to_dict()


def list_processes(query: str = "", limit: int = 100) -> list[dict[str, object]]:
    if platform.system().lower() != "linux":
        return []
    limit = max(1, min(int(limit), 250))
    query = str(query or "").strip().casefold()
    memory = _linux_memory()
    total_memory = memory.get("MemTotal", 0)
    rows: list[dict[str, object]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        snapshot = _linux_process(int(entry.name), total_memory)
        if snapshot is None:
            continue
        if query and query not in snapshot.name.casefold() and query not in snapshot.command.casefold():
            continue
        rows.append(snapshot.to_dict())
    rows.sort(key=lambda row: (float(row["memory_percent"]), int(row["rss_bytes"])), reverse=True)
    return rows[:limit]


def _validate_profile(memory_limit_mb: object, swap_limit_mb: object) -> tuple[int | None, int | None]:
    memory = None if memory_limit_mb in (None, "", "unlimited") else int(memory_limit_mb)
    swap = None if swap_limit_mb in (None, "", "unlimited") else int(swap_limit_mb)
    if memory is not None and not _MIN_MEMORY_MB <= memory <= _MAX_MEMORY_MB:
        raise ValueError(f"memory_limit_mb must be between {_MIN_MEMORY_MB} and {_MAX_MEMORY_MB}.")
    if swap is not None and not 0 <= swap <= _MAX_SWAP_MB:
        raise ValueError(f"swap_limit_mb must be between 0 and {_MAX_SWAP_MB}.")
    return memory, swap


def preview_profile(pid: int, memory_limit_mb: object, swap_limit_mb: object) -> dict[str, object]:
    memory, swap = _validate_profile(memory_limit_mb, swap_limit_mb)
    current = process_snapshot(pid)
    return {
        "mode": "preview",
        "pid": int(pid),
        "current": current,
        "requested": {"memory_limit_mb": memory, "swap_limit_mb": swap},
        "warnings": [
            "A memory limit can cause an application to fail or be terminated if it exceeds the configured limit.",
            "Swap limits may be unavailable unless PASI has a delegated Linux cgroup v2 hierarchy.",
        ],
        "applicable": bool(capabilities()["features"].get("memory_limit")),
    }


def apply_profile(pid: int, memory_limit_mb: object, swap_limit_mb: object) -> dict[str, object]:
    pid = int(pid)
    if pid in {0, 1, os.getpid()}:
        raise PermissionError("PASI refuses to resource-limit PID 0, PID 1, or its own server process.")
    memory, swap = _validate_profile(memory_limit_mb, swap_limit_mb)
    cap = capabilities()["features"]
    if not cap.get("memory_limit"):
        return {
            "mode": "apply",
            "applied": False,
            "pid": pid,
            "reason": "Linux cgroup v2 memory control is not delegated to PASI on this host.",
            "capabilities": cap,
        }
    root = Path("/sys/fs/cgroup")
    parent = root / "pasi"
    target = parent / f"process-{pid}"
    try:
        parent.mkdir(exist_ok=True)
        target.mkdir(exist_ok=True)
        if memory is not None:
            target.joinpath("memory.max").write_text(str(memory * 1024 * 1024))
        if swap is not None and cap.get("swap_limit"):
            target.joinpath("memory.swap.max").write_text(str(swap * 1024 * 1024))
        target.joinpath("cgroup.procs").write_text(str(pid))
    except OSError as exc:
        return {
            "mode": "apply",
            "applied": False,
            "pid": pid,
            "reason": f"OS denied the cgroup change: {exc}",
            "capabilities": cap,
        }
    _PROFILE_STATE[pid] = {
        "cgroup": str(target),
        "applied_at": time.time(),
        "memory_limit_mb": memory,
        "swap_limit_mb": swap,
    }
    return {
        "mode": "apply",
        "applied": True,
        "pid": pid,
        "profile": _PROFILE_STATE[pid],
    }


def clear_profile(pid: int) -> dict[str, object]:
    pid = int(pid)
    record = _PROFILE_STATE.get(pid)
    target = Path(str(record["cgroup"])) if record else Path("/sys/fs/cgroup/pasi") / f"process-{pid}"
    if not target.exists():
        return {"mode": "clear", "cleared": False, "pid": pid, "reason": "No PASI-managed profile is present for this PID."}
    parent = target.parent
    try:
        parent.joinpath("cgroup.procs").write_text(str(pid))
        target.rmdir()
        _PROFILE_STATE.pop(pid, None)
    except OSError as exc:
        return {"mode": "clear", "cleared": False, "pid": pid, "reason": f"OS denied profile removal: {exc}"}
    return {"mode": "clear", "cleared": True, "pid": pid}


__all__ = [
    "capabilities",
    "host_snapshot",
    "list_processes",
    "process_snapshot",
    "preview_profile",
    "apply_profile",
    "clear_profile",
]
