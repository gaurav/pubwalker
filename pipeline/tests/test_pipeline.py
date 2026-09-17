"""Offline checks for the pure logic: JATS passage extraction, windowing, grounding, flattening.
Run: cd pipeline && uv run python -m unittest discover -s tests"""
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import httpx

from pubwalker import analyze, export, http, llm
from pubwalker.analyze import fulltext, grounded, has_body, histogram, references, tidy_structure
from pubwalker.fetch import flatten, slugify
from pubwalker.passages import citing_paragraphs, find_ref, in_window

JATS = """<article><body>
<sec><title>Methods</title>
  <sec><title>Phylogenetics</title>
    <p>Loci were concatenated in SequenceMatrix <xref ref-type="bibr" rid="B2">[2]</xref> and analysed in RAxML <xref ref-type="bibr" rid="B3">[3]</xref>.</p>
  </sec></sec>
<sec><title>Discussion</title><p>Unrelated paragraph citing <xref ref-type="bibr" rid="B3">[3]</xref>.</p></sec>
</body><back><ref-list>
<ref id="B2"><mixed-citation>Vaidya G (2011) SequenceMatrix. <pub-id pub-id-type="doi">10.1111/j.1096-0031.2010.00329.x</pub-id></mixed-citation></ref>
<ref id="B3"><mixed-citation>Stamatakis A (2014) RAxML. <pub-id pub-id-type="pmid">24451623</pub-id></mixed-citation></ref>
</ref-list></back></article>"""
ROOT = ET.fromstring(JATS)


class Passages(unittest.TestCase):
    def test_find_ref_by_doi_and_pmid(self):
        self.assertEqual(find_ref(ROOT, {"doi": "10.1111/j.1096-0031.2010.00329.x"}), "B2")
        self.assertEqual(find_ref(ROOT, {"pmid": "24451623"}), "B3")
        self.assertIsNone(find_ref(ROOT, {"doi": "10.1/nope", "pmid": "1"}))

    def test_paragraphs_carry_section_chain(self):
        ps = citing_paragraphs(ROOT, {"doi": "10.1111/j.1096-0031.2010.00329.x"})
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0]["section"], "Methods > Phylogenetics")
        self.assertIn("concatenated in SequenceMatrix", ps[0]["text"])
        self.assertEqual(len(citing_paragraphs(ROOT, {"pmid": "24451623"})), 2)

    def test_in_window_uses_date_then_year(self):
        today = dt.date(2026, 9, 16)
        self.assertTrue(in_window({"date": "2026-01-01"}, 365, today))
        self.assertFalse(in_window({"date": "2025-01-01"}, 365, today))
        self.assertTrue(in_window({"date": None, "year": 2026}, 365, today))
        self.assertFalse(in_window({"date": None, "year": None}, 365, today))
        self.assertTrue(in_window({"date": None, "year": None}, None, today))


