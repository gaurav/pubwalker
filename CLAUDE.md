# pubwalker: notes for agents

- The ideas and the tooling survey live in `docs/`; read `docs/citation-role.md` and
  `docs/argument-structure.md` before changing prompts or schemas in `pipeline/pubwalker/analyze.py`.
- `data/` is gitignored scratch. Every HTTP response (`data/cache/http`) and LLM response
  (`data/cache/llm`) is cached by hash, so a re-run of any pipeline step is offline and free
  unless a prompt, model or schema changed. Per-paper intermediates are `data/<doi-slug>/*.json`.
- All LLM calls go through `pipeline/pubwalker/llm.py` (`claude -p`, custom system prompt, no
  tools, JSON schema). Keep it that way so an open-weight model can be swapped in for a SPARK entry.
  What each step spent is banked per paper in `data/<slug>/cost.json` by `llm.record`, counting
  cache hits at their original price. That is why `roles` and `outgoing` re-ask for items they have
  already classified rather than skipping them: the cache, not a skip list, is what makes a re-run
  free, and skipping hides those calls from the tally. Don't reintroduce the skip.
- `site/` is dependency-free vanilla HTML/JS with no build step; it reads `site/data/*.json`
  written by `pubwalker export`. Check it with `cd pipeline && uv run serve`
  (livereload on :8765) or `python3 -m http.server -d site`. To see it rendered without a
  browser window: `cd pipeline && uv run screenshot out.png <doi> anatomy` (headless Chromium
  via playwright, a dev dependency; `uv run playwright install chromium` once), or
  `node tools/render.mjs <doi> out.html` for the panel's HTML under a stub DOM. `uv run clicktest [doi]`
  clicks every tab and fails on page errors, which a load-time screenshot cannot catch. Firefox's
  `-headless -screenshot` fails on this machine ("Could not find profile folder").
- Tests: `cd pipeline && uv run python -m unittest discover -s tests`. They use inline fixtures
  and never touch the network or `claude`. The site's logic is tested from the same suite: `call_js`
  lifts one top-level arrow function out of `site/app.js` by name and runs it under node, so don't
  reimplement a site function in Python to test it. Its regex only matches a multi-line arrow
  function ending in a line-initial `};`, so a one-liner like `money` or `fmt` cannot be lifted
  (the lazy match runs past it and `eval` throws); and the lifted function is evaluated alone, so
  it must not reference anything else in `app.js`. Put logic worth testing in a self-contained
  helper rather than reformatting a one-liner to suit the harness.
- Gotchas: Europe PMC `fullTextXML` returns 500 for author manuscripts (NCBI efetch works); some PMC
  records are PDF-only deposits whose XML is front matter with no `<body>` (e.g. PMC2994087,
  PMC3063043), so check `analyze.has_body` before trusting a PMCID as full text; OpenAlex's
  `has_pmcid:true` filter returns 0 results, so to find PMC papers filter on
  `locations.source.id:S2764455111|S4306400806` (PMC, Europe PMC) instead;
  OpenAlex's `per-page` also caps `group_by` results; NIH's SPARK page gives a wrong PMCID for
  Bunting 2010 (correct: PMC2857570); Semantic Scholar contexts are sometimes just reference numbers.
