"""Corpus mining helpers."""
import collections
import os
import unittest

import claim_gate as CG
import completeness_review as CR

HERE = os.path.dirname(os.path.abspath(__file__))

# THE SNAPSHOT THESE COUNTS WERE MEASURED OVER (added 2026-08-08).
#
# load_corpus() globs every run directory, so the corpus GROWS whenever a run happens -- the 74-call
# paid smoke moved the admitted count from 594 to 668 and broke three pinned assertions. The wrong
# fix is to bump the literals: they would break again on the next run, and a number that gets bumped
# on every failure has stopped being a pin at all.
#
# So the two kinds of claim are separated:
#   * COUNT claims  -> asserted over this FROZEN snapshot, which cannot move
#   * INVARIANT claims ("there are no natural truncations") -> asserted over the WHOLE corpus,
#     including every future run, because that is where a first real truncation would show up
def corpus():
    return CG.load_snapshot()


def full_corpus():
    return CG.load_corpus()


def refusals(admitted):
    out = []
    for rec in admitted:
        t = (rec.get("text") or "").strip()
        if t and not CR._BOXED.findall(t) and len(t) <= 400:
            out.append((rec["model"], t))
    return out


class RefusalCorpus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.res = CG.Claim("refusal phrasings", requires=["text"]).admit(corpus())
        cls.refusals = refusals(cls.res.admitted)

    def test_the_claim_is_gated_on_the_field_it_needs(self):
        self.assertEqual(self.res.admitted_n, 594)
        self.assertEqual(self.res.rejected_n, 417)

    def test_every_refusal_in_the_corpus_is_recognised_as_FINISHED(self):
        missed = [(m, t) for m, t in self.refusals if not CR.looks_finished(t)]
        self.assertEqual(missed, [], f"unrecognised refusal phrasings: {missed}")

    def test_every_refusal_scores_as_NON_COMPLIANCE_not_as_an_error(self):
        for m, t in self.refusals:
            v, _ = CR.deterministic_verdict(
                {"text": t, "finish_reason": "stop", "usage": {"prompt_tokens": 300}})
            self.assertEqual(v, CR.NO_ANSWER, f"{m}: {t[:60]!r} -> {v}")
            self.assertIn(v, CR.SCOREABLE)

    def test_the_measured_counts_are_pinned(self):
        self.assertEqual(len(self.refusals), 12)
        self.assertEqual(len({t[:70] for _, t in self.refusals}), 5, "distinct phrasings")

    def test_the_pattern_list_remains_a_KNOWN_LIMIT(self):
        novel = "Prediction unavailable"          # no terminal punctuation, no refusal opener
        self.assertFalse(CR.looks_finished(novel),
                         "documents the residual risk rather than claiming it away")


class NaturalTruncationSearch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.res = CG.Claim("natural truncation search",
                           requires=["finish_reason", "text"]).admit(corpus())

    def test_the_claim_is_gated_on_finish_reason(self):
        self.assertEqual(self.res.admitted_n, 594)
        self.assertEqual(self.res.missing_field_counts.get("finish_reason"), 417)

    def test_there_are_ZERO_natural_truncations(self):
        fr = collections.Counter(r.get("finish_reason") for r in self.res.admitted)
        self.assertEqual(dict(fr), {"stop": 594})
        nat = [r for r in self.res.admitted if r.get("finish_reason") == "length"]
        self.assertEqual(len(nat), 0)

    def test_the_invariant_holds_over_the_WHOLE_corpus_including_new_runs(self):
        res = CG.Claim("natural truncation, full corpus",
                       requires=["finish_reason", "text"]).admit(full_corpus())
        fr = collections.Counter(r.get("finish_reason") for r in res.admitted)
        self.assertGreaterEqual(res.admitted_n, 594, "the corpus should only ever grow")
        self.assertEqual(fr.get("length", 0), 0,
                         f"a natural truncation now exists in the corpus ({res.admitted_n} admitted "
                         f"records): RE-CALIBRATE the reader against it instead of relying on "
                         f"seeded cuts")

    def test_therefore_reader_recall_rests_entirely_on_seeded_cuts(self):
        nat = [r for r in self.res.admitted if r.get("finish_reason") == "length"]
        self.assertEqual(len(nat), 0,
                         "a natural truncation now exists: RE-CALIBRATE the reader against it "
                         "instead of relying on seeded cuts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
