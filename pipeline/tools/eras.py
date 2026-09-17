"""Sample citation roles by fixed era instead of by rolling window. A spike for #10.

The pipeline's three windows are nested -- last-12-months is inside last-5-years is inside
all-time -- and each is sampled across its whole span, so comparing them cannot answer "has
the way this paper is cited changed since it was published". This samples a fixed number of
citers per era and classifies them with the same Haiku prompt `pubwalker roles` uses, which
is enough to see a trend without changing the pipeline's schema.

    cd pipeline && uv run python tools/eras.py <doi> [--n 45] [--eras 2007-2011,2012-2016,...]

Needs `pubwalker fetch` to have run for the doi. Everything else comes from the HTTP and LLM
caches, so a re-run is free. Results are printed and written to data/<slug>/eras.json.

This is deliberately not a pipeline step: it does not write to the site, and the era bounds
are a judgement call per paper. Folding it in properly is #10.
"""
import argparse
import collections
import json
import math
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import httpx

from pubwalker import DATA
from pubwalker.analyze import ROLE_SCHEMA, ROLE_SYSTEM, cite
from pubwalker.fetch import slugify
from pubwalker.llm import ask
from pubwalker.passages import citing_paragraphs, epmc_oa_citers, jats, s2_contexts
import random

DEFAULT_ERAS = "2007-2011,2012-2016,2017-2021,2022-2026"


def fisher(a, b, c, d):
    """Two-tailed Fisher exact p for [[a,b],[c,d]]. Counts here are small enough that a chi-square
    would be the wrong test and scipy is not a dependency."""
    f = math.factorial

    def p(a, b, c, d):
        return f(a + b) * f(c + d) * f(a + c) * f(b + d) / (f(a) * f(b) * f(c) * f(d) * f(a + b + c + d))

    obs, total = p(a, b, c, d), 0.0
    for i in range(min(a + b, a + c) + 1):
        j, k, l = a + b - i, a + c - i, d - a + i
        if j >= 0 and k >= 0 and l >= 0 and p(i, j, k, l) <= obs * (1 + 1e-9):
            total += p(i, j, k, l)
    return total


def passages_for(c, anchor, cached):
    if c["id"] in cached:
        return cached[c["id"]]["passages"]
    ps = []
    if c["epmc_pmcid"]:
        try:
            ps = citing_paragraphs(jats(c["epmc_pmcid"]), anchor)
        except (httpx.HTTPError, ET.ParseError) as e:
            print(f"  {c['epmc_pmcid']}: {e}")
    return ps + [{"source": "s2", "section": None, "text": t} for t in c["s2"].get("contexts", [])]


def run(doi, n, eras, seed=1, workers=4, names=None):
    d = DATA / slugify(doi)
    anchor = json.loads((d / "anchor.json").read_text())
    citers = json.loads((d / "citers.json").read_text())
    ctx = s2_contexts(doi)
    oa = epmc_oa_citers(anchor["pmid"]) if anchor.get("pmid") else {}
    for c in citers:
        c["s2"] = ctx.get(c["doi"] or "") or ctx.get(c["pmid"] or "") or {}
        c["epmc_pmcid"] = oa.get(c["doi"] or "") or oa.get(c["pmid"] or "") or (c["pmcid"] if c.get("is_oa") else None)
    # Passages already fetched for the rolling windows are reused rather than re-fetched.
    cached = json.loads((d / "passages.json").read_text())["passages"] if (d / "passages.json").exists() else {}

    samples = {}
    for name, (lo, hi) in eras.items():
        members = [c for c in citers if c.get("year") and lo <= c["year"] <= hi]
        cands = [c for c in members if c["s2"].get("contexts") or c["epmc_pmcid"]]
        samples[name] = random.Random(seed).sample(cands, min(n, len(cands)))
        print(f"{name}: {len(members)} citers, {len(cands)} with a passage source, {len(samples[name])} sampled")

    def one(c):
        ps = passages_for(c, anchor, cached)
        if not ps:
            return c["id"], None
        body = "\n\n".join(f"[{p['source']}{', section: ' + p['section'] if p['section'] else ''}]\n{p['text'][:3000]}" for p in ps[:4])
        prompt = f"Cited paper: {anchor['title']} ({anchor['year']}).\nCiting paper: {cite(c)}.\n\nPassages:\n{body}"
        try:
            return c["id"], ask(prompt, model="haiku", system=ROLE_SYSTEM, schema=ROLE_SCHEMA)
        except RuntimeError as e:
            if "limit" in str(e).lower():  # a usage limit would leave every era unclassified
                raise
            print(f"  {c['id']}: {e}")
            return c["id"], None

    out = {}
    for name, sample in samples.items():
        with ThreadPoolExecutor(workers) as ex:
            out[name] = {cid: r for cid, r in ex.map(one, sample) if r}
    (d / "eras.json").write_text(json.dumps(out, indent=1))

    print("\n== roles by era ==")
    for name, v in out.items():
        h = collections.Counter(r["role"] for r in v.values())
        print(f"{name} n={len(v):3d}  " + "  ".join(f"{k}={h[k]} ({100 * h[k] / len(v):.0f}%)" for k in sorted(h, key=lambda k: -h[k])))
    print("\n== stance by era ==")
    for name, v in out.items():
        print(f"{name} n={len(v):3d}  {dict(collections.Counter(r['stance'] for r in v.values()))}")

    if names:
        pat = re.compile(names, re.I)
        # The role label alone undercounts reuse of one named thing; search what the classifier wrote too.
        named = {name: [bool(pat.search(r["what_for"] + " " + " ".join(r["combined_with"]) + " " + r["evidence_quote"]))
                        for r in v.values()] for name, v in out.items()}
        print(f"\n== passages naming /{names}/ ==")
        for name, hits in named.items():
            print(f"{name} n={len(hits):3d}  {sum(hits)} ({100 * sum(hits) / len(hits):.0f}%)")

    # First era against the rest, which is the comparison a "has this changed" question wants.
    first, rest = list(out)[0], [r for name in list(out)[1:] for r in out[name].values()]
    print(f"\n== {first} vs the rest ==")
    for label, hit in [("uses-tool-or-method", lambda r: r["role"] == "uses-tool-or-method"),
                       ("background-claim", lambda r: r["role"] == "background-claim"),
                       ("critical stance", lambda r: r["stance"] == "critical")] + (
                      [(f"names /{names}/", lambda r: re.search(names, r["what_for"] + " " + " ".join(r["combined_with"]) + " " + r["evidence_quote"], re.I))]
                      if names else []):
        a = sum(1 for r in out[first].values() if hit(r))
        c = sum(1 for r in rest if hit(r))
        print(f"{label:22s} {a}/{len(out[first])} vs {c}/{len(rest)}  p={fisher(a, len(out[first]) - a, c, len(rest) - c):.4f}")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("doi")
    p.add_argument("--n", type=int, default=45, help="citers sampled per era")
    p.add_argument("--eras", default=DEFAULT_ERAS, help="comma-separated inclusive year ranges")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--names", help="regex for a specific reuse (a tool, a protocol); reported per era alongside the roles, "
                                   "because a citation to where a method came from often reads as background-claim and so "
                                   "does not show up in the role counts")
    a = p.parse_args()
    eras = {e: tuple(int(x) for x in e.split("-")) for e in a.eras.split(",")}
    run(a.doi, a.n, eras, seed=a.seed, names=a.names)


if __name__ == "__main__":
    main()
