"""M6-T15/S2 — acceptance for the six BLOCKING findings of the Codex verification re-gate.

Codex returned NO-GO on 2026-08-08 (job task-mskugr8u-g4hm6m) with the summary judgement that the
remaining flaw was not the old wiring gap but that "several publication and crash-resume guarantees
are still post-hoc or optional -- a green runner can spend money, emit records, and still not
produce the auditable deliverable the design promises."

One class per finding:
  C1  the spend ledger was written only after the executor finished, so a crash after paid calls
      left records that resume would skip and a ledger that understated the spend
  C2  analyze and provenance were never called by the paid path -- the same gap as the 11 unwired
      modules, one layer out
  C3  a layer-1 provisional COMPLETE could be published as final. NOTE: layer 1 NEVER self-certifies
      (it always defers to a reader), so in real mode EVERY record is provisional -- this gate is the
      normal path, not a corner case
  C4  quarantined units became MISSING instead of CENSORED, breaking the promised partition
  C5  per_provider was recorded in the schedule and enforced by nothing
  C6  the raw sidecar was keyed on model/item/arm, so a retry could not be told from a first attempt

Offline. No network. No spend.  Run: python3 -m unittest test_finalize -v
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest

import analyze as AN
import finalize as FZ
import manifest as MF
import provenance as PV
import schedule as SC
import spend as SP

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = os.path.join(HERE, "runs", "fx_smoke4.json")

ROSTER = [{"series": "A", "id": "alpha/one", "cutoff": "2025-01", "basis": "PUB",
           "release": "2025", "in": 1.0, "out": 2.0},
          {"series": "A", "id": "alpha/two", "cutoff": "2025-01", "basis": "PUB",
           "release": "2025", "in": 1.0, "out": 2.0},
          {"series": "B", "id": "beta/one", "cutoff": "2025-01", "basis": "PUB",
           "release": "2025", "in": 1.0, "out": 2.0}]


def _interpretable_box(items, item_id):
    """A box that genuinely answers THAT question -- A12 checks the answer against its own item."""
    import bench_formats as BF
    it = next(i for i in items if i["item_id"] == item_id)
    kind = BF.expected_answer_type(it["prompt"])
    if kind == "binary":
        return "Yes"
    if kind == "multiple_choice":
        return BF.options_offered(it["prompt"])[0]
    return "a substantive free-text prediction"


def build_run_dir(d, complete_models=None, quarantine=None, pending=False, halted=False,
                  sidecar="full", n_models=None):
    """A run directory exactly as the runner writes one, so finalize is exercised on real shapes.

    n_models widens the synthetic roster. Needed because A1 now decides on a CONFIDENCE BOUND: the
    3-model fixture yields 12 replies, whose 95% lower bound is 0.758 even at a 100% rate, so it
    cannot demonstrate a passing A1 no matter how healthy it is.
    """
    roster = ROSTER if not n_models else [
        {"series": "A", "id": f"prov{i % 4}/model{i}", "cutoff": "2025-01", "basis": "PUB",
         "release": "2025", "in": 1.0, "out": 2.0} for i in range(n_models)]
    items = json.load(open(ITEMS))
    json.dump(items, open(os.path.join(d, "items.json"), "w"))   # A12 needs the questions
    mani = MF.build(roster, items, arms=("original",))
    MF.save(mani, os.path.join(d, "manifest.json"))
    sched = SC.build(mani)
    SC.save(sched, os.path.join(d, "schedule.json"))

    complete_models = complete_models or [m["id"] for m in roster]
    quarantine = quarantine or {}
    recs, raws = [], []
    for u in mani["units"]:
        if u["model"] in quarantine or u["model"] not in complete_models:
            continue
        aid = MF.attempt_id(u["unit_id"], 1, "first")
        r = {"model": u["model"], "item_id": u["item_id"], "arm": u["arm"],
             "unit_id": u["unit_id"], "attempt_id": aid, "manifest_id": mani["manifest_id"],
             "prompt_sha": u["prompt_sha"], "text": "answer\n\\boxed{yes}",
             "finish_reason": "stop", "completeness": "COMPLETE", "compliant": True,
             "answer_extractable": True, "cost": 0.001,
             # A11 reads `parsed`: a COMPLETE record must carry the answer it claims to have.
             "parsed": {"answer": ["yes"], "raw_box": _interpretable_box(items, u["item_id"]),
                        "n_boxes": 1, "compliant": True},
             # non-overlapping intervals: one provider, one call at a time
             "started_at": 1000.0 + 2 * len(recs), "ended_at": 1001.0 + 2 * len(recs),
             "duration_s": 1.0, "provider_group": u["model"].split("/")[0]}
        if pending:
            r["pending_review"] = True
        recs.append(r)
        raws.append({"unit_id": u["unit_id"], "attempt_id": aid,
                     "manifest_id": mani["manifest_id"], "model": u["model"],
                     "item_id": u["item_id"], "arm": u["arm"], "prompt_sha": u["prompt_sha"],
                     "prompt": "x", "response": {"choices": []}})
    with open(os.path.join(d, "records.jsonl"), "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    if sidecar != "none":
        rows = raws[:-1] if sidecar == "missing_one" else (raws + [raws[0]] if sidecar == "dupe"
                                                           else raws)
        with open(os.path.join(d, "raw_responses.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    skipped = [{"model": m, "provider_hint": m.split("/")[0], "item_id": u["item_id"],
                "arm": u["arm"]}
               for m in quarantine for u in mani["units"] if u["model"] == m]
    json.dump({"run_config": {}, "run_config_hash": "x", "finished_at": "now",
               "quarantined_models": [{"model": m, "first_verdict": v, "failures": [],
                                       "attempts": 1} for m, v in quarantine.items()],
               "units_to_rerun": skipped, "units_to_rerun_count": len(skipped),
               "halted": halted, "halt_reason": "spend ceiling reached" if halted else None},
              open(os.path.join(d, "quarantine_manifest.json"), "w"))
    led = SP.Ledger(ceiling=10.0)
    for r in recs:
        led.charge(r["attempt_id"], r["model"], actual=r["cost"], unit_id=r["unit_id"])
    led.save(os.path.join(d, "ledger.json"))
    return mani, sched, recs


class C1_TheLedgerSurvivesACrash(unittest.TestCase):
    """A ledger written only at the end understates the spend of a run that died mid-flight."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.j = os.path.join(self.d, "ledger.jsonl")

    def test_each_charge_is_durable_IMMEDIATELY(self):
        led = SP.Ledger(ceiling=10.0, journal=self.j)
        led.charge("u1:1:first", "a/one", actual=0.25)
        led.charge("u2:1:first", "a/one", actual=0.25)
        # no save() at all -- the process "dies" here
        back = SP.Ledger.rebuild_from_journal(self.j, ceiling=10.0)
        self.assertEqual(back.total, 0.50)
        self.assertEqual(len(back.entries), 2)

    def test_the_JOURNAL_WINS_over_a_stale_summary(self):
        """The exact crash Codex named: records exist, resume skips them, the summary is behind."""
        led = SP.Ledger(ceiling=10.0, journal=self.j)
        led.charge("u1:1:first", "a/one", actual=0.25)
        led.save(os.path.join(self.d, "ledger.json"))       # summary written HERE
        led.charge("u2:1:first", "a/one", actual=0.25)      # paid AFTER the summary, then crash
        back = SP.Ledger.load(os.path.join(self.d, "ledger.json"), journal=self.j)
        self.assertEqual(back.total, 0.50, "the summary understated the spend and won anyway")
        self.assertEqual(back.recovered_from_journal, 1)

    def test_a_crashed_run_with_NO_journal_REFUSES_to_guess(self):
        with self.assertRaises(SP.SpendError) as cm:
            SP.Ledger.rebuild_from_journal(os.path.join(self.d, "nothing.jsonl"), ceiling=10.0)
        self.assertIn("cannot be reconstructed", str(cm.exception))

    def test_recovery_does_not_double_charge(self):
        led = SP.Ledger(ceiling=10.0, journal=self.j)
        led.charge("u1:1:first", "a/one", actual=0.25)
        led.save(os.path.join(self.d, "ledger.json"))
        back = SP.Ledger.load(os.path.join(self.d, "ledger.json"), journal=self.j)
        self.assertEqual(back.total, 0.25, "the same attempt appeared in both and was counted twice")


