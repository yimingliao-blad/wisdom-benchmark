"""Spend caps and token-ceiling selection."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLISHED, UNPUBLISHED = "maker/has-a-ceiling", "maker/no-ceiling"
UNBOUNDED = UNPUBLISHED

# Records every max_tokens the runner asked for, then answers normally. The point is the REQUEST, so
# the stub captures it rather than the test asserting on downstream effects.
HARNESS = r'''
import json, sys
sys.path.insert(0, {here!r})
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")
import run_openrouter as R, completeness_review as CR

ASKED = []
LONG = {long!r}

def fake_call(prompt, model, max_tokens=None, timeout=None, temperature=0.0, reasoning=None):
    ASKED.append({{"model": model, "max_tokens": max_tokens}})
    n = LONG if model == {published!r} else 50
    body = "Reasoning enough to be prose. " * 8 + "\\boxed{{A}}"
    raw = {{"provider": "Stub",
            "usage": {{"prompt_tokens": 100, "completion_tokens": n}},
            "choices": [{{"finish_reason": "stop", "message": {{"content": body}}}}]}}
    return body, raw

import llm_api
llm_api.openrouter_chat = fake_call
CR.review = lambda *a, **k: (CR.COMPLETE, "verdict: complete", "stop")
sys.argv = {argv!r}
try:
    R.main()
finally:
    json.dump(ASKED, open({asked!r}, "w"))
'''


def _inputs(d):
    items = [{"item_id": "q0", "level": 1,
              "prompt": "IMPORTANT: Your final answer MUST end with this exact format:\n"
                        "\\boxed{Yes} or \\boxed{No}"}]
    json.dump(items, open(os.path.join(d, "items.json"), "w"))
    roster = [
        {"series": "S", "id": PUBLISHED, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
         "in": 0.1, "out": 0.1, "cap": 128000, "cap_basis": "max_completion_tokens"},
        {"series": "S", "id": UNPUBLISHED, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
         "in": 0.1, "out": 0.1, "cap": 1000000, "cap_basis": "context_length"},
    ]
    json.dump(roster, open(os.path.join(d, "roster.json"), "w"))


def _run(d, tag, extra=(), long_tokens=50):
    asked = os.path.join(d, f"asked_{tag}.json")
    argv = ["run_openrouter.py", "--items", os.path.join(d, "items.json"), "--bench", "futurex",
            "--tag", tag, "--models", os.path.join(d, "roster.json"),
            "--caps", os.path.join(d, "none.json"), "--max-calls", "50", "--max-spend", "5",
            "--workers", "1", "--mode", "real", "--no-review", "--arms", "original"] + list(extra)
    src = HARNESS.format(here=HERE, argv=argv, asked=asked, published=PUBLISHED, long=long_tokens)
    p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=180)
    got = json.load(open(asked)) if os.path.exists(asked) else []
    rp = os.path.join(HERE, "runs", f"or_futurex_{tag}", "records.jsonl")
    recs = ([json.loads(l) for l in open(rp, encoding="utf-8") if l.strip()]
            if os.path.exists(rp) else [])
    return p, {a["model"]: a["max_tokens"] for a in got}, recs, p.stdout + p.stderr


FAIL_HARNESS = HARNESS.replace(
    "    ASKED.append({{\"model\": model, \"max_tokens\": max_tokens}})",
    "    ASKED.append({{\"model\": model, \"max_tokens\": max_tokens}})\n"
    "    import llm_api as _l; _e = _l.LlmError('provider exploded'); _e.status = 400; raise _e   # non-retryable: keeps the suite fast")


def _run_failing(d, tag):
    asked = os.path.join(d, f"asked_{tag}.json")
    argv = ["run_openrouter.py", "--items", os.path.join(d, "items.json"), "--bench", "futurex",
            "--tag", tag, "--models", os.path.join(d, "roster.json"),
            "--caps", os.path.join(d, "none.json"), "--max-calls", "50", "--max-spend", "5",
            "--workers", "1", "--mode", "real", "--no-review", "--arms", "original"]
    src = FAIL_HARNESS.format(here=HERE, argv=argv, asked=asked, published=PUBLISHED, long=50)
    subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=180)
    # M6-T23: a failed call writes a FAULT EVENT, not a record. The guarantee moved with it.
    fp = os.path.join(HERE, "runs", f"or_futurex_{tag}", "faults.jsonl")
    return ([json.loads(l) for l in open(fp, encoding="utf-8") if l.strip()]
            if os.path.exists(fp) else [])


def _clean(tag):
    shutil.rmtree(os.path.join(HERE, "runs", f"or_futurex_{tag}"), ignore_errors=True)


class TheRequestCarriesNoInventedNumber(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        _inputs(cls.d)
        cls.p, cls.asked, cls.recs, cls.out = _run(cls.d, "budgetpol")

    @classmethod
    def tearDownClass(cls):
        _clean("budgetpol")
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_a_model_with_a_PUBLISHED_ceiling_is_asked_for_exactly_that(self):
        self.assertEqual(self.asked.get(PUBLISHED), 128000,
                         f"asked {self.asked.get(PUBLISHED)}; 64000 means the invented cap is back")

    def test_a_model_with_NO_published_ceiling_is_asked_with_NO_limit(self):
        self.assertIn(UNPUBLISHED, self.asked)
        self.assertIsNone(self.asked[UNPUBLISHED],
                          "a context window is not an output ceiling and must not become max_tokens")

    def test_the_run_SAYS_which_models_were_called_unbounded(self):
        self.assertIn("NO PUBLISHED OUTPUT CEILING", self.out)
        self.assertIn(UNPUBLISHED, self.out)

    def test_the_record_states_what_was_requested(self):
        by = {r["model"]: r for r in self.recs}
        self.assertEqual(by[PUBLISHED]["requested_max_tokens"], 128000)
        self.assertFalse(by[PUBLISHED]["unbounded_request"])
        self.assertIsNone(by[UNPUBLISHED]["requested_max_tokens"])
        self.assertTrue(by[UNPUBLISHED]["unbounded_request"])


class AnExplicitOverrideStillApplies(unittest.TestCase):

    def test_the_override_reaches_every_model(self):
        d = tempfile.mkdtemp()
        _inputs(d)
        try:
            _p, asked, _r, _o = _run(d, "budgetovr", extra=["--max-tokens", "4096"])
            self.assertEqual(asked.get(PUBLISHED), 4096)
            self.assertEqual(asked.get(UNPUBLISHED), 4096)
        finally:
            _clean("budgetovr")
            shutil.rmtree(d, ignore_errors=True)


class TwelveKIsAnObservationNotABarrier(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        _inputs(cls.d)
        cls.p, cls.asked, cls.recs, cls.out = _run(cls.d, "budgetlong", long_tokens=30000)

    @classmethod
    def tearDownClass(cls):
        _clean("budgetlong")
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_a_long_completion_is_FLAGGED_with_its_actual_count(self):
        by = {r["model"]: r for r in self.recs}
        self.assertTrue(by[PUBLISHED]["suspicious_length"])
        self.assertEqual(by[PUBLISHED]["completion_tokens"], 30000)

    def test_a_short_completion_is_NOT_flagged(self):
        by = {r["model"]: r for r in self.recs}
        self.assertFalse(by[UNPUBLISHED]["suspicious_length"])

    def test_it_is_REPORTED_in_the_run_summary(self):
        self.assertIn("SUSPICIOUS LENGTH", self.out)
        self.assertIn("30,000", self.out)

    def test_it_changes_NOTHING_ELSE(self):
        by = {r["model"]: r for r in self.recs}
        self.assertNotIn("QUARANTINED", self.out)
        self.assertNotIn("HALT", self.out)
        self.assertEqual(by[PUBLISHED]["completeness"], "COMPLETE")
        self.assertTrue(by[PUBLISHED].get("compliant"))
        self.assertEqual(len(self.recs), 2, "both units still ran")

    def test_the_threshold_is_named_and_not_a_magic_number(self):
        import run_openrouter as R
        self.assertEqual(R.SUSPICIOUS_COMPLETION_TOKENS, 12000)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class AFailedCallIsNotAnUnboundedRequest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        _inputs(cls.d)
        cls.faults = _run_failing(cls.d, "budgetfail")

    @classmethod
    def tearDownClass(cls):
        _clean("budgetfail")
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_a_raised_call_still_records_what_was_requested(self):
        by = {r["model"]: r for r in self.faults}
        self.assertTrue(self.faults, "the run should have persisted its FAULT EVENTS")
        self.assertEqual(by[PUBLISHED]["requested_max_tokens"], 128000,
                         "the ceiling was known before the call; failing does not unknow it")
        self.assertFalse(by[PUBLISHED]["unbounded_request"])

    def test_a_model_with_no_ceiling_still_reads_as_deliberately_unbounded(self):
        by = {r["model"]: r for r in self.faults}
        self.assertIsNone(by[UNBOUNDED]["requested_max_tokens"])
        self.assertTrue(by[UNBOUNDED]["unbounded_request"])

    def test_the_two_cases_are_DISTINGUISHABLE_which_is_the_whole_defect(self):
        by = {r["model"]: r for r in self.faults}
        self.assertNotEqual(by[PUBLISHED]["unbounded_request"], by[UNBOUNDED]["unbounded_request"])
        self.assertTrue(all("requested_max_tokens" in r for r in self.faults),
                        "the field must be on EVERY fault event, or .get() re-creates the defect")

    def test_a_failed_call_writes_NO_record_at_all(self):
        rp = os.path.join(HERE, "runs", "or_futurex_budgetfail", "records.jsonl")
        recs = ([json.loads(l) for l in open(rp, encoding="utf-8") if l.strip()]
                if os.path.exists(rp) else [])
        self.assertEqual(recs, [], "a call that delivered nothing is not a result")


class ACeilingMustFitBesideThePrompt(unittest.TestCase):

    def setUp(self):
        import run_openrouter as R
        self.R = R

    def test_a_ceiling_equal_to_the_context_is_lowered_to_fit(self):
        got = self.R.fits_in_context(262144, 262144, "x" * 960)
        self.assertLess(got, 262144)
        self.assertGreater(got, 260000, "lowered to fit, not slashed")

    def test_the_room_it_leaves_covers_the_prompt(self):
        prompt = "x" * 3000
        got = self.R.fits_in_context(262144, 262144, prompt)
        self.assertLessEqual(got + len(prompt) // 3 + 1, 262144,
                             "output plus prompt must fit the window, which is the whole point")

    def test_a_ceiling_WELL_UNDER_the_context_is_untouched(self):
        self.assertEqual(self.R.fits_in_context(64000, 200000, "x" * 960), 64000)
        self.assertEqual(self.R.fits_in_context(16384, 131072, "x" * 5000), 16384)

    def test_an_unbounded_request_stays_unbounded(self):
        self.assertIsNone(self.R.fits_in_context(None, 262144, "x" * 960))

    def test_an_unknown_context_leaves_the_ceiling_alone(self):
        self.assertEqual(self.R.fits_in_context(64000, None, "x" * 960), 64000)

    def test_it_never_returns_a_useless_or_negative_budget(self):
        self.assertGreaterEqual(self.R.fits_in_context(1000, 100, "x" * 90000), 1)

    def test_the_real_endpoint_accepted_the_lowered_request(self):
        self.assertEqual(self.R.fits_in_context(262144, 262144, "x" * 512), 261461)
