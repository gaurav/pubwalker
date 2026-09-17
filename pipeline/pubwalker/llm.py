"""Every LLM call goes through `claude -p` (Claude Code login, no API key) and is cached by
sha256(model, system, prompt, schema) under data/cache/llm/, so prompt iteration only re-bills
what changed. `--system-prompt` replaces Claude Code's large default prompt; `--tools ""` makes
it a pure completion; `--json-schema` gives structured output."""
import hashlib
import json
import subprocess
import sys

from . import DATA
from .fetch import slugify

CACHE = DATA / "cache" / "llm"
SPENT = []  # what this process spent, counting cached calls at their original price so a re-run still tallies


def ask(prompt, *, model, system, schema=None):
    key = hashlib.sha256(json.dumps([model, system, prompt, schema], sort_keys=True).encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        SPENT.append(cached.get("cost_usd") or 0)
        return cached["output"]
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
        raise RuntimeError(f"claude -p error ({d.get('subtype')}): {d.get('result') or d.get('errors') or json.dumps(d)[:600]}")
    out = d.get("structured_output") if schema else d.get("result")
    if schema and out is None:  # older claude: structured answer only in `result`
        try:
            out = json.loads(d["result"])
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(f"claude -p returned no structured output ({d.get('subtype')}): {str(d.get('result'))[:300]!r}")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "cost_usd": d.get("total_cost_usd"), "output": out}))
    SPENT.append(d.get("total_cost_usd") or 0)
    print(f"  [{model}] ${d.get('total_cost_usd', 0):.4f}", file=sys.stderr)
    return out


def record(doi, step):
    """Bank what this step spent in data/<slug>/cost.json, one entry per step so a re-run overwrites its own
    entry rather than double-counting. The whole-cache total would be misleading: it also holds papers that
    were dropped from the site and every prompt iteration thrown away along the way."""
    if not SPENT:
        return
    path = DATA / slugify(doi) / "cost.json"
    costs = json.loads(path.read_text()) if path.exists() else {}
    costs[step] = round(sum(SPENT), 4)
    path.write_text(json.dumps(costs, indent=1))
    SPENT.clear()


def cost(doi):
    path = DATA / slugify(doi) / "cost.json"
    return round(sum(json.loads(path.read_text()).values()), 4) if path.exists() else None
