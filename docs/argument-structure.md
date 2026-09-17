# What is the structure of a paper's argument?

## The question

A paper is an argument wrapped in prose. Somewhere inside it are the assumptions it starts
from (usually borrowed, with a citation), a design intended to test something, data collected
under that design, an analysis, conclusions, and an implicit "and therefore" about what the
field now knows. Readers reconstruct this every time they read carefully, and lose it as soon
as they close the PDF.

Taxonomy went through this once already. Plazi's TaxonX schema and GoldenGATE editor
([Agosti & Egloff 2009](https://pubmed.ncbi.nlm.nih.gov/19331688/)) mark up taxonomic
treatments so that the nomenclatural act, the material examined, the description and the
diagnosis become addressable, reusable units rather than paragraphs. The bet here is that
the argument of a research paper can be marked up the same way, and that an LLM with the full
text can produce a first draft of that markup cheaply enough to do it for every paper we care
about.

## Proposed schema

Produced as JSON from the full text (PMC JATS XML where available), one record per paper.

| Section | Contents |
| --- | --- |
| `question` | The question or hypothesis the paper says it addresses, in one sentence. |
| `assumptions` | Premises the argument depends on, each with the reference(s) it is attributed to, or `unsourced` if asserted without citation. |
| `design` | Study type; arms, conditions or comparison groups; what is manipulated and what is measured; sample or population. |
| `data` | What was collected or reused, with any accession or repository identifiers. |
| `analysis` | The methods applied to the data, with the software or statistical tests named. |
| `results` | The findings as stated, tied to the design arm they come from. |
| `conclusions` | What the authors say the results show. |
| `implications` | What follows for the field if the conclusions hold; what the paper says should be done next. |
| `limitations` | Stated caveats, and anything the model notices the paper does not address. |

Every entry carries an `evidence` field with the verbatim span it was derived from and the
section it came from, so the markup can be checked against the paper. Each entry also carries:

| Field | Contents |
| --- | --- |
| `kind` | A statement type that cuts across the sections: `fact` (established knowledge taken as given), `method` (how something was done), `finding` (observed or measured in this work), `claim` (the authors' interpretation, argument or proposal), `gap` (a caveat or something not addressed). Within Assumptions this separates cited facts from bare premises; within Results, measurements from interpretation; within Limitations, stated caveats from gaps the model noticed. |
| `text` | One sentence, with the 2–6 words that carry its point wrapped in `**…**`; the site bolds them. (Asking for the phrase as a separate field failed: the model copied it from the paper rather than from its own sentence.) |
| `highlight` | True for the one to three entries per section a reader should see first. |
| `based_on` | Conclusions only: the results the conclusion rests on, as `R1`, `R2`, … numbering the `results` list from 1. |

## Uses

- **Reading aid.** The record is a structured abstract that actually covers the argument
  rather than the headline result.
- **Dependency graph.** `assumptions` with their sources link a paper to the papers it rests
  on. Walk it two steps and you have the evidential base of a claim.
- **Comparison with citation roles.** From the [citation-role](citation-role.md) work we know
  what citers use a paper for. Compare that with `conclusions` and `results`: a paper cited
  overwhelmingly for a Methods detail, or for one figure, while its stated conclusion is
  never mentioned, is worth knowing about.
- **Contradiction detection.** Two records whose `conclusions` disagree while sharing
  `assumptions` are candidates for a real disagreement rather than a difference in framing.
  This is the "contradiction handling" SPARK Track 2 scores.
- **Follow-up questions.** `implications` and `limitations` are where the next question
  lives, which is the other Track 2 output.

## Related formats

- **Structured abstracts** (Background / Methods / Results / Conclusions) are the
  lightweight version, but do not carry assumptions or their sources.
- **Nanopublications** and the **Micropublications** model express single claims with
  provenance; the schema above is coarser and per-paper, and could emit nanopublications.
- **SciClaim / claim annotation** (as in hypothes.is-style annotation projects) marks claims
  in place; our `evidence` spans are compatible with that.
- **Plazi TaxonX / TaxPub** for treatments, as above, as the working model for "mark up a
  document into reusable units".

## Things to watch

- **Full text is required.** Abstracts do not contain the design or the assumptions. About a
  third of the literature has PMC XML; OA PDFs need GROBID; paywalled papers are out for a
  public tool.
- **Attribution of assumptions** is the hard part: the model has to resolve an in-text
  citation marker to a reference-list entry, and JATS makes this reliable while PDFs do not.
- **Hallucinated structure.** Papers do not always have a clean design. The schema should
  allow "not stated" everywhere, and the evidence spans make the gaps visible.
- **Start with one well-structured paper.** The demo uses Bunting et al. 2010 (53BP1 and
  BRCA1-deficient cells, PMC2846171), a classic experimental paper with open full text.
