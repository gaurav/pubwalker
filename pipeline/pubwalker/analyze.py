"""Steps 3-6: classify each sampled passage (Haiku), synthesise per window and overall (Opus),
extract the anchor's argument structure from its full text (Opus), and compare the two."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from . import DATA
from .fetch import flatten, slugify
from .http import openalex
from .llm import ask
from .passages import jats, paragraphs_citing, text

ROLES = ["uses-tool-or-method", "uses-data", "background-claim", "compares-against",
         "extends-or-modifies", "critiques-or-contradicts", "incidental"]

ROLE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["role", "what_for", "combined_with", "stance", "evidence_quote", "confidence"],
    "properties": {
        "role": {"type": "string", "enum": ROLES},
        "what_for": {"type": "string", "description": "One sentence: what the citing paper does with the cited paper."},
        "combined_with": {"type": "array", "items": {"type": "string"}, "description": "Other tools, methods or datasets named in the passage."},
        "stance": {"type": "string", "enum": ["positive", "neutral", "critical"]},
        "evidence_quote": {"type": "string", "description": "Verbatim span from the passage the label rests on."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}
ROLE_DEFS = """Roles: uses-tool-or-method (runs the cited software or applies its method); uses-data (reanalyses its data);
background-claim (cites it for a fact or finding); compares-against (benchmarks or contrasts with it);
extends-or-modifies (builds a new method or result on it); critiques-or-contradicts (disputes it or reports a limitation);
incidental (appears in a list of alternatives, a review table, or a history). Label only what the passage supports.
The section a passage comes from is a strong hint: Methods usually means use, Introduction usually means background."""
ROLE_SYSTEM = "You classify how a citing paper uses a cited paper, from the passage(s) where the citation appears.\n" + ROLE_DEFS
# Same roles from the other side: what the anchor paper uses each of its own references for.
OUT_ROLE_SYSTEM = "You classify what a paper uses one of its own references for, from the passage(s) where it cites that reference.\n" + ROLE_DEFS

CLAIMS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["claims", "follow_ups"],
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["text", "cites", "highlight"],
                   "properties": {"text": {"type": "string", "description": "One or two sentences, with the 2-6 words that carry the point wrapped in **double asterisks**."},
                                  "cites": {"type": "array", "items": {"type": "string"}, "description": "Ids of the citing papers that support this claim."},
                                  "highlight": {"type": "boolean", "description": "True for the 1-3 claims a reader should see first."}}}},
        "follow_ups": {"type": "array", "items": {"type": "string"}, "description": "3 to 5 follow-up questions a reader could pursue next."},
    },
}
SYNTH_SYSTEM = """You write short, grounded syntheses of how a paper is used by the papers that cite it.
Every claim must be supported by the listed citing papers and cite them by id. Say what the evidence shows, including
disagreement and complaints. Cover: the dominant use; the workflows and other tools it appears alongside; stance and
complaints; anything unexpected. Write 5 to 8 claims of one or two sentences each, wrapping the 2 to 6 words that carry each
claim's point in **double asterisks** and marking the 1 to 3 most important claims highlight=true, then 3 to 5 follow-up questions."""

STRUCT_KINDS = ["fact", "method", "finding", "claim", "gap"]
STRUCT_ITEM_PROPS = {
    "text": {"type": "string", "description": "One sentence, with the 2-6 words that carry its point wrapped in **double asterisks**."},
    "kind": {"type": "string", "enum": STRUCT_KINDS, "description": "fact: established knowledge taken as given; method: how something was done; finding: observed or measured in this work; claim: the authors' interpretation, argument or proposal; gap: a caveat or something not addressed."},
    "highlight": {"type": "boolean", "description": "True for the 1-3 items in this field a reader should see first."},
    "evidence": {"type": "string", "description": "Verbatim span from the paper, or 'not stated'."},
    "section": {"type": "string", "description": "The paper's own section heading the evidence sits under (as given after ## in the text), 'abstract' if only the abstract was available, or '' if not stated."},
}
STRUCT_ITEM = {"type": "object", "additionalProperties": False, "required": [*STRUCT_ITEM_PROPS], "properties": STRUCT_ITEM_PROPS}
STRUCT_SOURCED = {"type": "object", "additionalProperties": False, "required": [*STRUCT_ITEM_PROPS, "sources"],
                  "properties": {**STRUCT_ITEM_PROPS, "sources": {"type": "array", "items": {"type": "string"}, "description": "Reference ids like B12 that the paper attributes this to; empty if unsourced."}}}
STRUCT_CONCLUSION = {"type": "object", "additionalProperties": False, "required": [*STRUCT_ITEM_PROPS, "based_on"],
                     "properties": {**STRUCT_ITEM_PROPS, "based_on": {"type": "array", "items": {"type": "string"}, "description": "The results this conclusion rests on, as R1, R2, ... numbering the results field from 1."}}}
