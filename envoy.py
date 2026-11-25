"""Agent Envoy - a live terminal dashboard for a local llama.cpp server.

    python envoy.py [--config path] [--screenshot out.svg]

Panels: the server's model/flags/state, GPU (util, VRAM, temp, power, fan),
CPU (per-core, frequency, temp where the OS exposes it), RAM, tokens/s and
context fill from llama-server's own /metrics, and a tail of its log.

Keys (also in the footer): s start/stop  r restart  +/- ngl  a ngl=auto
[ ] context  m next model  q quit
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import deque
from pathlib import Path

from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, RichLog, Static

import metrics
from server import LlamaServer

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"

SPARK = "▁▂▃▄▅▆▇█"
FULL, EMPTY = "█", "░"

STATE_RUNNING = "●"
STATE_STOPPED = "○"


# ---------------------------------------------------------------- config ---
def _find_binary() -> str:
    """llama-server, in the places a build actually ends up on each OS."""
    explicit = os.environ.get("LLAMA_SERVER")
    if explicit:
        return explicit
    candidates = [
        Path.home() / ".unsloth/llama.cpp/build/bin/Release/llama-server.exe",
        Path.home() / ".unsloth/llama.cpp/build/bin/llama-server",
        Path.home() / "llama.cpp/build/bin/llama-server",
        Path("/opt/homebrew/bin/llama-server"),
        Path("/usr/local/bin/llama-server"),
        Path("C:/llama.cpp/build/bin/Release/llama-server.exe"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return shutil.which("llama-server") or "llama-server"


def _models() -> list[Path]:
    """Every .gguf next to this app or in the usual siblings, smallest first."""
    found: list[Path] = []
    for folder in (HERE / "models", HERE.parent / "models", Path.home() / "models"):
        if folder.is_dir():
            found.extend(sorted(folder.glob("*.gguf")))
            break
    unique = {p.resolve() for p in found}
    return sorted(unique, key=lambda p: p.stat().st_size)


def _default_config() -> dict:
    models = _models()
    return {
        "binary": _find_binary(),
        "model": str(models[0]) if models else "",
        "host": "127.0.0.1",
        "port": 58880,
        "ngl": "auto",
        "ctx": 32768,
        "threads": min(8, os.cpu_count() or 8),
        "flash_attn": "on",
        # --reasoning off replaces the deprecated --chat-template-kwargs form.
        "extra_args": ["--reasoning", "off"],
    }


def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = _default_config()
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg.update(saved)
        except (OSError, ValueError):
            pass
    else:
        try:
            path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except OSError:
            pass
    return cfg


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    try:
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------- drawing ---
def bar(pct: float | None, width: int) -> Text:
    """A block meter. Unknown values stay dim rather than pretending to be 0%."""
    if pct is None:
        return Text(EMPTY * width, style="dim")
    pct = max(0.0, min(100.0, pct))
    filled = round(width * pct / 100.0)
    style = "green" if pct < 60 else "yellow" if pct < 85 else "red"
    out = Text(FULL * filled, style=style)
    out.append(EMPTY * (width - filled), style="dim")
    return out


def spark(values: deque | list, width: int, vmax: float = 100.0) -> Text:
    vals = list(values)[-width:]
    if not vals:
        return Text(" " * min(width, 1), style="dim")
    out = Text()
    for value in vals:
        ratio = 0.0 if vmax <= 0 else max(0.0, min(1.0, value / vmax))
        index = min(len(SPARK) - 1, int(ratio * (len(SPARK) - 1) + 0.5))
        out.append(SPARK[index], style="cyan")
    return out


def row(left: Text, right: Text, width: int) -> Text:
    """left ... right, on one line, clipped to width."""
    gap = width - left.cell_len - right.cell_len
    if gap < 1:
        clipped = left.copy()
        clipped.truncate(width - right.cell_len - 1)
        out = clipped
        gap = max(1, width - out.cell_len - right.cell_len)
    else:
        out = left.copy()
    out.append(" " * gap)
    out.append_text(right)
    return out


def field(label: str, value: str, label_style: str = "dim") -> Text:
    out = Text(f"{label:<7}", style=label_style)
    out.append(value)
    return out


def gib(num_bytes: float) -> str:
    return f"{num_bytes / 1024**3:.1f} GiB"


def human_time(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def tps(value: float | None) -> str:
    if not value:
        return "-"
    return f"{value:,.1f} tok/s"


# ------------------------------------------------------------------- app ---
class LlamaDash(App):
    TITLE = "Agent Envoy"
    SUB_TITLE = "Autonomous Loop Studio"
    CSS = """
    Screen { layout: vertical; }
    Static { height: auto; }
    #log { height: 1fr; min-height: 5; border: round $panel; padding: 0 1; scrollbar-gutter: auto; }
    #log:focus { border: round $accent; }
    """
    BINDINGS = [
        Binding("s", "toggle", "start/stop"),
        Binding("r", "restart", "restart"),
        Binding("plus", "ngl_up", "ngl +"),
        Binding("minus", "ngl_down", "ngl -"),
        Binding("a", "ngl_auto", "auto"),
        Binding("right_square_bracket", "ctx_up", "ctx +"),
        Binding("left_square_bracket", "ctx_down", "ctx -"),
        Binding("m", "next_model", "model"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.srv = LlamaServer()
        self.snap: dict = {}
        self.hist = {"gpu": deque(maxlen=60), "cpu": deque(maxlen=60)}
        self.pending = False
        self._inflight = False
        self.last_tps: dict[str, float] = {}
        self._external_noted = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="server")
        yield Static(id="host")
        yield Static(id="tokens")
        yield RichLog(id="log", max_lines=4000, auto_scroll=True, wrap=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#log", RichLog).border_title = "LOG"
        if self.srv.adopt():
            self._log_lines([f"attached to llama-server pid {self.srv.pid_value}", ""
                             "(output follows this dashboard's log file only)"])
        else:
            self._log_lines(["(server not started - press s)"])
        metrics.cpu_stats()  # prime psutil's first sample; it needs a baseline
        self.set_interval(1.0, self.tick)
        self.tick()

    # ---- polling ---------------------------------------------------------
    def tick(self) -> None:
        self._drain_log()
        if self._inflight:
            return
        self._inflight = True
        self.run_worker(self._collect, thread=True, exclusive=True, exit_on_error=False)

    def _collect(self) -> None:
        snap = {
            "gpu": metrics.gpu_stats(),
            "cpu": metrics.cpu_stats(),
            "mem": metrics.mem_stats(),
            "srv": metrics.server_stats(self.cfg["host"], int(self.cfg["port"])),
            "pid": self.srv.pid(),
            "uptime": self.srv.uptime(),
            "rss": metrics.proc_rss_mib(self.srv.pid()),
            "running": self.srv.running,
        }
        self.call_from_thread(self._apply, snap)

    def _apply(self, snap: dict) -> None:
        self._inflight = False
        self.snap = snap
        gpu = snap.get("gpu") or {}
        cpu = snap.get("cpu") or {}
        self.hist["gpu"].append(gpu.get("util") or 0.0)
        self.hist["cpu"].append(cpu.get("total") or 0.0)
        # llama.cpp's throughput gauges drop back to 0 between requests; keep
        # the last real number so an idle dashboard still shows what it did.
        srv = snap.get("srv") or {}
        for key in ("gen_tps", "prompt_tps"):
            if srv.get(key):
                self.last_tps[key] = srv[key]
        if not srv.get("up") or not srv.get("metrics"):
            self.last_tps.clear()
        if srv.get("up") and not snap.get("running") and not self._external_noted:
            # Someone else owns the port (the .bat, a manual run): we can read
            # /health and /metrics but there is no log to tail and no stop.
            self._external_noted = True
            self._log_lines(
                [f"(port {self.cfg.get('port')} is served by a process Agent Envoy did not start - no log for it)"]
            )
        elif not srv.get("up"):
            self._external_noted = False
        self.render()

    # ---- rendering -------------------------------------------------------
    def _width(self, minimum: int = 30) -> int:
        return max(minimum, self.size.width - 4)  # borders + padding

    def render(self) -> None:
        width = self._width()
        self.query_one("#server", Static).update(self._server_panel(width))
        self.query_one("#host", Static).update(self._host_panel(width))
        self.query_one("#tokens", Static).update(self._tokens_panel(width))

    def _server_panel(self, width: int) -> Panel:
        snap = self.snap
        model = Path(self.cfg.get("model") or "?").name
        try:
            size = gib(Path(self.cfg["model"]).stat().st_size)
        except OSError:
            size = "?"

        if snap.get("running"):
            state = Text()
            state.append(f"{STATE_RUNNING} running", style="green")
            if not snap.get("srv", {}).get("up"):
                state.append("  (loading...)", style="yellow")
            extra = []
            if snap.get("pid"):
                extra.append(f"pid {snap['pid']}")
            if snap.get("rss"):
                extra.append(f"{snap['rss']:,.0f} MiB rss")
            if snap.get("uptime"):
                extra.append(f"up {human_time(snap['uptime'])}")
            if extra:
                state.append("   " + "   ".join(extra), style="dim")
        elif snap.get("srv", {}).get("up"):
            state = Text(f"{STATE_RUNNING} running (not started by Agent Envoy)", style="green")
        else:
            state = Text(f"{STATE_STOPPED} stopped   ", style="red")
            state.append("press s to start", style="dim")

        if self.pending:
            state.append("   ◆ flags changed - r to apply", style="yellow")

        ngl = self.cfg.get("ngl", "auto")
        flags = f"-ngl {ngl}   -c {self.cfg.get('ctx')}   -fa {self.cfg.get('flash_attn', 'on')}   -t {self.cfg.get('threads')}   --metrics"
        addr = f"http://{self.cfg.get('host')}:{self.cfg.get('port')}"

        lines = [
            row(field("MODEL", f"{model}", "dim"), Text(size, style="dim"), width),
            row(state, Text(addr, style="cyan"), width),
            Text(flags, style="dim"),
        ]
        return Panel(Text("\n").join(lines), border_style="grey37", padding=(0, 1), expand=True)

    def _host_panel(self, width: int) -> Panel:
        snap = self.snap
        gpu = snap.get("gpu") or {}
        cpu = snap.get("cpu") or {}
        mem = snap.get("mem") or {}
        lines: list[Text] = []

        # GPU ---------------------------------------------------------------
        if gpu:
            util = gpu.get("util")
            head = Text(f"{'GPU':<7}", style="dim")
            head.append(str(gpu.get("name", "gpu"))[:28], style="bold")
            head.append("   util ")
            head.append_text(spark(self.hist["gpu"], 16))
            if util is None:
                head.append("     -", style="dim")
            else:
                head.append(f" {util:>5.0f}%")
            lines.append(head)

            used, total = gpu.get("vram_used"), gpu.get("vram_total")
            pct = (used / total * 100) if used is not None and total else None
            info = Text(" " * 7)
            info.append("vram ")
            info.append_text(bar(pct, 18))
            info.append(f" {used / 1024:>5.1f}/{total / 1024:.1f} GiB" if used and total else "      -")
            info.append("   ")
            parts = []
            if gpu.get("temp") is not None:
                parts.append(f"{gpu['temp']:.0f}°C")
            if gpu.get("power") is not None:
                parts.append(f"{gpu['power']:.0f}W")
            if gpu.get("fan") is not None:
                parts.append(f"fan {gpu['fan']:.0f}%")
            info.append("   ".join(parts) or "-", style="dim")
            lines.append(info)
        else:
            lines.append(Text("GPU   no nvidia-smi on this machine (macOS or non-NVIDIA)", style="dim"))

        # CPU ---------------------------------------------------------------
        if cpu:
            head = Text(f"{'CPU':<7}", style="dim")
            head.append(f"{cpu.get('count', 0)} cores", style="bold")
            head.append("   ")
            head.append_text(spark(self.hist["cpu"], 16))
            head.append(f" {cpu.get('total', 0):>5.0f}%")
            if cpu.get("freq"):
                head.append(f"   {cpu['freq'] / 1000:.1f} GHz", style="dim")
            temp = cpu.get("temp")
            if temp is not None:
                head.append(f"   {temp:.0f}°C", style="dim")
            else:
                head.append("   temp n/a", style="dim")
            lines.append(head)

            # Per-core meters, only when there is room for them.
            cores = cpu.get("per_core") or []
            if cores and self.size.height >= 27 and width >= 70:
                cols = 4 if width >= 100 else 3 if width >= 80 else 2
                cell = width // max(1, cols)
                per_line = max(1, (len(cores) + cols - 1) // cols)
                for index in range(per_line):
                    line = Text()
                    for column in range(cols):
                        core = index + column * per_line
                        if core >= len(cores):
                            continue
                        value = cores[core]
                        cell_text = Text()
                        cell_text.append(f"c{core:<2}", style="dim")
                        cell_text.append_text(bar(value, 8))
                        cell_text.append(f" {value:>3.0f}%")
                        line.append_text(cell_text)
                        line.append(" " * max(1, cell - cell_text.cell_len))
                    lines.append(line)

        # RAM ---------------------------------------------------------------
        if mem:
            pct = mem.get("percent")
            line = Text(f"{'RAM':<7}", style="dim")
            line.append_text(bar(pct, 18))
            line.append(f" {mem.get('used_gb', 0):.1f}/{mem.get('total_gb', 0):.1f} GiB")
            line.append(f"  {pct:.0f}%", style="dim")
            if mem.get("swap_total_gb"):
                line.append(f"   swap {mem.get('swap_used_gb', 0):.1f}/{mem['swap_total_gb']:.1f}", style="dim")
            lines.append(line)

        return Panel(Text("\n").join(lines), border_style="grey37", padding=(0, 1), expand=True)

    def _tokens_panel(self, width: int) -> Panel:
        srv = self.snap.get("srv") or {}
        ctx = int(self.cfg.get("ctx") or 0)
        peak = srv.get("ctx_peak") or 0
        pct = (peak / ctx * 100) if ctx else 0.0

        if not srv.get("up"):
            body = Text("server is not answering on ", style="dim")
            body.append(f"{self.cfg.get('host')}:{self.cfg.get('port')}", style="cyan")
            body.append(" - press s to start it", style="dim")
            return Panel(body, border_style="grey37", padding=(0, 1), expand=True)

        if not srv.get("metrics"):
            body = Text("no /metrics from this server - token rates unavailable", style="yellow")
            body.append("\nAgent Envoy passes --metrics when it starts the server itself", style="dim")
            return Panel(body, border_style="grey37", padding=(0, 1), expand=True)

        def rate(key: str) -> str:
            live = srv.get(key)
            if live:
                return tps(live)
            remembered = self.last_tps.get(key)
            return f"{tps(remembered)} (last)" if remembered else "-"

        head = field("GEN", rate("gen_tps"))
        head.append("   ")
        head.append_text(field("PROMPT", rate("prompt_tps")))
        head.append("   ctx ")
        head.append_text(bar(pct, 12))
        head.append(f" {peak:,}/{ctx:,}  {pct:.0f}%")

        busy = srv.get("busy_slots") or []
        req = Text(" " * 7)
        req.append(f"processing {int(srv.get('processing') or 0)}   deferred {int(srv.get('deferred') or 0)}", style="dim")
        req.append(f"   slots {srv.get('slots', 1)} ({'busy' if busy else 'idle'})", style="dim")
        req.append(
            f"   total {int(srv.get('generated') or 0):,} gen / {int(srv.get('prompted') or 0):,} prompt",
            style="dim",
        )
        return Panel(Text("\n").join([head, req]), border_style="grey37", padding=(0, 1), expand=True)

    # ---- log -------------------------------------------------------------
    def _drain_log(self) -> None:
        self._log_lines(self.srv.drain())

    def _log_lines(self, lines: list[str]) -> None:
        if not lines:
            return
        log = self.query_one("#log", RichLog)
        for line in lines:
            style = "dim"
            low = line.lower()
            if "error" in low or "failed" in low:
                style = "red"
            elif low.startswith("w ") or " warn" in low:
                style = "yellow"
            log.write(Text(line, style=style))

    # ---- actions ---------------------------------------------------------
    def _save(self) -> None:
        save_config(self.cfg)

    def _changed(self) -> None:
        self._save()
        if self.srv.running:
            self.pending = True
        self.render()

    def action_toggle(self) -> None:
        if self.srv.running:
            if self.srv.stop():
                self.notify("server stopped")
            self.pending = False
        elif (self.snap.get("srv") or {}).get("up"):
            # An external server owns the port (e.g. start.bat): stop it too.
            ok, message = self.srv.stop_listener(int(self.cfg.get("port", 0)))
            if ok:
                self._external_noted = False
                self.notify(message)
            else:
                self.notify(message, severity="warning")
        else:
            ok, message = self.srv.start(self.cfg)
            self.notify(message, severity="information" if ok else "error")
            if ok:
                self.pending = False
        self.render()

    def action_restart(self) -> None:
        was_running = self.srv.running
        if was_running:
            self.srv.stop()
            self.pending = False
        ok, message = self.srv.start(self.cfg)
        self.notify(message if ok else message, severity="information" if ok else "error")
        if ok:
            self.pending = False
        self.render()

    def action_ngl_up(self) -> None:
        current = self.cfg.get("ngl", "auto")
        self.cfg["ngl"] = 4 if current == "auto" else min(99, int(current) + 4)
        self._changed()

    def action_ngl_down(self) -> None:
        current = self.cfg.get("ngl", "auto")
        self.cfg["ngl"] = 0 if current == "auto" else max(0, int(current) - 4)
        self._changed()

    def action_ngl_auto(self) -> None:
        self.cfg["ngl"] = "auto"
        self._changed()

    def action_ctx_up(self) -> None:
        self.cfg["ctx"] = min(262144, int(self.cfg.get("ctx", 32768)) * 2)
        self._changed()

    def action_ctx_down(self) -> None:
        self.cfg["ctx"] = max(1024, int(self.cfg.get("ctx", 32768)) // 2)
        self._changed()

    def action_next_model(self) -> None:
        models = _models()
        if not models:
            self.notify("no .gguf files found", severity="warning")
            return
        names = [str(p) for p in models]
        try:
            index = names.index(self.cfg.get("model"))
        except ValueError:
            index = -1
        self.cfg["model"] = names[(index + 1) % len(names)]
        self.notify(f"model: {Path(self.cfg['model']).name}")
        self._changed()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live dashboard for a local llama.cpp server.")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="path to config.json")
    parser.add_argument(
        "--screenshot",
        metavar="SVG",
        help="render one frame headlessly to an SVG file and exit (useful for reviews)",
    )
    parser.add_argument("--width", type=int, default=120, help="screenshot width in cells")
    parser.add_argument("--height", type=int, default=38, help="screenshot height in cells")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))

    if args.screenshot:
        import asyncio

        async def shoot() -> None:
            app = LlamaDash(cfg)
            async with app.run_test(size=(args.width, args.height)) as pilot:
                for _ in range(4):
                    await pilot.pause(0.9)
                Path(args.screenshot).write_text(app.export_screenshot(), encoding="utf-8")
            print(f"wrote {args.screenshot}")

        asyncio.run(shoot())
        return 0

    LlamaDash(cfg).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
