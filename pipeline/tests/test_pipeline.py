"""Offline checks for the pure logic: JATS passage extraction, windowing, grounding, flattening.
Run: cd pipeline && uv run python -m unittest discover -s tests"""
import datetime as dt
import unittest
import xml.etree.ElementTree as ET

from pubwalker.analyze import fulltext, grounded, histogram, tidy_structure
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
        out = grounded({"claims": [{"text": "x", "cites": ["[W1]", "W2", "W9"]}], "follow_ups": []}, {"W1", "W2"})
        self.assertEqual(out["claims"][0]["cites"], ["W1", "W2"])

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


class Fetch(unittest.TestCase):
    def test_flatten_and_slug(self):
        w = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1000/ABC", "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/42"},
             "title": "T", "publication_year": 2020, "publication_date": "2020-05-01", "type": "article",
             "open_access": {"is_oa": True}, "primary_location": {"source": {"display_name": "J"}}, "topics": [{"display_name": "A"}, {"display_name": "B"}, {"display_name": "C"}]}
        f = flatten(w)
        self.assertEqual((f["id"], f["doi"], f["pmid"], f["pmcid"], f["venue"], f["topics"]), ("W1", "10.1000/abc", "42", None, "J", ["A", "B"]))
        self.assertEqual(slugify("10.1111/j.1096-0031.2010.00329.x"), "10-1111-j-1096-0031-2010-00329-x")


if __name__ == "__main__":
    unittest.main()