class Analyze(unittest.TestCase):
    def test_grounded_keeps_only_known_ids(self):
        out = grounded({"claims": [{"text": "**x** and **y**", "cites": ["[W1]", "W2", "W9"]}, {"text": "a **b** c", "cites": []}], "follow_ups": []}, {"W1", "W2"})
        self.assertEqual(out["claims"][0]["cites"], ["W1", "W2"])
        self.assertEqual([c["text"] for c in out["claims"]], ["x and y", "a **b** c"])  # one key phrase kept, two stripped

    def test_histogram_ignores_unclassified(self):
        h = histogram(["a", "b", "c"], {"a": {"role": "incidental"}, "b": {"role": "incidental"}})
        self.assertEqual(h["incidental"], 2)
        self.assertEqual(sum(h.values()), 2)

    def test_tidy_structure_checks_keys_and_result_ids(self):
        item = lambda text: {"text": text, "kind": "claim", "highlight": True, "evidence": "x"}
        out = {k: [] for k in ["assumptions", "design", "data", "analysis", "implications", "limitations"]}
        out["results"] = [item("Tumours **fell tenfold**."), item("**HR** was **restored**."), item("Stray ** marker.")]
        out["conclusions"] = [{**item("53BP1 **is required**."), "based_on": ["R1", "[r2]", "R3", "D1"]}]
        tidy_structure(out)
        self.assertEqual([r["text"] for r in out["results"]], ["Tumours **fell tenfold**.", "HR was restored.", "Stray  marker."])
        self.assertEqual(out["conclusions"][0]["based_on"], ["R1", "R2", "R3"])

    def test_fulltext_marks_bibr_xrefs_and_collects_refs(self):
        body, refs = fulltext(ROOT)
        self.assertIn("SequenceMatrix [B2] and analysed in RAxML [B3]", body)
        self.assertIn("## Phylogenetics", body)
        self.assertIn("10.1111/j.1096-0031.2010.00329.x", refs["B2"])

    def test_has_body_rejects_front_matter_only_records(self):
        self.assertTrue(has_body(ROOT))
        self.assertFalse(has_body(ET.fromstring("<article><front><article-meta/></front></article>")))
        self.assertFalse(has_body(ET.fromstring("<article><body/></article>")))

    def test_references_carry_ids_years_and_mentions(self):
        refs = {r["id"]: r for r in references(ROOT)}
        self.assertEqual((refs["B2"]["doi"], refs["B2"]["year"], len(refs["B2"]["mentions"])), ("10.1111/j.1096-0031.2010.00329.x", 2011, 1))
        self.assertEqual((refs["B3"]["pmid"], [m["section"] for m in refs["B3"]["mentions"]]), ("24451623", ["Methods > Phylogenetics", "Discussion"]))

    def test_enrich_matches_by_doi_then_pmid_and_fills_year(self):
        work = lambda id, doi=None, pmid=None, year=2000: {"id": f"https://openalex.org/{id}", "doi": doi and f"https://doi.org/{doi}", "ids": {"pmid": pmid and f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"},
                                                              "cited_by_count": 7, "publication_year": year, "open_access": {"is_oa": True}}
        calls = []

        def fake_openalex(path, **params):
            calls.append(params["filter"])
            return {"results": [work("W1", doi="10.1/a")] if params["filter"].startswith("doi:") else [work("W2", pmid="99", year=1999)]}

        refs = [{"id": "B1", "doi": "10.1/a", "pmid": None, "year": 2001}, {"id": "B2", "doi": None, "pmid": "99", "year": None}, {"id": "B3", "doi": None, "pmid": None, "year": None}]
        with mock.patch.object(analyze, "openalex", fake_openalex):
            analyze.enrich(refs)
        self.assertEqual(calls, ["doi:10.1/a", "pmid:99"])  # one batched request per id type, only for refs still unmatched
        self.assertEqual((refs[0]["openalex_id"], refs[0]["cited_by_count"], refs[0]["year"]), ("W1", 7, 2001))  # a known year is kept
        self.assertEqual((refs[1]["openalex_id"], refs[1]["year"]), ("W2", 1999))  # a missing one is filled
        self.assertNotIn("openalex_id", refs[2])


class Http(unittest.TestCase):
    def test_get_retries_transport_errors_then_succeeds(self):
        ok = httpx.Response(200, json={"a": 1}, request=httpx.Request("GET", "https://x/y"))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(http, "CACHE", Path(tmp)), mock.patch.object(http.time, "sleep") as sleep, \
                mock.patch.object(http.httpx, "get", side_effect=[httpx.ReadTimeout("slow"), ok]) as get:
            self.assertEqual(http.get("https://x/y", {"q": "test-retry"}), {"a": 1})
            self.assertEqual((get.call_count, sleep.call_count), (2, 1))
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)  # the successful response was cached


class Fetch(unittest.TestCase):
    def test_flatten_and_slug(self):
        w = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1000/ABC", "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/42"},
             "title": "T", "publication_year": 2020, "publication_date": "2020-05-01", "type": "article",
             "open_access": {"is_oa": True}, "primary_location": {"source": {"display_name": "J"}}, "topics": [{"display_name": "A"}, {"display_name": "B"}, {"display_name": "C"}]}
        f = flatten(w)
        self.assertEqual((f["id"], f["doi"], f["pmid"], f["pmcid"], f["venue"], f["topics"]), ("W1", "10.1000/abc", "42", None, "J", ["A", "B"]))
        self.assertEqual(slugify("10.1111/j.1096-0031.2010.00329.x"), "10-1111-j-1096-0031-2010-00329-x")


