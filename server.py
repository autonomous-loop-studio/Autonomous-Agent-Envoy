"""llama-server process control for Agent Envoy.

The process is spawned directly (no shell, no .bat) so the same code starts it
on Windows, Linux and macOS.

Its output goes to logs/llama-server.log and the UI tails that file, not a
pipe: a pipe nobody is draining blocks the server once the buffer fills, which
is exactly what would happen if the dashboard were closed while the server
kept running. With a file the server survives the dashboard, and the log stays
there to read afterwards.

A pid file lets a restarted dashboard recognise (and stop) the server it
started in an earlier session.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class LlamaServer:
    def __init__(self, log_dir: Path | None = None) -> None:
        log_dir = log_dir or Path(__file__).resolve().parent / "logs"
        self.log_dir = log_dir
        self.log_path = log_dir / "llama-server.log"
        self.pid_path = log_dir / "llama-server.pid"
        self.proc: subprocess.Popen | None = None
        self.pid_value: int | None = None
        self.started_at: float | None = None
        self._pos = self._size()      # do not replay an old session on launch
        self._partial = ""

    # ---- helpers ---------------------------------------------------------
    def _size(self) -> int:
        try:
            return self.log_path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _alive(pid: int | None) -> bool:
        if not pid:
            return False
        if psutil is not None:
            try:
                proc = psutil.Process(pid)
                return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            except Exception:
                return False
        try:
            os.kill(pid, 0)  # signal 0 is a liveness probe, POSIX only
            return True
        except OSError:
            return False

    def _write_pid(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.pid_path.write_text(str(self.pid_value or ""), encoding="utf-8")
        except OSError:
            pass

    # ---- state -----------------------------------------------------------
    @property
    def running(self) -> bool:
        if self.proc is not None and self.proc.poll() is not None:
            self.proc = None
            if self.pid_value:
                # exited on its own (crash, port in use, model too big)
                self.pid_value = None
                self.started_at = None
                self._write_pid()
        return bool(self.pid_value and self._alive(self.pid_value))

    def pid(self) -> int | None:
        return self.pid_value if self.running else None

    def uptime(self) -> float | None:
        if not self.running or not self.started_at:
            return None
        return time.time() - self.started_at

    def adopt(self) -> bool:
        """Pick up a server started by an earlier Agent Envoy session."""
        if self.running:
            return True
        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return False
        self.pid_value = pid if self._alive(pid) else None
        self.started_at = None
        return self.pid_value is not None

    # ---- argv ------------------------------------------------------------
    def argv(self, cfg: dict) -> list[str]:
        ngl = cfg.get("ngl", "auto")
        args = [
            cfg["binary"],
            "-m", cfg["model"],
            "-ngl", str(ngl),
            "-c", str(int(cfg.get("ctx", 32768))),
            "-fa", str(cfg.get("flash_attn", "on")),
            "-t", str(int(cfg.get("threads", 8))),
            "--host", str(cfg.get("host", "127.0.0.1")),
            "--port", str(int(cfg.get("port", 58880))),
            "-np", "1",
            # Agent Envoy's token/s and context panels read this endpoint.
            "--metrics",
        ]
        args.extend(str(a) for a in cfg.get("extra_args", []))
        return args

    # ---- lifecycle -------------------------------------------------------
    def start(self, cfg: dict) -> tuple[bool, str]:
        if self.running:
            return False, "already running"
        if not os.path.exists(cfg["binary"]):
            return False, f"llama-server not found: {cfg['binary']}"
        if not os.path.exists(cfg["model"]):
            return False, f"model not found: {cfg['model']}"

        argv = self.argv(cfg)
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._pos = self._size()
            with open(self.log_path, "a", encoding="utf-8", errors="replace") as log:
                log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start ===\n")
                log.write("$ " + " ".join(argv) + "\n")
                self.proc = subprocess.Popen(
                    argv,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=_NO_WINDOW,
                )
        except OSError as exc:
            self.proc = None
            return False, f"could not start: {exc}"

        self.pid_value = self.proc.pid
        self.started_at = time.time()
        self._write_pid()
        return True, "starting"

    def stop(self, timeout: float = 10.0) -> bool:
        """Terminate the server (ours, or one we started in an earlier session)."""
        pid = self.pid_value
        if not pid:
            return False
        proc = self.proc
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
            elif self._alive(pid) and psutil is not None:
                handle = psutil.Process(pid)
                handle.terminate()
                try:
                    handle.wait(timeout=timeout)
                except psutil.TimeoutExpired:
                    handle.kill()
        except Exception:
            pass
        self.proc = None
        self.pid_value = None
        self.started_at = None
        self._write_pid()
        return True

    def stop_listener(self, port: int, timeout: float = 10.0) -> tuple[bool, str]:
        """Terminate whatever process is listening on `port`, even if Agent Envoy
        did not start it (e.g. a server launched from start.bat)."""
        if psutil is None:
            return False, "psutil unavailable"
        pids: set[int] = set()
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port == port and conn.pid:
                    pids.add(conn.pid)
        except Exception:
            pass
        if not pids:
            try:
                for proc in psutil.process_iter(["pid"]):
                    try:
                        for conn in proc.net_connections(kind="tcp"):
                            if conn.laddr and conn.laddr.port == port:
                                pids.add(proc.pid)
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass
            except Exception:
                pass
        if not pids:
            return False, f"no process found on port {port}"
        for pid in pids:
            try:
                handle = psutil.Process(pid)
                handle.terminate()
                try:
                    handle.wait(timeout=timeout)
                except psutil.TimeoutExpired:
                    handle.kill()
            except Exception:
                pass
        try:
            self.pid_path.unlink(missing_ok=True)
        except Exception:
            pass
        self.proc = None
        self.pid_value = None
        self.started_at = None
        return True, f"stopped process on port {port}"

    # ---- log -------------------------------------------------------------
    def drain(self) -> list[str]:
        """New lines appended to the log file since the last call."""
        try:
            size = self.log_path.stat().st_size
        except OSError:
            return []
        if size < self._pos:  # file replaced or truncated
            self._pos = 0
            self._partial = ""
        if size == self._pos:
            return []
        try:
            with open(self.log_path, "rb") as handle:
                handle.seek(self._pos)
                chunk = handle.read(size - self._pos)
        except OSError:
            return []
        self._pos += len(chunk)
        text = self._partial + chunk.decode("utf-8", "replace")
        *complete, self._partial = text.split("\n")
        if len(self._partial) > 8192:  # pathological line, flush it
            complete.append(self._partial)
            self._partial = ""
        return [line.rstrip("\r") for line in complete if line.strip()]
