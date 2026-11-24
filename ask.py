"""Ask ALS-Cyber-Qwen for a tool call, grammar-constrained to its trained protocol.

  python ask.py "list the js files in ui/js"        # precise per-tool arg grammar
  python ask.py --loose "run ls -la"                # any-JSON-arg grammar
  python ask.py --answer "what does a symlink do?"  # free-form, no grammar
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM = (
    'You are an agent that acts by replying with exactly one bare JSON object '
    'of the form {"tool":"NAME","arg":...} and nothing else. No prose, no markdown.'
)

ap = argparse.ArgumentParser()
ap.add_argument("prompt")
ap.add_argument("--port", default="58880")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--answer", action="store_true", help="allow prose instead of a tool call")
ap.add_argument("--loose", action="store_true", help="use the any-JSON-arg grammar")
ap.add_argument("--tools", default=os.path.join(HERE, "tools.txt"))
ap.add_argument("--grammar", default=None)
ap.add_argument("--temperature", type=float, default=0.0)
ap.add_argument("--max-tokens", type=int, default=256)
a = ap.parse_args()

grammar_path = a.grammar or os.path.join(
    HERE, "tool_call_loose.gbnf" if a.loose else "tool_call.gbnf"
)

system = SYSTEM
if os.path.exists(a.tools):
    system += "\n\nTools:\n" + open(a.tools, encoding="utf-8").read().strip()

body = {
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": a.prompt},
    ],
    "temperature": a.temperature,
    "max_tokens": a.max_tokens,
    "cache_prompt": True,
}
if not a.answer:
    if not os.path.exists(grammar_path):
        sys.exit("grammar missing: %s (run gen_tables.py)" % grammar_path)
    body["grammar"] = open(grammar_path, encoding="utf-8").read()

url = "http://%s:%s/v1/chat/completions" % (a.host, a.port)
req = urllib.request.Request(
    url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}
)
try:
    out = json.load(urllib.request.urlopen(req, timeout=300))
except urllib.error.HTTPError as e:
    detail = e.read().decode("utf-8", "replace")
    sys.exit("HTTP %s: %s" % (e.code, detail[:800]))
except Exception as e:
    sys.exit("request failed (%s) - is launch.py running?" % e)

text = (out["choices"][0]["message"].get("content") or "").strip()
print(text)
if not a.answer:
    try:
        call = json.loads(text)
        print("\nparsed -> tool=%s arg=%r" % (call["tool"], call.get("arg")))
    except Exception as e:
        print("\nPARSE FAILED: %s" % e)
