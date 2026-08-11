"""Selection of units for the follow-up arm."""
import json
import os
import unittest

import completeness_review as CR
import followup_select as FS

HERE = os.path.dirname(os.path.abspath(__file__))
FXGATE = os.path.join(HERE, "runs", "_frozen_fxgate_2026-08-08", "records.jsonl")   # FROZEN
ROSTER = os.path.join(HERE, "survey", "_snapshot_roster_2026-08-09.json")   # FROZEN: counts below are pinned to it

PROSE = "Because the underlying series has trended upward for six consecutive quarters and the " \
        "policy window closes before the resolution date, the balance of evidence favours yes. " \
        "I weigh the base rate against the recent revision and settle on the affirmative option."


def rec(model="a/one", item="q1|2026-07-01", verdict="COMPLETE", text=r"\boxed{A}",
        reasoning=None, **over):
    r = {"model": model, "item_id": item, "arm": "original", "completeness": verdict,
         "text": text, "reasoning": reasoning, "finish_reason": "stop", "ok": True}
    r.update(over)
    return r


class ItSelectsExactlyTheBareAnswers(unittest.TestCase):

    def test_a_terse_answer_is_selected(self):
        pairs, rep = FS.select([rec()])
        self.assertEqual([(p["model"], p["item_id"]) for p in pairs], [("a/one", "q1|2026-07-01")])
        self.assertEqual(rep["selected"], 1)

    def test_a_reply_that_reasoned_IN_PROSE_is_not_selected(self):
        self.assertEqual(FS.select([rec(text=PROSE + r" \boxed{A}")])[0], [])

    def test_a_reply_that_reasoned_ONLY_ON_THE_API_CHANNEL_is_not_selected(self):
        pairs, rep = FS.select([rec(reasoning=PROSE)])
        self.assertEqual(pairs, [])
        self.assertIn("excluded_already_reasoned:reasoning_field", rep["exclusions"])

    def test_prose_BELOW_the_threshold_still_counts_as_bare(self):
        short = "Yes." * 3
        self.assertLess(len(short), CR.REASONING_MIN_CHARS)
        self.assertEqual(len(FS.select([rec(text=short + r" \boxed{A}")])[0]), 1)

    def test_prose_AFTER_the_box_does_not_count(self):
        self.assertEqual(len(FS.select([rec(text=r"\boxed{A} " + PROSE)])[0]), 1)


class TheNearMissesAreRefused(unittest.TestCase):

    def test_a_TRUNCATED_reply_is_never_followed_up(self):
        pairs, rep = FS.select([rec(verdict="TRUNCATED")])
        self.assertEqual(pairs, [])
        self.assertEqual(rep["exclusions"]["excluded_not_scoreable:TRUNCATED"], 1)

    def test_a_PROVIDER_ERROR_is_never_followed_up(self):
        pairs, rep = FS.select([rec(verdict="PROVIDER_ERROR", text="", finish_reason=None)])
        self.assertEqual(pairs, [])
        self.assertIn("excluded_not_scoreable:PROVIDER_ERROR", rep["exclusions"])

    def test_a_REFUSAL_is_excluded_by_default_and_COUNTED_not_dropped(self):
        pairs, rep = FS.select([rec(verdict="NO_ANSWER", text="I can't fulfill that request.")])
        self.assertEqual(pairs, [])
        self.assertEqual(rep["exclusions"]["excluded_refusal_NO_ANSWER"], 1)
        self.assertEqual(rep["exclusions"]["refusals_that_were_also_bare"], 1)
        self.assertIn("EXCLUDED by default", rep["no_answer_policy"])

    def test_a_REFUSAL_is_included_only_when_asked_for_explicitly(self):
        pairs, rep = FS.select([rec(verdict="NO_ANSWER", text="I can't fulfill that request.")],
                               include_no_answer=True)
        self.assertEqual(len(pairs), 1)
        self.assertIn("INCLUDED", rep["no_answer_policy"])

    def test_a_model_outside_the_roster_is_excluded(self):
        pairs, rep = FS.select([rec(model="gone/dropped")], roster_ids={"a/one"})
        self.assertEqual(pairs, [])
        self.assertEqual(rep["exclusions"]["excluded_not_in_roster"], 1)

    def test_a_duplicate_unit_is_selected_once(self):
        pairs, rep = FS.select([rec(), rec()])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(rep["exclusions"]["excluded_duplicate_unit"], 1)

    def test_nothing_to_follow_up_yields_an_EMPTY_list_not_a_missing_one(self):
        pairs, rep = FS.select([rec(text=PROSE + r" \boxed{A}")])
        self.assertEqual(pairs, [])
        self.assertEqual(rep["selected"], 0)
        self.assertEqual(rep["reasoning_rate"], 1.0)


