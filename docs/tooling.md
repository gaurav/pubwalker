# Tooling landscape

What we can lean on, checked 2026-09-16. "Keyless" means it worked from this machine with no
credentials; keys raise rate limits and are listed in `env.default`.

## Discovery and metadata

| Source | Gives us | Limits | Auth |
| --- | --- | --- | --- |
| [OpenAlex](https://docs.openalex.org/) | Citing works via `works?filter=cites:W...`, cursor pagination; DOI, PMID, PMCID, venue, type, OA status, topics, abstract (inverted index). SequenceMatrix: 2,594 citers. | About 85% of Google Scholar's recall; misses theses and regional journals. | Keyless; `mailto` for the polite pool, free key for higher limits. |
| [Semantic Scholar Graph API](https://api.semanticscholar.org/api-docs/) | `paper/DOI:.../citations?fields=contexts,intents,isInfluential`: sentence-level citation contexts and coarse intents. | Contexts missing for many pairs; shared anonymous pool, 429s under load. | Keyless; free key for 1 req/s. |
| [Europe PMC REST](https://europepmc.org/RestfulWebService) | `search?query=CITES:<pmid>_MED` lists citers it knows; `/PMC<id>/fullTextXML` returns JATS for OA papers; annotations API for text-mined entities. | Only what is in Europe PMC; full text only for the OA subset. | Keyless. |
| [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/) | `elink` cited-by within PMC, `efetch` abstracts and PMC XML, ID conversion. | 3 req/s anonymous. | Key raises to 10 req/s. |
| [iCite](https://icite.od.nih.gov/api) (NIH) | `api/pubs?pmids=` in batches: the complete citing-PMID list in one request with no pagination, and `citedByPmidsByYear` giving each citer's year; the paper's own reference PMIDs; and field-normalised metrics (Relative Citation Ratio, NIH percentile, expected vs actual citations per year). Meier 2006: 735 citers, 43 references, RCR 25.6, 99.5th percentile. | PubMed-indexed citing papers only -- 735 against OpenAlex's 1,445 for that same paper, so roughly half. Metrics are NIH's own and are defined for research articles. Checked 2026-09-17. | Keyless. |
| [Crossref](https://api.crossref.org) | Reference lists, funders, licence URLs. | No cited-by without membership. | Keyless with `mailto`. |
| [Unpaywall](https://unpaywall.org/products/api) | OA PDF locations by DOI. | OpenAlex already carries this; rarely needed directly. | Email. |

## Full text and extraction

| Tool | Gives us | Notes |
| --- | --- | --- |
| Europe PMC JATS XML | Section-tagged text with `<xref ref-type="bibr">` resolving to `<ref>` entries. | Best input for both ideas. No PDF parsing. |
| [GROBID](https://grobid.readthedocs.io/) | PDF to TEI XML, including citation markers. | Docker, one-shot. Needed for the OA-PDF third of citers. Not in the demo. |
| [CZ Software Mentions](https://github.com/chanzuckerberg/software-mentions) | Sentence-level software mentions across PMC and a publisher collection. | Cutoff October 2021. Already checked for SequenceMatrix in taxondna: 372 papers. |
| [Softcite](https://github.com/softcite), [SoMeSci](https://data.gesis.org/somesci/) | Gold-standard software-mention corpora and extractors. | Useful to evaluate the `uses-tool-or-method` label. |

## Local corpora

| Tool | Gives us | Notes |
| --- | --- | --- |
| [pubmed2db](https://github.com/TranslatorSRI/pubmed2db) | All of PubMed in DuckDB with version history; abstracts, MeSH, journal, article IDs and, in recent loads, cited PMIDs. Gaurav can download the current 69 GB database. | Abstracts only, no full text. Enough for an offline PubMed-internal citation graph and for the frozen-corpus mode a SPARK entry would need. |
| PMC OA bulk / [PMC OAI](https://pmc.ncbi.nlm.nih.gov/tools/oai/) | Bulk JATS for the OA subset. | For scaling past per-paper API calls. |

## LLM plumbing

| Tool | Gives us | Notes |
| --- | --- | --- |
| Claude Code headless: `claude -p` | Runs a prompt under the Claude Code login, no API key. `--output-format json` returns the answer, cost and usage; `--json-schema` enforces structured output; `--system-prompt` replaces the default (large) system prompt; `--tools ""` and `--no-session-persistence` keep it a pure completion. Verified: a Haiku call from this machine took about 2 s and reported ~2 cents, most of it the default system prompt, which `--system-prompt` removes. | The demo pipeline's only LLM path. Swap for the Anthropic SDK if a key is preferred. |
| Anthropic API | Cheaper per call, prompt caching, batch API for the full-corpus run. | Optional; `ANTHROPIC_API_KEY` in `.env`. |
| Open-weight models via vLLM or Ollama | Required for an actual SPARK submission (no external API calls allowed). | Not needed for the demo; the pipeline's LLM layer is one function to replace. |

## Interactive front end

| Pattern | Gives us | Notes |
| --- | --- | --- |
| Static HTML/JS on GitHub Pages | Zero-setup viewing of precomputed reports; OpenAlex and Semantic Scholar allow browser CORS calls, so a keyless live mode is possible. | The demo site. |
| [prcoder](https://github.com/gaurav/prcoder/pull/1) pattern: `node-pty` + `ws` + `xterm.js` | A live Claude Code terminal inside a web page, with the fetched corpus on disk for it to grep. Five dependencies, no build step. | Candidate for a later local-only mode that lets you interrogate the citing papers conversationally. |

## Prior work in our own repos

- [taxondna PR #128](https://github.com/gaurav/taxondna/pull/128), branch `analyze-citations`,
  directory `citations/`: OpenAlex fetch and flatten scripts, metadata digest, CZ Software
  Mentions cross-check, full-text coverage table (33% PMC XML, 36% OA PDF, 30% paywalled).
  The fetch scripts are the starting point for step 1 of the citation-role pipeline.
