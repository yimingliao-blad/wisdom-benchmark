"""Manifest supersession and record retention."""
import json
import os
import unittest

import completeness_review as CR
import manifest as MF
import persistence as PS

HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS = json.load(open(os.path.join(os.path.join(HERE, "runs", "_frozen_fxgate_2026-08-08"), "items.json")))[:4]


def roster(*ids):
    return [{"series": "S", "id": i, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
             "in": 0.1, "out": 0.1} for i in ids]


def record(mani, model, item_id, verdict="COMPLETE", **over):
    u = next(u for u in mani["units"]
             if u["model"] == model and u["item_id"] == item_id and u["arm"] == "original")
    rec = {"model": model, "item_id": item_id, "arm": "original", "unit_id": u["unit_id"],
           "attempt_id": f"{u['unit_id']}:1:first", "prompt_sha": u["prompt_sha"],
           "completeness": verdict, "finish_reason": "stop", "text": "x", "ok": True}
    rec.update(over)
    return rec


def undelivered(mani, model, item_id, verdict="PROVIDER_ERROR"):
    return record(mani, model, item_id, verdict=verdict,
                  finish_reason=None, text="", ok=False, prompt_sha=None, cost=0)


class AFailedCallIsNotACompletedOne(unittest.TestCase):

    def setUp(self):
        self.m = MF.build(roster("a/one", "a/two"), ITEMS, arms=("original",), bench="futurex")

    def test_a_unit_whose_only_row_is_a_provider_error_is_STILL_TODO(self):
        rs = PS.resume_state(self.m, [undelivered(self.m, "a/one", ITEMS[0]["item_id"])])
        uid = MF.unit_id("a/one", ITEMS[0]["item_id"], "original")
        self.assertIn(uid, rs["todo"], "a 403 left a row; that is not an answer")
        self.assertEqual(rs["done"], 0)
        self.assertEqual(rs["requeued_undelivered"], [uid])

    def test_a_unit_with_a_delivered_answer_is_NOT_re_bought(self):
        rs = PS.resume_state(self.m, [record(self.m, "a/one", ITEMS[0]["item_id"])])
        self.assertNotIn(MF.unit_id("a/one", ITEMS[0]["item_id"], "original"), rs["todo"])
        self.assertEqual(rs["done"], 1)
        self.assertEqual(rs["requeued_undelivered"], [])

    def test_transport_error_and_empty_http_are_also_re_queued(self):
        for v in ("TRANSPORT_ERROR", "EMPTY_HTTP"):
            rs = PS.resume_state(self.m, [undelivered(self.m, "a/one", ITEMS[0]["item_id"], v)])
            self.assertEqual(rs["done"], 0, v)

    def test_a_delivered_but_UNSCOREABLE_reply_is_kept_not_re_bought(self):
        for v in ("TRUNCATED", "EMPTY_PARSE", "UNDECIDED", "NO_ANSWER"):
            rs = PS.resume_state(self.m, [record(self.m, "a/one", ITEMS[0]["item_id"], verdict=v)])
            self.assertEqual(rs["done"], 1, f"{v} delivered a body and must not be re-bought")

    def test_a_later_good_attempt_settles_a_unit_that_first_failed(self):
        recs = [undelivered(self.m, "a/one", ITEMS[0]["item_id"]),
                record(self.m, "a/one", ITEMS[0]["item_id"])]
        rs = PS.resume_state(self.m, recs)
        self.assertEqual(rs["done"], 1)
        self.assertEqual(rs["requeued_undelivered"], [], "the retry succeeded; nothing to re-queue")

    def test_an_UNRECOGNISED_verdict_RAISES_rather_than_being_guessed(self):
        bad = record(self.m, "a/one", ITEMS[0]["item_id"], verdict="SORT_OF_FINE")
        with self.assertRaises(CR.VerdictError):
            PS.resume_state(self.m, [bad])

    def test_a_record_with_no_verdict_falls_back_to_the_SIDECAR_rule(self):
        m, iid = self.m, ITEMS[0]["item_id"]
        no_body = record(m, "a/one", iid); no_body.pop("completeness"); no_body["finish_reason"] = None
        with_body = record(m, "a/two", iid); with_body.pop("completeness")
        self.assertEqual(PS.resume_state(m, [no_body])["done"], 0)
        self.assertEqual(PS.resume_state(m, [with_body])["done"], 1)


