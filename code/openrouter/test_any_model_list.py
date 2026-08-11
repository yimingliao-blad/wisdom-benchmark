"""The pipeline runs on ANY model list, and the plan cannot go stale when the list changes.

Owner, 2026-08-09/10:
  "make the current project can work on the list no matter what i ask you to do"
  "the point is not model you should check. I ask you to build the code on flexible model I ask you
   to do. also, make the plan auditable, resumable, and testable"

The three properties, each proven rather than asserted:

  FLEXIBLE   an arbitrary list of names -- not the owner's 25, not any list this code has seen --
             goes end to end: roster -> manifest -> schedule -> resume -> table. Then the list
             CHANGES mid-flight and the run continues.
  AUDITABLE  every derived value names its source, and the manifest carries the lineage of what it
             superseded, so the plan a number was computed under is recoverable from the artifacts.
  RESUMABLE  work already answered survives a list change; a call that never delivered does not
             count as done; a record for a dropped model is retained, not deleted or absorbed.
  TESTABLE   the plan's own scope block is regenerated from the roster and compared, so changing the
             list and forgetting the plan fails HERE instead of publishing a stale scope.

Offline. The catalog is a fixture, the items are synthetic, no key is read and nothing is bought.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_formats as BF      # noqa: E402
import manifest as MF           # noqa: E402
import persistence as PS        # noqa: E402
import schedule as SC           # noqa: E402
import analyze as AN            # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "roster_build", os.path.join(HERE, "survey", "roster_build.py"))
RB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RB)
_spec2 = importlib.util.spec_from_file_location(
    "plan_scope", os.path.join(HERE, "survey", "plan_scope.py"))
PSCOPE = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(PSCOPE)

PLAN_MD = os.path.join(HERE, "..", "..", "..", "plans", "openrouter-output-integrity", "plan.md")


def catalog(ids):
    """A catalog fixture for arbitrary ids -- deliberately varied, so the derivations get exercised."""
    out = []
    for i, mid in enumerate(ids):
        out.append({
            "id": mid, "name": f"Maker{i}: Model {i}", "created": 1745875945 + i,
            "pricing": {"prompt": f"0.000000{i + 1}", "completion": f"0.000001{i + 1}"},
            "top_provider": {"max_completion_tokens": 4096 + i},
            "context_length": 100000,
            "hugging_face_id": f"Maker{i}/Model-{i}" if i % 2 == 0 else "",
            "knowledge_cutoff": "2025-01-31" if i % 3 else None,
        })
    return {"data": out}


MARKER = "IMPORTANT: Your final answer MUST end with this exact format:"


def items(n=3):
    """Synthetic but VALID items -- item_validate refuses a corpus that is not fit to ask, and it is
    right to: the format marker decides how the prompt renders, and an end_time before the
    contamination anchor would let a model answer from memory. The first version of this fixture had
    neither and was rejected, which is the validator doing its job on a test's shortcut."""
    return [{"item_id": f"q{i}|2026-07-0{i + 1}", "level": 1,
             "end_time": f"2026-07-0{i + 1}", "ground_truth": "A",
             "prompt": (f"Will thing {i} happen by mid-2026?\n\n{MARKER}\n"
                        "\\boxed{A} for a single correct option.\n"
                        "Options:\nA. Yes\nB. No\n")} for i in range(n)]


