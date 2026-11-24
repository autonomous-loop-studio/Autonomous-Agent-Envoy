"""Generate GBNF grammars for the ALS bare-JSON tool protocol.

  {"tool": "NAME", "arg": <that tool's own shape>}

Reads real arg shapes out of the training jsonl and emits two grammars:

  grammars/tool_call.gbnf         precise: one rule per tool, arg keys/types inferred
  grammars/tool_call_loose.gbnf   fallback: any valid JSON arg
  grammars/tools.txt              the tool list for the system prompt

  python gen_tables.py --data data/tool-usage-train.jsonl
  python gen_tables.py --data x.jsonl --out /tmp/g
  python gen_tables.py --data x.jsonl --js ui/js/grammar.js   # also write a JS module

Two llama.cpp GBNF constraints bite this generator, both verified against llama-server:

  * alternatives must be on ONE line: `a ::= "x" | "y"` (split lines = parse error)
  * rule names cannot contain `_` (digits and `-` are fine), so names are hyphenated
"""
import argparse
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

NOARG = object()


class Gen:
    def __init__(self):
        self.rules = []  # list of (name, body)
        self.counter = 0

    def new(self, base):
        self.counter += 1
        return ident("%s-%d" % (base, self.counter))

    def value(self, obs, base):
        """Rule name accepting every observed JSON value (recursive)."""
        types = {kind(v) for v in obs}
        alts = []
        if "str" in types:
            alts.append("string")
        if "num" in types:
            alts.append("number")
        if "bool" in types:
            alts.append("boolean")
        if "null" in types:
            alts.append('"null"')
        if "list" in types:
            elems = [e for v in obs if isinstance(v, list) for e in v]
            name = self.new(base + "_arr")
            elem = self.value(elems, name + "_el") if elems else "value"
            self.rules.append((name, '"[" ws (%s (ws "," ws %s)*)? ws "]"' % (elem, elem)))
            alts.append(name)
        if "dict" in types:
            dicts = [v for v in obs if isinstance(v, dict)]
            keys = []
            for d in dicts:
                for k in d:
                    if k not in keys:
                        keys.append(k)
            name = self.new(base + "_obj")
            if not keys:
                self.rules.append((name, '"{" ws "}"'))
            else:
                parts = []
                for i, k in enumerate(keys):
                    sub = [d[k] for d in dicts if k in d]
                    member = '"\\"%s\\":" ws %s' % (
                        k.replace('"', '\\"'),
                        self.value(sub, name + "_" + k),
                    )
                    parts.append(member if i == 0 else '(ws "," ws %s)?' % member)
                self.rules.append((name, '"{" ws ' + " ".join(parts) + ' ws "}"'))
            alts.append(name)
        if not alts:
            alts = ["value"]
        if len(alts) == 1:
            return alts[0]
        name = self.new(base + "_alt")
        self.rules.append((name, " | ".join(alts)))  # one line, always
        return name


def ident(name):
    """GBNF rule name. llama.cpp rejects '_' in symbols; letters, digits and '-' are fine."""
    return re.sub(r"[^0-9A-Za-z-]", "-", name).strip("-") or "r"


def kind(v):
    if v is NOARG:
        return "noarg"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    if v is None:
        return "null"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    return "str"


def q(name):
    return '"\\"' + name.replace("\\", "\\\\").replace('"', '\\"') + '\\""'


BASE_RULES = """value     ::= string | number | object | array | boolean | "null"
object    ::= "{" ws (pair (ws "," ws pair)*)? ws "}"
pair      ::= string ws ":" ws value
array     ::= "[" ws (value (ws "," ws value)*)? ws "]"
boolean   ::= "true" | "false"
string    ::= "\\"" char* "\\""
char      ::= [^"\\\\] | "\\\\" (["\\\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
number    ::= "-"? int frac? exp?
int       ::= "0" | [1-9] [0-9]*
frac      ::= "." [0-9]+
exp       ::= [eE] [+-]? [0-9]+
ws        ::= [ \\t\\r\\n]*
"""