class Export(unittest.TestCase):
    def paper(self, tmp, **extra):
        """A one-citer paper on disk, as the steps before `export` would have left it."""
        d = Path(tmp) / "10-1-a"
        d.mkdir()
        files = {"anchor": {"id": "W0", "doi": "10.1/a", "title": "T", "year": 2010, "cited_by_count": 9},
                 "citers": [{"id": "W1", "title": "C", "year": 2012, "type": "article"}, {"id": "W2", "title": "Predates it", "year": 2009}],
                 "passages": {"windows": {"all-time": {"total": 2, "with_passages": 1, "sampled": ["W1"]}}, "passages": {"W1": {"passages": []}}},
                 "roles": {"W1": {"role": "uses-data"}}, "synthesis": {"all-time": {"claims": []}, "overall": {"claims": []}},
                 "cost": {"roles": {"haiku": 0.25}, "synth": {"opus": 0.5}}, **extra}
        for name, obj in files.items():
            (d / f"{name}.json").write_text(json.dumps(obj))
        return d

    def test_index_entry_carries_each_section_and_the_paper_s_own_cost(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as site, \
                mock.patch.object(export, "DATA", Path(tmp)), mock.patch.object(analyze, "DATA", Path(tmp)), \
                mock.patch.object(llm, "DATA", Path(tmp)), mock.patch.object(export, "SITE_DATA", Path(site)):
            self.paper(tmp, structure={"source": "pmc-full-text"}, outgoing={"references": [{"id": "B1"}, {"id": "B2"}]})
            export.run("10.1/a")
            entry, = json.loads((Path(site) / "index.json").read_text())
            self.assertEqual((entry["cost_usd"], entry["source"], entry["outgoing"]), (0.75, "pmc-full-text", 2))
            self.assertEqual(entry["roles"]["uses-data"], 1)  # the all-time histogram, for the home page's bar and sort
            report = json.loads((Path(site) / "10-1-a.json").read_text())
            self.assertEqual(report["cost_usd"], 0.75)
            self.assertEqual(report["cost_by_model"], {"opus": 0.5, "haiku": 0.25})  # biggest first
            self.assertEqual(report["cost_by_step"], {"roles": {"haiku": 0.25}, "synth": {"opus": 0.5}})  # the site says which model did which job
            for field in ("cost_by_model", "cost_by_step"):  # both are report-page figures; the home page keeps the scalar,
                self.assertNotIn(field, entry)  # and index.json is fetched on every page view, report pages included
            self.assertEqual(report["years"], [[2012, 1]])  # the citer OpenAlex dates before the paper it cites is dropped

    def test_a_paper_without_full_text_says_so_rather_than_reporting_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as site, \
                mock.patch.object(export, "DATA", Path(tmp)), mock.patch.object(analyze, "DATA", Path(tmp)), \
                mock.patch.object(llm, "DATA", Path(tmp)), mock.patch.object(export, "SITE_DATA", Path(site)):
            self.paper(tmp)
            export.run("10.1/a")
            entry, = json.loads((Path(site) / "index.json").read_text())
            self.assertEqual((entry["source"], entry["outgoing"]), (None, None))


class ClosedAccess(unittest.TestCase):
    """An anchor with no PMCID at all (a paywalled paper Europe PMC has no deposit for). Both steps
    that need the anchor's own full text must degrade rather than fail, and neither may reach the
    network to find that out."""

    def anchor(self, tmp, **extra):
        d = Path(tmp) / "10-1-a"
        d.mkdir()
        (d / "anchor.json").write_text(json.dumps({"id": "W0", "doi": "10.1/a", "title": "T", "year": 2006, "pmcid": None, **extra}))
        return d

    def test_outgoing_is_skipped_without_a_pmcid_and_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(analyze, "DATA", Path(tmp)), \
                mock.patch.object(analyze, "jats", side_effect=AssertionError("must not fetch")) as jats:
            self.anchor(tmp)
            self.assertIsNone(analyze.outgoing("10.1/a"))
            jats.assert_not_called()
            self.assertFalse((Path(tmp) / "10-1-a" / "outgoing.json").exists())  # export reads its absence as "no outgoing"

    def test_structure_falls_back_to_the_abstract_and_keeps_what_the_model_saw(self):
        struct = {k: [] for k in ["assumptions", "conclusions", "design", "data", "analysis", "results", "implications", "limitations"]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(analyze, "DATA", Path(tmp)), \
                mock.patch.object(analyze, "jats", side_effect=AssertionError("must not fetch")), \
                mock.patch.object(analyze, "abstract", return_value="Barcoding fails in flies."), \
                mock.patch.object(analyze, "ask", return_value={**struct, "question": "Q"}) as ask:
            self.anchor(tmp)
            out = analyze.structure("10.1/a")
            self.assertEqual(out["source"], "abstract-only")
            self.assertEqual(out["abstract"], "Barcoding fails in flies.")  # shown on the site so a reader sees the model's whole input
            self.assertEqual(out["references"], {})  # no full text means no reference list to attribute assumptions to
            self.assertIn("Only the abstract is available", ask.call_args.args[0])


class Cost(unittest.TestCase):
    def paper(self, tmp, costs=None):
        d = Path(tmp) / "10-1-a"
        d.mkdir()
        if costs is not None:
            (d / "cost.json").write_text(json.dumps(costs))
        return d

    def test_each_step_banks_its_own_spend_and_a_rerun_does_not_double_count(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(llm, "DATA", Path(tmp)):
            self.paper(tmp)
            self.assertIsNone(llm.cost("10.1/a"))  # nothing spent on this paper yet
            for step, spend in [("roles", [("haiku", 0.01), ("haiku", 0.02)]), ("synth", [("opus", 0.5)])]:
                llm.SPENT.extend(spend)
                llm.record("10.1/a", step)
            self.assertEqual(llm.cost("10.1/a"), 0.53)
            self.assertEqual(llm.per_model("10.1/a"), {"opus": 0.5, "haiku": 0.03})
            self.assertEqual(json.loads((Path(tmp) / "10-1-a" / "cost.json").read_text()),
                             {"roles": {"haiku": 0.03}, "synth": {"opus": 0.5}})
            llm.SPENT.extend([("haiku", 0.01), ("haiku", 0.02)])  # a re-run of roles replays the same cached calls
            llm.record("10.1/a", "roles")
            self.assertEqual(llm.cost("10.1/a"), 0.53)
            self.assertEqual(llm.SPENT, [])  # and the tally is cleared for the next step

    def test_a_step_that_mixes_models_banks_one_entry_per_model(self):
        """Nothing enforces one model per step, and CLAUDE.md expects an open-weight model to be swapped in,
        which is exactly when inferring the model from the step name would go quietly wrong."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(llm, "DATA", Path(tmp)):
            self.paper(tmp)
            llm.SPENT.extend([("haiku", 0.01), ("opus", 0.2), ("haiku", 0.02)])
            llm.record("10.1/a", "roles")
            self.assertEqual(json.loads((Path(tmp) / "10-1-a" / "cost.json").read_text()), {"roles": {"haiku": 0.03, "opus": 0.2}})
            self.assertEqual(llm.per_model("10.1/a"), {"opus": 0.2, "haiku": 0.03})

    def test_a_cost_file_from_before_the_split_still_totals_but_cannot_be_split(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(llm, "DATA", Path(tmp)):
            self.paper(tmp, {"roles": 1.0, "synth": 2.0})
            self.assertEqual(llm.cost("10.1/a"), 3.0)
            self.assertIsNone(llm.per_model("10.1/a"))
            self.assertIsNone(llm.by_step("10.1/a"))  # nor can it say which model did which job

    def test_a_half_migrated_cost_file_totals_without_claiming_a_split(self):
        """`record` migrates one step at a time, so this is the ordinary state of a run in progress -- not a
        stale checkout. It must total correctly rather than raising, and must not report a partial split."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(llm, "DATA", Path(tmp)):
            self.paper(tmp, {"roles": {"haiku": 1.0}, "synth": 2.0})
            self.assertEqual(llm.cost("10.1/a"), 3.0)
            self.assertIsNone(llm.per_model("10.1/a"))


APP_JS = Path(__file__).resolve().parents[2] / "site" / "app.js"
# The site is dependency-free vanilla JS, so lift a single top-level arrow function out of app.js by name
# and run it under node rather than reimplementing it here. Its result comes back as JSON.
CALL_JS = """
const src = require('node:fs').readFileSync(process.env.APP_JS, 'utf8');
const fn = eval('(' + src.match(new RegExp(`const ${process.env.FN} = ([\\\\s\\\\S]*?\\\\n\\\\});`))[1] + ')');
process.stdout.write(JSON.stringify(fn(...JSON.parse(process.env.ARGS))));
"""


def call_js(fn, *args):
    out = subprocess.run(["node", "-e", CALL_JS], capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"], "APP_JS": str(APP_JS), "FN": fn, "ARGS": json.dumps(args)})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Variety(unittest.TestCase):
    """The order of the home page and of the Examples dropdown: the effective number of roles a paper is cited for."""

    def test_effective_number_of_roles(self):
        self.assertAlmostEqual(call_js("variety", {"background-claim": 39}), 1.0)  # cited for one thing only
        self.assertAlmostEqual(call_js("variety", {r: 5 for r in "abcdefg"}), 7.0)  # an even spread over all seven roles
        remap = {"uses-tool-or-method": 3, "uses-data": 24, "background-claim": 7, "compares-against": 3, "extends-or-modifies": 1, "incidental": 1}
        self.assertAlmostEqual(call_js("variety", remap), 3.29, places=2)
        self.assertLess(call_js("variety", {"uses-data": 20, "background-claim": 19}),  # an even split of two roles beats
                        call_js("variety", remap))                                     # a lopsided spread over six
        self.assertEqual(call_js("variety", {"uses-data": 0}), None)  # nothing classified, so nothing to say
        self.assertEqual(call_js("variety", None), None)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class CostSplit(unittest.TestCase):
    """Which per-model cost tiles a report page shows beside its total."""

    def test_the_note_names_the_models_that_were_actually_billed(self):
        by = {"roles": {"haiku": 1.0}, "synth": {"opus": 2.0}, "structure": {"opus": 0.5}}
        self.assertEqual(call_js("modelsFor", by, ["roles", "outgoing"]), "Haiku")  # a step that never ran contributes nothing
        self.assertEqual(call_js("modelsFor", by, ["synth", "structure"]), "Opus")  # one name, not two, when both used it
        self.assertEqual(call_js("modelsFor", {"roles": {"haiku": 1.0, "llama": 0.0}}, ["roles"]), "Haiku and Llama")
        self.assertEqual(call_js("modelsFor", None, ["roles"]), "")  # a report exported before the split; the note falls back

    def test_rows_are_biggest_first_and_only_when_there_is_something_to_compare(self):
        self.assertEqual(call_js("costRows", {"haiku": 2.5, "opus": 1.0}), [["haiku", 2.5], ["opus", 1.0]])
        self.assertEqual(call_js("costRows", {"opus": 1.0, "haiku": 2.5}), [["haiku", 2.5], ["opus", 1.0]])  # key order does not matter
        self.assertEqual(call_js("costRows", {"opus": 1.0}), [])  # one model says nothing the total does not
        self.assertEqual(call_js("costRows", {"haiku": 2.5, "opus": 0}), [])  # a model that billed nothing is not a second model
        self.assertEqual(call_js("costRows", None), [])  # a report exported before the split was recorded


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class YearChart(unittest.TestCase):
    def chart(self, years):
        return call_js("yearChart", years)

    def test_empty_years_are_filled_so_the_axis_stays_linear(self):
        html = self.chart([[2001, 3], [2009, 5], [2010, 1]])
        self.assertEqual(html.count("<div style="), 10)  # one bar per year 2001..2010, not one per year with citations
        self.assertIn('data-l="2005: 0"', html)
        self.assertIn('height:100.0%" data-l="2009: 5"', html)  # the bars are scaled to the tallest year
        self.assertIn("<span>2001</span><span>2010</span>", html)  # the axis labels are the real endpoints

    def test_no_years_renders_nothing(self):
        self.assertEqual(self.chart([]), "")


if __name__ == "__main__":
    unittest.main()