class C2_TheLifecycleProducesTheDeliverable(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_finalize_writes_the_table_AND_a_verified_bundle(self):
        build_run_dir(self.d)
        r = FZ.finalize(self.d)
        self.assertTrue(os.path.exists(os.path.join(self.d, "analysis_table.json")))
        self.assertTrue(os.path.exists(os.path.join(self.d, "provenance.json")))
        self.assertTrue(r["provenance"]["verified"])

    def test_the_bundle_binds_THIS_runs_table(self):
        build_run_dir(self.d)
        FZ.finalize(self.d)
        b = json.load(open(os.path.join(self.d, "provenance.json")))
        t = json.load(open(os.path.join(self.d, "analysis_table.json")))
        self.assertEqual(b["table_sha"], PV._sha_obj(t))
        self.assertTrue(PV.verify(b, table=t,
                                  records_path=os.path.join(self.d, "records.jsonl"))["ok"])

    def test_a_run_dir_missing_its_plan_is_REFUSED(self):
        build_run_dir(self.d)
        os.remove(os.path.join(self.d, "manifest.json"))
        with self.assertRaises(FZ.FinalizeError) as cm:
            FZ.finalize(self.d)
        self.assertIn("not a finalizable run", str(cm.exception))


class C3_ProvisionalResultsCannotBePublished(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_a_pending_record_yields_NO_provenance_bundle(self):
        build_run_dir(self.d, pending=True)
        r = FZ.finalize(self.d)
        self.assertTrue(r["provisional"])
        self.assertIsNone(r["provenance"])
        self.assertFalse(os.path.exists(os.path.join(self.d, "provenance.json")),
                         "a bundle CERTIFIES a result; it must not certify unreviewed guesses")
        self.assertTrue(os.path.exists(os.path.join(self.d, "analysis_table.provisional.json")))

    def test_the_provisional_table_SAYS_SO(self):
        build_run_dir(self.d, pending=True)
        FZ.finalize(self.d)
        t = json.load(open(os.path.join(self.d, "analysis_table.provisional.json")))
        self.assertTrue(t["provisional"])
        self.assertGreater(t["n_pending_review"], 0)
        self.assertIn("PROVISIONAL", AN.render(t))

    def test_the_analysis_API_itself_REFUSES_by_default(self):
        mani, _, recs = build_run_dir(self.d, pending=True)
        with self.assertRaises(AN.AnalysisError) as cm:
            AN.per_model_table(mani, recs)
        self.assertIn("pending_review", str(cm.exception))

    def test_clearing_the_flag_makes_it_publishable(self):
        build_run_dir(self.d, pending=True)
        p = os.path.join(self.d, "records.jsonl")
        recs = [json.loads(l) for l in open(p) if l.strip()]
        for r in recs:
            r.pop("pending_review")                  # what review_pending.py does
        with open(p, "w") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        r = FZ.finalize(self.d)
        self.assertFalse(r["provisional"])
        self.assertTrue(r["provenance"]["verified"])


class C4_QuarantinedUnitsAreCENSOREDnotMISSING(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_censored_equals_units_to_rerun_and_missing_is_zero(self):
        build_run_dir(self.d, quarantine={"beta/one": "PROVIDER_ERROR"})
        FZ.finalize(self.d)
        t = json.load(open(os.path.join(self.d, "analysis_table.json")))
        q = json.load(open(os.path.join(self.d, "quarantine_manifest.json")))
        self.assertEqual(t["totals"]["CENSORED"], q["units_to_rerun_count"])
        self.assertEqual(t["totals"]["MISSING"], 0,
                         "an abandoned unit must not hide in the same bucket as an unstarted one")

    def test_the_quarantined_model_gets_no_rate_rather_than_zero(self):
        build_run_dir(self.d, quarantine={"beta/one": "PROVIDER_ERROR"})
        FZ.finalize(self.d)
        t = json.load(open(os.path.join(self.d, "analysis_table.json")))
        row = t["rows"]["beta/one"]
        self.assertIsNone(row["compliance_rate"])
        self.assertEqual(row["rate_basis"], "no_rate:nothing_observed")
        self.assertEqual(row["CENSORED"], row["planned"])

    def test_a_SPEND_HALT_also_censors_rather_than_leaving_MISSING(self):
        build_run_dir(self.d, complete_models=["alpha/one"], halted=True)
        FZ.finalize(self.d)
        t = json.load(open(os.path.join(self.d, "analysis_table.json")))
        self.assertEqual(t["totals"]["MISSING"], 0)
        self.assertGreater(t["totals"]["CENSORED"], 0)

    def test_a_quarantined_unit_outside_the_plan_RAISES(self):
        build_run_dir(self.d)
        qp = os.path.join(self.d, "quarantine_manifest.json")
        q = json.load(open(qp))
        q["units_to_rerun"] = [{"model": "ghost/model", "item_id": "nope", "arm": "original"}]
        json.dump(q, open(qp, "w"))
        with self.assertRaises(FZ.FinalizeError) as cm:
            FZ.finalize(self.d)
        self.assertIn("not in manifest", str(cm.exception))


class C6_TheRawSidecarIsOneToOne(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_a_healthy_sidecar_passes(self):
        build_run_dir(self.d)
        self.assertTrue(FZ.check_raw_sidecar(
            self.d, [json.loads(l) for l in open(os.path.join(self.d, "records.jsonl"))])["ok"])

    def test_a_MISSING_row_is_caught(self):
        build_run_dir(self.d, sidecar="missing_one")
        with self.assertRaises(FZ.FinalizeError) as cm:
            FZ.finalize(self.d)
        self.assertIn("without re-buying", str(cm.exception))

    def test_a_DUPLICATE_row_is_caught(self):
        build_run_dir(self.d, sidecar="dupe")
        with self.assertRaises(FZ.FinalizeError) as cm:
            FZ.finalize(self.d)
        self.assertIn("duplicated", str(cm.exception))

    def test_rows_carry_the_ATTEMPT_identity_not_just_the_unit(self):
        """Keyed on model/item/arm alone, a retry cannot be told from a first attempt."""
        build_run_dir(self.d)
        rows = [json.loads(l) for l in open(os.path.join(self.d, "raw_responses.jsonl"))]
        for r in rows:
            self.assertIn("attempt_id", r)
            self.assertTrue(r["attempt_id"].startswith(r["unit_id"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
