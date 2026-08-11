"""Record persistence, resume and duplicate detection."""
import json
import os
import unittest

import manifest as MF
import persistence as PS

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))
ROSTER = json.load(open(os.path.join(HERE, "survey", "roster_refined.json")))[:3]


def mf():
    return MF.build(ROSTER, ITEMS, arms=("original",))


def rec(u, verdict="COMPLETE", **kw):
    return {"model": u["model"], "item_id": u["item_id"], "arm": u["arm"],
            "completeness": verdict, "prompt_sha": u["prompt_sha"], **kw}


class OneKeyNotTwo(unittest.TestCase):

    def test_the_resume_key_is_the_manifest_key(self):
        m = mf()
        u = m["units"][0]
        self.assertEqual(PS.record_unit_id(rec(u)), u["unit_id"],
                         "resume and the manifest must use the SAME key function")

    def test_key_drift_is_detected_not_silent(self):
        m = mf()
        self.assertEqual(PS.assert_resume_key_matches_manifest(m), m["n_units"])
        tampered = json.loads(json.dumps(m))
        tampered["units"][0]["unit_id"] = "0" * 16
        with self.assertRaises(PS.PersistenceError) as cm:
            PS.assert_resume_key_matches_manifest(tampered)
        self.assertIn("resume key drift", str(cm.exception))


class DuplicatesAreDataNotSilentlyResolved(unittest.TestCase):
    def setUp(self):
        self.m = mf()

    def test_a_duplicate_within_one_run_is_an_ERROR(self):
        u = self.m["units"][0]
        with self.assertRaises(PS.PersistenceError) as cm:
            PS.require_unique_within_run([rec(u), rec(u)])
        self.assertIn("more than once", str(cm.exception))

    def test_a_clean_run_passes(self):
        recs = [rec(u) for u in self.m["units"]]
        self.assertEqual(PS.require_unique_within_run(recs), len(recs))

    def test_a_MISSING_verdict_is_not_a_disagreement(self):
        u = self.m["units"][0]
        pair = [rec(u, "COMPLETE"), rec(u, None)]
        self.assertEqual(PS.verdict_conflicts(pair), {},
                         "a record with no verdict cannot disagree with one that has a verdict")

    def test_a_GENUINE_disagreement_is_reported(self):
        u = self.m["units"][0]
        c = PS.verdict_conflicts([rec(u, "COMPLETE"), rec(u, "NO_ANSWER")])
        self.assertEqual(len(c), 1)
        self.assertEqual(list(c.values())[0]["verdicts"], ["COMPLETE", "NO_ANSWER"])

    def test_the_real_corpus_has_exactly_the_measured_conflicts(self):
        import claim_gate as CG
        corpus = CG.load_snapshot(ok_only=False)
        dups = PS.find_duplicates(corpus)
        conflicts = PS.verdict_conflicts(corpus)
        self.assertEqual(len(dups), 237, "duplicated units across the 9 snapshot runs")
        self.assertEqual(len(conflicts), 4, "GENUINELY conflicting verdicts, not 222")

    def test_the_INVARIANT_holds_over_the_WHOLE_corpus_including_new_runs(self):
        import claim_gate as CG
        import collections as _c
        import glob as _g
        import json as _j
        import os as _o
        here = _o.path.dirname(_o.path.abspath(__file__))
        for f in sorted(_g.glob(_o.path.join(here, "runs", "or_*", "records.jsonl"))):
            recs = [_j.loads(l) for l in open(f) if l.strip()]
            # THE INVARIANT IS "NEVER PAID TWICE", not "never appears twice" (corrected 2026-08-10).
            # D-OR-18 re-queues a unit whose first attempt delivered nothing, so a resumed run
            # legitimately holds the failed attempt AND the answer. The paid smoke produced exactly
            # that: gpt-5.5 as PROVIDER_ERROR then COMPLETE, llama-3.1-8b as two PROVIDER_ERRORs at
            # $0.00 each. Asserting on row-presence would have made every resumed run fail, and the
            # obvious way to "fix" that is to delete the record of the failed attempt -- destroying
            # the evidence D-OR-16 exists to preserve.
            paid_twice = PS.bought_twice(recs)
            self.assertEqual(paid_twice, {},
                             f"{_o.path.basename(_o.path.dirname(f))} DELIVERED a unit twice")


class ResumeIsFaithful(unittest.TestCase):
    def setUp(self):
        self.m = mf()

    def test_resume_reports_exactly_what_is_left(self):
        recs = [rec(u) for u in self.m["units"][:5]]
        st = PS.resume_state(self.m, recs)
        self.assertEqual(st["done"], 5)
        self.assertEqual(len(st["todo"]), self.m["n_units"] - 5)

    def test_resume_never_re_buys_a_completed_unit(self):
        recs = [rec(u) for u in self.m["units"]]
        self.assertEqual(PS.resume_state(self.m, recs)["todo"], [])

    def test_resume_REFUSES_when_a_record_is_not_in_the_manifest(self):
        recs = [rec(self.m["units"][0])]
        recs[0]["model"] = "someone/not-planned"
        with self.assertRaises(PS.PersistenceError) as cm:
            PS.resume_state(self.m, recs)
        self.assertIn("manifest changed under the run", str(cm.exception))

    def test_non_strict_resume_reports_the_unplanned_instead_of_raising(self):
        recs = [rec(self.m["units"][0])]
        recs[0]["item_id"] = "not-a-planned-item"
        st = PS.resume_state(self.m, recs, strict=False)
        self.assertEqual(len(st["unplanned"]), 1)


class CombiningRunsIsANamedDecision(unittest.TestCase):

    def test_combining_is_forbidden_by_default(self):
        with self.assertRaises(PS.PersistenceError) as cm:
            PS.combine_runs([[{"model": "m", "item_id": "i", "arm": "original"}]])
        self.assertIn("DIFFERENT observations", str(cm.exception))

    def test_an_explicit_policy_requires_a_written_reason(self):
        with self.assertRaises(PS.PersistenceError):
            PS.combine_runs([[]], policy="explicit_latest")

    def test_explicit_latest_deduplicates_on_the_record(self):
        u = mf()["units"][0]
        out = PS.combine_runs([[rec(u, "NO_ANSWER")], [rec(u, "COMPLETE")]],
                              policy="explicit_latest", note="re-run after the reader fix")
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["records"][0]["completeness"], "COMPLETE")
        self.assertTrue(out["note"])

    def test_explicit_all_keeps_both_observations(self):
        u = mf()["units"][0]
        out = PS.combine_runs([[rec(u, "NO_ANSWER")], [rec(u, "COMPLETE")]],
                              policy="explicit_all", note="studying nondeterminism")
        self.assertEqual(out["n"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
