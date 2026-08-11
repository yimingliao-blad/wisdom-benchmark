"""Manifest construction and identity."""
import json
import os
import unittest

import manifest as MF
import bench_formats as BF

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))
ROSTER = json.load(open(os.path.join(HERE, "survey", "roster_refined.json")))[:3]


def small_manifest():
    return MF.build(ROSTER, ITEMS, arms=("original",))


def record_for(unit, sha=None):
    return {"model": unit["model"], "item_id": unit["item_id"], "arm": unit["arm"],
            "ok": True, "prompt_sha": sha if sha is not None else unit["prompt_sha"]}


class TheManifestIsAnArtifact(unittest.TestCase):
    def test_it_freezes_the_full_cross_product(self):
        m = small_manifest()
        self.assertEqual(m["n_units"], len(ROSTER) * len(ITEMS))
        self.assertEqual(len({u["unit_id"] for u in m["units"]}), m["n_units"])

    def test_the_hash_is_of_the_prompt_the_RUNNER_will_send(self):
        m = small_manifest()
        u = m["units"][0]
        it = next(i for i in ITEMS if i["item_id"] == u["item_id"])
        self.assertEqual(u["prompt_sha"], MF._sha(BF.futurex_render(it, u["arm"])))

    def test_determinism_same_inputs_same_id(self):
        self.assertEqual(small_manifest()["manifest_id"], small_manifest()["manifest_id"])

    def test_different_inputs_different_id(self):
        a = small_manifest()
        b = MF.build(ROSTER[:2], ITEMS, arms=("original",))
        self.assertNotEqual(a["manifest_id"], b["manifest_id"])

    def test_it_is_derived_from_the_VALIDATED_corpus(self):
        bad = json.loads(json.dumps(ITEMS)); bad[0]["prompt"] = ""
        with self.assertRaises(Exception):
            MF.build(ROSTER, bad, arms=("original",))


class TheDrawIsSeededAndBalanced(unittest.TestCase):
    def setUp(self):
        # a pool deliberately NON-uniform across levels, like the real one (36.6/39.6/11.7/12.0)
        self.pool = ([{"item_id": f"a{i}", "level": 1} for i in range(366)]
                     + [{"item_id": f"b{i}", "level": 2} for i in range(396)]
                     + [{"item_id": f"c{i}", "level": 3} for i in range(117)]
                     + [{"item_id": f"d{i}", "level": 4} for i in range(121)])

    def test_a_seeded_draw_is_reproducible(self):
        x, _ = MF.draw_items(self.pool, 100)
        y, _ = MF.draw_items(self.pool, 100)
        self.assertEqual([i["item_id"] for i in x], [i["item_id"] for i in y])

    def test_the_band_comes_from_the_POOL_not_from_25_25_25_25(self):
        _, info = MF.draw_items(self.pool, 100)
        self.assertAlmostEqual(info["pool_fracs"][1], 0.366, places=2)
        self.assertNotAlmostEqual(info["pool_fracs"][1], 0.25, places=2)

    def test_a_PREFIX_draw_would_halt_the_gate(self):
        prefix = self.pool[:100]
        import collections
        got = collections.Counter(i["level"] for i in prefix)
        self.assertEqual(got[1], 100, "the fixture must make a prefix pathological")
        # and the real draw must NOT look like that
        picked, _ = MF.draw_items(self.pool, 100)
        self.assertLess(collections.Counter(i["level"] for i in picked)[1], 100)

    def test_an_off_band_draw_HALTS(self):
        with self.assertRaises(MF.ManifestError) as cm:
            MF.draw_items(self.pool, 100, tol=0.001)      # a band nothing can satisfy
        self.assertIn("balance gate HALT", str(cm.exception))


class ARecordMustProveItsRequest(unittest.TestCase):

    def setUp(self):
        self.m = small_manifest()

    def test_matching_records_are_clean(self):
        recs = [record_for(u) for u in self.m["units"]]
        r = MF.verify_records_against(self.m, recs)
        self.assertTrue(r["clean"])
        self.assertEqual(r["counts"]["MATCH"], self.m["n_units"])
        self.assertEqual(r["counts"]["MISSING"], 0)

    def test_a_ONE_CHARACTER_hash_change_is_caught(self):
        recs = [record_for(u) for u in self.m["units"]]
        bad = recs[0]["prompt_sha"]
        recs[0]["prompt_sha"] = ("0" if bad[0] != "0" else "1") + bad[1:]
        r = MF.verify_records_against(self.m, recs)
        self.assertEqual(r["counts"].get("MISASSOCIATED"), 1)
        self.assertFalse(r["clean"])
        d = [x for x in r["detail"] if x["verdict"] == "MISASSOCIATED"][0]
        self.assertIn("planned_sha", d)
        self.assertIn("record_sha", d)

    def test_a_record_for_an_unplanned_unit_is_caught(self):
        recs = [record_for(self.m["units"][0])]
        recs[0]["model"] = "someone/not-in-the-roster"
        r = MF.verify_records_against(self.m, recs)
        self.assertEqual(r["counts"].get("UNPLANNED"), 1)
        self.assertFalse(r["clean"])

    def test_a_planned_unit_with_no_record_is_MISSING(self):
        recs = [record_for(u) for u in self.m["units"][:-2]]
        r = MF.verify_records_against(self.m, recs)
        self.assertEqual(r["counts"]["MISSING"], 2)
        self.assertTrue(r["missing_units"])

    def test_a_record_with_no_hash_cannot_pass_as_clean(self):
        recs = [record_for(u) for u in self.m["units"]]
        recs[0].pop("prompt_sha")
        r = MF.verify_records_against(self.m, recs)
        self.assertEqual(r["counts"].get("NO_HASH"), 1)
        self.assertNotEqual(r["counts"].get("MATCH"), self.m["n_units"])


class ImmutabilityIsWriteOnce(unittest.TestCase):
    def test_saving_over_an_existing_manifest_is_refused(self):
        import tempfile
        m = small_manifest()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m.json")
            MF.save(m, p)
            with self.assertRaises(MF.ManifestError) as cm:
                MF.save(m, p)
            self.assertIn("WRITE-ONCE", str(cm.exception))

    def test_a_superseding_manifest_records_why(self):
        m = MF.build(ROSTER[:2], ITEMS, arms=("original",),
                     supersedes="abc123", reason="roster trimmed")
        self.assertEqual(m["supersedes"], "abc123")
        self.assertEqual(m["reason"], "roster trimmed")


class AttemptIdentity(unittest.TestCase):

    def test_attempt_ids_differ_across_kinds_and_numbers(self):
        uid = MF.unit_id("m", "i", "original")
        a = MF.attempt_id(uid, 1, "first")
        self.assertNotEqual(a, MF.attempt_id(uid, 2, "retry"))
        self.assertNotEqual(a, MF.attempt_id(uid, 1, "resumed"))

    def test_an_unknown_attempt_kind_is_refused(self):
        with self.assertRaises(MF.ManifestError):
            MF.attempt_id(MF.unit_id("m", "i", "original"), 1, "whatever")


if __name__ == "__main__":
    unittest.main(verbosity=2)
