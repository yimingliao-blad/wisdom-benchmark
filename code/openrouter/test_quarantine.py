"""M4 acceptance — the quarantine policy (owner ruling 2026-08-08).

An error is a METHOD defect, not bad luck. In REAL mode a failing model's remaining units are
dropped, EVERY OTHER MODEL RUNS TO COMPLETION, and the manifest enumerates exactly what to re-run.
In SMOKE mode the same error halts the run instead, because smoke is where the method gets fixed.

THE FAILURE THIS GUARDS: a unit that disappears without appearing anywhere. A silent drop shrinks
the sample for precisely the models that misbehave, which biases the result toward the well-behaved
ones — invisibly.

No network: the API call is replaced by a stub. Run: python3 -m unittest test_quarantine -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BROKEN = "broken/always-fails"
GOOD_A, GOOD_B = "good/model-a", "good/model-b"

# A stub run injected with -c so the real runner executes end to end without touching the network.
HARNESS = r'''
import json, sys, types
sys.path.insert(0, {here!r})
import run_openrouter as R, completeness_review as CR

def fake_call(prompt, mr, start_tokens, cap, reasoning=None):
    trace = [{{"budget": start_tokens, "outcome": "ok", "chars": 40}}]
    if mr["id"] == {broken!r}:
        # A provider error delivered with HTTP 200 -- the mistral-small-3.1 shape.
        raw = {{"provider": "FakeCloud", "usage": {{"prompt_tokens": 0, "completion_tokens": 1}},
                "choices": [{{"finish_reason": "error",
                              "message": {{"content": "To predict whether the sha"}}}}]}}
        return "To predict whether the sha", raw, 0.0001, trace
    raw = {{"provider": "FakeGood", "usage": {{"prompt_tokens": 300, "completion_tokens": 40}},
            "choices": [{{"finish_reason": "stop",
                          "message": {{"content": "Weighing it up.\n\n\\boxed{{No}}"}}}}]}}
    return "Weighing it up.\n\n\\boxed{{No}}", raw, 0.0001, trace

R.call_with_escalation = fake_call
CR.review = lambda *a, **k: (CR.COMPLETE, "verdict: complete", "stop")   # layer 2 stubbed
sys.argv = {argv!r}
R.main()
'''


def _write_inputs(d, n_items=3):
    items = [{"item_id": f"q{i}", "prompt": "IMPORTANT: Your final answer MUST end with this exact "
                                            "format:\n\\boxed{Yes} or \\boxed{No}", "level": 1}
             for i in range(n_items)]
    json.dump(items, open(os.path.join(d, "items.json"), "w"))
    roster = [{"series": "S", "id": m, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
               "in": 0.1, "out": 0.1} for m in (GOOD_A, BROKEN, GOOD_B)]
    json.dump(roster, open(os.path.join(d, "roster.json"), "w"))
    json.dump({m: 128000 for m in (GOOD_A, BROKEN, GOOD_B)}, open(os.path.join(d, "caps.json"), "w"))
    return items, roster


def _run(d, mode, tag, workers=1):
    argv = ["run_openrouter.py", "--items", os.path.join(d, "items.json"), "--bench", "futurex",
            "--tag", tag, "--models", os.path.join(d, "roster.json"),
            "--caps", os.path.join(d, "caps.json"), "--max-calls", "500", "--max-spend", "5",
            "--workers", str(workers), "--mode", mode,
            # EXPLICIT: this suite predates the CoT drop and assumed the old two-arm default.
            # Pinning both arms here keeps its 3-items-x-2-arms=6 arithmetic meaningful, and stops
            # it silently re-encoding whatever the default happens to be.
            "--arms", "original,cot"]
    src = HARNESS.format(here=HERE, broken=BROKEN, argv=argv)
    p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=180)
    return p


class Quarantine(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        _write_inputs(self.d)
        self.tag = "qtest"
        self.out = os.path.join(HERE, "runs", f"or_futurex_{self.tag}")
        shutil.rmtree(self.out, ignore_errors=True)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_real_mode_quarantines_the_broken_model_and_finishes_the_others(self):
        p = _run(self.d, "real", self.tag)
        self.assertEqual(p.returncode, 0, f"runner failed:\n{p.stdout}\n{p.stderr}")
        recs = [json.loads(l) for l in open(os.path.join(self.out, "records.jsonl")) if l.strip()]
        man = json.load(open(os.path.join(self.out, "quarantine_manifest.json")))

        by_model = {}
        for r in recs:
            by_model.setdefault(r["model"], []).append(r)

        # SIBLINGS UNTOUCHED: 3 items x 2 arms each.
        for good in (GOOD_A, GOOD_B):
            self.assertEqual(len(by_model.get(good, [])), 6,
                             f"{good} must complete all 6 units; the quarantine must not touch it")
            self.assertTrue(all(r["completeness"] == "COMPLETE" for r in by_model[good]))
            self.assertTrue(all(r["compliant"] is True for r in by_model[good]))

        # THE BROKEN MODEL: stopped early, and never scored as non-compliant.
        broken_recs = by_model.get(BROKEN, [])
        self.assertGreaterEqual(len(broken_recs), 1)
        self.assertLess(len(broken_recs), 6, "the broken model must NOT run all its units")
        for r in broken_recs:
            self.assertEqual(r["completeness"], "PROVIDER_ERROR")
            self.assertIsNone(r["compliant"], "a dead call must never carry a compliance value")

        # NO SILENT DROPS: attempted + listed-for-rerun == the full plan for that model.
        self.assertIn(BROKEN, [q["model"] for q in man["quarantined_models"]])
        rerun = [u for u in man["units_to_rerun"] if u["model"] == BROKEN]
        self.assertEqual(len(broken_recs) + len(rerun), 6,
                         "every planned unit must be either attempted or listed for re-run")
        self.assertEqual(man["units_to_rerun_count"], len(man["units_to_rerun"]))

    def test_manifest_carries_the_fields_needed_to_reproduce_the_rerun(self):
        """Codex C6: model, arm, question id, attempt count, failure reason, run config + hash."""
        _run(self.d, "real", self.tag)
        man = json.load(open(os.path.join(self.out, "quarantine_manifest.json")))
        self.assertTrue(man["run_config_hash"])
        for k in ("bench", "arms", "items", "models", "max_tokens", "mode"):
            self.assertIn(k, man["run_config"])
        q = man["quarantined_models"][0]
        for k in ("model", "first_verdict", "failures", "attempts"):
            self.assertIn(k, q)
        self.assertTrue(q["failures"][0]["reason"], "a failure must carry its reason")
        for u in man["units_to_rerun"]:
            for k in ("model", "item_id", "arm"):
                self.assertIn(k, u)

    def test_smoke_mode_records_every_error_and_runs_to_completion(self):
        """Owner 2026-08-08: the smoke surfaces EVERY error class in one pass.

        It used to halt on the first defect. That revealed one class per run and threw away the
        remaining planned calls each time -- ~230 already-bought calls on one occasion. Now every
        error is recorded and the run continues; the ledger carries them all.
        """
        p = _run(self.d, "smoke", self.tag)
        self.assertEqual(p.returncode, 0, f"smoke must complete:\n{p.stdout}\n{p.stderr}")
        self.assertIn("recorded, continuing", p.stdout, "the error must be logged, not swallowed")
        recs = [json.loads(l) for l in open(os.path.join(self.out, "records.jsonl")) if l.strip()]
        by_model = {}
        for r in recs:
            by_model.setdefault(r["model"], []).append(r)
        # EVERY model runs its full 6 units, including the broken one: no halt, no quarantine.
        for m in (GOOD_A, GOOD_B, BROKEN):
            self.assertEqual(len(by_model.get(m, [])), 6,
                             f"{m} must complete all units in smoke mode")
        man = json.load(open(os.path.join(self.out, "quarantine_manifest.json")))
        self.assertFalse(man["halted"])
        self.assertEqual(man["units_to_rerun"], [], "nothing is deferred when nothing is quarantined")
        # and the failure ledger must DOCUMENT them
        led = json.load(open(os.path.join(self.out, "failure_ledger.json")))
        self.assertEqual(led["n_failures"], 6, "all 6 broken units must appear in the ledger")
        self.assertIn("PROVIDER_ERROR", str(led["by_class"]))


class PostRunInvariant(unittest.TestCase):
    """Codex C7 — the check must catch a forbidden record written OUTSIDE the runner."""

    def test_a_forbidden_record_is_caught(self):
        import run_openrouter as R
        d = tempfile.mkdtemp()
        p = os.path.join(d, "records.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"model": "m", "item_id": "q1", "arm": "original",
                                "completeness": "TRUNCATED", "compliant": True,
                                "answer_extractable": True}) + "\n")
        with self.assertRaises(SystemExit) as cm:
            R.verify_records(p)
        self.assertIn("PREMISE-COMPLIANCE-ONLY-WHEN-OBSERVED", str(cm.exception))
        shutil.rmtree(d, ignore_errors=True)

    def test_a_refusal_scored_as_unknown_is_caught(self):
        """The M5 correction, enforced on disk: NO_ANSWER is the study's negative result and MUST
        carry compliant=False. Recording it as None silently deletes the observation."""
        import run_openrouter as R
        d = tempfile.mkdtemp(); p = os.path.join(d, "records.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"model": "m", "item_id": "q1", "arm": "original",
                                "completeness": "NO_ANSWER", "compliant": None,
                                "answer_extractable": False}) + "\n")
        with self.assertRaises(SystemExit) as cm:
            R.verify_records(p)
        self.assertIn("NO_ANSWER must score compliant=False", str(cm.exception))
        shutil.rmtree(d, ignore_errors=True)

    def test_a_clean_file_passes(self):
        import run_openrouter as R
        d = tempfile.mkdtemp()
        p = os.path.join(d, "records.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"model": "m", "item_id": "q1", "arm": "original",
                                "completeness": "COMPLETE", "compliant": True,
                                "answer_extractable": True}) + "\n")
            f.write(json.dumps({"model": "m", "item_id": "q2", "arm": "cot",
                                "completeness": "TRUNCATED", "compliant": None,
                                "answer_extractable": False}) + "\n")
            f.write(json.dumps({"model": "m", "item_id": "q3", "arm": "original",
                                "completeness": "NO_ANSWER", "compliant": False,
                                "answer_extractable": False}) + "\n")
        R.verify_records(p)          # must not raise
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
