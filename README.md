# pubwalker

A sandbox for LLM-assisted ways of reading the PubMed / PubMed Central literature, prompted by
the [NIH SPARK PubMed/PMC Challenge](docs/spark-challenge.md) but aimed first at tools we would
actually use ourselves.

Two ideas, which are the same problem facing in opposite directions:

1. **[What role does a paper play in the literature?](docs/citation-role.md)** Find everything
   that cites it, pull out the passage where it is cited, have a cheap model say what each
   citation is *for* (a method being reused, a data set, a background claim, a comparison, a
   critique), and have a stronger model turn those into a report with quoted evidence, per
   time window. The motivating case is working out who still uses
   [SequenceMatrix](https://github.com/gaurav/taxondna/pull/128) fifteen years on, and in what
   workflows, to justify further work on it.

2. **[What is the structure of a paper's argument?](docs/argument-structure.md)** Extract the
   assumptions it rests on and where they came from, how the study was designed, what data
   was collected and how it was analysed, what was concluded, and what would follow if the
   conclusions hold. Then compare that with how the paper is actually cited: does the
   literature use it for what it claims?

`docs/tooling.md` surveys the data sources and tools we can lean on (OpenAlex, Semantic
Scholar, Europe PMC, pubmed2db, Claude Code in headless mode, and so on).

## Demo

`site/` is a static page (no build step) that shows precomputed reports for fourteen papers and a
keyless live look-up for any DOI. It deploys to GitHub Pages from `main`; locally:

```sh
cd pipeline && uv run serve   # http://localhost:8765/, reloads the browser when site/ changes
```

Without uv, `python3 -m http.server 8765 -d site` does the same minus the reloading.

A paper page is `/?doi=<doi>&tab=anatomy|outgoing|backscatter|comparison`; a DOI without a
precomputed report falls back to the live look-up. The tabs run from the paper outwards.
**Anatomy** is the paper taken apart: question and conclusions first, then assumptions, design,
data, analysis, results, implications and limitations, each statement typed and tied to the span
and section it was read from (schema in [docs/argument-structure.md](docs/argument-structure.md)).
**Outgoing** is its own reference list read with the citation roles: what it uses each reference
for, where in the paper, how old they are, and which ones carry the argument. **Backscatter** is
how the literature uses the paper (roles per citing passage, syntheses per time window with
linked evidence). **Claimed vs cited** sets the paper's claims against what it is cited for. `uv run screenshot out.png <doi> anatomy` renders a
page in headless Chromium for checking without a browser window, and `uv run clicktest [doi]`
clicks through every tab and fails on any page error.

`pipeline/` produces the reports. It needs [uv](https://docs.astral.sh/uv/) and a Claude Code
login (`claude` on your PATH); every LLM call goes through `claude -p` and is cached, as is
every HTTP response, under `data/`.

```sh
cd pipeline
uv run pubwalker all 10.1111/j.1096-0031.2010.00329.x     # fetch → passages → roles → synth → structure → compare → export
uv run pubwalker roles 10.1016/j.cell.2010.03.012 --n 40  # or one step at a time
```

Steps: `fetch` lists citers from OpenAlex; `passages` pulls the citing paragraph from Europe
PMC full text or the citing sentence from Semantic Scholar and samples 40 citers per time
window; `roles` labels each passage with Haiku; `synth` writes per-window and overall
syntheses with Opus, each claim tied to citer ids; `structure` extracts the anchor's argument
from its PMC full text (or abstract); `outgoing` classifies what the anchor uses each of its own
references for, with the same roles; `compare` sets claimed against cited; `export` writes
`site/data/<slug>.json`. A full run for one paper costs a few dollars: each step banks what it
spent in `data/<slug>/cost.json`, and the report page and the home page show the per-paper total
and the total over all reports.

To add a report, run `all` for the DOI and commit the new `site/data/` files; `export` merges it
into `index.json`. Anatomy and Outgoing need PMC full text with a body, which a PMCID alone does
not guarantee (some deposits are PDF-only; see the gotchas in `CLAUDE.md`), so check
`analyze.has_body(passages.jats(pmcid))` first. The fourteen demo papers were sampled from OpenAlex
(open access, in PMC, 100–2000 citations, 2008–2019) for variety of field and paper type.

## Setup

Copy `env.default` to `.env` and fill in whatever keys you have. Nothing here requires a
key: OpenAlex, Semantic Scholar and Europe PMC all work anonymously at lower rate limits,
and LLM calls go through `claude -p` using a Claude Code login rather than an API key.

`data/` is gitignored scratch space for downloads and caches. It currently holds a saved
copy of the SPARK challenge announcement.