STRUCT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["question", "assumptions", "design", "data", "analysis", "results", "conclusions", "implications", "limitations"],
    "properties": {
        "question": {"type": "string"},
        "assumptions": {"type": "array", "items": STRUCT_SOURCED},
        "conclusions": {"type": "array", "items": STRUCT_CONCLUSION},
        **{k: {"type": "array", "items": STRUCT_ITEM} for k in ["design", "data", "analysis", "results", "implications", "limitations"]},
    },
}
STRUCT_SYSTEM = """You extract the structure of a scientific paper's argument. Fill each field only from the text:
question (what it sets out to answer); assumptions (premises it relies on, with the reference ids it attributes them to,
or empty sources if asserted without citation); design (study type, arms or comparison groups, what is manipulated and
measured); data (what was collected or reused, with identifiers); analysis (methods, software, tests); results (as
stated, tied to the design they come from); conclusions (what the authors say the results show, each listing the
results it rests on as R1, R2, ... in the order you give them); implications (what follows for the field if the
conclusions hold, and proposed next steps); limitations (stated caveats, plus anything important the paper does not
address, marked as such). Every item is one sentence with its key 2 to 6 words wrapped in **double asterisks**, plus a
verbatim evidence span, the paper's section heading that span sits under, a kind, and highlight=true for the 1 to 3
items per field a reader should see first. The fields above are the argument's parts; the section is where the paper
puts them, and they need not agree (a result stated in the Discussion still goes under results). The kind
is independent of the field: an assumption asserted without citation is a claim, not a fact; a result that interprets
rather than reports is a claim; a limitation the authors state is a finding or fact, one they do not address is a gap.
Use 'not stated' rather than inventing. Be concise: 3 to 10 items per field."""

COMPARE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["points"],
    "properties": {"points": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["kind", "text"],
                   "properties": {"kind": {"type": "string", "enum": ["cited-as-claimed", "cited-for-something-else", "claimed-but-not-cited"]}, "text": {"type": "string"}}}}},
}
COMPARE_SYSTEM = """You compare what a paper claims with what the literature cites it for. Given the paper's own
conclusions and results and a summary of how citing papers use it, write 3 to 7 points, each tagged: cited-as-claimed
(citers use it for something it set out to show), cited-for-something-else (citers use a method, tool, figure or side
result the paper did not present as its point), claimed-but-not-cited (a conclusion the citers ignore). Be specific."""


def load(doi, name):
    return json.loads((DATA / slugify(doi) / f"{name}.json").read_text())


def save(doi, name, obj):
    (DATA / slugify(doi) / f"{name}.json").write_text(json.dumps(obj, indent=1))


def cite(c):
    return f"{c.get('title')} ({c.get('year')}, {c.get('venue') or c.get('type')})"


def roles(doi, workers=4):
    anchor, citers, P = load(doi, "anchor"), {c["id"]: c for c in load(doi, "citers")}, load(doi, "passages")
    done = load(doi, "roles") if (DATA / slugify(doi) / "roles.json").exists() else {}

    def one(cid):
        c, ps = citers[cid], P["passages"][cid]["passages"]
        body = "\n\n".join(f"[{p['source']}{', section: ' + p['section'] if p['section'] else ''}]\n{p['text'][:3000]}" for p in ps[:4])
        prompt = f"Cited paper: {anchor['title']} ({anchor['year']}).\nCiting paper: {cite(c)}.\n\nPassages:\n{body}"
        try:
            return cid, ask(prompt, model="haiku", system=ROLE_SYSTEM, schema=ROLE_SCHEMA)
        except RuntimeError as e:  # one bad passage must not sink the run; it is simply left unclassified
            if "limit" in str(e).lower():  # but a usage or rate limit would leave every passage unclassified: stop and retry later
                raise
            print(f"  {cid}: {e}")
            return cid, None

    todo = [cid for cid in P["passages"] if cid not in done]
    with ThreadPoolExecutor(workers) as ex:
        for cid, out in ex.map(one, todo):
            if out:
                done[cid] = out
    save(doi, "roles", done)
    hist = {}
    for r in done.values():
        hist[r["role"]] = hist.get(r["role"], 0) + 1
    print(f"{len(done)} passages classified: {hist}")
    return done


def histogram(ids, R):
    h = {r: 0 for r in ROLES}
    for i in ids:
        if i in R:
            h[R[i]["role"]] += 1
    return h


def listing(ids, citers, R):
    lines = []
    for i in ids:
        if i in R:
            r, c = R[i], citers[i]
            lines.append(f"[{i}] {cite(c)} | role={r['role']} | stance={r['stance']} | {r['what_for']} | with: {', '.join(r['combined_with']) or '-'} | quote: \"{r['evidence_quote'][:300]}\"")
    return "\n".join(lines)


