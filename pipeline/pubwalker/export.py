"""Step 7: one JSON per paper for the static site, plus site/data/index.json."""
import datetime as dt
import json

from . import DATA, SITE_DATA
from .analyze import histogram, load
from .fetch import slugify
from .llm import by_step, cost, per_model


def run(doi):
    slug = slugify(doi)
    anchor, citers, P, R, S = load(doi, "anchor"), {c["id"]: c for c in load(doi, "citers")}, load(doi, "passages"), load(doi, "roles"), load(doi, "synthesis")
    struct = load(doi, "structure") if (DATA / slug / "structure.json").exists() else None
    comp = load(doi, "comparison") if (DATA / slug / "comparison.json").exists() else None
    outgoing = load(doi, "outgoing") if (DATA / slug / "outgoing.json").exists() else None
    keep = ["id", "doi", "pmid", "pmcid", "title", "year", "venue", "type"]
    years = {}
    for c in citers.values():
        if c.get("year") and c["year"] >= (anchor.get("year") or 0):  # OpenAlex dates the odd citer before the paper it cites
            years[c["year"]] = years.get(c["year"], 0) + 1
    out = {
        "slug": slug, "anchor": anchor, "generated": dt.date.today().isoformat(),
        "windows": {name: {**w, "roles": histogram(w["sampled"], R), "synthesis": S.get(name)} for name, w in P["windows"].items()},
        "overall": S.get("overall"),
        "citers": {i: {**{k: citers[i].get(k) for k in keep}, **P["passages"][i], "role": R.get(i)} for i in P["passages"]},
        "years": sorted(years.items()),
        "structure": struct, "comparison": comp, "outgoing": outgoing, "cost_usd": cost(doi), "cost_by_model": per_model(doi), "cost_by_step": by_step(doi),
    }
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / f"{slug}.json").write_text(json.dumps(out, indent=1))
    index_path = SITE_DATA / "index.json"
    index = {e["slug"]: e for e in json.loads(index_path.read_text())} if index_path.exists() else {}
    index[slug] = {"slug": slug, "doi": anchor["doi"], "title": anchor["title"], "year": anchor["year"], "venue": anchor.get("venue"),
                   "cited_by_count": anchor.get("cited_by_count"), "windows": {n: w["total"] for n, w in P["windows"].items()},
                   "generated": out["generated"], "cost_usd": out["cost_usd"],
                   # enough of each section for the home page to say what the report holds, without loading the report itself
                   "roles": out["windows"]["all-time"]["roles"], "source": (struct or {}).get("source"),
                   "outgoing": len(outgoing["references"]) if outgoing else None}
    index_path.write_text(json.dumps(sorted(index.values(), key=lambda e: e["year"] or 0), indent=1))
    print(f"wrote {SITE_DATA / (slug + '.json')} ({len(out['citers'])} citers with passages)")
