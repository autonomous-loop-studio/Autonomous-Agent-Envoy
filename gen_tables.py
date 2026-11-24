"""Generate per-tool GBNF grammars for ALS-Cyber-Qwen's bare-JSON tool protocol.

Reads the real arg shapes out of tool-usage-train.jsonl and emits:

  tool_call.gbnf        precise: one rule per tool, arg object keys/types inferred
  tool_call_loose.gbnf  fallback: any valid JSON arg (old behaviour)

  python gen_tables.py [outdir]
"""
import io
import json
import os
import sys

DATA = r"C:/Users/anonb/Desktop/datasets/tool-usage-train.jsonl"
OUT = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/anonb/Desktop/ALS-Cyber-Qwen/agent"

NOARG = object()

rows = [json.loads(l) for l in open(DATA, encoding="utf-8") if l.strip()]

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

names = sorted(tools)
if not names:
    raise SystemExit("no tool names in %s" % DATA)
os.makedirs(OUT, exist_ok=True)


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


class Gen:
    def __init__(self):
        self.rules = []          # list of (name, body)
        self.counter = 0

    def new(self, base):
        self.counter += 1
        return "%s_%d" % (base, self.counter)

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
            elem_alts = []
            if elems:
                elem_alts.append(self.value(elems, name + "_el"))
            else:
                elem_alts.append("value")
            self.rules.append(
                (name, '"[" ws (%s (ws "," ws %s)*)? ws "]"' % (elem_alts[0], elem_alts[0]))
            )
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
                    member = '"\\"%s\\":" ws %s' % (k.replace('"', '\\"'), self.value(sub, name + "_" + k))
                    if i == 0:
                        parts.append(member)
                    else:
                        parts.append('(ws "," ws %s)?' % member)
                self.rules.append((name, '"{" ws ' + " ".join(parts) + ' ws "}"'))
            alts.append(name)
        if not alts:
            alts = ["value"]
        if len(alts) == 1:
            return alts[0]
        name = self.new(base + "_alt")
        self.rules.append((name, " |\n    ".join(alts)))
        return name


def q(name):
    return '"\\"' + name.replace("\\", "\\\\").replace('"', '\\"') + '\\""'


gen = Gen()
tool_alts = []
for t in names:
    obs = shapes[t]
    tool_rule = gen.new("t_" + t.replace("-", "_"))
    has_arg = any(v is not NOARG for v in obs)
    arg_obs = [v for v in obs if v is not NOARG]
    if not has_arg:
        gen.rules.append((tool_rule, '"{\\"tool\\":" ws %s ws "}"' % q(t)))
    else:
        arg_rule = gen.value(arg_obs, "a_" + t.replace("-", "_"))
        opt = ' (%s ws "\\"arg\\":" ws %s)?' % ("ws \",\"", arg_rule)
        gen.rules.append((tool_rule, '"{\\"tool\\":" ws %s%s ws "}"' % (q(t), opt)))
    tool_alts.append(tool_rule)

PRELUDE = """# Per-tool GBNF for ALS-Cyber-Qwen. Generated from tool-usage-train.jsonl by gen_tables.py.
# Each tool gets its own rule with the argument keys and value types seen in training.
root      ::= %s
"""

base_rules = """value     ::= string | number | object | array | boolean | "null"
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
ws        ::= [ \\t\\n]*
"""

precise = PRELUDE % " |\n    ".join(tool_alts) + base_rules
for name, body in gen.rules:
    precise += "%-24s ::= %s\n" % (name, body)

loose = """# Loose fallback: any valid JSON arg. Generated by gen_tables.py.
root      ::= "{\\"tool\\":" ws tool (ws "," ws "\\"arg\\":" ws value)? ws "}"
tool      ::= %s
""" % " |\n    ".join(q(t) for t in names) + base_rules

io.open(os.path.join(OUT, "tool_call.gbnf"), "w", encoding="utf-8", newline="\n").write(precise)
io.open(os.path.join(OUT, "tool_call_loose.gbnf"), "w", encoding="utf-8", newline="\n").write(loose)
io.open(os.path.join(OUT, "tools.txt"), "w", encoding="utf-8", newline="\n").write(
    "\n".join("%s \u2014 %s" % (n, tools[n]) for n in names) + "\n"
)

print("tools:", len(names), "| per-tool rules:", len(tool_alts), "| total rules:", len(gen.rules))
print("precise grammar bytes:", len(precise), "| loose:", len(loose))
for t in ("now", "exec", "glob_files", "read_file", "todo_write"):
    for name, body in gen.rules:
        if name == "t_" + t:
            print("%-14s %s" % (t, body.replace("\n", " ")[:150]))
            break