def key_phrase(text):
    """Keep the **key phrase** markup only when there is exactly one pair."""
    return text if text.count("**") == 2 else text.replace("**", "")


def grounded(out, allowed):
    for cl in out["claims"]:
        cl["cites"] = [x.strip("[]") for x in cl["cites"] if x.strip("[]") in allowed]
        cl["text"] = key_phrase(cl["text"])
    return out


def synth(doi):
    anchor, citers, P, R = load(doi, "anchor"), {c["id"]: c for c in load(doi, "citers")}, load(doi, "passages"), load(doi, "roles")
    out = {}
    for name, w in P["windows"].items():
        ids = w["sampled"]
        prompt = (f"Cited paper: {anchor['title']} ({anchor['year']}, {anchor.get('venue')}).\nWindow: {name}: {w['total']} citing works, "
                  f"{w['with_passages']} with a retrievable passage, {len(ids)} sampled and classified.\nRole counts: {histogram(ids, R)}\n\n"
                  f"Classified citing papers:\n{listing(ids, citers, R)}")
        out[name] = grounded(ask(prompt, model="opus", system=SYNTH_SYSTEM, schema=CLAIMS_SCHEMA), set(ids))
        print(f"{name}: {len(out[name]['claims'])} claims")
    summary = "\n\n".join(f"## {name} ({P['windows'][name]['total']} citers; roles {histogram(P['windows'][name]['sampled'], R)})\n" +
                          "\n".join(f"- {c['text']} {c['cites']}" for c in s["claims"]) for name, s in out.items())
    prompt = (f"Cited paper: {anchor['title']} ({anchor['year']}).\nBelow are per-window syntheses with the citing-paper ids behind each claim. "
              f"Write an overall account: what the paper is used for, how that changed over time, and what a maintainer or reader should take away. "
              f"Reuse the ids as cites.\n\n{summary}")
    out["overall"] = grounded(ask(prompt, model="opus", system=SYNTH_SYSTEM, schema=CLAIMS_SCHEMA), set(R))
    save(doi, "synthesis", out)
    return out


def fulltext(root):
    """Body text with section headings and [rid] markers for bibliographic xrefs, plus the reference list."""
    def walk(el):
        if el.tag == "xref" and el.get("ref-type") == "bibr":
            return f"[{el.get('rid')}]" + (el.tail or "")
        s = el.text or ""
        for ch in el:
            s += walk(ch)
        return s + (el.tail or "")
    parts = []
    body = root.find(".//body")
    for sec in (body.iter("sec") if body is not None else []):
        t = sec.find("title")
        if t is not None:
            parts.append(f"\n## {text(t)}\n")
        for p in sec.findall("p"):
            parts.append(" ".join(walk(p).split()))
    refs = {r.get("id"): text(r) for r in root.iter("ref")}
    return "\n".join(parts), refs


def references(root):
    """The paper's own reference list: each <ref> with its ids and every paragraph that cites it."""
    parent = {c: p for p in root.iter() for c in p}
    out = []
    for r in root.iter("ref"):
        pub = {p.get("pub-id-type"): text(p) for p in r.iter("pub-id")}
        t, y = r.find(".//article-title"), r.find(".//year")
        m = re.search(r"\b(19|20)\d{2}\b", text(y) if y is not None else text(r))  # mixed-citation refs often have no <year>
        out.append({"id": r.get("id"), "text": text(r), "title": text(t) if t is not None else None, "year": int(m.group()) if m else None,
                    "doi": (pub.get("doi") or "").lower() or None, "pmid": pub.get("pmid"), "mentions": paragraphs_citing(root, r.get("id"), parent)})
    return out


def enrich(refs):
    """OpenAlex id, citation count and OA flag for references with a DOI or PMID, 50 per request. Fills a missing year."""
    for key in ("doi", "pmid"):
        todo = [r for r in refs if r.get(key) and not r.get("openalex_id")]
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            page = openalex("/works", filter=f"{key}:" + "|".join(r[key] for r in chunk), select="id,doi,ids,cited_by_count,publication_year,open_access", **{"per-page": 50})
            found = {}
            for w in page["results"]:
                f = flatten(w)
                found[f["doi"]] = found[f["pmid"]] = {"openalex_id": f["id"], "cited_by_count": w.get("cited_by_count"), "is_oa": f["is_oa"], "year": f["year"]}
            for r in chunk:
                if hit := found.get(r[key]):
                    r.update({**hit, "year": r["year"] or hit["year"]})
    return refs


