"""Every LLM call goes through `claude -p` (Claude Code login, no API key) and is cached by
sha256(model, system, prompt, schema) under data/cache/llm/, so prompt iteration only re-bills
what changed. `--system-prompt` replaces Claude Code's large default prompt; `--tools ""` makes
it a pure completion; `--json-schema` gives structured output."""
import hashlib
import json
import subprocess
import sys

from . import DATA

CACHE = DATA / "cache" / "llm"


def ask(prompt, *, model, system, schema=None):
    key = hashlib.sha256(json.dumps([model, system, prompt, schema], sort_keys=True).encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())["output"]
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--system-prompt", system,
           "--no-session-persistence", "--tools", ""]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p failed: {r.stderr[-500:] or r.stdout[-500:]}")
    if d.get("is_error"):
        raise RuntimeError(d.get("result"))
    out = d.get("structured_output") if schema else d.get("result")
    if schema and out is None:  # older claude: structured answer only in `result`
        out = json.loads(d["result"])
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "cost_usd": d.get("total_cost_usd"), "output": out}))
    print(f"  [{model}] ${d.get('total_cost_usd', 0):.4f}", file=sys.stderr)
    return out


def total_cost():
    return round(sum(json.loads(p.read_text()).get("cost_usd") or 0 for p in CACHE.glob("*.json")), 4) if CACHE.exists() else 0
