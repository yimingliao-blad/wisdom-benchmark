"""Claim gate over recorded results."""
import json
import os
import unittest

import claim_gate as CG
import corpus_profile as CP

HERE = os.path.dirname(os.path.abspath(__file__))


class S3_RealCorpus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.profile = CP.profile()
        cls.corpus = CG.load_corpus()

    def test_the_profile_matches_the_corpus_the_gate_reads(self):
        self.assertEqual(self.profile["records_ok"], len(self.corpus),
                         "the profiler and the gate must read the same corpus")

    def test_truncation_claim_admits_only_records_that_could_show_a_truncation(self):
        full = self.profile["generations"]["full_capture"]["n"]
        pre = self.profile["generations"]["pre_capture"]["n"]
        c = CG.Claim("natural truncation rate", requires=["finish_reason", "text"])
        r = c.admit(self.corpus)
        self.assertEqual(r.admitted_n, full)
        self.assertEqual(r.rejected_n, pre)
        self.assertEqual(r.missing_field_counts.get("finish_reason"), pre,
                         "every rejected record must be rejected FOR the named field")

    def test_a_reasoning_claim_admits_fewer_than_full_capture(self):
        c = CG.Claim("reasoning presence rate", requires=["reasoning", "text"])
        r = c.admit(self.corpus)
        full = self.profile["generations"]["full_capture"]["n"]
        self.assertLess(r.admitted_n, full,
                        "if this ever equals full-capture, the corpus changed and the claim's "
                        "admissible set must be re-derived")
        self.assertGreater(r.admitted_n, 0)

    def test_cost_claims_admit_the_pre_capture_records(self):
        c = CG.Claim("cost per call", requires=["cost", "usage"])
        r = c.admit(self.corpus)
        self.assertGreater(r.admitted_n, self.profile["generations"]["full_capture"]["n"],
                           "a cost claim must reach beyond full-capture into the older records")


class S4_TheGateCanFail(unittest.TestCase):

    def setUp(self):
        self.corpus = CG.load_corpus()
        self.full = CP.profile()["generations"]["full_capture"]["n"]

    def test_defect_a_permissive_gate_silently_admits_everything(self):
        with self.assertRaises(CG.ClaimError):
            CG.Claim("truncation, undeclared", requires=[])
        # and the seeded permissive version would swallow the whole corpus
        def permissive(records, requires):
            return records                      # the defect
        self.assertEqual(len(permissive(self.corpus, ["finish_reason"])), len(self.corpus))
        real = CG.Claim("truncation", requires=["finish_reason"]).admit(self.corpus)
        self.assertNotEqual(real.admitted_n, len(self.corpus),
                            "the real gate must NOT admit what the permissive defect admits")

    def test_defect_b_a_null_field_counted_as_present(self):
        rec = {"ok": True, "text": "answer", "finish_reason": None}
        self.assertFalse(CG.field_present(rec, "finish_reason"))
        broken = lambda r, f: f in r            # the defect: presence by key only
        self.assertTrue(broken(rec, "finish_reason"),
                        "the seeded defect must disagree with the real rule, or this is vacuous")
        r = CG.Claim("truncation", requires=["finish_reason"]).admit(
            [rec, {"ok": True, "finish_reason": "stop"}])
        self.assertEqual(r.admitted_n, 1)
        self.assertEqual(r.rejected_n, 1)

    def test_defect_c_silent_filtering_hides_the_loss(self):
        r = CG.Claim("truncation", requires=["finish_reason", "text"]).admit(self.corpus)
        self.assertTrue(r.rejected, "the rejected set must be returned, not discarded")
        self.assertIn("finish_reason", r.missing_field_counts)
        self.assertTrue(r.rejected_by_field("finish_reason"),
                        "the caller must be able to enumerate WHICH records were dropped and why")
        silent = [x for x in self.corpus if CG.field_present(x, "finish_reason")]   # the defect
        self.assertEqual(len(silent), r.admitted_n,
                         "same admitted set, but the silent version returns no loss information")

    def test_rule_4_zero_evidence_halts(self):
        with self.assertRaises(CG.ClaimError):
            CG.Claim("impossible", requires=["a_field_no_record_has"]).admit(self.corpus)

    def test_an_unnamed_claim_is_refused(self):
        with self.assertRaises(CG.ClaimError):
            CG.Claim("", requires=["cost"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
