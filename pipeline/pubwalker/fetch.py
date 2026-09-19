"""Step 1: resolve the anchor paper and list everything that cites it, from OpenAlex."""
import json
import re

from . import DATA
from .http import epmc, openalex

SELECT = "id,doi,ids,title,publication_year,publication_date,type,open_access,primary_location,topics"


def slugify(doi):
    return re.sub(r"[^a-z0-9]+", "-", doi.lower()).strip("-")


def short(openalex_url):
    return openalex_url.rsplit("/", 1)[-1] if openalex_url else None


def flatten(w):
    ids = w.get("ids") or {}
    loc = w.get("primary_location") or {}
    return {
        "id": short(w["id"]),
        "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower() or None,
        "pmid": short(ids.get("pmid")),
        "pmcid": short(ids.get("pmcid")),
        "title": w.get("title"),
        "year": w.get("publication_year"),
        "date": w.get("publication_date"),
        "type": w.get("type"),
        "venue": ((loc.get("source") or {}).get("display_name")),
        "is_oa": (w.get("open_access") or {}).get("is_oa"),
        "topics": [t["display_name"] for t in (w.get("topics") or [])[:2]],
    }


def resolve(doi):
    """Anchor record: OpenAlex fields plus PMID/PMCID from Europe PMC (OpenAlex often lacks the PMCID)."""
    w = flatten(openalex(f"/works/https://doi.org/{doi}", select=SELECT + ",cited_by_count"))
    w["cited_by_count"] = openalex(f"/works/https://doi.org/{doi}", select="cited_by_count")["cited_by_count"]
    hits = epmc("/search", query=f'DOI:"{doi}"', format="json", resultType="lite")["resultList"]["result"]
    med = next((h for h in hits if h.get("source") == "MED"), hits[0] if hits else {})
    w["pmid"] = w["pmid"] or med.get("pmid")
    w["pmcid"] = w["pmcid"] or med.get("pmcid")
    return w


def citers(work_id):
    out, cursor = [], "*"
    while cursor:
        page = openalex("/works", filter=f"cites:{work_id}", select=SELECT, **{"per-page": 200, "cursor": cursor})
        out += [flatten(w) for w in page["results"]]
        cursor = page["meta"].get("next_cursor")
    return out


def run(doi):
    anchor = resolve(doi)
    d = DATA / slugify(doi)
    d.mkdir(parents=True, exist_ok=True)
    (d / "anchor.json").write_text(json.dumps(anchor, indent=1))
    cs = citers(anchor["id"])
    (d / "citers.json").write_text(json.dumps(cs, indent=1))
    print(f"{anchor['title']!r}: {len(cs)} citing works (OpenAlex says {anchor['cited_by_count']}) -> {d}")
    return anchor, cs
