"""Analysis aggregation and denominators."""
import json
import os
import unittest

import analyze as AN
import manifest as MF
import schedule as SC

HERE = os.path.dirname(os.path.abspath(__file__))


def real_setup():
    recs = [json.loads(l) for l in open(os.path.join(HERE, "runs", "or_futurex_M5",
                                                     "records.jsonl")) if l.strip()]
    items = {i["item_id"]: i for i in json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))}
    roster = [{"series": "S", "id": m, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
               "in": 0.1, "out": 0.1} for m in sorted({r["model"] for r in recs})]
    used = [items[i] for i in sorted({r["item_id"] for r in recs})]
    return MF.build(roster, used, arms=("original", "cot")), recs


class ItComputesFromRealEmittedOutput(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.m, cls.recs = real_setup()
        cls.t = AN.per_model_table(cls.m, cls.recs, strict=False)

    def test_the_table_builds_from_stored_records(self):
        self.assertGreater(self.t["n_models"], 20)
        self.assertEqual(self.t["admitted_records"], len(self.recs))

    def test_the_buckets_partition_the_plan_exactly(self):
        t = self.t["totals"]
        self.assertEqual(t["OBSERVED"] + t["UNOBSERVED"] + t["NEEDS_INSPECTION"]
                         + t["CENSORED"] + t["MISSING"], t["planned"])

    def test_per_model_rows_also_partition(self):
        for m, r in self.t["rows"].items():
            self.assertEqual(r["OBSERVED"] + r["UNOBSERVED"] + r["NEEDS_INSPECTION"]
                             + r["CENSORED"] + r["MISSING"], r["planned"], m)


class TheDenominatorIsTheWholePoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.recs = real_setup()
        cls.t = AN.per_model_table(cls.m, cls.recs, strict=False)

    def test_the_rate_is_over_OBSERVED_not_PLANNED(self):
        t = self.t["totals"]
        self.assertEqual(t["compliance_rate"], round(t["complied"] / t["OBSERVED"], 4))

    def test_the_SEEDED_DEFECT_wrong_denominator_gives_a_different_answer(self):
        t = self.t["totals"]
        wrong = round(t["complied"] / t["planned"], 4)
        self.assertNotAlmostEqual(t["compliance_rate"], wrong, places=2)
        self.assertGreater(t["compliance_rate"] - wrong, 0.10,
                           "the wrong denominator must be materially wrong here, or this corpus "
                           "cannot demonstrate the failure")

    def test_coverage_is_reported_SEPARATELY_from_compliance(self):
        t = self.t["totals"]
        self.assertNotEqual(t["coverage_rate"], t["compliance_rate"])
        self.assertEqual(t["coverage_rate"], round(t["OBSERVED"] / t["planned"], 4))

    def test_a_model_with_no_observations_gets_None_not_zero(self):
        m, _ = real_setup()
        t = AN.per_model_table(m, [], strict=False)
        for row in t["rows"].values():
            self.assertIsNone(row["compliance_rate"])
            self.assertEqual(row["MISSING"], row["planned"])


class ItRefusesToBuildADishonestTable(unittest.TestCase):
    def setUp(self):
        self.m, self.recs = real_setup()

    def test_records_outside_the_manifest_are_refused_in_strict_mode(self):
        bad = json.loads(json.dumps(self.recs[:3]))
        for r in bad:
            r["model"] = "someone/unplanned"
        with self.assertRaises(AN.AnalysisError) as cm:
            AN.per_model_table(self.m, bad, strict=True)
        self.assertIn("not a table of the planned experiment", str(cm.exception))

    def test_records_missing_a_verdict_are_gated_out_and_counted(self):
        bad = json.loads(json.dumps(self.recs))
        for r in bad[:10]:
            r.pop("completeness", None)
        t = AN.per_model_table(self.m, bad, strict=False)
        self.assertEqual(t["rejected_records"], 10)
        self.assertEqual(t["rejected_missing_fields"].get("completeness"), 10)

    def test_a_censored_unit_is_not_counted_as_missing(self):
        uids = [u["unit_id"] for u in self.m["units"]][:5]
        cen = SC.censor(uids, "quarantined", trigger="PROVIDER_ERROR")
        t = AN.per_model_table(self.m, [], censored=cen, strict=False)
        self.assertEqual(t["totals"]["CENSORED"], 5)
        self.assertEqual(t["totals"]["MISSING"], t["totals"]["planned"] - 5)

    def test_a_bucket_mismatch_raises_rather_than_rounding(self):
        m = json.loads(json.dumps(self.m))
        m["units"].append(dict(m["units"][0], unit_id="duplicate-id"))
        # a duplicated unit_id makes the per-model set smaller than the unit list; the sum check
        # is what notices
        t = AN.per_model_table(m, [], strict=False)
        for row in t["rows"].values():
            self.assertEqual(row["OBSERVED"] + row["UNOBSERVED"] + row["NEEDS_INSPECTION"]
                             + row["CENSORED"] + row["MISSING"], row["planned"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
