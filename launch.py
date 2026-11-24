"""Start llama-server for ALS-Cyber-Qwen (hardened/abliterated build by default).

  python launch.py                 # auto-picks the hardened GGUF if it exists
  python launch.py --model X.gguf  # explicit file
  python launch.py --ngl 0         # weights in RAM, CPU only

No tool-schema / --jinja tool mode: this model was trained to emit bare JSON
itself, not the chat template's <tool_call> XML. Tools live in the system prompt
(tools.txt) and the reply shape is forced per-request by tool_call.gbnf (ask.py).
"""
import argparse
import glob
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = r"C:/Users/anonb/.unsloth/llama.cpp/build/bin/Release/llama-server.exe"
MODELS_DIR = r"C:/Users/anonb/Documents/models"

# Anything carrying these markers is a decensored/abliterated build.
HARDENED_NAMES = [
    os.path.join(ROOT, "ALS-Cyber-Qwen-hardened.Q8_0.gguf"),
    os.path.join(ROOT, "ALS-Cyber-Qwen-abliterated.Q8_0.gguf"),
    os.path.join(ROOT, "heretic-out", "ALS-Cyber-Qwen-hardened.Q8_0.gguf"),
]
CENSORED_FALLBACK = os.path.join(
    MODELS_DIR, "MBHudson", "ALS-MYTHOS-Qwen-9B-Q8-abliterated-GUFF", "ALS-Cyber-Qwen.Q8_0.gguf"
)


def resolve(model_arg):
    """Return (path, is_hardened)."""
    if model_arg and model_arg != "auto":
        base = os.path.basename(model_arg).lower()
        return model_arg, ("hardened" in base or "abliterated" in base)
    for p in HARDENED_NAMES:
        if os.path.exists(p):
            return p, True
    hits = []
    for pat in ("*-hardened*.gguf", "*-abliterated*.gguf", "*heretic*.gguf"):
        hits += glob.glob(os.path.join(ROOT, pat)) + glob.glob(os.path.join(MODELS_DIR, "**", pat), recursive=True)
    # only ever this project's model: never another abliterated download that happens to match
    hits = [h for h in sorted(set(hits))
            if "mmproj" not in os.path.basename(h).lower()
            and "als-cyber-qwen" in os.path.basename(h).lower()]
    if hits:
        return hits[0], True
    return CENSORED_FALLBACK, False


ap = argparse.ArgumentParser()
ap.add_argument("--model", default="auto", help="'auto' prefers a hardened/abliterated GGUF")
ap.add_argument("--ngl", default="99", help="layers on GPU; 0 = all in RAM")
ap.add_argument("--ctx", default="8192")
ap.add_argument("--port", default="58880")
ap.add_argument("--threads", default=str(max(4, (os.cpu_count() or 8) // 2)))
a = ap.parse_args()

model, hardened = resolve(a.model)
if not os.path.exists(model):
    sys.exit("model not found: %s\n(pass --model)" % model)
print("model: %s\n  hardened: %s" % (model, "YES" if hardened else "NO - censored build, no hardened GGUF found yet"),
      flush=True)

cmd = [
    BIN,
    "-m", os.path.abspath(model),
    "-ngl", a.ngl,
    "-c", a.ctx,
    "-t", a.threads,
    "--host", "127.0.0.1",
    "--port", a.port,
    "-np", "1",
    "--cache-reuse", "256",
    "--chat-template-kwargs", '{"enable_thinking": false}',
    "--no-warmup",
]

print(" ".join(cmd), flush=True)
proc = subprocess.Popen(cmd)

health = "http://127.0.0.1:%s/health" % a.port
for _ in range(300):
    if proc.poll() is not None:
        sys.exit("llama-server exited with code %s" % proc.returncode)
    try:
        if urllib.request.urlopen(health, timeout=2).status == 200:
            print("ready: http://127.0.0.1:%s/v1" % a.port, flush=True)
            break
    except Exception:
        time.sleep(1)

try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