class OnTheRealStageOneRecords(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(FXGATE, encoding="utf-8") as fh:
            cls.recs = [json.loads(l) for l in fh if l.strip()]
        with open(ROSTER, encoding="utf-8") as fh:
            cls.ids = {m["id"] for m in json.load(fh)}

    def test_it_picks_the_18_bare_answers_and_nothing_else(self):
        pairs, rep = FS.select(self.recs, self.ids)
        self.assertEqual(rep["scoreable_records"], 398)
        self.assertEqual(len(pairs), 18)
        self.assertEqual(rep["already_reasoned"], 380)
        self.assertAlmostEqual(rep["reasoning_rate"], 0.9548, places=3)

    def test_the_follow_up_is_a_small_fraction_of_a_second_arm(self):
        pairs, _ = FS.select(self.recs, self.ids)
        self.assertLess(len(pairs) / 398, 0.06)

    def test_every_exclusion_is_accounted_for(self):
        pairs, rep = FS.select(self.recs, self.ids)
        self.assertEqual(sum(v for k, v in rep["exclusions"].items()
                             if k != "refusals_that_were_also_bare") + len(pairs),
                         len(self.recs))

    def test_the_pairs_are_runner_ready(self):
        pairs, _ = FS.select(self.recs, self.ids)
        for p in pairs:
            self.assertIn("model", p)
            self.assertIn("item_id", p)
            self.assertIn("selected_because", p)




class ReasoningCoverageIsReportedPerStage(unittest.TestCase):

    def setUp(self):
        import analyze as AN
        self.AN = AN

    def test_the_four_states_are_kept_apart(self):
        recs = [
            rec(model="m/self", item="i1", text=PROSE + r" \boxed{A}"),          # reasoned unasked
            rec(model="m/prompted", item="i2"),                                   # bare originally
            rec(model="m/prompted", item="i2", arm="cot", text=PROSE + r" \boxed{A}"),
            rec(model="m/stubborn", item="i3"),                                   # bare originally
            rec(model="m/stubborn", item="i3", arm="cot"),                        # STILL bare
            rec(model="m/pending", item="i4"),                                    # no follow-up yet
        ]
        c = self.AN.reasoning_coverage(recs)
        self.assertEqual(c["rows"]["m/self"]["from_base"], 1)
        self.assertEqual(c["rows"]["m/prompted"]["after_followup"], 1)
        self.assertEqual(c["rows"]["m/stubborn"]["absent_after_both"], 1)
        self.assertEqual(c["rows"]["m/pending"]["followup_not_run"], 1)

    def test_an_unrun_followup_is_not_scored_as_a_failure(self):
        c = self.AN.reasoning_coverage([rec(model="m/pending", item="i4")])
        self.assertIsNone(c["rows"]["m/pending"]["reasoning_rate_over_asked"])
        self.assertEqual(c["totals"]["reasoning_rate_over_asked"], None)

    def test_a_model_that_reasons_only_when_asked_is_visible_as_such(self):
        recs = [rec(model="m/prompted", item=f"i{i}") for i in range(4)] + \
               [rec(model="m/prompted", item=f"i{i}", arm="cot", text=PROSE + r" \boxed{A}")
                for i in range(4)]
        c = self.AN.reasoning_coverage(recs)["rows"]["m/prompted"]
        self.assertEqual(c["reasoning_rate_over_asked"], 1.0)   # every unit ends up with reasoning
        self.assertEqual(c["unprompted_rate"], 0.0)             # and none of it was volunteered


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheSelectorAndTheDeliverableCANNOTDisagree(unittest.TestCase):

    def setUp(self):
        import analyze as AN
        self.AN = AN

    def counts(self, recs, ids=None):
        sel, _ = FS.select(recs, ids)
        cov = self.AN.reasoning_coverage(recs, models=ids)
        return len(sel), cov["totals"].get("followup_not_run", 0)

    def test_they_agree_on_the_real_corpus(self):
        p = os.path.join(HERE, "runs", "_frozen_fxgate_2026-08-08", "records.jsonl")
        if not os.path.exists(p):
            self.skipTest("the fxgate corpus is not present")
        with open(p, encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        with open(ROSTER, encoding="utf-8") as fh:
            ids = {m["id"] for m in json.load(fh)}
        sel, cov = self.counts(recs, ids)
        self.assertEqual((sel, cov), (18, 18))

    def test_they_agree_on_a_refusal(self):
        recs = [rec(verdict="NO_ANSWER", text="I can't fulfill that request.")]
        self.assertEqual(self.counts(recs), (0, 0))

    def test_a_refusal_is_its_own_state_in_the_deliverable(self):
        recs = [rec(verdict="NO_ANSWER", text="I can't fulfill that request.")]
        c = self.AN.reasoning_coverage(recs)
        self.assertEqual(c["totals"].get("not_a_followup_candidate"), 1)
        self.assertEqual(c["totals"].get("followup_not_run", 0), 0)