def outgoing(doi, workers=4):
    anchor = load(doi, "anchor")
    if not anchor.get("pmcid"):
        print("no full text, so no outgoing citations")
        return None
    refs = enrich(references(jats(anchor["pmcid"])))
    prev = load(doi, "outgoing")["references"] if (DATA / slugify(doi) / "outgoing.json").exists() else []
    done = {r["id"]: r["role"] for r in prev if r.get("role")}

    def one(r):
        body = "\n\n".join(f"[section: {m['section'] or 'not stated'}]\n{m['text'][:3000]}" for m in r["mentions"][:4])
        prompt = f"Paper: {anchor['title']} ({anchor['year']}).\nReference [{r['id']}]: {r['text'][:600]}\n\nPassages citing it:\n{body}"
        try:
            return r["id"], ask(prompt, model="haiku", system=OUT_ROLE_SYSTEM, schema=ROLE_SCHEMA)
        except RuntimeError as e:
            if "limit" in str(e).lower():
                raise
            print(f"  {r['id']}: {e}")
            return r["id"], None

    todo = [r for r in refs if r["mentions"] and r["id"] not in done]  # a reference never cited in a paragraph (figure-only, say) is left unclassified
    with ThreadPoolExecutor(workers) as ex:
        for rid, out in ex.map(one, todo):
            if out:
                done[rid] = out
    for r in refs:
        r["role"] = done.get(r["id"])
    hist = {role: sum(1 for r in refs if r["role"] and r["role"]["role"] == role) for role in ROLES}
    save(doi, "outgoing", {"references": refs, "roles": hist})
    print(f"{len(refs)} references, {sum(1 for r in refs if r['mentions'])} cited in the text, {len(done)} classified: {hist}")
    return refs


def abstract(work_id):
    inv = openalex(f"/works/{work_id}", select="abstract_inverted_index").get("abstract_inverted_index") or {}
    words = sorted((pos, w) for w, ps in inv.items() for pos in ps)
    return " ".join(w for _, w in words)


def tidy_structure(out):
    """Keep the **key phrase** markup only when there is exactly one pair, and only `based_on` ids that name a real result."""
    fields = ["assumptions", "design", "data", "analysis", "results", "conclusions", "implications", "limitations"]
    for it in (it for k in fields for it in out[k]):
        it["text"] = key_phrase(it["text"])
    ok = {f"R{i}" for i in range(1, len(out["results"]) + 1)}
    for c in out["conclusions"]:
        c["based_on"] = [r for r in (s.strip("[] ").upper() for s in c.get("based_on", [])) if r in ok]
    return out


def structure(doi):
    anchor = load(doi, "anchor")
    refs = {}
    if anchor.get("pmcid"):
        body, refs = fulltext(jats(anchor["pmcid"]))
        source, reflist = "pmc-full-text", "\n".join(f"[{k}] {v}" for k, v in refs.items())
        prompt = f"Paper: {anchor['title']} ({anchor['year']}).\n\n{body[:90000]}\n\n## References\n{reflist[:30000]}"
    else:
        abs_text = abstract(anchor["id"])
        source, prompt = "abstract-only", f"Paper: {anchor['title']} ({anchor['year']}).\nOnly the abstract is available:\n\n{abs_text}"
    out = ask(prompt, model="opus", system=STRUCT_SYSTEM, schema=STRUCT_SCHEMA)
    out["source"] = source
    if source == "abstract-only":
        out["abstract"] = abs_text  # shown on the site so a reader can see everything the model saw
    for a in out["assumptions"]:
        a["sources"] = [s.strip("[]") for s in a["sources"]]
    out["references"] = {k: refs[k] for k in sorted({s for a in out["assumptions"] for s in a["sources"]} & set(refs))}
    tidy_structure(out)
    save(doi, "structure", out)
    print(f"structure from {source}: {len(out['assumptions'])} assumptions, {len(out['conclusions'])} conclusions")
    return out


def compare(doi):
    anchor, S, R, P = load(doi, "anchor"), load(doi, "structure"), load(doi, "roles"), load(doi, "passages")
    ids = P["windows"]["all-time"]["sampled"]
    uses = sorted({R[i]["what_for"] for i in ids if i in R})
    prompt = (f"Paper: {anchor['title']} ({anchor['year']}).\nQuestion: {S['question']}\nResults: " + "; ".join(r["text"] for r in S["results"]) +
              "\nConclusions: " + "; ".join(c["text"] for c in S["conclusions"]) +
              f"\n\nHow {len(ids)} sampled citing papers (all time) use it. Role counts: {histogram(ids, R)}\nUses:\n- " + "\n- ".join(uses))
    out = ask(prompt, model="opus", system=COMPARE_SYSTEM, schema=COMPARE_SCHEMA)
    save(doi, "comparison", out)
    print(f"comparison: {len(out['points'])} points")
    return out