class SupersedingAPlanKeepsTheWorkAlreadyBought(unittest.TestCase):

    def setUp(self):
        self.prior = MF.build(roster("a/one", "a/two", "a/three"), ITEMS, bench="futurex")
        self.kept = roster("a/one", "a/two")          # a/three dropped from the roster

    def test_a_supersession_with_no_reason_RAISES(self):
        with self.assertRaises(MF.ManifestError) as cm:
            MF.supersede(self.prior, self.kept, ITEMS, bench="futurex", reason="  ")
        self.assertIn("written reason", str(cm.exception))

    def test_superseding_with_an_IDENTICAL_plan_RAISES(self):
        with self.assertRaises(MF.ManifestError) as cm:
            MF.supersede(self.prior, roster("a/one", "a/two", "a/three"), ITEMS,
                         bench="futurex", reason="no actual change")
        self.assertIn("identical plan", str(cm.exception))

    def test_the_lineage_names_the_predecessor_and_the_reason(self):
        new = MF.supersede(self.prior, self.kept, ITEMS, bench="futurex", reason="owner dropped one")
        self.assertEqual(new["supersedes"], self.prior["manifest_id"])
        self.assertEqual(new["reason"], "owner dropped one")
        self.assertEqual(new["history"][-1]["manifest_id"], self.prior["manifest_id"])
        self.assertEqual(new["history"][-1]["n_units"], self.prior["n_units"])

    def test_the_chain_accumulates_across_two_supersessions(self):
        a = MF.supersede(self.prior, self.kept, ITEMS, bench="futurex", reason="first")
        b = MF.supersede(a, roster("a/one"), ITEMS, bench="futurex", reason="second")
        self.assertEqual([h["manifest_id"] for h in b["history"]],
                         [self.prior["manifest_id"], a["manifest_id"]])

    def test_the_id_ignores_the_lineage_so_it_still_identifies_the_PLAN(self):
        a = MF.supersede(self.prior, self.kept, ITEMS, bench="futurex", reason="one route")
        plain = MF.build(self.kept, ITEMS, bench="futurex")
        self.assertEqual(a["manifest_id"], plain["manifest_id"])

    def test_records_for_a_DROPPED_model_are_kept_out_of_plan_never_deleted(self):
        new = MF.supersede(self.prior, self.kept, ITEMS, bench="futurex", reason="dropped a/three")
        recs = ([record(self.prior, "a/one", i["item_id"]) for i in ITEMS]
                + [record(self.prior, "a/three", i["item_id"]) for i in ITEMS])
        part = PS.partition_by_manifest(new, recs)
        self.assertEqual(len(part["in_plan_answered"]), len(ITEMS))
        self.assertEqual(len(part["out_of_plan"]), len(ITEMS))
        self.assertTrue(all(r["model"] == "a/three" for r in part["out_of_plan"]))

    def test_a_MISASSOCIATED_record_still_fails_after_a_supersession(self):
        new = MF.supersede(self.prior, self.kept, ITEMS, bench="futurex", reason="dropped a/three")
        bad = record(self.prior, "a/one", ITEMS[0]["item_id"], prompt_sha="deadbeefdeadbeef")
        self.assertEqual(len(PS.partition_by_manifest(new, [bad])["misassociated"]), 1)

    def test_kept_records_are_skipped_and_only_the_gap_is_bought(self):
        new = MF.supersede(self.prior, self.kept, ITEMS, bench="futurex", reason="dropped a/three")
        recs = [record(self.prior, "a/one", i["item_id"]) for i in ITEMS]
        rs = PS.resume_state(new, recs, strict=False)
        self.assertEqual(rs["planned"], 2 * len(ITEMS))
        self.assertEqual(rs["done"], len(ITEMS))
        self.assertEqual(len(rs["todo"]), len(ITEMS))
        self.assertEqual(set(rs["todo"]),
                         {MF.unit_id("a/two", i["item_id"], "original") for i in ITEMS},
                         "the gap must be exactly a/two's units -- a/one's were already answered")


