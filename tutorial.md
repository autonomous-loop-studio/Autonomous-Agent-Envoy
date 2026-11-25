# Agent Envoy — quick tutorial

Agent Envoy — a live terminal dashboard for a local `llama-server`,
part of Autonomous Loop Studio. Everything it reads comes
from your own machine: no cloud, no account, no API key.

## Quick start

1. Open a terminal in this folder.
2. Run it:
   ```bat
   .venv\Scripts\python envoy.py
   ```
   Or double-click `run.cmd`, which runs the same thing.
3. If nothing is serving port 58880 yet, press `s` to start the model server.
   It boots in ~8 s; the log panel fills with its startup lines and the status
   line turns green (`● running`).
4. If your server was already started by `start.bat` or manually,
   Agent Envoy attaches to it read-only (no log tail, no stop) and says so in
   the log panel.

## What it reads (endpoints)

- `/health` — is the server up
- `/slots` — context size, busy/idle slots
- `/metrics` — tokens/s and peak context used (only exists if the server was
  started with `--metrics`; Agent Envoy adds it automatically when it starts
  the server itself)

GPU/CPU/RAM/temp come from `nvidia-smi` and `psutil`. CPU temperature is only
available on Linux; on Windows/macOS the dashboard prints `n/a` rather than
inventing a number.

## Keys

| Key | Action |
|---|---|
| `s` | Start/stop the model server (only if Agent Envoy owns the port) |
| `r` | Restart with the current flags |
| `+` / `-` | Nudge `-ngl` by 4 (converts `auto` to a number) |
| `a` | Set `-ngl` back to `auto` |
| `]` / `[` | Double / halve `-c` (context size) |
| `m` | Cycle through `.gguf` files in the `models` folder |
| `q` | Quit |

Flag changes made while the server is running are saved to `config.json` and
shown as `◆ flags changed - r to apply`; they only take effect on restart.

## No API

Agent Envoy never touches the network except your own `127.0.0.1`. It does not
phone home, need a key, or require an account. Your model and your data stay on
your machine.

## Configuration

`config.json` next to `envoy.py` holds the binary path, model path, port, `-ngl`,
`-c`, threads, flash-attn, and extra args. Edit it by hand or use the keys
above. Settings persist across restarts.

## Notes

- Quitting the dashboard leaves the model server running (it logs to
  `logs\llama-server.log`); the next launch re-attaches to it via the pid file.
- If a port is already served by another process, `s` refuses to start a
  clashing instance and warns you.
- macOS / AMD GPUs: no `nvidia-smi`, so the GPU panel reports "no nvidia-smi".
- The `.bat` launcher (`models\start.bat`) now also passes `--metrics`, so
  dashboards started from either place show token rates.
```
