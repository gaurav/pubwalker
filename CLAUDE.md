# pubwalker: notes for agents

- The ideas and the tooling survey live in `docs/`; read `docs/citation-role.md` and
  `docs/argument-structure.md` before changing prompts or schemas in `pipeline/pubwalker/analyze.py`.
- `data/` is gitignored scratch. Every HTTP response (`data/cache/http`) and LLM response
  (`data/cache/llm`) is cached by hash, so a re-run of any pipeline step is offline and free
  unless a prompt, model or schema changed. Per-paper intermediates are `data/<doi-slug>/*.json`.
- All LLM calls go through `pipeline/pubwalker/llm.py` (`claude -p`, custom system prompt, no
  tools, JSON schema). Keep it that way so an open-weight model can be swapped in for a SPARK entry.
- `site/` is dependency-free vanilla HTML/JS with no build step; it reads `site/data/*.json`
  written by `pubwalker export`. Check it with `cd pipeline && uv run serve`
  (livereload on :8765) or `python3 -m http.server -d site`. To see it rendered without a
  browser window: `cd pipeline && uv run screenshot out.png <doi> anatomy` (headless Chromium
  via playwright, a dev dependency; `uv run playwright install chromium` once), or
  `node tools/render.mjs <doi> out.html` for the panel's HTML under a stub DOM. `uv run clicktest [doi]`
  clicks every tab and fails on page errors, which a load-time screenshot cannot catch. Firefox's
  `-headless -screenshot` fails on this machine ("Could not find profile folder").
- Tests: `cd pipeline && uv run python -m unittest discover -s tests`. They use inline fixtures
  and never touch the network or `claude`.
- Gotchas: Europe PMC `fullTextXML` returns 500 for author manuscripts (NCBI efetch works); some PMC
  records are PDF-only deposits whose XML is front matter with no `<body>` (e.g. PMC2994087,
  PMC3063043), so check `analyze.has_body` before trusting a PMCID as full text; OpenAlex's
  `has_pmcid:true` filter returns 0 results, so to find PMC papers filter on
  `locations.source.id:S2764455111|S4306400806` (PMC, Europe PMC) instead;
  OpenAlex's `per-page` also caps `group_by` results; NIH's SPARK page gives a wrong PMCID for
  Bunting 2010 (correct: PMC2857570); Semantic Scholar contexts are sometimes just reference numbers.
