"""Readings for Agent Envoy.

Every probe is best-effort. A machine without nvidia-smi (macOS, AMD, a bare
container) reports None for the GPU rather than raising, and a machine where
Python cannot see CPU temperatures (Windows, macOS) reports None for that
number instead of inventing one.

Sources
  GPU        nvidia-smi --query-gpu (Windows + Linux with an NVIDIA driver)
  CPU/RAM    psutil
  CPU temp   psutil.sensors_temperatures (Linux only; absent elsewhere)
  server     llama-server: /health, /slots, /metrics (needs --metrics)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request

try:
    import psutil
except ImportError:  # psutil is in requirements.txt; keep import failure soft
    psutil = None

# Keep nvidia-smi from flashing a console window on Windows.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

GPU_FIELDS = (
    "name",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "temperature.gpu",
    "power.draw",
    "fan.speed",
)


def _run(cmd: list[str], timeout: float = 2.0) -> str | None:
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def _number(text: str | None) -> float | None:
    """nvidia-smi writes '[N/A]' for values the card/driver does not expose."""
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def gpu_stats() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    out = _run(["nvidia-smi", f"--query-gpu={','.join(GPU_FIELDS)}", "--format=csv,noheader,nounits"])
    if not out or not out.strip():
        return None
    parts = [p.strip() for p in out.strip().splitlines()[0].split(",")]
    if len(parts) < 6:
        return None
    return {
        "name": parts[0],
        "util": _number(parts[1]),          # %
        "vram_used": _number(parts[2]),     # MiB
        "vram_total": _number(parts[3]),    # MiB
        "temp": _number(parts[4]),          # C
        "power": _number(parts[5]),         # W
        "fan": _number(parts[6]) if len(parts) > 6 else None,
    }


# Driver sensor group names that describe the CPU rather than a disk or a NIC.
_CPU_TEMP_GROUPS = ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal", "soc_thermal")


def cpu_temp() -> float | None:
    if psutil is None or not hasattr(psutil, "sensors_temperatures"):
        return None
    try:
        groups = psutil.sensors_temperatures() or {}
    except Exception:
        return None
    for name in _CPU_TEMP_GROUPS:
        for entry in groups.get(name, []):
            if entry.current:
                return float(entry.current)
    return None


def cpu_stats() -> dict:
    if psutil is None:
        return {}
    per_core = psutil.cpu_percent(percpu=True, interval=None)
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.current) if f else None
    except Exception:
        freq = None
    return {
        "count": len(per_core),
        "per_core": per_core,
        "total": (sum(per_core) / len(per_core)) if per_core else 0.0,
        "freq": freq,          # MHz
        "temp": cpu_temp(),
    }


def proc_rss_mib(pid: int | None) -> float | None:
    """Resident memory of the server process, in MiB. None when it is gone."""
    if psutil is None or not pid:
        return None
    try:
        return psutil.Process(pid).memory_info().rss / 1024**2
    except Exception:
        return None


def mem_stats() -> dict:
    if psutil is None:
        return {}
    vm = psutil.virtual_memory()
    swap_used = swap_total = None
    try:
        sm = psutil.swap_memory()
        swap_used, swap_total = sm.used, sm.total
    except Exception:
        pass
    return {
        "used_gb": vm.used / 1024**3,
        "total_gb": vm.total / 1024**3,
        "percent": vm.percent,
        "swap_used_gb": (swap_used / 1024**3) if swap_used else None,
        "swap_total_gb": (swap_total / 1024**3) if swap_total else None,
    }


def _get(url: str, timeout: float) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        return None


def _parse_prometheus(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or " " not in line:
            continue
        name, _, raw = line.rpartition(" ")
        try:
            values[name] = float(raw)
        except ValueError:
            continue
    return values


def server_stats(host: str = "127.0.0.1", port: int = 58880, timeout: float = 0.5) -> dict:
    """One snapshot of llama-server. Never raises; `up` is False if it is not there."""
    base = f"http://{host}:{int(port)}"
    stats: dict = {"up": False, "metrics": False}
    if _get(base + "/health", timeout) is None:
        return stats
    stats["up"] = True

    raw_metrics = _get(base + "/metrics", timeout)
    if raw_metrics:
        m = _parse_prometheus(raw_metrics)
        if m:
            stats.update(
                metrics=True,
                gen_tps=m.get("llamacpp:predicted_tokens_seconds"),
                prompt_tps=m.get("llamacpp:prompt_tokens_seconds"),
                processing=m.get("llamacpp:requests_processing"),
                deferred=m.get("llamacpp:requests_deferred"),
                ctx_peak=m.get("llamacpp:n_tokens_max"),
                generated=m.get("llamacpp:tokens_predicted_total"),
                prompted=m.get("llamacpp:prompt_tokens_total"),
            )

    raw_slots = _get(base + "/slots", timeout)
    if raw_slots:
        try:
            slots = json.loads(raw_slots)
        except ValueError:
            slots = []
        if isinstance(slots, list):
            stats["slots"] = len(slots)
            busy = [s.get("id") for s in slots if s.get("is_processing")]
            stats["busy_slots"] = busy
            for slot in slots:
                if slot.get("n_ctx"):
                    stats["n_ctx"] = slot["n_ctx"]
                # An idle slot keeps the size of its last prompt; use it only
                # when /metrics did not provide a peak.
                if not stats.get("ctx_peak"):
                    stats["ctx_peak"] = slot.get("n_prompt_tokens") or 0
    return stats
