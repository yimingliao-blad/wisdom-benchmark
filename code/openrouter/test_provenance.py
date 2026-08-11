"""Provenance bundle contents."""
import json
import os
import tempfile
import unittest

import analyze as AN
import manifest as MF
import provenance as PV
import schedule as SC
import spend as SP

HERE = os.path.dirname(os.path.abspath(__file__))
RECS = os.path.join(HERE, "runs", "or_futurex_M5", "records.jsonl")


def real_setup():
    recs = [json.loads(l) for l in open(RECS) if l.strip()]
    items = {i["item_id"]: i for i in json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))}
    roster = [{"series": "S", "id": m, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
               "in": 0.1, "out": 0.1} for m in sorted({r["model"] for r in recs})]
    used = [items[i] for i in sorted({r["item_id"] for r in recs})]
    m = MF.build(roster, used, arms=("original", "cot"))
    s = SC.build(m)
    t = AN.per_model_table(m, recs, strict=False)
    return m, s, t, recs


class ABundleBindsARealPublishedTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.s, cls.t, cls.recs = real_setup()
        cls.b = PV.build(cls.m, cls.s, cls.t, RECS)

    def test_it_binds_the_inputs(self):
        self.assertEqual(self.b["manifest_id"], self.m["manifest_id"])
        self.assertEqual(self.b["schedule_id"], self.s["schedule_id"])
        self.assertEqual(self.b["roster_hash"], self.m["roster_hash"])

    def test_it_binds_the_OUTPUT_too(self):
        self.assertEqual(self.b["table_sha"], PV._sha_obj(self.t))
        self.assertEqual(self.b["table_totals"], self.t["totals"])

    def test_it_binds_every_module_that_can_change_a_number(self):
        for f in ("completeness_review.py", "analyze.py", "run_openrouter.py", "response_schema.py",
                  "finalize.py"):
            self.assertIn(f, self.b["code_sha"])
        self.assertEqual(len(self.b["code_sha"]), len(PV.CODE_FILES))

    def test_the_VERIFIER_is_bound_SEPARATELY_from_the_computation(self):
        self.assertIn("provenance.py", self.b["verifier_sha"])
        self.assertNotIn("provenance.py", self.b["code_sha"])

    def test_a_weakened_VERIFIER_is_caught(self):
        b = json.loads(json.dumps(self.b))
        b["verifier_sha"]["provenance.py"] = "0" * 16
        v = PV.verify(b)
        self.assertTrue(any("verifier_sha: provenance.py changed" in m for m in v["mismatches"]))

    def test_the_bundle_id_is_derived_from_what_it_binds(self):
        again = PV.build(self.m, self.s, self.t, RECS)
        self.assertEqual(again["bundle_id"], self.b["bundle_id"], "same inputs -> same id")

    def test_it_states_that_it_is_NOT_the_semantic_authority(self):
        note = self.b["authority_note"].lower()
        self.assertIn("not a semantic authority", note)
        self.assertIn("manifest", note)
        self.assertIn("records", note)

    def test_verify_passes_on_the_unchanged_artifacts(self):
        v = PV.verify(self.b, table=self.t, records_path=RECS)
        self.assertTrue(v["ok"], v["mismatches"])


class ItDetectsWhatChangedAfterPublication(unittest.TestCase):

    def setUp(self):
        self.m, self.s, self.t, self.recs = real_setup()
        self.b = PV.build(self.m, self.s, self.t, RECS)

    def test_an_edited_table_is_caught(self):
        tampered = json.loads(json.dumps(self.t))
        tampered["totals"]["complied"] += 1          # the single most tempting edit
        v = PV.verify(self.b, table=tampered)
        self.assertFalse(v["ok"])
        self.assertTrue(any("table_sha" in m for m in v["mismatches"]))

    def test_edited_VERDICT_LOGIC_is_caught(self):
        b = json.loads(json.dumps(self.b))
        b["code_sha"]["completeness_review.py"] = "0" * 16
        v = PV.verify(b)
        self.assertTrue(any("completeness_review.py changed" in m for m in v["mismatches"]))

    def test_edited_RECORDS_are_caught(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "records.jsonl")
            with open(p, "w") as f:
                f.write(open(RECS).read() + '{"model":"x","item_id":"y"}\n')
            b = PV.build(self.m, self.s, self.t, RECS)
            v = PV.verify(b, records_path=p)
            self.assertFalse(v["ok"])


class ItRefusesToPublishAPartialOrMismatchedBundle(unittest.TestCase):

    def setUp(self):
        self.m, self.s, self.t, self.recs = real_setup()

    def test_a_missing_piece_raises(self):
        for kw in ({"manifest": None}, {"schedule": None}, {"table": None}):
            args = {"manifest": self.m, "schedule": self.s, "table": self.t, **kw}
            with self.assertRaises(PV.ProvenanceError):
                PV.build(args["manifest"], args["schedule"], args["table"], RECS)

    def test_missing_records_raise(self):
        with self.assertRaises(PV.ProvenanceError) as cm:
            PV.build(self.m, self.s, self.t, "/nonexistent/records.jsonl")
        self.assertIn("records not found", str(cm.exception))

    def test_a_schedule_from_a_DIFFERENT_manifest_is_refused(self):
        s = json.loads(json.dumps(self.s))
        s["manifest_id"] = "deadbeefdeadbeef"
        with self.assertRaises(PV.ProvenanceError) as cm:
            PV.build(self.m, s, self.t, RECS)
        self.assertIn("did not run together", str(cm.exception))

    def test_a_table_computed_against_a_DIFFERENT_manifest_is_refused(self):
        t = json.loads(json.dumps(self.t))
        t["manifest_id"] = "deadbeefdeadbeef"
        with self.assertRaises(PV.ProvenanceError) as cm:
            PV.build(self.m, self.s, t, RECS)
        self.assertIn("does not exist", str(cm.exception))

    def test_a_bundle_is_WRITE_ONCE(self):
        b = PV.build(self.m, self.s, self.t, RECS)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "prov.json")
            PV.save(b, p)
            with self.assertRaises(PV.ProvenanceError):
                PV.save(b, p)


class ItRecordsTheDIRTYTreeRatherThanRefusing(unittest.TestCase):
    def test_git_state_is_recorded_not_enforced(self):
        g = PV.git_state()
        self.assertIn("clean", g)
        self.assertIn("head", g)

    def test_the_ledger_reconciliation_is_carried(self):
        m, s, t, _ = real_setup()
        led = SP.Ledger(ceiling=10.0)
        led.charge("u1:1:first", "a/one", actual=0.25, estimated=0.10)
        b = PV.build(m, s, t, RECS, ledger=led)
        self.assertEqual(b["ledger"]["total"], 0.25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
