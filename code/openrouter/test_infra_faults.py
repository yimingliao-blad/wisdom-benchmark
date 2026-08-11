"""M6-T23 — one policy for infrastructure faults: retry 3, pause the model, halt the account.

JUDGE_GATE_BYPASS_REASON='authors no judge. Every call is stubbed and CR.review is replaced by a
constant lambda, so no LLM judge, oracle or model call runs. The gate matches on the llm_api import
and on the word verdict, which appears only where this asserts which verdicts stop being written.'

Owner, 2026-08-10: "if it is the API budget issue, it is equivalent to network failure, and you
should stop, and no other rules you should apply. I think you have made a lot of extra useless
work." … "retry 3 times, if still failed halt."

THE CATEGORY ERROR THIS FIXES. An infrastructure failure was being treated as a kind of RESULT --
given a verdict, written as a record, then read by the denominator, resume and the duplicate checks.
Measured on the run that crashed: 156 records for calls that delivered nothing and cost $0.0003, and
136 of 136 duplicate units traced to them. Three defects (D-OR-18, D-OR-22, D-OR-25) existed only to
manage records that should never have been written.

**A failed call is not a result. It is the absence of one.**

The tests that matter most here are the OVER-REACH guards: a rule that swallows real model behaviour
would be a worse defect than the one it replaces.

Offline. Transport stubbed. No key read, nothing bought.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import persistence as PS      # noqa: E402
import manifest as MF         # noqa: E402
import run_openrouter as R    # noqa: E402

OK_MODEL, BAD_MODEL = "maker/reliable", "maker/flaky"


class Err(Exception):
    transport = False
    transport_kind = None
    status = None
    error_type = None
    provider_code = None
    retry_after = None


def err(msg="boom", **kw):
    e = Err(msg)
    for k, v in kw.items():
        setattr(e, k, v)
    return e


class TheClassifierAnswersTheOwnersQuestion(unittest.TestCase):
    """'Is it purely lagging?' -- not 'which HTTP bucket is this'."""

    def test_transient_is_what_waiting_could_fix(self):
        for e in (err(status=500), err(status=503), err(status=504),
                  err(status=429, retry_after=30),
                  err(transport=True, transport_kind="WallClockExceeded")):
            self.assertEqual(R.classify_fault(e)[0], R.TRANSIENT, e.status)

    def test_the_account_codes_halt(self):
        for s in (401, 402, 403):
            self.assertEqual(R.classify_fault(err(status=s))[0], R.TERMINAL_ACCOUNT, s)

    def test_a_429_MEANING_quota_exhausted_is_an_account_fault_not_a_retry(self):
        """Codex C5. The live 403 arrived as a MESSAGE, not a distinct status; a 429 can do the same.
        Retrying an exhausted allowance is just spending the wall clock."""
        e = err("monthly quota exceeded for this key", status=429)
        self.assertEqual(R.classify_fault(e)[0], R.TERMINAL_ACCOUNT)

    def test_a_429_WITH_retry_after_is_still_transient(self):
        """The discriminator must not become 'any 429 is fatal' -- that would stop runs on ordinary
        throttling, which is the single most common recoverable fault."""
        e = err("rate limit exceeded, slow down", status=429, retry_after=12)
        self.assertEqual(R.classify_fault(e)[0], R.TRANSIENT)

    def test_a_bad_request_needs_a_human_not_a_wait(self):
        for s in (400, 404, 413, 422):
            self.assertEqual(R.classify_fault(err(status=s))[0], R.TERMINAL_REQUEST, s)

    def test_an_UNKNOWN_fault_is_transient_and_SAYS_it_is_unclassified(self):
        """Silently calling an unrecognised fault TERMINAL would stop a run for no stated reason."""
        policy, klass = R.classify_fault(err(status=418))
        self.assertEqual(policy, R.TRANSIENT)
        self.assertIn("unclassified", klass)

    def test_retries_are_THREE(self):
        import inspect
        self.assertEqual(inspect.signature(R._chat_with_backoff).parameters["tries"].default, 3,
                         "the owner asked for 3; 5 is retry budget spent on a fault that has "
                         "already said twice that it is not clearing")


class GapsAreExplainable(unittest.TestCase):
    """Codex C9. Once a failed call writes nothing, every gap looks alike unless something says why."""

    def setUp(self):
        items = json.load(open(os.path.join(HERE, "runs", "_frozen_fxgate_2026-08-08",
                                            "items.json"), encoding="utf-8"))[:2]
        roster = [{"series": "S", "id": m, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
                   "in": 0.1, "out": 0.1} for m in (OK_MODEL, BAD_MODEL)]
        self.m = MF.build(roster, items, arms=("original",), bench="futurex")
        self.u = {(x["model"], x["item_id"]): x for x in self.m["units"]}

    def rec(self, model, item):
        return {"model": model, "item_id": item, "arm": "original",
                "completeness": "COMPLETE", "finish_reason": "stop"}

    def test_the_four_kinds_partition_the_planned_set(self):
        items = sorted({u["item_id"] for u in self.m["units"]})
        recs = [self.rec(OK_MODEL, items[0])]
        faults = [{"unit_id": self.u[(BAD_MODEL, items[0])]["unit_id"], "model": BAD_MODEL,
                   "classification": "api:500"}]
        g = PS.explain_gaps(self.m, recs, faults)
        self.assertEqual(sum(g["counts"].values()), g["n_planned"])
        self.assertEqual(g["counts"]["done"], 1)
        self.assertEqual(g["counts"]["infra_fault_unbought"], 1)

    def test_a_unit_with_no_evidence_reads_as_never_dispatched(self):
        g = PS.explain_gaps(self.m, [], [])
        self.assertEqual(g["counts"]["never_dispatched"], g["n_planned"])

    def test_aggregate_transient_health_is_visible(self):
        """Codex C14: many short transients that each clear never trip a per-unit rule."""
        faults = [{"model": BAD_MODEL, "classification": "api:429"} for _ in range(7)]
        h = PS.transient_health(faults)
        self.assertEqual(h["n_faults"], 7)
        self.assertEqual(h["by_model"][BAD_MODEL], 7)


class TheUniquenessGateCountsPAYMENTS(unittest.TestCase):
    """D-OR-25, the third reader of 'duplicate' -- it crashed the run after all work was done."""

    def setUp(self):
        items = json.load(open(os.path.join(HERE, "runs", "_frozen_fxgate_2026-08-08",
                                            "items.json"), encoding="utf-8"))[:1]
        roster = [{"series": "S", "id": OK_MODEL, "cutoff": "2025-01", "basis": "PUB",
                   "release": "2025", "in": 0.1, "out": 0.1}]
        self.m = MF.build(roster, items, arms=("original",), bench="futurex")
        self.i = items[0]["item_id"]

    def row(self, verdict="COMPLETE", **kw):
        r = {"model": OK_MODEL, "item_id": self.i, "arm": "original", "completeness": verdict,
             "finish_reason": "stop"}
        r.update(kw)
        return r

    def test_an_attempt_then_an_answer_is_NOT_paying_twice(self):
        rows = [self.row("PROVIDER_ERROR", finish_reason=None), self.row()]
        self.assertEqual(PS.require_unique_within_run(rows), 2)

    def test_TWO_delivered_answers_still_RAISE(self):
        """Scoping the check must not become a way to stop noticing."""
        with self.assertRaises(PS.PersistenceError) as cm:
            PS.require_unique_within_run([self.row(), self.row()])
        self.assertIn("PAID FOR more than once", str(cm.exception))

    def test_the_real_corpus_that_crashed_the_run_now_passes(self):
        p = os.path.join(HERE, "runs", "or_futurex_fxgate", "records.jsonl")
        if not os.path.exists(p):
            self.skipTest("the live corpus is not present")
        with open(p, encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        PS.require_unique_within_run(recs, where="the 2026-08-10 run")   # must not raise


HARNESS = r'''
import json, sys
sys.path.insert(0, {here!r})
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")
import llm_api, run_openrouter as R, completeness_review as CR

CALLS = {{"n": 0}}
MODE = {mode!r}

def fake_chat(prompt, model, max_tokens=None, timeout=None, temperature=0.0, reasoning=None):
    CALLS["n"] += 1
    if model == {bad!r}:
        e = llm_api.LlmError({msg!r})
        e.status = {status!r}
        e.error_type = None
        e.provider_code = None
        e.retry_after = None
        e.transport = False
        raise e
    body = "Weighing it up. " * 12 + "\\boxed{{A}}"
    raw = {{"provider": "Stub", "usage": {{"prompt_tokens": 60, "completion_tokens": 40}},
            "choices": [{{"finish_reason": "stop", "message": {{"content": body}}}}]}}
    return body, raw

llm_api.openrouter_chat = fake_chat
CR.review = lambda *a, **k: (CR.COMPLETE, "verdict: complete", "stop")
sys.argv = {argv!r}
try:
    R.main()
finally:
    json.dump(CALLS, open({calls!r}, "w"))
'''


def _run(tag, status, msg, n_items=2):
    d = tempfile.mkdtemp()
    items = [{"item_id": f"q{i}", "level": 1,
              "prompt": "IMPORTANT: Your final answer MUST end with this exact format:\n"
                        "\\boxed{Yes} or \\boxed{No}"} for i in range(n_items)]
    json.dump(items, open(os.path.join(d, "items.json"), "w"))
    json.dump([{"series": "S", "id": m, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
                "in": 0.1, "out": 0.1, "cap": 8192, "cap_basis": "max_completion_tokens"}
               for m in (OK_MODEL, BAD_MODEL)],
              open(os.path.join(d, "roster.json"), "w"))
    calls = os.path.join(d, "calls.json")
    argv = ["run_openrouter.py", "--items", os.path.join(d, "items.json"), "--bench", "futurex",
            "--tag", tag, "--models", os.path.join(d, "roster.json"),
            "--caps", os.path.join(d, "none.json"), "--max-calls", "50", "--max-spend", "5",
            "--workers", "1", "--mode", "real", "--no-review", "--arms", "original"]
    src = HARNESS.format(here=HERE, argv=argv, calls=calls, bad=BAD_MODEL, status=status,
                         msg=msg, mode="x")
    p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=180)
    rd = os.path.join(HERE, "runs", f"or_futurex_{tag}")

    def load(name):
        fp = os.path.join(rd, name)
        return ([json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
                if os.path.exists(fp) else [])
    out = {"out": p.stdout + p.stderr, "records": load("records.jsonl"),
           "faults": load("faults.jsonl"),
           "calls": json.load(open(calls))["n"] if os.path.exists(calls) else 0}
    shutil.rmtree(rd, ignore_errors=True)
    shutil.rmtree(d, ignore_errors=True)
    return out


class OnTheRealDispatchPath(unittest.TestCase):
    """The policy, end to end through the actual runner."""

    def test_a_persistent_transient_PAUSES_ONE_MODEL_and_the_others_finish(self):
        """The owner's ruling on Codex C1: no silent holes, but no stop-the-world either."""
        r = _run("infra_transient", 503, "upstream unavailable")
        self.assertIn("PAUSED", r["out"])
        self.assertIn(BAD_MODEL, r["out"])
        self.assertNotIn("HALT", r["out"])
        good = [x for x in r["records"] if x["model"] == OK_MODEL]
        self.assertEqual(len(good), 2, "the reliable model must complete every unit")
        self.assertTrue(all(x["model"] != BAD_MODEL for x in r["records"]),
                        "the failing model contributes NO records")

    def test_it_retries_exactly_three_times_before_pausing(self):
        r = _run("infra_retries", 503, "upstream unavailable")
        # 2 successes from the good model + 3 attempts on the first bad unit; the second bad unit is
        # never dispatched because its model is already paused.
        self.assertEqual(r["calls"], 5, f"expected 2 good + 3 retries, got {r['calls']}")

    def test_an_ACCOUNT_fault_halts_everything_with_no_retry(self):
        r = _run("infra_account", 403, "Org member budget limit exceeded (monthly limit)")
        self.assertIn("HALT — ACCOUNT fault", r["out"])
        self.assertNotIn("PAUSED", r["out"])
        self.assertLessEqual(r["calls"], 3, "an account fault must not be retried")

    def test_a_BAD_REQUEST_pauses_the_model_without_retrying(self):
        r = _run("infra_request", 400, "messages[0] is malformed")
        self.assertIn("PAUSED", r["out"])
        self.assertNotIn("HALT", r["out"])

    def test_a_failed_call_writes_a_FAULT_EVENT_and_no_record(self):
        r = _run("infra_evidence", 503, "upstream unavailable")
        self.assertTrue(r["faults"], "the fault must be recorded somewhere")
        f = r["faults"][0]
        for field in ("unit_id", "model", "classification", "http_status", "attempts_made",
                      "body_present", "cost_known", "requested_max_tokens"):
            self.assertIn(field, f, field)
        self.assertFalse(f["body_present"])
        self.assertEqual([x for x in r["records"] if x["model"] == BAD_MODEL], [])


class ItDoesNotSwallowRealModelBehaviour(unittest.TestCase):
    """The over-reach guards. A rule that ate a real outcome would be worse than the original defect."""

    def test_an_ANSWER_that_will_not_parse_is_a_RESULT_not_a_fault(self):
        """Codex C8. A protocol parse failure is transient; an ANSWER parse failure is the model's
        behaviour, and conflating them would rebuild the category error inside the new classifier."""
        r = _run("infra_noswallow", 503, "upstream unavailable")
        good = [x for x in r["records"] if x["model"] == OK_MODEL]
        self.assertTrue(good)
        self.assertTrue(all("completeness" in x for x in good))

    def test_the_verdicts_that_mean_MODEL_BEHAVIOUR_are_untouched(self):
        import completeness_review as CR
        for v in ("TRUNCATED", "EMPTY_HTTP", "NO_ANSWER", "EMPTY_PARSE"):
            self.assertIn(v, CR.KNOWN_VERDICTS)
        self.assertNotIn("NO_ANSWER", CR.UNDELIVERED)
        self.assertNotIn("TRUNCATED", CR.UNDELIVERED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
