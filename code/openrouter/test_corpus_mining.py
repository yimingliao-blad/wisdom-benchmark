"""M6-T10 (L-C) + M6-T11 (L-H) — what the stored corpus can and cannot tell us.

Both leaves go through the admissibility gate, so neither can be computed over records that lack the
fields it needs. Both pin their results so a later change cannot alter them quietly.

L-C  refusal phrasings: does the detector catch every refusal the corpus actually contains?
L-H  natural truncation: are there ANY real (non-seeded) truncation positives to calibrate against?

The L-H answer is NO, and that is the point: it converts "the reader's recall may be optimistic"
from a caveat into a measured fact.

Offline. No network. No spend.  Run: python3 -m unittest test_corpus_mining -v
"""
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
    """The frozen snapshot the pinned counts describe. Defined ONCE, in claim_gate."""
    return CG.load_snapshot()


def full_corpus():
    """Everything on disk, including runs made after the snapshot."""
    return CG.load_corpus()


def refusals(admitted):
    """A finished reply, short, with no answer marker."""
    out = []
    for rec in admitted:
        t = (rec.get("text") or "").strip()
        if t and not CR._BOXED.findall(t) and len(t) <= 400:
            out.append((rec["model"], t))
    return out


class RefusalCorpus(unittest.TestCase):
    """C10: a refusal phrased outside the pattern list would be mislabelled TRUNCATED and drop out
    of the denominator -- the same class of error as the bug that already bit once."""

    @classmethod
    def setUpClass(cls):
        cls.res = CG.Claim("refusal phrasings", requires=["text"]).admit(corpus())
        cls.refusals = refusals(cls.res.admitted)

    def test_the_claim_is_gated_on_the_field_it_needs(self):
        self.assertEqual(self.res.admitted_n, 594)
        self.assertEqual(self.res.rejected_n, 417)

    def test_every_refusal_in_the_corpus_is_recognised_as_FINISHED(self):
        """If looks_finished misses one, it becomes TRUNCATED and vanishes from the denominator."""
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
        """0 missed in THIS corpus is not 0 missed in general. A novel phrasing that neither ends in
        punctuation nor matches the list would still be mislabelled."""
        novel = "Prediction unavailable"          # no terminal punctuation, no refusal opener
        self.assertFalse(CR.looks_finished(novel),
                         "documents the residual risk rather than claiming it away")


class NaturalTruncationSearch(unittest.TestCase):
    """L9: the reader's recall was measured on SEEDED cuts. Are there real ones to check against?"""

    @classmethod
    def setUpClass(cls):
        cls.res = CG.Claim("natural truncation search",
                           requires=["finish_reason", "text"]).admit(corpus())

    def test_the_claim_is_gated_on_finish_reason(self):
        """The 417 pre-capture records COULD NOT have shown a truncation -- counting them would turn
        absence of evidence into evidence of absence."""
        self.assertEqual(self.res.admitted_n, 594)
        self.assertEqual(self.res.missing_field_counts.get("finish_reason"), 417)

    def test_there_are_ZERO_natural_truncations(self):
        fr = collections.Counter(r.get("finish_reason") for r in self.res.admitted)
        self.assertEqual(dict(fr), {"stop": 594})
        nat = [r for r in self.res.admitted if r.get("finish_reason") == "length"]
        self.assertEqual(len(nat), 0)

    def test_the_invariant_holds_over_the_WHOLE_corpus_including_new_runs(self):
        """The count pins are frozen to a snapshot; THIS claim must hold over everything, forever.

        A first real truncation would most likely arrive in a NEW run, which is exactly the data the
        frozen snapshot cannot see -- so the invariant is checked separately and unfrozen.
        """
        res = CG.Claim("natural truncation, full corpus",
                       requires=["finish_reason", "text"]).admit(full_corpus())
        fr = collections.Counter(r.get("finish_reason") for r in res.admitted)
        self.assertGreaterEqual(res.admitted_n, 594, "the corpus should only ever grow")
        self.assertEqual(fr.get("length", 0), 0,
                         f"a natural truncation now exists in the corpus ({res.admitted_n} admitted "
                         f"records): RE-CALIBRATE the reader against it instead of relying on "
                         f"seeded cuts")

    def test_therefore_reader_recall_rests_entirely_on_seeded_cuts(self):
        """Not a failure -- a stated limitation, converted from a caveat into a measured fact.

        If a natural truncation ever appears, this test fails and the reader must be re-calibrated
        against it. That is the intended trigger, not a defect.
        """
        nat = [r for r in self.res.admitted if r.get("finish_reason") == "length"]
        self.assertEqual(len(nat), 0,
                         "a natural truncation now exists: RE-CALIBRATE the reader against it "
                         "instead of relying on seeded cuts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