class AnArbitraryListGoesEndToEnd(unittest.TestCase):
    # Names this codebase has never seen, from vendors that do not exist.
    IDS = ["acme/thinker-1", "acme/thinker-2", "beta-labs/reasoner-x", "gamma/tiny-7b"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cat = os.path.join(self.tmp, "cat.json")
        json.dump(catalog(self.IDS + ["delta/late-arrival"]), open(self.cat, "w"))
        self.items = items()

    def build_roster(self, ids, overrides=None):
        mfile = os.path.join(self.tmp, "m.txt")
        open(mfile, "w").write("\n".join(ids) + "\n")
        out = os.path.join(self.tmp, "r.json")
        argv = ["rb", "--models", mfile, "--catalog-cache", self.cat, "--out", out]
        if overrides:
            ofile = os.path.join(self.tmp, "o.json")
            json.dump(overrides, open(ofile, "w"))
            argv += ["--overrides", ofile]
        old, sys.argv = sys.argv, argv
        try:
            RB.main()
        finally:
            sys.argv = old
        return json.load(open(out))

    def record(self, mani, model, item_id, verdict="COMPLETE", **over):
        u = next(u for u in mani["units"] if u["model"] == model and u["item_id"] == item_id)
        r = {"model": model, "series": "S", "cutoff": "2025-01-31", "item_id": item_id,
             "arm": "original", "unit_id": u["unit_id"], "attempt_id": f"{u['unit_id']}:1:first",
             "prompt_sha": u["prompt_sha"], "completeness": verdict, "finish_reason": "stop",
             "text": "x", "ok": True, "compliant": True, "usage": {"prompt_tokens": 10,
                                                                   "completion_tokens": 5}}
        r.update(over)
        return r

    # ---- FLEXIBLE ------------------------------------------------------------------------------

    def test_names_this_code_has_never_seen_produce_a_runnable_plan(self):
        roster = self.build_roster(self.IDS)
        self.assertEqual([r["id"] for r in roster], self.IDS)
        mani = MF.build(roster, self.items, arms=("original",), bench="futurex")
        self.assertEqual(mani["n_units"], len(self.IDS) * len(self.items))
        sched = SC.build(mani, global_workers=4, per_provider=2)
        self.assertEqual(len(sched["order"]), mani["n_units"])
        # and the whole thing is costable, because every row carries a price and a ceiling
        self.assertTrue(all(r["in"] and r["out"] and r["cap"] for r in roster))

    def test_a_one_model_list_and_a_large_list_both_work(self):
        for ids in ([self.IDS[0]], self.IDS):
            mani = MF.build(self.build_roster(ids), self.items, arms=("original",), bench="futurex")
            self.assertEqual(mani["n_models"], len(ids))

    def test_the_pipeline_never_needed_to_know_the_names(self):
        """The manifest, schedule and table are built from the roster, whatever is in it."""
        roster = self.build_roster(self.IDS)
        mani = MF.build(roster, self.items, arms=("original",), bench="futurex")
        recs = [self.record(mani, m["id"], i["item_id"]) for m in roster for i in self.items]
        t = AN.per_model_table(mani, recs, strict=True, allow_pending=True)
        self.assertEqual(set(t["rows"]), set(self.IDS))
        self.assertEqual(t["totals"]["OBSERVED"], mani["n_units"])

    # ---- RESUMABLE -----------------------------------------------------------------------------

    def test_changing_the_list_mid_run_keeps_the_answered_work(self):
        """The owner's rule: already answered by a model still on the list -> keep. Otherwise buy."""
        roster_a = self.build_roster(self.IDS)
        mani_a = MF.build(roster_a, self.items, arms=("original",), bench="futurex")
        done = [self.record(mani_a, self.IDS[0], i["item_id"]) for i in self.items]
        done += [self.record(mani_a, "gamma/tiny-7b", self.items[0]["item_id"])]

        # the owner swaps one model out and one in
        new_ids = [self.IDS[0], self.IDS[1], "delta/late-arrival"]
        roster_b = self.build_roster(new_ids)
        mani_b = MF.supersede(mani_a, roster_b, self.items, arms=("original",), bench="futurex",
                              reason="owner changed the list")

        part = PS.partition_by_manifest(mani_b, done)
        self.assertEqual(len(part["in_plan_answered"]), len(self.items))   # thinker-1's work kept
        self.assertEqual(len(part["out_of_plan"]), 1)                      # tiny-7b's retained
        self.assertEqual(part["misassociated"], [])
        rs = PS.resume_state(mani_b, done, strict=False)
        self.assertEqual(rs["done"], len(self.items))
        self.assertEqual(len(rs["todo"]), len(new_ids) * len(self.items) - len(self.items))

    def test_a_call_that_never_delivered_is_not_counted_as_done(self):
        roster = self.build_roster(self.IDS)
        mani = MF.build(roster, self.items, arms=("original",), bench="futurex")
        dead = self.record(mani, self.IDS[0], self.items[0]["item_id"],
                           verdict="PROVIDER_ERROR", finish_reason=None, text="", ok=False,
                           prompt_sha=None)
        rs = PS.resume_state(mani, [dead])
        self.assertEqual(rs["done"], 0)
        self.assertEqual(len(rs["requeued_undelivered"]), 1)

    # ---- AUDITABLE -----------------------------------------------------------------------------

    def test_every_derived_field_names_its_source(self):
        for row in self.build_roster(self.IDS):
            for f in ("in", "out", "cap", "release", "weights", "cutoff", "series"):
                self.assertTrue(row["field_sources"].get(f), f"{row['id']}.{f} has no source")

    def test_the_manifest_records_what_it_superseded_and_why(self):
        a = MF.build(self.build_roster(self.IDS), self.items, bench="futurex")
        b = MF.supersede(a, self.build_roster(self.IDS[:2]), self.items, bench="futurex",
                         reason="dropped two")
        self.assertEqual(b["supersedes"], a["manifest_id"])
        self.assertEqual(b["reason"], "dropped two")
        self.assertEqual(b["history"][-1]["n_models"], len(self.IDS))

    def test_a_declared_value_is_never_indistinguishable_from_a_published_one(self):
        r = self.build_roster([self.IDS[0]], overrides={
            self.IDS[0]: {"cutoff": "2024-01", "why": "vendor blog"}})[0]
        self.assertEqual(r["basis"], "DECLARED")
        self.assertIn("vendor blog", r["field_sources"]["cutoff"])


class ThePlanCannotSilentlyGoStale(unittest.TestCase):
    """TESTABLE: change the list, forget the plan -> this fails, instead of the plan lying."""

    # EVERY arm of the experiment, not just the one that was rebuilt last. The BTF-3 rows carried
    # figures from the superseded roster while FutureX was regenerated, and a single-arm check would
    # have gone on passing over exactly that staleness.
    ARGS = ["--roster", os.path.join(HERE, "survey", "roster_25.json"),
            "--bench", "futurex",
            "--items", os.path.join(HERE, "runs", "fx_items_110.json"), "--arms", "original",
            "--records", os.path.join(HERE, "runs", "or_futurex_fxgate", "records.jsonl"),
            # TWO arms since the owner's 2026-08-10 prompt ruling: FutureX on the official prompt
            # and BTF-3 on the TIGHTENED answer line only. BTF-3 native is not run.
            "--stage", f"btf3:{os.path.join(HERE, 'runs', 'btf3_items_110.json')}:tight:"
                       f"{os.path.join(HERE, 'runs', 'or_btf3_btftight', 'records.jsonl')}"]

    def test_the_plans_scope_block_matches_the_current_roster(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "survey", "plan_scope.py")]
                           + self.ARGS + ["--check", PLAN_MD],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_check_would_FAIL_on_a_drifted_plan(self):
        """A freshness check that cannot fail proves nothing."""
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "plan.md")
            open(fake, "w").write(f"{PSCOPE.BEGIN}\nstale numbers from another roster\n{PSCOPE.END}\n")
            r = subprocess.run([sys.executable, os.path.join(HERE, "survey", "plan_scope.py")]
                               + self.ARGS + ["--check", fake], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("does NOT match the current roster", r.stdout + r.stderr)

    def test_it_covers_EVERY_arm_not_just_the_one_last_rebuilt(self):
        """The staleness this exists to catch: FutureX regenerated, BTF-3 left on old figures."""
        r = subprocess.run([sys.executable, os.path.join(HERE, "survey", "plan_scope.py")]
                           + self.ARGS + ["--check", PLAN_MD], capture_output=True, text=True)
        self.assertIn("2 arm(s)", r.stdout + r.stderr)
        body = open(PLAN_MD, encoding="utf-8").read()
        self.assertIn("| `tight` | btf3 |", body)
        self.assertIn("5,280 units", body)

    def test_a_stage_with_a_missing_item_corpus_is_REFUSED(self):
        """A stage cannot be scoped without its items, and guessing the count defeats the purpose."""
        r = subprocess.run([sys.executable, os.path.join(HERE, "survey", "plan_scope.py")]
                           + self.ARGS + ["--stage", "btf3:/nope/items.json:cot"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not exist", r.stdout + r.stderr)

    def test_a_document_with_no_generated_region_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "plan.md")
            open(fake, "w").write("# a plan that types its numbers by hand\n25 models, 2750 units\n")
            r = subprocess.run([sys.executable, os.path.join(HERE, "survey", "plan_scope.py")]
                               + self.ARGS + ["--check", fake], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("no <!-- GEN:plan-scope -->", (r.stdout + r.stderr).replace("has no ", "no "))


if __name__ == "__main__":
    unittest.main(verbosity=2)
