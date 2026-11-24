# 🤖 Autonomous Agent Envoy

> **The Python side of the [Autonomous Loop Studio](https://huggingface.co/MBHudson/Autonomous-Loop-Studio) agent stack.**
> It serves a local llama.cpp model and forces it to answer with **exactly one bare JSON tool call** — no `tools=[...]`, no `<tool_call>` XML, no markdown fence.

![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg?logo=python&logoColor=white)
![llama.cpp](https://img.shields.io/badge/backend-llama.cpp-111111.svg)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)

```json
{"tool":"now"}
```

Optional — [Autonomous](https://github.com/autonomous-loop-studio/Autonomous) runs without it. This is the bridge for **llama.cpp-backed, decensored models** that speak the ALS bare-JSON protocol.

---

## 📑 Table of Contents

- [✨ What it is](#-what-it-is)
- [🧠 How the protocol works](#-how-the-protocol-works)
- [📦 What's in the box](#-whats-in-the-box)
- [🚀 Quick start](#-quick-start)
- [🛠️ Installation (detailed)](#️-installation-detailed)
- [⚙️ Configuration](#️-configuration)
- [▶️ Running the app](#️-running-the-app)
- [📊 Flag reference (ctx, ngl, threads, …)](#-flag-reference-ctx-ngl-threads-)
- [🧠 Models & datasets](#-models--datasets)
- [📐 Grammar note (GBNF)](#-grammar-note-gbnf)
- [🔗 Related projects](#-related-projects)
- [📜 License](#-license)

---

## ✨ What it is

**Autonomous Agent Envoy** is a tiny, stdlib-only Python toolkit that:

1. 🧠 **Serves** a local GGUF model with `llama-server` in "bare-JSON" mode (thinking off, tool schemas unused).
2. 📜 **Generates** a GBNF grammar from real training data so the model can *never* emit prose or malformed JSON.
3. 🔌 **Bridges** those models into the Autonomous Loop Studio web app, which parses the bare JSON and runs the tool itself.

The result: a local, decensored agent that calls tools with ~14-token replies and ~100% structural validity.

---

## 🧠 How the protocol works

Instead of sending `tools=[...]` (100+ tokens per tool, every turn), the toolkit:

1. Puts the tool list in the **system prompt** as one short line per tool (`now — current date/time`).
2. Lets the model emit its trained bare JSON: `{"tool":"NAME","arg":...}`.
3. **Parses that JSON itself** in the runner.
4. Constrains the output with a **GBNF grammar** so malformed output is *impossible* to generate.

> 💡 This single change — no schemas, short prompt lines, tiny reply, hard grammar — is the biggest token win in the whole stack.

---

## 📦 What's in the box

| File | What it does |
|------|--------------|
| `gen_tables.py` | Reads a training jsonl and writes `grammars/tool_call.gbnf` (one rule per tool, real arg shapes), `tool_call_loose.gbnf` (any JSON arg) and `tools.txt`. Supports `--js` to also emit a JS module. |
| `launch.py` | Starts `llama-server` on `127.0.0.1:58880` with thinking off and tool schemas unused; auto-picks a heretic/abliterated GGUF. |
| `ask.py` | One question → one grammar-constrained reply, parsed and printed. |
| `grammars/` | Generated GBNF grammars + `tools.txt`. |
| `datasets/` | Training/eval jsonl + config used to build the grammars. |
| `old-tools/` | Backup of pre-fix grammars (for reference). |

Stdlib only — **no `pip install` required** for the core scripts.

---

## 🚀 Quick start

```bash
# 1) Generate grammars from training data
python gen_tables.py --data datasets/tool-usage-train.jsonl

# 2) Start the server (auto-picks a heretic/abliterated GGUF in the cwd)
python launch.py

# 3) Ask it something
python ask.py "list the js files in ui/js"
```

Expected output:

```text
{"tool":"glob_files","arg":"ui/js/**/*.js"}

parsed -> tool=glob_files arg='ui/js/**/*.js'
```

---

## 🛠️ Installation (detailed)

### 1. Prerequisites

| Requirement | Notes |
|-------------|-------|
| 🐍 **Python 3.10+** | Stdlib only for the core scripts. |
| 🦙 **llama.cpp** | Need the `llama-server` binary (build with CUDA/Metal/CPU as you like). |
| 🎮 **GPU (optional)** | NVIDIA/Apple Silicon recommended; CPU-only works with `--ngl 0`. |
| 📦 **A GGUF model** | A decensored/abliterated build (see [Models & datasets](#-models--datasets)). |

### 2. Clone

```bash
git clone https://github.com/autonomous-loop-studio/Autonomous-Agent-Envoy.git
cd Autonomous-Agent-Envoy
```

### 3. (Optional) virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

### 4. Get `llama-server`

Either put `llama-server` on your `PATH`, or point to it:

```bash
# env var
export LLAMA_SERVER=/path/to/llama-server        # Linux/macOS
set LLAMA_SERVER=C:\path\to\llama-server.exe    # Windows

# or per-command
python launch.py --bin /path/to/llama-server
```

### 5. Get a model

Drop a heretic/abliterated GGUF into the project folder (or anywhere), then either let `launch.py` auto-pick it or pass it explicitly:

```bash
python launch.py --model path/to/ALS-MYTHOS-4B-heretic-f16.gguf
```

`launch.py` auto-detects any filename containing `heretic`, `abliterated`, or `hardened`.

### 6. (Optional) JS grammar output

If you're wiring the web app, regenerate the JS module too:

```bash
python gen_tables.py --data datasets/tool-usage-train.jsonl --js ui/js/grammar.js
```

---

## ⚙️ Configuration

### Environment variables

| Variable | Purpose |
|----------|---------|
| `LLAMA_SERVER` | Path to the `llama-server` binary. |
| `LLAMA_MODELS` | Directory scanned by `--model auto`. |

### `launch.py` arguments

| Flag | Default | Meaning |
|------|---------|---------|
| `--model` | `auto` | GGUF path, or `auto` to pick the largest heretic/abliterated build. |
| `--models-dir` | `$LLAMA_MODELS` or cwd | Where to scan for `auto`. |
| `--bin` | `$LLAMA_SERVER` or `llama-server` | The llama-server binary. |
| `--ngl` | `99` | Layers offloaded to GPU. `0` = CPU only. |
| `--ctx` | `8192` | Context window size in tokens. |
| `--port` | `58880` | HTTP port for the server. |
| `--threads` | `max(4, cores/2)` | CPU threads for prompt processing. |

### `ask.py` arguments

| Flag | Default | Meaning |
|------|---------|---------|
| `prompt` | — | The user message. |
| `--port` / `--host` | `58880` / `127.0.0.1` | Target server. |
| `--answer` | off | Allow free-form prose instead of a tool call. |
| `--loose` | off | Use the any-JSON-arg grammar instead of the precise one. |
| `--tools` | `grammars/tools.txt` | Tool list injected into the system prompt. |
| `--grammar` | auto | Override the GBNF file path. |
| `--temperature` | `0.0` | Sampling temperature. |
| `--max-tokens` | `256` | Max generated tokens. |

### `gen_tables.py` arguments

| Flag | Default | Meaning |
|------|---------|---------|
| `--data` | `data/tool-usage-train.jsonl` | Training jsonl with `tool`/`use`/`output` fields. |
| `--out` | `grammars/` | Output directory. |
| `--js` | none | Also write a JS module exporting `LOOSE_TOOL_GRAMMAR`. |

> ⚠️ **`--cache-reuse 256` is intentionally NOT used.** llama.cpp build b12651 warns it's unsupported; `launch.py` and `start.bat` have it removed. Don't re-add it.

---

## ▶️ Running the app

### Start the server

```bash
python launch.py
# or
python launch.py --model path/to/model.gguf --ngl 0 --ctx 4096
```

You'll see:

```text
model: ...ALS-MYTHOS-4B-heretic-f16.gguf
  decensored: yes
ready: http://127.0.0.1:58880/v1
```

### Ask a question

```bash
python ask.py "list the js files in ui/js"          # precise grammar
python ask.py --loose "run ls -la"                  # loose grammar
python ask.py --answer "what does a symlink do?"    # free-form, no grammar
```

### Regenerate grammars

```bash
python gen_tables.py --data datasets/tool-usage-train.jsonl
```

---

## 📊 Flag reference (ctx, ngl, threads, …)

| Term | What it means |
|------|---------------|
| **`-ngl` (ngl)** | *Number of GPU Layers.* How many model layers are offloaded to the GPU. Higher = faster, more VRAM. `0` = everything in RAM (CPU only). `99` = "as many as fit". |
| **`-c` (ctx)** | *Context window.* Max tokens the model can see at once (prompt + reply). Bigger = longer conversations but more VRAM/RAM. Common: 4096 / 8192 / 32768. |
| **`-t` (threads)** | CPU threads used for prompt processing / generation on CPU. Usually `cores/2` to `cores`. |
| **`-np`** | *Number of parallel slots.* Set to `1` here (single user). |
| **`--host` / `--port`** | Where the server listens. Default `127.0.0.1:58880` (localhost only — not exposed to the network). |
| **`--chat-template-kwargs`** | Injects `{"enable_thinking": false}` so the model skips chain-of-thought and replies directly. Saves tokens. |
| **`--no-warmup`** | Skip the warmup pass at startup (faster boot). |
| **`--reasoning off`** | Disables reasoning output in the response. |
| **`cache_prompt`** | Reuses the KV cache for repeated prefixes (saves tokens on multi-turn). |
| **`temperature`** | `0.0` = deterministic (best for tool calls). |
| **`max_tokens`** | Caps the reply length (256 is plenty for a bare JSON tool call). |

> 🎯 For tool-calling, keep `temperature=0.0` and a tight `max_tokens`. The grammar makes the output reliable; the tight budget makes it cheap.

---

## 🧠 Models & datasets

Everything lives on Hugging Face under **MBHudson**:

### 🤖 Models
- 🏠 **Hub profile:** [huggingface.co/MBHudson/Autonomous-Loop-Studio](https://huggingface.co/MBHudson/Autonomous-Loop-Studio)
- 🧠 Pre-made (decensored/abliterated) GGUF models are published there — drop one into the project folder and `launch.py` will auto-pick it (it looks for `heretic` / `abliterated` / `hardened` in the filename).

### 📚 Datasets
- 📦 **Dataset repo:** [huggingface.co/datasets/MBHudson/Autonomous-Loop-Studio](https://huggingface.co/datasets/MBHudson/Autonomous-Loop-Studio)
- Contains the tool-usage training/eval jsonl (`tool-usage-train.jsonl`, `tool-usage-eval.jsonl`) and the training config used to fine-tune the ALS models.

### Getting them

```bash
# Option A: huggingface-cli
pip install huggingface_hub
huggingface-cli download MBHudson/Autonomous-Loop-Studio --local-dir ./models

# Option B: git clone the dataset
git clone https://huggingface.co/datasets/MBHudson/Autonomous-Loop-Studio
```

Then point the toolkit at them:

```bash
python launch.py --model ./models/ALS-MYTHOS-4B-heretic-f16.gguf
python gen_tables.py --data ./Autonomous-Loop-Studio/tool-usage-train.jsonl
```

---

## 📐 Grammar note (GBNF)

llama.cpp GBNF has two gotchas this generator already handles:

1. 🔗 **Alternatives must be on ONE line**: `root ::= "a" | "b"` (split lines → parse error).
2. 🔤 **Rule names cannot contain `_`** (digits and `-` are fine) — names are hyphenated.

`gen_tables.py` joins alternatives and hyphenates names, so don't hand-edit those parts back. The `ws` rule includes `\r` and trailing `ws` after `}` so Windows line endings and trailing spaces don't break parsing.

---

## 🔗 Related projects

- 🌐 **Autonomous (web app)** — the host that consumes these tool calls. Runs fine without this toolkit; this is the bridge for llama.cpp models.
- 🧠 **ALS models & data** — [MBHudson/Autonomous-Loop-Studio](https://huggingface.co/MBHudson/Autonomous-Loop-Studio) on Hugging Face.

---

## 📜 License

Apache-2.0. See [`LICENSE`](./LICENSE).

---

<div align="center">

**Made by M. Bryce Hudson Bryce Hudson*

</div>
