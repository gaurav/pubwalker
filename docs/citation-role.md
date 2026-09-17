# What role does a paper play in the literature?

## The question

A citation count says a paper is used. It does not say *how*. For a software paper the
difference matters: are people running the tool, or citing it in a list of alternatives, or
cataloguing it as a historical step on the way to what they actually used? For a results
paper: is the finding being built on, tested, contradicted, or repeated as background?

The motivating case is [SequenceMatrix](https://doi.org/10.1111/j.1096-0031.2010.00329.x)
(Vaidya, Lohman & Meier 2011), which had 2,594 citing works in OpenAlex on 2026-09-16 and is
still cited 250 to 300 times a year fifteen years after publication. To justify further
development we want to know what those papers use it for, what it is combined with, what
they complain about, and whether the recent citers differ from the early ones. The earlier
pass on this in [taxondna PR #128](https://github.com/gaurav/taxondna/pull/128) got as far as
metadata analysis (venues, topics, co-mentioned software from titles and abstracts) and a
full-text coverage table (about a third of citers have section-tagged PMC XML, another third
an open-access PDF), but stopped short of reading the citing passages.

The same question applies to any paper, and answering it is a form of the grounded
synthesis the [SPARK challenge](spark-challenge.md) is asking for, with the twist that the
"question" is a paper rather than a sentence.

## Pipeline

Each step caches its inputs and outputs, so re-running after a prompt change costs only the
LLM calls that changed.

1. **Discover citers.** OpenAlex `works?filter=cites:<id>` with cursor pagination. For each
   citing work keep the identifiers (OpenAlex, DOI, PMID, PMCID), title, year, type, venue,
   open-access status and topics. OpenAlex sees roughly 85% of what Google Scholar sees; the
   remainder is theses, proceedings and regional journals, acceptable for trend analysis.

2. **Extract the citing passage.** Two free sources, in order:
   - **Semantic Scholar** returns sentence-level `contexts` for many citation pairs, plus its
     own coarse `intents` (background, method, result). Keyless, one call per cited paper
     page. Coverage is partial: many pairs come back with no context.
   - **Europe PMC** full-text XML for open-access citers with a PMCID. Find the `<ref>`
     entry matching our DOI or PMID, then every paragraph containing an `<xref>` to it,
     along with the enclosing section title. This gives whole paragraphs and knows which
     section (Methods, Discussion, Introduction) the citation sits in.
   Passages carry their source and section so later steps can weight them.

3. **Sample per time window.** Windows: last 12 months, last 5 years, all time. Up to 40
   citers with passages per window, seeded random. About 120 LLM calls per paper, which is
   cheap enough to iterate on. Full-corpus classification is a later option, not a
   requirement.

4. **Classify each passage** with a cheap model (Claude Haiku), structured output:

   | Field | Meaning |
   | --- | --- |
   | `role` | one of the roles below |
   | `what_for` | one sentence: what the citing paper does with the cited one |
   | `combined_with` | other tools, methods or data sets named in the passage |
   | `stance` | `positive`, `neutral`, `critical` |
   | `evidence_quote` | verbatim span the label rests on |
   | `confidence` | `high`, `medium`, `low` |

   Roles:

   | Role | Typical passage |
   | --- | --- |
   | `uses-tool-or-method` | "sequences were concatenated in SequenceMatrix" |
   | `uses-data` | reanalyses data the cited paper published |
   | `background-claim` | cites it for a fact or finding in the introduction or discussion |
   | `compares-against` | benchmarks or contrasts with it |
   | `extends-or-modifies` | builds a new method or result on top of it |
   | `critiques-or-contradicts` | disputes it or reports a limitation |
   | `incidental` | appears in a list of alternatives, a review table, or a history |

5. **Synthesise per window** with a frontier model (Claude Opus). Input is the classified
   passages with quotes; output is a short report whose every numbered claim points at
   specific citing papers and quotes, with its key phrase marked and the one to three most
   important claims flagged as highlights, plus three to five follow-up questions. Then one
   cross-window synthesis: what changed over time. This is deliberately the shape of a SPARK
   Track 2 answer (synthesis, citations, supporting passages, follow-up actions).

6. **Report.** For a software author: adoption trend by window; the workflows the tool sits
   in (what it is combined with, upstream and downstream); recurring complaints; what
   citers who did *not* use it chose instead. For a results paper: which claim is cited,
   whether it is being confirmed or contested, and by whom.

## The other direction: outgoing citations

The same question can be asked of the paper's own reference list: what does *it* use each
reference for? Where we have JATS full text, every `<ref>` is paired with the paragraphs that
`<xref>` it (with their section path), enriched from OpenAlex (id, citation count, OA), and
classified by the cheap model with the **same seven roles**, from the citing side. Using one
taxonomy in both directions is the point: the site can set "roles out" against "roles in", show
where in the paper each role appears (Introduction is background, Methods is tools, or not), how
old the references are per role, which references carry the most weight (mentions, sections,
assumptions in the argument structure that name them), and whether the paper cites others the
way it is itself cited.

## Things to watch

- **Passage coverage is the bottleneck, not the LLM.** About 30% of citers are paywalled and
  another third are PDFs that would need GROBID. Report coverage honestly per window.
- **Section matters.** A Methods citation almost always means use; an Introduction citation
  almost never does. Feed the section to the classifier and show it in the report.
- **Sampling bias.** Open-access citers with PMC full text skew towards biomedical journals;
  taxonomy journals are under-represented for SequenceMatrix specifically.
- **Cache every LLM response** keyed by model and prompt hash, so prompt iteration does not
  re-bill for unchanged passages.
- **Spot-check.** Hand-label 20 to 30 passages against the model's labels before trusting the
  histogram.
- **The windows are nested, so they cannot show a trend.** `last-12-months` is a subset of
  `last-5-years` is a subset of `all-time`, and each is sampled independently across its whole
  span. Comparing the three answers "what does a recent citer do, versus a citer at any time",
  not "has this changed since publication" — the all-time sample is thin in the early years
  precisely where a trend question needs it (for a 2006 paper it was 9 pre-2013 citers out of
  40). To ask whether the pattern shifted, sample a fixed number per *era* and classify those;
  the roles step is Haiku and cheap, so a 45-per-era run over four eras costs little. Note that
  the synthesis prompt cheerfully generates "has this shifted by year?" as a follow-up question
  the report itself cannot answer.
- **Role counts undercount method reuse.** A passage citing a paper for where a protocol came
  from often reads as `background-claim`, because the citing sentence is about the method's
  provenance rather than about running it. Testing "is this now cited as a method template?" on
  the role label alone was noisy and non-significant across eras, while the same passages tested
  for whether they *name* the toolkit or protocol gave a clean, significant trend. When a
  question is about one specific reuse, search the `what_for`, `combined_with` and
  `evidence_quote` fields for it rather than counting roles.

## Relation to the argument-structure idea

The roles above describe what the literature *does* with a paper. The
[argument structure](argument-structure.md) describes what the paper *claims*. Putting the
two side by side answers a question neither can alone: is the paper cited for what it set out
to show, or for an incidental method, a figure, or a data set?