class WriteOnceReopensOnlyForADeclaredSuccessor(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "manifest.json")
        self.prior = MF.build(roster("a/one", "a/two"), ITEMS, bench="futurex")
        MF.save(self.prior, self.p)
        self.new = MF.supersede(self.prior, roster("a/one"), ITEMS, bench="futurex", reason="drop")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def test_a_plain_overwrite_is_still_refused(self):
        with self.assertRaises(MF.ManifestError) as cm:
            MF.save(self.new, self.p)
        self.assertIn("WRITE-ONCE", str(cm.exception))

    def test_claiming_to_replace_an_id_that_is_not_there_is_refused(self):
        with self.assertRaises(MF.ManifestError) as cm:
            MF.save(self.new, self.p, replacing="0000000000000000")
        self.assertIn("has not actually read", str(cm.exception))

    def test_a_successor_that_does_not_NAME_its_predecessor_is_refused(self):
        orphan = MF.build(roster("a/one"), ITEMS, bench="futurex")   # no supersedes
        with self.assertRaises(MF.ManifestError) as cm:
            MF.save(orphan, self.p, replacing=self.prior["manifest_id"])
        self.assertIn("must name what it", str(cm.exception))

    def test_a_declared_successor_lands(self):
        MF.save(self.new, self.p, replacing=self.prior["manifest_id"])
        self.assertEqual(json.load(open(self.p))["manifest_id"], self.new["manifest_id"])

    def test_the_schedule_guard_reopens_on_the_same_terms(self):
        import schedule as SC
        sp = os.path.join(self.d, "schedule.json")
        a = SC.build(self.prior, global_workers=4, per_provider=2)
        SC.save(a, sp)
        b = SC.build(self.new, global_workers=4, per_provider=2)
        with self.assertRaises(SC.ScheduleError):
            SC.save(b, sp)
        with self.assertRaises(SC.ScheduleError):
            SC.save(b, sp, replacing="0000000000000000")
        SC.save(b, sp, replacing=a["schedule_id"])
        self.assertEqual(json.load(open(sp))["schedule_id"], b["schedule_id"])


