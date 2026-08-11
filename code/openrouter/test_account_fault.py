"""D-OR-16 regression — an ACCOUNT-level fault halts the run and blames no model.

JUDGE_GATE_BYPASS_REASON='this test AUTHORS NO JUDGE: it replaces CR.review with a constant lambda so
that no LLM judge or oracle runs at all, exactly as test_quarantine.py already does. The gate matched
the assignment to CR.review; there is no judge prompt, no grading, and no model call in this file.'

WHAT HAPPENED (2026-08-08, live, mid-run). OpenRouter returned
`HTTP 403 "Org member budget limit exceeded (monthly limit)"` to every model. The runner treated each
403 as that model's failure and quarantined 22 of 37 models, none of which had misbehaved. Left
unfixed it would have censored ~2,400 units against innocent models and A13 would have failed them
for a loss that was never theirs. The discriminator is one question: *would this error have hit any
model I called?*

WHY IT NEEDS A TEST AND NOT A COMMENT. The fix is one `if` ahead of the quarantine branch. Anyone
reordering that block, or adding a status to the retry set, silently restores the defect — and it is
invisible offline, because it only shows up when a provider returns 4xx to everything at once.

No network: the API call is stubbed. Run: python3 -m unittest test_account_fault -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = ["good/model-a", "good/model-b", "good/model-c"]

HARNESS = r'''
import json, sys
sys.path.insert(0, {here!r})
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")
import llm_api, run_openrouter as R, completeness_review as CR

STATUS = {status!r}

def fake_call(prompt, mr, start_tokens, cap, reasoning=None):
    # EVERY model gets the same account-level rejection -- that is what makes it account-level.
    e = llm_api.LlmError("Org member budget limit exceeded (monthly limit)")
    e.status = STATUS
    e.error_type = "insufficient_credits"
    raise e

R.call_with_escalation = fake_call
CR.review = lambda *a, **k: (CR.COMPLETE, "verdict: complete", "stop")
sys.argv = {argv!r}
R.main()
'''


def _inputs(d):
    items = [{"item_id": f"q{i}", "level": 1,
              "prompt": "IMPORTANT: Your final answer MUST end with this exact format:\n"
                        "\\boxed{Yes} or \\boxed{No}"} for i in range(3)]
    json.dump(items, open(os.path.join(d, "items.json"), "w"))
    json.dump([{"series": "S", "id": m, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
                "in": 0.1, "out": 0.1, "cap": 128000} for m in MODELS],
              open(os.path.join(d, "roster.json"), "w"))
    return items


def _run(d, status, tag="acctfault"):
    argv = ["run_openrouter.py", "--items", os.path.join(d, "items.json"), "--bench", "futurex",
            "--tag", tag, "--models", os.path.join(d, "roster.json"),
            "--caps", os.path.join(d, "missing-caps.json"),
            "--max-calls", "500", "--max-spend", "5", "--workers", "1", "--mode", "real",
            "--no-review", "--arms", "original"]
    src = HARNESS.format(here=HERE, status=status, argv=argv)
    return subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=180)


class AnAccountFaultIsRunFatalNotModelFatal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        _inputs(cls.d)
        cls.p = _run(cls.d, 403)
        cls.out = cls.p.stdout + cls.p.stderr
        d = os.path.join(HERE, "runs", "or_futurex_acctfault")
        rp, fp = os.path.join(d, "records.jsonl"), os.path.join(d, "faults.jsonl")
        cls.recs = ([json.loads(l) for l in open(rp, encoding="utf-8") if l.strip()]
                    if os.path.exists(rp) else [])
        # M6-T23: a call that delivered nothing writes a FAULT EVENT, not a record.
        cls.faults = ([json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
                      if os.path.exists(fp) else [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(os.path.join(HERE, "runs", "or_futurex_acctfault"), ignore_errors=True)
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_the_run_HALTS_and_says_it_is_a_run_fault(self):
        self.assertIn("HALT — ACCOUNT fault (account:403)", self.out)
        self.assertIn("ACCOUNT's, not any model's", self.out)

    def test_NO_model_is_quarantined(self):
        """22 of 37 were, live. Not one of them had misbehaved."""
        self.assertNotIn("QUARANTINED", self.out)

    def test_a_403_writes_a_FAULT_EVENT_and_NO_RECORD(self):
        """M6-T23 changed this contract deliberately. A 403 delivered no body, so it is not a
        result and must not sit in the records file where the denominator, resume and the
        duplicate checks will read it -- that is what produced D-OR-18, D-OR-22 and D-OR-25 and
        crashed the 2026-08-10 run."""
        self.assertEqual(self.recs, [], "a call that delivered nothing must write NO record")
        self.assertTrue(self.faults, "it must still be recorded -- as a fault event")
        f = self.faults[0]
        self.assertEqual(f["classification"], "account:403")
        self.assertFalse(f["body_present"])
        self.assertEqual(f["http_status"], 403)
        self.assertIn("requested_max_tokens", f, "D-OR-20 must survive the move to fault events")

    def test_the_work_is_left_re_runnable(self):
        """The point of D-OR-16 and D-OR-18, now achieved by absence rather than by a re-queue
        rule: with no record written, the unit is simply not done and resume buys it."""
        import persistence as PS
        mp = os.path.join(HERE, "runs", "or_futurex_acctfault", "manifest.json")
        if not os.path.exists(mp):
            self.skipTest("the run halted before writing a manifest")
        with open(mp, encoding="utf-8") as fh:
            mani = json.load(fh)
        rs = PS.resume_state(mani, self.recs, strict=False)
        self.assertEqual(rs["done"], 0)
        self.assertEqual(len(rs["todo"]), mani["n_units"], "every unit stays buyable")
        self.assertEqual(rs["requeued_undelivered"], [], "nothing to re-queue: nothing was written")


class TheDiscriminatorIsTheSTATUSNotTheModel(unittest.TestCase):
    """401/402/403 are account-level; a 500 is not, and must keep the per-model policy."""

    def test_the_account_fatal_set_is_exactly_the_auth_and_billing_codes(self):
        import run_openrouter as R
        self.assertEqual(R.ACCOUNT_FATAL_STATUS, {401, 402, 403})

    def test_a_server_error_is_NOT_account_fatal(self):
        import run_openrouter as R
        for s in (500, 502, 503, 504, 429):
            self.assertNotIn(s, R.ACCOUNT_FATAL_STATUS,
                             f"{s} is a provider/transport problem; quarantine policy still applies")
        self.assertTrue(R.RETRYABLE_STATUS & {500, 502, 503, 504, 429})


if __name__ == "__main__":
    unittest.main(verbosity=2)
