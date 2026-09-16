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

## Status

Ideas and tooling notes only. A demo website with a pipeline that produces these reports for
a couple of example papers is being built on a separate branch; when it lands it will live in
`pipeline/` (Python, run locally) and `site/` (static, GitHub Pages).

## Setup

Copy `env.default` to `.env` and fill in whatever keys you have. Nothing here requires a
key: OpenAlex, Semantic Scholar and Europe PMC all work anonymously at lower rate limits,
and LLM calls go through `claude -p` using a Claude Code login rather than an API key.

`data/` is gitignored scratch space for downloads and caches. It currently holds a saved
copy of the SPARK challenge announcement.