class OnTheRealHaltedRun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        d = os.path.join(HERE, "runs", "_frozen_fxgate_2026-08-08")   # FROZEN, see pinned-counts-need-a-frozen-scope
        cls.recs = [json.loads(l) for l in open(os.path.join(d, "records.jsonl")) if l.strip()]
        cls.prior = json.load(open(os.path.join(d, "manifest.json")))
        cls.items = json.load(open(os.path.join(d, "items.json")))
        cls.roster25 = json.load(open(os.path.join(HERE, "survey", "_snapshot_roster_2026-08-09.json")))

    def test_the_old_run_requeues_its_259_undelivered_units(self):
        rs = PS.resume_state(self.prior, self.recs)
        self.assertEqual(len(rs["requeued_undelivered"]), 259,
                         "255 PROVIDER_ERROR + 4 TRANSPORT_ERROR were being counted as done")
        self.assertEqual(rs["done"], len(self.recs) - 259)

    def test_the_25_model_supersession_keeps_411_and_buys_2339(self):
        new = MF.supersede(self.prior, self.roster25, self.items, arms=("original",),
                           bench="futurex", reason="owner's 25-model list, 2026-08-09")
        part = PS.partition_by_manifest(new, self.recs)
        self.assertEqual(len(part["in_plan_answered"]), 411)
        self.assertEqual(len(part["in_plan_unanswered"]), 112)
        self.assertEqual(len(part["out_of_plan"]), 608)
        self.assertEqual(part["misassociated"], [])
        rs = PS.resume_state(new, self.recs, strict=False)
        self.assertEqual(rs["planned"], 2750)
        self.assertEqual(rs["done"], 411)
        self.assertEqual(len(rs["todo"]), 2339)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ASupersededRunCanStillProduceItsTable(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import analyze as AN
        cls.AN = AN
        d = os.path.join(HERE, "runs", "_frozen_fxgate_2026-08-08")   # FROZEN, see pinned-counts-need-a-frozen-scope
        with open(os.path.join(d, "records.jsonl"), encoding="utf-8") as fh:
            cls.recs = [json.loads(l) for l in fh if l.strip()]
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
            cls.prior = json.load(fh)
        with open(os.path.join(d, "items.json"), encoding="utf-8") as fh:
            cls.items = json.load(fh)
        with open(os.path.join(HERE, "survey", "_snapshot_roster_2026-08-09.json"), encoding="utf-8") as fh:
            cls.roster25 = json.load(fh)   # FROZEN: see pinned-counts-need-a-frozen-scope
        cls.new = MF.supersede(cls.prior, cls.roster25, cls.items, arms=("original",),
                               bench="futurex", reason="owner's 25-model list")

    def table(self, mani):
        return self.AN.per_model_table(mani, self.recs, strict=True, allow_pending=True)

    def test_a_DECLARED_supersession_builds_the_table_in_strict_mode(self):
        t = self.table(self.new)
        self.assertEqual(t["supersedes"], self.prior["manifest_id"])
        self.assertEqual(t["n_planned"], 2750)

    def test_an_UNDECLARED_roster_change_is_still_refused(self):
        plain = MF.build(self.roster25, self.items, arms=("original",), bench="futurex")
        self.assertIsNone(plain.get("supersedes"))
        with self.assertRaises(self.AN.AnalysisError) as cm:
            self.table(plain)
        self.assertIn("not in manifest", str(cm.exception))

    def test_admitted_records_counts_ONLY_the_records_in_THIS_plan(self):
        t = self.table(self.new)
        self.assertEqual(t["admitted_records"], 523)      # not 1,131
        self.assertEqual(t["out_of_plan_records"], 608)
        self.assertEqual(t["admitted_records"] + t["out_of_plan_records"], len(self.recs))

    def test_out_of_plan_records_touch_no_rate_and_no_denominator(self):
        t = self.table(self.new)
        tot = t["totals"]
        self.assertEqual(tot["OBSERVED"], 401)
        self.assertEqual(tot["coverage_rate"], round(401 / 2750, 4))
        self.assertEqual(tot["OBSERVED"] + tot["UNOBSERVED"] + tot["NEEDS_INSPECTION"]
                         + tot["CENSORED"] + tot["MISSING"], tot["planned"])
        self.assertEqual(set(t["rows"]), {m["id"] for m in self.roster25})

    def test_they_are_REPORTED_not_silently_dropped(self):
        t = self.table(self.new)
        self.assertEqual(len(t["out_of_plan_by_model"]), 20)
        self.assertIn("RETAINED OUT-OF-PLAN: 608", self.AN.render(t))


class ThePostRunChecksDescribeTHISPlan(unittest.TestCase):

    def setUp(self):
        import tempfile
        import run_openrouter as RO
        self.RO = RO
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "records.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, rows):
        with open(self.path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def bad_row(self, model):
        return {"model": model, "item_id": "q1", "arm": "original", "completeness": "COMPLETE",
                "answer_extractable": False, "compliant": True}

    def good_row(self, model):
        return {"model": model, "item_id": "q2", "arm": "original", "completeness": "COMPLETE",
                "answer_extractable": True, "compliant": True}

    def test_an_out_of_plan_record_does_NOT_halt_the_current_stage(self):
        self.write([self.good_row("in/plan"), self.bad_row("gone/superseded")])
        self.RO.verify_records(self.path, planned_models={"in/plan"})   # must not raise

    def test_the_SAME_defect_IN_plan_still_halts(self):
        self.write([self.good_row("in/plan"), self.bad_row("in/plan")])
        with self.assertRaises(SystemExit) as cm:
            self.RO.verify_records(self.path, planned_models={"in/plan"})
        self.assertIn("COMPLETE with no extractable answer", str(cm.exception))

    def test_unscoped_still_checks_everything(self):
        self.write([self.bad_row("anyone/at-all")])
        with self.assertRaises(SystemExit):
            self.RO.verify_records(self.path, planned_models=None)

    def test_the_skipped_count_is_REPORTED_not_hidden(self):
        import contextlib, io
        self.write([self.good_row("in/plan")] + [self.good_row(f"gone/{i}") for i in range(3)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.RO.verify_records(self.path, planned_models={"in/plan"})
        out = buf.getvalue()
        self.assertIn("1 in-plan records", out)
        self.assertIn("3 out-of-plan record(s)", out)


class ARequeuedUnitIsNotAUnitBoughtTwice(unittest.TestCase):

    def setUp(self):
        self.m = MF.build(roster("a/one"), ITEMS, arms=("original",), bench="futurex")
        self.iid = ITEMS[0]["item_id"]

    def test_a_failed_attempt_then_an_answer_is_NOT_bought_twice(self):
        rows = [undelivered(self.m, "a/one", self.iid), record(self.m, "a/one", self.iid)]
        self.assertEqual(PS.bought_twice(rows), {})
        self.assertEqual(len(PS.find_duplicates(rows)), 1, "still visible as DATA")

    def test_two_failed_attempts_are_NOT_bought_twice(self):
        rows = [undelivered(self.m, "a/one", self.iid), undelivered(self.m, "a/one", self.iid)]
        self.assertEqual(PS.bought_twice(rows), {})

    def test_TWO_DELIVERED_answers_for_one_unit_IS_the_defect(self):
        rows = [record(self.m, "a/one", self.iid), record(self.m, "a/one", self.iid)]
        got = PS.bought_twice(rows)
        self.assertEqual(list(got), [MF.unit_id("a/one", self.iid, "original")])
        self.assertEqual(len(got[MF.unit_id("a/one", self.iid, "original")]), 2)

    def test_a_single_row_is_never_flagged(self):
        self.assertEqual(PS.bought_twice([record(self.m, "a/one", self.iid)]), {})
