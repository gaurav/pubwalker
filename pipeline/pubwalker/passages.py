"""Step 2: find the passage where each citer cites the anchor, then sample per time window.

Sources, in order of quality: Europe PMC full-text JATS (whole paragraph + section title; only
for the open-access subset) and Semantic Scholar citation contexts (one sentence, wider
coverage). Full text is fetched only for sampled citers to keep the run small."""
import datetime as dt
import json
import random
import xml.etree.ElementTree as ET

import httpx

from . import DATA
from .fetch import slugify
from .http import epmc, ncbi, s2

WINDOWS = {"last-12-months": 365, "last-5-years": 5 * 365 + 1, "all-time": None}


def s2_contexts(doi):
    """{doi|pmid -> {"contexts": [...], "intents": [...]}} for every citer Semantic Scholar knows."""
    out, offset = {}, 0
    while offset is not None:
        page = s2(f"/paper/DOI:{doi}/citations", fields="contexts,intents,isInfluential,externalIds", limit=1000, offset=offset)
        for c in page.get("data", []):
            ids = c["citingPaper"].get("externalIds") or {}
            rec = {"contexts": c.get("contexts") or [], "intents": c.get("intents") or []}
            if ids.get("DOI"):
                out[ids["DOI"].lower()] = rec
            if ids.get("PubMed"):
                out[ids["PubMed"]] = rec
        offset = page.get("next")
    return out


def epmc_oa_citers(pmid):
    """{doi|pmid -> pmcid} for open-access citers Europe PMC can serve full text for."""
    out, cursor = {}, "*"
    while cursor:
        page = epmc("/search", query=f"CITES:{pmid}_MED AND OPEN_ACCESS:y", format="json", pageSize=1000, cursorMark=cursor)
        for r in page["resultList"]["result"]:
            if r.get("pmcid"):
                if r.get("doi"):
                    out[r["doi"].lower()] = r["pmcid"]
                if r.get("pmid"):
                    out[r["pmid"]] = r["pmcid"]
        nxt = page.get("nextCursorMark")
        cursor = nxt if nxt and nxt != cursor and page["resultList"]["result"] else None
    return out


def jats(pmcid):
    """Full text as an ElementTree root. Europe PMC first; NCBI efetch for author manuscripts it 500s on."""
    try:
        xml = epmc(f"/{pmcid}/fullTextXML")
    except httpx.HTTPStatusError:
        xml = ncbi("efetch", db="pmc", id=pmcid.replace("PMC", ""))
    return ET.fromstring(xml)


def text(el):
    return " ".join("".join(el.itertext()).split())


def find_ref(root, anchor):
    for ref in root.iter("ref"):
        blob = ET.tostring(ref, encoding="unicode")
        if (anchor.get("doi") and anchor["doi"] in blob.lower()) or (anchor.get("pmid") and f">{anchor['pmid']}<" in blob):
            return ref.get("id")
        if anchor.get("title") and anchor["title"][:40].lower() in blob.lower():
            return ref.get("id")
    return None


def paragraphs_citing(root, rid, parent=None):
    """Every paragraph with an xref to reference `rid`, with its section path. Pass `parent` (child -> parent map) when
    calling for many rids on the same tree."""
    parent = parent or {c: p for p in root.iter() for c in p}
    out = []
    for p in root.iter("p"):
        if not any(x.get("rid") == rid for x in p.iter("xref")):
            continue
        titles, node = [], p
        while node in parent:
            node = parent[node]
            if node.tag == "sec" and (t := node.find("title")) is not None:
                titles.append(text(t))
        out.append({"section": " > ".join(reversed(titles)) or None, "text": text(p)})
    return out


def citing_paragraphs(root, anchor):
    rid = find_ref(root, anchor)
    return [{"source": "epmc", **p} for p in paragraphs_citing(root, rid)] if rid else []


def in_window(citer, days, today):
    if days is None:
        return True
    date = citer.get("date") or (f"{citer['year']}-01-01" if citer.get("year") else None)
    return bool(date) and dt.date.fromisoformat(date) >= today - dt.timedelta(days=days)


def run(doi, n=40, seed=1):
    d = DATA / slugify(doi)
    anchor = json.loads((d / "anchor.json").read_text())
    citers = json.loads((d / "citers.json").read_text())
    ctx = s2_contexts(doi)
    oa = epmc_oa_citers(anchor["pmid"]) if anchor.get("pmid") else {}
    for c in citers:
        c["s2"] = ctx.get(c["doi"] or "") or ctx.get(c["pmid"] or "") or {}
        c["epmc_pmcid"] = oa.get(c["doi"] or "") or oa.get(c["pmid"] or "") or (c["pmcid"] if c.get("is_oa") else None)
    today = dt.date.today()
    windows, passages, sampled_all = {}, {}, set()
    for name, days in WINDOWS.items():
        members = [c for c in citers if in_window(c, days, today)]
        cands = [c for c in members if c["s2"].get("contexts") or c["epmc_pmcid"]]
        sample = random.Random(seed).sample(cands, min(n, len(cands)))
        windows[name] = {"total": len(members), "with_passages": len(cands), "sampled": [c["id"] for c in sample]}
        sampled_all.update(c["id"] for c in sample)
    for c in citers:
        if c["id"] not in sampled_all:
            continue
        ps = []
        if c["epmc_pmcid"]:
            try:
                ps = citing_paragraphs(jats(c["epmc_pmcid"]), anchor)
            except (httpx.HTTPError, ET.ParseError) as e:
                print(f"  {c['epmc_pmcid']}: {e}")
        ps += [{"source": "s2", "section": None, "text": t} for t in c["s2"].get("contexts", [])]
        passages[c["id"]] = {"passages": ps, "s2_intents": c["s2"].get("intents", [])}
    # A sampled citer whose full text did not actually contain a matched reference and has no S2 context is dropped.
    empty = {k for k, v in passages.items() if not v["passages"]}
    for w in windows.values():
        w["sampled"] = [i for i in w["sampled"] if i not in empty]
    (d / "passages.json").write_text(json.dumps({"windows": windows, "passages": {k: v for k, v in passages.items() if k not in empty}}, indent=1))
    for name, w in windows.items():
        print(f"{name}: {w['total']} citers, {w['with_passages']} with a passage source, {len(w['sampled'])} sampled")
    print(f"S2 contexts for {sum(1 for c in citers if c['s2'].get('contexts'))} citers; Europe PMC OA full text for {sum(1 for c in citers if c['epmc_pmcid'])}; {len(empty)} sampled citers had no usable passage")
