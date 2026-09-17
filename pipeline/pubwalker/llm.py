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
SPENT = []  # (model, usd) per call this process made, counting cached calls at their original price so a re-run still tallies


def ask(prompt, *, model, system, schema=None):
    key = hashlib.sha256(json.dumps([model, system, prompt, schema], sort_keys=True).encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        SPENT.append((model, cached.get("cost_usd") or 0))  # the model is part of the cache key, so the argument is the record's model
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
    SPENT.append((model, d.get("total_cost_usd") or 0))
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
    by = {}
    for model, usd in SPENT:
        by[model] = by.get(model, 0) + usd
    costs[step] = {m: round(v, 4) for m, v in by.items()}  # rounded once at the end, so a single-model step matches the old scalar exactly
    path.write_text(json.dumps(costs, indent=1))
    SPENT.clear()


def _steps(doi):
    path = DATA / slugify(doi) / "cost.json"
    return list(json.loads(path.read_text()).values()) if path.exists() else None


def cost(doi):
    """Total dollars banked for a paper. Tolerates the flat {step: dollars} shape written before costs were
    split by model: `record` migrates one step at a time, so a half-migrated file is the ordinary state of
    the tool mid-run, not a stale-checkout edge case."""
    steps = _steps(doi)
    return round(sum(sum(s.values()) if isinstance(s, dict) else s for s in steps), 4) if steps is not None else None


def per_model(doi):
    """{model: dollars}, biggest first, or None if any step predates the split. A partial split would not add
    up to the total shown beside it, which is worse than showing no split at all."""
    steps = _steps(doi)
    if not steps or not all(isinstance(s, dict) for s in steps):
        return None
    by = {}
    for s in steps:
        for m, usd in s.items():
            by[m] = by.get(m, 0) + usd
    return {m: round(v, 4) for m, v in sorted(by.items(), key=lambda kv: -kv[1])}