def load(data_path):
    rows = [json.loads(l) for l in open(data_path, encoding="utf-8") if l.strip()]
    tools, shapes = {}, {}
    for r in rows:
        t = r.get("tool")
        if not t:
            continue
        if t not in tools:
            u = r.get("use")
            desc = u.strip() if isinstance(u, str) and 3 < len(u) < 120 else None
            if not desc:
                desc = (r.get("instruction") or "").strip().split(":")[0][:70]
            tools[t] = desc
            shapes[t] = []
        try:
            obj = json.loads(r["output"])
        except Exception:
            continue
        shapes[t].append(obj["arg"] if isinstance(obj, dict) and "arg" in obj else NOARG)
    if not tools:
        raise SystemExit("no tool names in %s" % data_path)
    return tools, shapes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "data", "tool-usage-train.jsonl"),
                    help="training jsonl with tool/use/output fields")
    ap.add_argument("--out", default=os.path.join(HERE, "grammars"), help="output directory")
    ap.add_argument("--js", default=None, metavar="PATH",
                    help="also write a JS module exporting LOOSE_TOOL_GRAMMAR to PATH")
    a = ap.parse_args()
    if not os.path.exists(a.data):
        raise SystemExit("data not found: %s\n(pass --data path/to/tool-usage-train.jsonl)" % a.data)

    tools, shapes = load(a.data)
    names = sorted(tools)
    os.makedirs(a.out, exist_ok=True)

    gen = Gen()
    tool_alts = []
    for t in names:
        obs = shapes[t]
        rule = gen.new("t_" + t.replace("-", "_"))
        arg_obs = [v for v in obs if v is not NOARG]
        if not arg_obs:
            gen.rules.append((rule, '"{\\"tool\\":" ws %s ws "}" ws' % q(t)))
        else:
            arg = gen.value(arg_obs, "a_" + t.replace("-", "_"))
            gen.rules.append(
                (rule, '"{\\"tool\\":" ws %s (ws "," ws "\\"arg\\":" ws %s)? ws "}" ws' % (q(t), arg))
            )
        tool_alts.append(rule)

    precise = (
        "# Per-tool GBNF for the ALS bare-JSON protocol. Generated by gen_tables.py.\n"
        "# Each tool gets its own rule, with the argument keys and types seen in training.\n"
        "root      ::= %s\n\n" % " | ".join(tool_alts)
        + BASE_RULES
        + "\n"
    )
    for name, body in gen.rules:
        precise += "%-24s ::= %s\n" % (name, body)

    loose = (
        "# Loose fallback: any valid JSON arg. Generated by gen_tables.py.\n"
        'root      ::= "{\\"tool\\":" ws tool (ws "," ws "\\"arg\\":" ws value)? ws "}" ws\n'
        "tool      ::= %s\n\n" % " | ".join(q(t) for t in names)
        + BASE_RULES
    )

    for fn, text in (("tool_call.gbnf", precise), ("tool_call_loose.gbnf", loose)):
        io.open(os.path.join(a.out, fn), "w", encoding="utf-8", newline="\n").write(text)
    io.open(os.path.join(a.out, "tools.txt"), "w", encoding="utf-8", newline="\n").write(
        "\n".join("%s \u2014 %s" % (n, tools[n]) for n in names) + "\n"
    )

    if a.js:
        js_dir = os.path.dirname(os.path.abspath(a.js))
        if js_dir and not os.path.isdir(js_dir):
            os.makedirs(js_dir, exist_ok=True)
        js_text = "export const LOOSE_TOOL_GRAMMAR = " + json.dumps(loose) + ";\n"
        io.open(a.js, "w", encoding="utf-8", newline="\n").write(js_text)

    print("tools: %d | total rules: %d" % (len(names), len(gen.rules) + 14))
    msgs = ["tool_call.gbnf", "tool_call_loose.gbnf", "tools.txt"]
    if a.js:
        msgs.append(os.path.basename(a.js))
    print("wrote " + ", ".join(msgs))


if __name__ == "__main__":
    main()
