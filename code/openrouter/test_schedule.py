"""Call scheduling."""
import collections
import json
import os
import unittest

import manifest as MF
import schedule as SC

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))
ROSTER = json.load(open(os.path.join(HERE, "survey", "roster_refined.json")))


def m():
    return MF.build(ROSTER, ITEMS, arms=("original",))


class OrderIsFrozenAndReproducible(unittest.TestCase):
    def setUp(self):
        self.mf = m()

    def test_same_manifest_and_seed_give_the_same_order(self):
        a, b = SC.build(self.mf), SC.build(self.mf)
        self.assertEqual(a["order"], b["order"])
        self.assertEqual(a["schedule_id"], b["schedule_id"])

    def test_a_different_seed_gives_a_different_order(self):
        self.assertNotEqual(SC.build(self.mf)["order"], SC.build(self.mf, seed=1)["order"])

    def test_it_covers_every_unit_exactly_once(self):
        s = SC.build(self.mf)
        self.assertEqual(len(s["order"]), self.mf["n_units"])
        self.assertEqual(set(s["order"]), {u["unit_id"] for u in self.mf["units"]})

    def test_the_schedule_is_write_once(self):
        import tempfile
        s = SC.build(self.mf)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            SC.save(s, p)
            with self.assertRaises(SC.ScheduleError):
                SC.save(s, p)


class ItDoesNotBurstOneProvider(unittest.TestCase):

    def setUp(self):
        self.mf = m()

    def test_it_bounds_the_burst_on_the_REAL_manifest_not_just_a_fixture(self):
        real = json.load(open(os.path.join(HERE, "runs", "manifest_4d3477ce313573a7.json")))
        s = SC.build(real)
        longest = SC.max_provider_run(s, real)
        biggest_share = max(s["providers"].values()) / s["n_units"]
        # with an even spread the worst run is bounded by roughly 1/(1-share), not by queue length
        bound = max(4, int(2 / (1 - biggest_share)))
        self.assertLessEqual(longest, bound,
                             f"burst {longest} on the real manifest (bound {bound}); "
                             f"largest provider share {biggest_share:.1%}")

    def test_the_small_fixture_is_also_bounded(self):
        s = SC.build(self.mf)
        self.assertLessEqual(SC.max_provider_run(s, self.mf), len(s["providers"]))

    def test_the_SEEDED_DEFECT_a_model_grouped_order_bursts_badly(self):
        grouped = {**self.mf}
        grouped_units = sorted(self.mf["units"], key=lambda u: (u["model"], u["item_id"]))
        grouped["units"] = grouped_units
        fake = {"order": [u["unit_id"] for u in grouped_units], "providers": {}}
        burst = SC.max_provider_run(fake, grouped)
        good = SC.max_provider_run(SC.build(self.mf), self.mf)
        self.assertGreater(burst, good * 3,
                           "the grouped order must be markedly worse, or this test proves nothing")

    def test_per_provider_cap_is_recorded_as_a_CHOICE(self):
        s = SC.build(self.mf)
        self.assertIn("per_provider", s)
        self.assertIn("policy_version", s)


class ResumePreservesOrder(unittest.TestCase):
    def test_resume_replays_the_same_order_minus_completed(self):
        mf = m()
        s = SC.build(mf)
        done = set(s["order"][:10])
        rest = SC.resume_order(s, done)
        self.assertEqual(rest, [u for u in s["order"] if u not in done])
        self.assertEqual(len(rest), len(s["order"]) - 10)


class CensoringIsRecordedNeverAbsent(unittest.TestCase):

    def setUp(self):
        self.mf = m()

    def _rec(self, u, verdict="COMPLETE"):
        return {"model": u["model"], "item_id": u["item_id"], "arm": u["arm"],
                "completeness": verdict, "prompt_sha": u["prompt_sha"]}

    def test_the_census_partitions_the_plan_exactly(self):
        us = self.mf["units"]
        recs = [self._rec(u) for u in us[:5]]
        cen = SC.censor([u["unit_id"] for u in us[5:8]], "quarantined", trigger="PROVIDER_ERROR")
        c = SC.census(self.mf, recs, cen)
        self.assertEqual(c["planned"], self.mf["n_units"])
        self.assertEqual(c["OBSERVED"] + c["UNOBSERVED"] + c["NEEDS_INSPECTION"]
                         + c["CENSORED"] + c["MISSING"], c["planned"])
        self.assertEqual(c["CENSORED"], 3)
        self.assertEqual(c["OBSERVED"], 5)

    def test_a_censored_unit_is_not_counted_as_missing(self):
        us = self.mf["units"]
        cen = SC.censor([u["unit_id"] for u in us[:4]], "quarantined")
        c = SC.census(self.mf, [], cen)
        self.assertEqual(c["CENSORED"], 4)
        self.assertEqual(c["MISSING"], self.mf["n_units"] - 4)

    def test_an_unknown_censor_reason_is_refused(self):
        with self.assertRaises(SC.ScheduleError):
            SC.censor(["x"], "because")

    def test_a_censor_record_carries_its_reason_and_trigger(self):
        c = SC.censor(["u1"], "spend_ceiling", trigger="max-spend reached", when="2026-08-08")
        self.assertEqual(c[0]["reason"], "spend_ceiling")
        self.assertEqual(c[0]["trigger"], "max-spend reached")

    def test_every_bucket_is_present_even_at_zero(self):
        c = SC.census(self.mf, [], [])
        for k in ("OBSERVED", "UNOBSERVED", "NEEDS_INSPECTION", "CENSORED", "MISSING"):
            self.assertIn(k, c, f"{k} must be reported even when it is zero")
        self.assertEqual(c["OBSERVED"], 0)
        self.assertEqual(c["MISSING"], self.mf["n_units"])

    def test_needs_inspection_is_its_own_bucket(self):
        us = self.mf["units"]
        recs = [self._rec(us[0], "EMPTY_PARSE"), self._rec(us[1], "COMPLETE"),
                self._rec(us[2], "TRUNCATED")]
        c = SC.census(self.mf, recs, [])
        self.assertEqual(c["NEEDS_INSPECTION"], 1)
        self.assertEqual(c["OBSERVED"], 1)
        self.assertEqual(c["UNOBSERVED"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
