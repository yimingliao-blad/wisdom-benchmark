"""Smoke acceptance criteria."""
import json
import os
import shutil
import tempfile
import unittest

import finalize as FZ
import smoke_acceptance as SA
from test_finalize import build_run_dir


# Comfortably past completeness_review's 120-character reasoning threshold. The first draft of this
# fixture was 103 characters and the checker correctly called it bare -- a reminder that the fixture
# has to clear the real bar, not look like it does.
LONG_REASONING = (
    "The indicator rose in each of the last four reporting periods and the underlying driver has "
    "not reversed, so continuation is the base case rather than a turning point. I weighed the "
    "seasonality counter-argument and found it too small to flip the sign.")


def rewrite(d, fn):
    p = os.path.join(d, "records.jsonl")
    recs = [json.loads(l) for l in open(p) if l.strip()]
    recs = fn(recs) or recs
    with open(p, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return recs


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def healthy(self):
        build_run_dir(self.d, n_models=18)
        rewrite(self.d, lambda recs: [dict(r, reasoning=LONG_REASONING, n_choices=1, ok=True)
                                      for r in recs])
        FZ.finalize(self.d)
        return SA.evaluate(self.d)

    def verdict(self, rep, cid):
        return next(r for r in rep["results"] if r["id"] == cid)


class AHealthyRunClears(Base):
    def test_every_criterion_passes(self):
        rep = self.healthy()
        bad = [(r["id"], r["verdict"], r["detail"]) for r in rep["results"]
               if r["verdict"] != "PASS"]
        self.assertEqual(bad, [], f"a healthy run did not clear: {bad}")
        self.assertTrue(rep["cleared"])


class M1ReasoningIsMEASUREDNotGated(Base):

    def test_it_is_NOT_in_the_pass_fail_criteria(self):
        rep = self.healthy()
        self.assertNotIn("M1", [r["id"] for r in rep["results"]])
        self.assertNotIn("A1", [r["id"] for r in rep["results"]])
        self.assertIn("M1", [m["id"] for m in rep["measurements"]])

    def test_a_ZERO_reasoning_rate_does_NOT_block_the_run(self):
        build_run_dir(self.d)
        rewrite(self.d, lambda recs: [dict(r, reasoning="", text="\\boxed{Yes}") for r in recs])
        FZ.finalize(self.d)
        rep = SA.evaluate(self.d)
        m1 = next(m for m in rep["measurements"] if m["id"] == "M1")
        self.assertEqual(m1["verdict"], "MEASURED")
        self.assertEqual(m1["evidence"]["rate"], 0.0)
        self.assertTrue(rep["cleared"], "a measurement must not decide clearance")

    def test_it_still_reports_the_rate_AND_its_confidence_bound(self):
        rep = self.healthy()
        m1 = next(m for m in rep["measurements"] if m["id"] == "M1")
        self.assertEqual(m1["evidence"]["rate"], 1.0)
        self.assertIn("wilson_lower_95", m1["evidence"])
        self.assertIn("CI lower bound", m1["detail"])

    def test_it_names_WHICH_models_answered_bare(self):
        build_run_dir(self.d)

        def strip_beta(recs):
            for r in recs:
                r["reasoning"] = LONG_REASONING
                if r["model"] == "beta/one":
                    r["reasoning"], r["text"] = "", "\\boxed{Yes}"
            return recs
        rewrite(self.d, strip_beta)
        FZ.finalize(self.d)
        m1 = next(m for m in SA.evaluate(self.d)["measurements"] if m["id"] == "M1")
        self.assertEqual(m1["evidence"]["bare_models"], ["beta/one"])

    def test_no_observed_replies_is_UNKNOWN_not_a_number(self):
        build_run_dir(self.d)
        rewrite(self.d, lambda recs: [dict(r, completeness="PROVIDER_ERROR", compliant=None,
                                           answer_extractable=False) for r in recs])
        v = SA.m1_reasoning_rate([json.loads(l) for l in
                                  open(os.path.join(self.d, "records.jsonl"))])
        self.assertEqual(v.verdict, "UNKNOWN")


class EachCriterionCanFail(Base):
    def test_A2_a_missing_sidecar_row(self):
        build_run_dir(self.d, sidecar="missing_one")
        recs = [json.loads(l) for l in open(os.path.join(self.d, "records.jsonl"))]
        self.assertEqual(SA.a2_sidecar_one_to_one(recs, run_dir=self.d).verdict, "FAIL")

    def test_A3_a_billed_call_absent_from_the_ledger(self):
        build_run_dir(self.d)
        lp = os.path.join(self.d, "ledger.json")
        led = json.load(open(lp))
        led["entries"] = led["entries"][:-1]
        led["total"] = round(sum(e["actual"] for e in led["entries"]), 8)
        json.dump(led, open(lp, "w"))
        r = SA.a3_ledger_reconciles(
            [json.loads(l) for l in open(os.path.join(self.d, "records.jsonl"))], run_dir=self.d)
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("understated", r.detail)

    def test_A4_a_multi_choice_envelope(self):
        build_run_dir(self.d)
        recs = rewrite(self.d, lambda rs: [dict(r, n_choices=2) for r in rs])
        self.assertEqual(SA.a4_no_unhandled_schema(recs).verdict, "FAIL")

    def test_A5_an_unclassified_failure(self):
        build_run_dir(self.d)
        recs = rewrite(self.d, lambda rs: [dict(rs[0], ok=False, failure_class=None,
                                                completeness_prelabel=None)] + rs[1:])
        self.assertEqual(SA.a5_provider_errors_are_classified(recs).verdict, "FAIL")

    def test_A5_an_UNDECIDED_record(self):
        build_run_dir(self.d)
        recs = rewrite(self.d, lambda rs: [dict(rs[0], completeness="UNDECIDED")] + rs[1:])
        r = SA.a5_provider_errors_are_classified(recs)
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("UNDECIDED", r.detail)

    def test_A6_a_real_cap_breach_reconstructed_from_the_timestamps(self):
        build_run_dir(self.d)
        sp = os.path.join(self.d, "schedule.json")
        sched = json.load(open(sp))
        sched["per_provider"] = 1
        json.dump(sched, open(sp, "w"))
        # make every alpha call overlap every other alpha call
        recs = rewrite(self.d, lambda rs: [dict(r, started_at=1000.0, ended_at=1010.0)
                                           if r["model"].startswith("alpha") else r for r in rs])
        r = SA.a6_per_provider_cap_held(recs, run_dir=self.d)
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("BREACHED", r.detail)
        self.assertGreater(r.evidence["observed_peak"]["alpha"], 1)

    def test_A6_passes_on_non_overlapping_calls(self):
        build_run_dir(self.d)
        recs = [json.loads(l) for l in open(os.path.join(self.d, "records.jsonl"))]
        r = SA.a6_per_provider_cap_held(recs, run_dir=self.d)
        self.assertEqual(r.verdict, "PASS")

    def test_A7_a_pending_record(self):
        build_run_dir(self.d, pending=True)
        recs = [json.loads(l) for l in open(os.path.join(self.d, "records.jsonl"))]
        self.assertEqual(SA.a7_pending_review_resolved(recs).verdict, "FAIL")

    def test_A8_quarantined_units_hiding_in_MISSING(self):
        build_run_dir(self.d, quarantine={"beta/one": "PROVIDER_ERROR"})
        FZ.finalize(self.d)
        t = json.load(open(os.path.join(self.d, "analysis_table.json")))
        t["totals"]["CENSORED"], t["totals"]["MISSING"] = 0, t["totals"]["CENSORED"]
        json.dump(t, open(os.path.join(self.d, "analysis_table.json"), "w"))
        r = SA.a8_quarantine_became_censored([], run_dir=self.d)
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("hiding in", r.detail)

    def test_A9_only_a_provisional_table(self):
        build_run_dir(self.d, pending=True)
        FZ.finalize(self.d)
        r = SA.a9_deliverable_exists([], run_dir=self.d)
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("not publishable", r.detail.replace("nothing is publishable",
                                                          "not publishable"))

    def test_A10_a_misassociated_record(self):
        build_run_dir(self.d)
        recs = rewrite(self.d, lambda rs: [dict(rs[0], prompt_sha="0" * 16)] + rs[1:])
        self.assertEqual(SA.a10_records_prove_their_request(recs, run_dir=self.d).verdict, "FAIL")


class A11CatchesASelfContradictoryVerdict(Base):

    def test_the_self_contradicting_shape_is_caught(self):
        # The shape is the subject, not the vendor: a TRUNCATED verdict on a record that finished
        # cleanly and parsed a compliant answer. A real model id here would imply the check is
        # about that model.
        recs = [{"model": "vendor-a/model-1", "unit_id": "u1", "completeness": "TRUNCATED",
                 "completeness_by": "layer2", "finish_reason": "stop",
                 "parsed": {"answer": ["C"], "n_boxes": 1, "compliant": True}}]
        r = SA.a11_verdicts_are_not_self_contradictory(recs)
        self.assertEqual(r.verdict, "FAIL")
        self.assertEqual(r.evidence["by_decider"], {"layer2": 1})

    def test_NO_ANSWER_with_an_extracted_answer_is_caught(self):
        recs = [{"model": "m", "completeness": "NO_ANSWER", "completeness_by": "layer1",
                 "parsed": {"compliant": True}}]
        self.assertEqual(SA.a11_verdicts_are_not_self_contradictory(recs).verdict, "FAIL")

    def test_COMPLETE_with_no_answer_is_caught(self):
        recs = [{"model": "m", "completeness": "COMPLETE", "completeness_by": "layer1",
                 "parsed": {"compliant": False}}]
        self.assertEqual(SA.a11_verdicts_are_not_self_contradictory(recs).verdict, "FAIL")

    def test_a_consistent_set_PASSES(self):
        recs = [{"model": "m", "completeness": "COMPLETE", "finish_reason": "stop",
                 "parsed": {"compliant": True}},
                {"model": "m2", "completeness": "TRUNCATED", "finish_reason": "length",
                 "parsed": {"compliant": False}}]
        self.assertEqual(SA.a11_verdicts_are_not_self_contradictory(recs).verdict, "PASS")


class A12TheAnswerItselfIsEvaluated(Base):

    def _with_box(self, box):
        build_run_dir(self.d)
        recs = rewrite(self.d, lambda rs: [dict(r, parsed={"raw_box": box, "n_boxes": 1,
                                                           "compliant": True},
                                                answer_interpretable=None) for r in rs])
        return SA.a12_answers_are_INTERPRETABLE(recs, run_dir=self.d)

    def test_a_healthy_run_passes(self):
        v = self.verdict(self.healthy(), "A12")
        self.assertEqual(v["verdict"], "PASS")
        self.assertEqual(v["evidence"]["n_uninterpretable"], 0)

    def test_a_HEDGE_in_a_well_formed_box_FAILS(self):
        r = self._with_box("maybe")
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("hedge", r.detail + str(r.evidence))

    def test_a_PLACEHOLDER_FAILS(self):
        self.assertEqual(self._with_box("N/A").verdict, "FAIL")

    def test_an_EMPTY_box_FAILS(self):
        self.assertEqual(self._with_box("").verdict, "FAIL")

    def test_an_OPTION_THE_QUESTION_NEVER_OFFERED_FAILS(self):
        r = self._with_box("Z")
        self.assertEqual(r.verdict, "FAIL")

    def test_a_STAMP_DISAGREEMENT_FAILS(self):
        build_run_dir(self.d)
        recs = rewrite(self.d, lambda rs: [dict(r, answer_interpretable=False) for r in rs])
        r = SA.a12_answers_are_INTERPRETABLE(recs, run_dir=self.d)
        self.assertEqual(r.verdict, "FAIL")
        self.assertIn("disagree", r.detail)

    def test_WITHOUT_the_questions_it_is_UNKNOWN_not_PASS(self):
        build_run_dir(self.d)
        os.remove(os.path.join(self.d, "items.json"))
        recs = [json.loads(l) for l in open(os.path.join(self.d, "records.jsonl"))]
        r = SA.a12_answers_are_INTERPRETABLE(recs, run_dir=self.d)
        self.assertEqual(r.verdict, "UNKNOWN",
                         "unable to check must never read as checked-and-fine")


class AnUnevaluatedCriterionIsNotAPass(Base):
    def test_UNKNOWN_blocks_clearance(self):
        build_run_dir(self.d)
        FZ.finalize(self.d)
        os.remove(os.path.join(self.d, "manifest.json"))     # A10 can no longer be evaluated
        rep = SA.evaluate(self.d)
        self.assertEqual(self.verdict(rep, "A10")["verdict"], "UNKNOWN")
        self.assertFalse(rep["cleared"],
                         "an unevaluated criterion was treated as a pass -- the exact failure this "
                         "whole plan exists to prevent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
