# The NIH SPARK PubMed/PMC Challenge, and how this work relates to it

Summary of the announcement saved in `data/nih-spark-pubmed-pmc-challenge/` (NIH page, read
2026-09-16). Check the live page for changes.

## What NIH is asking for

Build an end-to-end system that takes a biomedical information need in natural language and
returns a grounded answer. Three required capabilities: **grounding** (every response backed
by valid PubMed/PMC citations and explicit passages), **synthesis** (coherent, objective,
complete), **exploration** (generated follow-up actions, typically questions).

| Track | Task | Example |
| --- | --- | --- |
| 1: Known-item and provenance retrieval | Given a query, return the specific document(s) that satisfy it plus a provenance justification. | "Find the seminal paper by Doudna and colleagues describing programmable dual-RNA-guided DNA cleavage" → Jinek et al. 2012. |
| 2: Open-ended exploratory needs | Thematic synthesis across sources, each claim cited, controversial findings called out, 3 to 5 follow-up actions. | "What is the role of BRCA1 in DNA repair?" → six-sentence synthesis with four PMID/PMCID references and two follow-up actions. |

Timeline: registration 2026-09-15; submissions 2027-01-18 to 2027-01-31; judging to
2027-03-29; winners 2027-03-30. Prizes: $125,000 per track, split 80/20 between first and
second place. Up to three submissions per track per participant.

Evaluation: Track 1 by average retrieval accuracy over hundreds of information needs. Track 2
by an "effectiveness score" covering retrieval relevance, answer completeness and
answerability, factuality and groundedness (valid citations, low hallucination, low
self-contradiction), coverage of expected points, contradiction handling, and follow-up
action quality against expert-accepted follow-ups. Anti-gaming probes are planned.

Constraints that shape any entry:

- **Frozen corpus** drawn from PubMed and the PMC Open Access subset, released at launch,
  with sample information needs and reference responses.
- **Open-weight models only.** No calls to proprietary hosted LLMs. All models inside the
  Docker image.
- **Zero egress.** Docker image runs with network blocked except for named NLM services
  (for example UMLS Terminology Services).
- **Reproducibility.** Public source repository, architecture documentation, exact
  dependency versions, instructions to regenerate the submitted outputs.
- JSON output conforming to a schema published at launch; a mandatory local validation
  script.
- Eligibility: US citizens, permanent residents, or US entities to receive money; others may
  be team members. Federal grant funds may be used only consistently with the award's terms.

Pointers NIH gives: [TREC BioGen](https://trec-biogen.github.io/) as the closest prior
challenge; the NLM Strategic Futures AI workshop recordings.

## Why we think this is the wrong question

*Gaurav's section; the paragraph below is a placeholder to be rewritten in his words.*

SPARK treats the literature as a corpus to be queried and summarised, and scores the summary.
That is search with better prose. The harder and more useful problem is understanding what a
paper *is* in the web of other papers: what it rests on, what it is used for, whether the
field has since confirmed or undermined it. A system that knows that can answer SPARK-style
questions as a by-product, and can also answer questions SPARK does not ask, such as "is
this tool still worth maintaining?" or "which of this paper's conclusions has anyone
actually tested?".

## How the two ideas map onto SPARK

| SPARK requirement | Citation-role idea | Argument-structure idea |
| --- | --- | --- |
| Grounding: citations plus passages | Every claim in the synthesis cites citing papers and quotes the passage. | Every schema field carries a verbatim evidence span. |
| Synthesis | Per-window synthesis over classified passages is exactly a Track 2 answer to "how is paper X used?". | A structured record is a synthesis of one paper. |
| Contradiction handling | `critiques-or-contradicts` role surfaces disagreement directly. | Records with shared assumptions and conflicting conclusions. |
| Follow-up actions | Emitted per window from the synthesis step. | `implications` and `limitations` fields. |
| Track 1 provenance justification | Not addressed. | The `question` and `conclusions` fields are a provenance summary. |

## What would have to change to submit

1. Replace `claude -p` with an open-weight model served inside the container (one function
   in the pipeline).
2. Replace live OpenAlex, Semantic Scholar and Europe PMC calls with lookups against the
   frozen corpus. pubmed2db's DuckDB plus PMC OA JATS is roughly the right local shape.
3. Add a query front end: map an information need to anchor papers (Track 1 retrieval), then
   run the citation-role and argument-structure machinery on the anchors to produce the
   Track 2 synthesis.
4. Conform to the JSON output schema and pass the validation script.

None of this changes the ideas; it changes the plumbing. Other RENCI teams may take a more
direct retrieval-plus-generation route, and the two approaches could be combined.
