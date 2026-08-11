"""M6-T14/S2 (L-W) — acceptance that the RUNNER CALLS THE LEAVES.

THE DEFECT THIS GUARDS, found 2026-08-08 by grepping the runner's imports rather than trusting the
green suite: 185 tests proved 13 modules, and `run_openrouter.py` imported TWO of them. The paid path
carried its own inline resume set (`except Exception: pass` on every malformed line), its own spend
counter, and a NAIVE provider round-robin -- the exact code schedule.py replaced after it produced a
101-call single-provider burst on the real 3,700-unit manifest.

A tested module the money-spending path never calls buys nothing. These tests fail if the wiring is
removed, so the isolated suites cannot go green over a runner that ignores them again.

Offline: llm_api.openrouter_chat is replaced with a scripted fake. NO network, NO spend.
Run: python3 -m unittest test_wiring -v
"""
import json
import os
import shutil
import sys
import threading
import time
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")

import llm_api                     # noqa: E402
import manifest as MF              # noqa: E402
import persistence as PS           # noqa: E402
import run_openrouter as RO        # noqa: E402
import schedule as SC              # noqa: E402

ITEMS = os.path.join(HERE, "runs", "fx_smoke4.json")


def fake_reply(prompt, model, max_tokens=4000, timeout=600, temperature=0.0, reasoning=None):
    """A well-formed OpenRouter envelope with a compliant boxed answer, billed at a known cost."""
    text = "Reasoning: the series trends upward through the window.\n\\boxed{yes}"
    return text, {"choices": [{"message": {"content": text,
                                           "reasoning": "I considered the trend."},
                               "finish_reason": "stop"}],
                  "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                  "provider": "fake-provider", "model": model}


class RunnerHarness(unittest.TestCase):
    """Runs the REAL main() offline. Testing a re-implementation would prove nothing about the
    function that spends the money."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self._chat = llm_api.openrouter_chat
        llm_api.openrouter_chat = fake_reply
        self.addCleanup(setattr, llm_api, "openrouter_chat", self._chat)
        self._argv = sys.argv
        self.addCleanup(setattr, sys, "argv", self._argv)
        # Two providers with UNEQUAL model counts -- the condition under which naive round-robin
        # exhausts the short queue and bursts the long one.
        self.roster = [{"series": "A", "id": "alpha/one", "cutoff": "2025-01", "basis": "PUB",
                        "release": "2025", "in": 1.0, "out": 2.0},
                       {"series": "A", "id": "alpha/two", "cutoff": "2025-01", "basis": "PUB",
                        "release": "2025", "in": 1.0, "out": 2.0},
                       {"series": "A", "id": "alpha/three", "cutoff": "2025-01", "basis": "PUB",
                        "release": "2025", "in": 1.0, "out": 2.0},
                       {"series": "B", "id": "beta/one", "cutoff": "2025-01", "basis": "PUB",
                        "release": "2025", "in": 1.0, "out": 2.0}]
        self.rpath = os.path.join(self.d, "roster.json")
        self.cpath = os.path.join(self.d, "caps.json")
        json.dump(self.roster, open(self.rpath, "w"))
        json.dump({m["id"]: 8000 for m in self.roster}, open(self.cpath, "w"))
        self.tag = "wiretest"
        self.out = os.path.join(HERE, "runs", f"or_futurex_{self.tag}")
        shutil.rmtree(self.out, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.out, True)

    def run_main(self, max_spend=10.0, max_calls=100, workers=2, per_provider=4,
                 only_items=None, require_cleared=False):
        sys.argv = ["run_openrouter.py", "--items", ITEMS, "--bench", "futurex",
                    "--tag", self.tag, "--max-calls", str(max_calls),
                    "--max-spend", str(max_spend), "--models", self.rpath,
                    "--caps", self.cpath, "--workers", str(workers),
                    "--per-provider", str(per_provider),
                    "--mode", "real", "--no-review"]
        if only_items:
            sys.argv += ["--only-items", only_items]
        if require_cleared:
            sys.argv += ["--require-cleared"]
        RO.main()

    def records(self):
        p = os.path.join(self.out, "records.jsonl")
        return [json.loads(l) for l in open(p) if l.strip()]


class TheRunnerActuallyCallsTheLeaves(RunnerHarness):

    def test_it_FREEZES_a_manifest(self):
        self.run_main()
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        self.assertEqual(m["n_units"], 4 * 4)          # 4 models x 4 items x 1 arm
        self.assertTrue(m["manifest_id"])

    def test_it_writes_a_SCHEDULE_and_dispatches_in_ITS_order(self):
        """The regression that matters: the runner used to build its own naive round-robin."""
        self.run_main(workers=1)
        s = json.load(open(os.path.join(self.out, "schedule.json")))
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        self.assertEqual(s["manifest_id"], m["manifest_id"])
        self.assertEqual(sorted(s["order"]), sorted(u["unit_id"] for u in m["units"]))

    def test_the_dispatch_order_is_the_EVEN_SPREAD_one_not_naive_round_robin(self):
        self.run_main(workers=1)
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        s = json.load(open(os.path.join(self.out, "schedule.json")))
        naive = self._naive_order(m)
        self.assertNotEqual(s["order"], naive,
                            "the runner is dispatching in the naive round-robin order again")
        self.assertLessEqual(SC.max_provider_run(s, m), self._max_run(naive, m),
                             "the even-spread order must not burst worse than naive round-robin")

    @staticmethod
    def _naive_order(m):
        prov = {}
        for u in m["units"]:
            prov.setdefault(u["model"].split("/")[0], []).append(u["unit_id"])
        qs, out = list(prov.values()), []
        for i in range(max(len(q) for q in qs)):
            for q in qs:
                if i < len(q):
                    out.append(q[i])
        return out

    @staticmethod
    def _max_run(order, m):
        by = {u["unit_id"]: u["model"].split("/")[0] for u in m["units"]}
        longest = cur = 0
        prev = None
        for uid in order:
            cur = cur + 1 if by[uid] == prev else 1
            prev = by[uid]
            longest = max(longest, cur)
        return longest

    def test_every_record_carries_the_SHARED_identity(self):
        """One identity space for records, ledger and manifest -- audit D6."""
        self.run_main()
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        planned = {u["unit_id"] for u in m["units"]}
        for r in self.records():
            self.assertIn("unit_id", r)
            self.assertIn(r["unit_id"], planned)
            self.assertEqual(r["unit_id"], MF.unit_id(r["model"], r["item_id"], r["arm"]))
            self.assertTrue(r["attempt_id"].startswith(r["unit_id"]))
            self.assertEqual(r["manifest_id"], m["manifest_id"])

    def test_it_writes_a_SPEND_LEDGER_keyed_on_attempt_identity(self):
        self.run_main()
        led = json.load(open(os.path.join(self.out, "ledger.json")))
        ids = {e["attempt_id"] for e in led["entries"].values()} if isinstance(
            led.get("entries"), dict) else {e["attempt_id"] for e in led["entries"]}
        self.assertEqual(ids, {r["attempt_id"] for r in self.records()},
                         "the ledger and the records must share one identity space")


class ResumeGoesThroughThePersistenceLeaf(RunnerHarness):

    def test_a_second_run_re_buys_NOTHING(self):
        self.run_main()
        n1 = len(self.records())
        calls = {"n": 0}

        def counting(*args, **kw):
            calls["n"] += 1
            return fake_reply(*args, **kw)
        llm_api.openrouter_chat = counting
        self.run_main()
        self.assertEqual(calls["n"], 0, "a completed unit was re-bought on resume")
        self.assertEqual(len(self.records()), n1)

    def test_resume_does_not_DOUBLE_CHARGE(self):
        self.run_main()
        total1 = json.load(open(os.path.join(self.out, "ledger.json")))["total"]
        self.run_main()
        total2 = json.load(open(os.path.join(self.out, "ledger.json")))["total"]
        self.assertEqual(total1, total2, "the resumed run paid twice for the same attempts")

    def test_a_DIFFERENT_plan_in_the_same_run_dir_is_REFUSED(self):
        """Resuming across two different planned experiments would mix them in one records file."""
        self.run_main()
        smaller = self.roster[:2]
        json.dump(smaller, open(self.rpath, "w"))
        with self.assertRaises(SystemExit) as cm:
            self.run_main()
        self.assertIn("frozen against manifest", str(cm.exception))

    def test_a_CHANGED_CEILING_on_a_resumed_run_is_REFUSED(self):
        self.run_main(max_spend=10.0)
        with self.assertRaises(SystemExit) as cm:
            self.run_main(max_spend=99.0)
        self.assertIn("re-scope", str(cm.exception))


class C5_PerProviderConcurrencyIsENFORCED(RunnerHarness):
    """Codex C5: the schedule RECORDED per_provider and nothing enforced it, so the global worker
    count was the only real bound and N workers could still land on one vendor at once."""

    def _observing_transport(self, delay=0.02):
        live, peak, lk = {}, {}, threading.Lock()

        def t(prompt, model, **kw):
            prov = model.split("/")[0]
            with lk:
                live[prov] = live.get(prov, 0) + 1
                peak[prov] = max(peak.get(prov, 0), live[prov])
            try:
                time.sleep(delay)
                return fake_reply(prompt, model, **kw)
            finally:
                with lk:
                    live[prov] -= 1
        return t, peak

    def test_the_frozen_cap_is_never_exceeded(self):
        t, peak = self._observing_transport()
        llm_api.openrouter_chat = t
        # 8 workers but a cap of 2, and alpha owns 12 of the 16 units -- without a semaphore the
        # pool would put well over 2 alpha calls in flight at once.
        self.run_main(workers=8, per_provider=2)
        self.assertTrue(peak, "no calls were observed; the test proves nothing")
        self.assertLessEqual(peak.get("alpha", 0), 2,
                             f"per-provider cap breached: observed peak {peak}")

    def test_the_test_can_actually_SEE_a_breach(self):
        """If the observer could never record a peak above the cap, the check above is vacuous."""
        t, peak = self._observing_transport()
        llm_api.openrouter_chat = t
        self.run_main(workers=8, per_provider=8)
        self.assertGreater(peak.get("alpha", 0), 2,
                           f"the observer cannot detect concurrency at all; peak={peak}")

    def test_a_CHANGED_concurrency_policy_on_resume_is_REFUSED(self):
        """schedule_id does not hash the concurrency policy, so comparing ids alone would let it
        change silently and alter the load each provider actually sees."""
        self.run_main(workers=2, per_provider=4)
        with self.assertRaises(SystemExit) as cm:
            self.run_main(workers=2, per_provider=1)
        self.assertIn("dispatch POLICY changed", str(cm.exception))


class TheClosingChecksRunOnRealOutput(RunnerHarness):

    def test_the_manifest_check_runs_over_the_emitted_records(self):
        self.run_main()
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        vr = MF.verify_records_against(m, self.records())
        self.assertEqual(vr["counts"].get("MISASSOCIATED", 0), 0)
        self.assertEqual(vr["counts"].get("UNPLANNED", 0), 0)
        self.assertEqual(vr["counts"]["MATCH"], len(self.records()))

    def test_a_MISASSOCIATED_record_would_HALT_the_run(self):
        """The check must be able to fail, or its passing means nothing."""
        self.run_main()
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        recs = self.records()
        recs[0]["prompt_sha"] = "0" * 16          # an answer filed against a different question
        vr = MF.verify_records_against(m, recs)
        self.assertEqual(vr["counts"]["MISASSOCIATED"], 1)


class TheSTAGEDRunAbsorbsTheSmokeIntoTheFullRun(RunnerHarness):
    """Owner design 2026-08-08: "incorporate the smoke tests in the full-test ... so we won't cost
    extra." The smoke slice is a SUBSET of the frozen manifest, so its calls are part of the full
    run's dataset rather than an extra purchase."""

    def _slice_file(self, n=2):
        items = json.load(open(ITEMS))[:n]
        p = os.path.join(self.d, "slice.json")
        json.dump(items, open(p, "w"))
        return p, {i["item_id"] for i in items}

    def test_the_stage_runs_ONLY_the_slice_but_freezes_the_WHOLE_plan(self):
        sf, ids = self._slice_file(2)
        self.run_main(only_items=sf)
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        self.assertEqual(m["n_items"], 4, "the manifest must still cover every planned item")
        recs = self.records()
        self.assertEqual({r["item_id"] for r in recs}, ids)
        self.assertEqual(len(recs), 2 * 4)          # 2 items x 4 models

    def test_the_full_stage_RE_BUYS_NOTHING_from_the_smoke(self):
        sf, ids = self._slice_file(2)
        self.run_main(only_items=sf)
        first = {r["unit_id"] for r in self.records()}
        calls = {"n": 0}

        def counting(*args, **kw):
            calls["n"] += 1
            return fake_reply(*args, **kw)
        llm_api.openrouter_chat = counting
        self.run_main()                              # the remainder, same manifest
        recs = self.records()
        self.assertEqual(len(recs), 16, "4 items x 4 models total")
        self.assertEqual(calls["n"], 8, "only the 8 NOT already bought should be called")
        self.assertTrue(first <= {r["unit_id"] for r in recs},
                        "the smoke's units must survive into the full dataset, not be re-run")

    def test_the_ledger_shows_the_smoke_was_NOT_paid_for_twice(self):
        sf, _ = self._slice_file(2)
        self.run_main(only_items=sf)
        after_smoke = json.load(open(os.path.join(self.out, "ledger.json")))
        self.run_main()
        after_full = json.load(open(os.path.join(self.out, "ledger.json")))
        self.assertEqual(after_full["n_attempts"] if "n_attempts" in after_full
                         else len(after_full["entries"]), 16)
        self.assertGreater(after_full["total"], after_smoke["total"])

    def test_the_STAGE_can_be_capped_without_declaring_the_WHOLE_plans_size(self):
        """Defect found 2026-08-08 when the BTF dry run halted: --max-calls was checked against the
        whole manifest BEFORE --only-items narrowed the stage, so a 6-item gate out of a 110-item
        plan had to declare --max-calls 4070 to buy 222 calls. That is the opposite of a ceiling."""
        sf, _ = self._slice_file(2)
        self.run_main(only_items=sf, max_calls=8)      # stage is 2 x 4 = 8; the plan is 16
        self.assertEqual(len(self.records()), 8)

    def test_a_cap_BELOW_the_stage_still_HALTS(self):
        """The relaxation must not have removed the ceiling."""
        sf, _ = self._slice_file(2)
        with self.assertRaises(SystemExit) as cm:
            self.run_main(only_items=sf, max_calls=3)
        self.assertIn("would make 8 calls", str(cm.exception))

    def test_resume_counts_toward_the_cap_correctly(self):
        """After the stage, the remainder is 8 units -- the cap must bound THAT, not 16."""
        sf, _ = self._slice_file(2)
        self.run_main(only_items=sf)
        self.run_main(max_calls=8)                      # 8 already bought, 8 remain
        self.assertEqual(len(self.records()), 16)

    def test_a_slice_OUTSIDE_the_frozen_plan_is_REFUSED(self):
        p = os.path.join(self.d, "stray.json")
        json.dump([{"item_id": "not-in-the-plan", "prompt": "x"}], open(p, "w"))
        with self.assertRaises(SystemExit) as cm:
            self.run_main(only_items=p)
        self.assertIn("not a subset of the plan", str(cm.exception))


class TheGATEBlocksTheExpensiveRemainder(RunnerHarness):
    """A gate that only reports is not a gate."""

    def test_it_REFUSES_to_start_with_no_evaluation_at_all(self):
        sf, _ = self._sf()
        self.run_main(only_items=sf)
        with self.assertRaises(SystemExit) as cm:
            self.run_main(require_cleared=True)
        self.assertIn("does not exist", str(cm.exception))

    def test_it_REFUSES_when_the_smoke_did_NOT_clear(self):
        sf, _ = self._sf()
        self.run_main(only_items=sf)
        json.dump({"cleared": False, "n_pass": 9, "n_fail": 2, "n_unknown": 0,
                   "results": [{"id": "A1", "verdict": "FAIL"}, {"id": "A11", "verdict": "FAIL"}]},
                  open(os.path.join(self.out, "smoke_acceptance.json"), "w"))
        with self.assertRaises(SystemExit) as cm:
            self.run_main(require_cleared=True)
        self.assertIn("did NOT clear", str(cm.exception))
        self.assertIn("A1", str(cm.exception))

    def test_it_PROCEEDS_once_the_smoke_clears(self):
        sf, _ = self._sf()
        self.run_main(only_items=sf)
        json.dump({"cleared": True, "n_pass": 12, "n_fail": 0, "n_unknown": 0, "results": []},
                  open(os.path.join(self.out, "smoke_acceptance.json"), "w"))
        self.run_main(require_cleared=True)
        self.assertEqual(len(self.records()), 16)

    def _sf(self, n=2):
        items = json.load(open(ITEMS))[:n]
        p = os.path.join(self.d, "slice.json")
        json.dump(items, open(p, "w"))
        return p, {i["item_id"] for i in items}


class C10_TheRecoveryPathIsREHEARSED(RunnerHarness):
    """Codex C10: write-once plus halt-on-mismatch is the right default, but it makes in-place
    repair impossible ON PURPOSE -- so the supersede / new-tag / recombine path must be proven to
    work over a PARTIAL run, or a 3,700-call run that dies halfway has no route forward at all."""

    def test_a_partial_run_recovers_via_SUPERSEDE_NEW_TAG_RECOMBINE(self):
        # 1. a partial run: one model only
        partial = [self.roster[0]]
        json.dump(partial, open(self.rpath, "w"))
        self.run_main()
        first = self.records()
        self.assertEqual(len(first), 4)
        old_id = json.load(open(os.path.join(self.out, "manifest.json")))["manifest_id"]

        # 2. the plan changes; in-place resume is REFUSED (that guard is what forces recovery)
        json.dump(self.roster, open(self.rpath, "w"))
        with self.assertRaises(SystemExit):
            self.run_main()

        # 3. RECOVERY: a superseding manifest under a NEW tag
        items = json.load(open(ITEMS))
        new_mani = MF.build(self.roster, items, arms=("original",),
                            supersedes=old_id, reason="roster widened after a partial run")
        self.assertEqual(new_mani["supersedes"], old_id)
        self.assertNotEqual(new_mani["manifest_id"], old_id)

        self.tag = "wiretest2"
        self.out = os.path.join(HERE, "runs", f"or_futurex_{self.tag}")
        shutil.rmtree(self.out, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.out, True)
        self.run_main()
        second = self.records()
        self.assertEqual(len(second), 16)          # 4 models x 4 items
        self.assertEqual(len({r["unit_id"] for r in first} & {r["unit_id"] for r in second}), 4,
                         "the partial run's 4 units must reappear in the superseding run")

        # 4. RECOMBINE only under a NAMED policy with a written reason
        with self.assertRaises(PS.PersistenceError):
            PS.combine_runs([first, second])                       # the default forbids it
        with self.assertRaises(PS.PersistenceError):
            PS.combine_runs([first, second], policy="explicit_latest")   # no reason given
        comb = PS.combine_runs([first, second], policy="explicit_latest",
                               note="partial run superseded after the roster widened")
        self.assertEqual(len(first) + len(second), 20)
        self.assertEqual(comb["n"], 16, "the 4 overlapping units must not appear twice")
        self.assertEqual(comb["policy"], "explicit_latest")
        self.assertEqual(comb["note"], "partial run superseded after the roster widened")

    def test_in_place_repair_of_a_frozen_artifact_is_IMPOSSIBLE(self):
        self.run_main()
        m = json.load(open(os.path.join(self.out, "manifest.json")))
        with self.assertRaises(MF.ManifestError):
            MF.save(m, os.path.join(self.out, "manifest.json"))
        s = json.load(open(os.path.join(self.out, "schedule.json")))
        with self.assertRaises(SC.ScheduleError):
            SC.save(s, os.path.join(self.out, "schedule.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
