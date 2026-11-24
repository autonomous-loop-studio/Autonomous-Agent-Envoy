"""Start llama-server for an ALS model, in bare-JSON mode.

  python launch.py --model ALS-MYTHOS-4B-heretic-f16.gguf
  python launch.py                          # auto-picks a heretic/abliterated GGUF
  python launch.py --ngl 0                 # weights in RAM, CPU only

No tool-schema / --jinja mode. The model was trained to emit a bare JSON object
itself, so tools go in the system prompt (grammars/tools.txt) and the reply shape
is forced per request by a GBNF grammar (ask.py).

Paths: pass --bin / --models-dir, or set LLAMA_SERVER / LLAMA_MODELS.
"""
import argparse
import glob
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.environ.get("LLAMA_SERVER") or "llama-server"
MODELS_DIR = os.environ.get("LLAMA_MODELS") or HERE

# A decensored build carries one of these in its filename.
MARKERS = ("heretic", "abliterated", "hardened")


def is_hardened(path):
    base = os.path.basename(path).lower()
    return any(m in base for m in MARKERS)


def resolve(model_arg, models_dir):
    if model_arg and model_arg != "auto":
        return model_arg
    hits = []
    for pat in ("*.gguf", os.path.join("**", "*.gguf")):
        hits += glob.glob(os.path.join(models_dir, pat), recursive=True)
    hits = [h for h in hits
            if "mmproj" not in os.path.basename(h).lower() and is_hardened(h)]
    if hits:
        # largest = the fullest-precision build of the same model
        return max(sorted(set(hits)), key=os.path.getsize)
    raise SystemExit("no heretic/abliterated GGUF under %s (pass --model or --models-dir)" % models_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="auto", help="'auto' prefers a heretic/abliterated GGUF")
    ap.add_argument("--models-dir", default=MODELS_DIR, help="where to look for 'auto'")
    ap.add_argument("--bin", default=BIN, help="llama-server binary (or set LLAMA_SERVER)")
    ap.add_argument("--ngl", default="99", help="layers on GPU; 0 = all in RAM")
    ap.add_argument("--ctx", default="8192")
    ap.add_argument("--port", default="58880")
    ap.add_argument("--threads", default=str(max(4, (os.cpu_count() or 8) // 2)))
    a = ap.parse_args()

    model = resolve(a.model, a.models_dir)
    if not os.path.exists(model):
        sys.exit("model not found: %s" % model)
    print("model: %s\n  decensored: %s" % (model, "yes" if is_hardened(model) else "no"), flush=True)

    cmd = [
        a.bin,
        "-m", os.path.abspath(model),
        "-ngl", a.ngl,
        "-c", a.ctx,
        "-t", a.threads,
        "--host", "127.0.0.1",
        "--port", a.port,
        "-np", "1",
        "--chat-template-kwargs", '{"enable_thinking": false}',
        "--no-warmup",
    ]
    print(" ".join(cmd), flush=True)
    try:
        proc = subprocess.Popen(cmd)
    except FileNotFoundError:
        sys.exit("llama-server not found: %s\n(pass --bin or set LLAMA_SERVER)" % a.bin)

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


if __name__ == "__main__":
    main()
