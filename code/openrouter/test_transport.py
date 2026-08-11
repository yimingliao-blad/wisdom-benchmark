"""M6-T6 (L-D) — every transport and provider error class, injected through the REAL retry path.

WHY ATTEMPT COUNTS ARE ASSERTED, not just outcomes: the retry loop is the one place a bug SPENDS
MONEY SILENTLY. A permanent error retried five times buys five guaranteed failures and looks normal.

WHAT THIS REPLACES: classify_error was checked against 12 synthetic cases in a shell earlier today.
It was correct, and the check vanished with the shell. An inline demonstration protects no future
change; this re-runs.

LIMITATION: no real 429/503/truncated body has been seen since the classification was written (the
one real JSONDecodeError predates it). These are INJECTION tests against the documented contract,
not observations of provider behaviour.

Offline. No network. No spend.  Run: python3 -m unittest test_transport -v
"""
import json
import os
import sys
import tempfile
import time
import unittest

# llm_api lives outside this directory. run_openrouter puts it on sys.path as a side effect of
# import, but relying on IMPORT ORDER for a path is fragile -- state it explicitly instead.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")

import claim_gate as CG          # noqa: E402
import llm_api                   # noqa: E402
import run_openrouter as RO      # noqa: E402


def api_error(code, error_type=None, provider_code=None, retry_after=None):
    """An LlmError shaped exactly as llm_api._post builds one for an HTTP error."""
    e = llm_api.LlmError(f"HTTP {code}")
    e.status = code
    e.error_type = error_type
    e.provider_code = provider_code
    e.retry_after = retry_after
    e.ratelimit = {}
    e.transport = False
    return e


def transport_error(kind):
    """An LlmError shaped as _post builds one for a CLIENT-SIDE failure."""
    e = llm_api.LlmError(f"{kind} calling ...")
    e.status = e.error_type = e.provider_code = e.retry_after = None
    e.ratelimit = {}
    e.transport = True
    e.transport_kind = kind
    return e


class TheDocumentedTaxonomy(unittest.TestCase):
    """One case per class in OpenRouter's documented error contract."""

    def test_retryable_api_errors(self):
        for code, et in ((429, "rate_limit_exceeded"), (503, "provider_overloaded"),
                         (504, "timeout"), (500, "server"), (502, "provider_unavailable")):
            retry, klass = RO.classify_error(api_error(code, et))
            self.assertTrue(retry, f"{code} {et} must be retryable")
            self.assertEqual(klass, f"api:{et}")

    def test_permanent_api_errors_are_NOT_retried(self):
        """Retrying these buys guaranteed failures at full price."""
        for code, et in ((401, "authentication"), (402, "payment_required"),
                         (403, "permission_denied"), (400, "invalid_request"),
                         (400, "content_policy_violation")):
            retry, klass = RO.classify_error(api_error(code, et))
            self.assertFalse(retry, f"{code} {et} must NOT be retryable")

    def test_client_side_failures_are_transport_and_retryable(self):
        for kind in ("JSONDecodeError", "ConnectionResetError", "TimeoutError",
                     "IncompleteRead", "gaierror"):
            retry, klass = RO.classify_error(transport_error(kind))
            self.assertTrue(retry)
            self.assertEqual(klass, f"transport:{kind}")

    def test_a_non_json_5xx_body_is_still_retryable_by_status(self):
        retry, klass = RO.classify_error(api_error(502))
        self.assertTrue(retry)
        self.assertEqual(klass, "api:502")


class TheRealRetryLoop(unittest.TestCase):
    """Injected into the ACTUAL loop -- testing a re-implementation would prove nothing."""

    def setUp(self):
        self.orig_chat, self.orig_sleep = llm_api.openrouter_chat, RO.time.sleep
        RO.time.sleep = lambda s: None          # assert the DECISION, not the wall-clock
        self.calls = []

    def tearDown(self):
        llm_api.openrouter_chat, RO.time.sleep = self.orig_chat, self.orig_sleep

    def script(self, seq):
        def fake(prompt, model, max_tokens=None, reasoning=None, timeout=None):
            self.calls.append(max_tokens)
            item = seq[min(len(self.calls) - 1, len(seq) - 1)]
            if isinstance(item, Exception):
                raise item
            return item
        llm_api.openrouter_chat = fake

    def test_a_transient_failure_is_retried_then_succeeds(self):
        ok = ("answer", {"choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
        self.script([transport_error("JSONDecodeError"), ok])
        trace = []
        txt, raw = RO._chat_with_backoff("p", "m", 100, None, trace)
        self.assertEqual(txt, "answer")
        self.assertEqual(len(self.calls), 2, "must retry exactly once then succeed")
        self.assertEqual(trace[0]["failure_class"], "transport:JSONDecodeError")

    def test_a_PERMANENT_error_is_attempted_exactly_once(self):
        """The money-losing bug this test exists to prevent."""
        self.script([api_error(402, "payment_required")])
        with self.assertRaises(llm_api.LlmError) as cm:
            RO._chat_with_backoff("p", "m", 100, None, [])
        self.assertEqual(len(self.calls), 1, "a permanent error must NOT be retried")
        self.assertEqual(cm.exception.attempts_made, 1)
        self.assertEqual(cm.exception.gave_up_because, "permanent")

    def test_retries_are_capped_and_the_giveup_is_recorded(self):
        self.script([api_error(503, "provider_overloaded")])
        trace = []
        with self.assertRaises(llm_api.LlmError) as cm:
            RO._chat_with_backoff("p", "m", 100, None, trace, tries=4)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(cm.exception.gave_up_because, "retries_exhausted")
        self.assertEqual(len(trace), 3, "one trace entry per retry, not per attempt")

    def test_Retry_After_from_the_server_beats_the_guessed_backoff(self):
        self.script([api_error(429, "rate_limit_exceeded", retry_after=7.0),
                     ("ok", {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": 1, "completion_tokens": 1}})])
        trace = []
        RO._chat_with_backoff("p", "m", 100, None, trace)
        self.assertEqual(trace[0]["sleep"], 7.0, "the served value must win")
        self.assertTrue(trace[0]["from_header"], "and the choice must be auditable")

    def test_escalation_stops_at_the_cap_rather_than_climbing_to_the_ceiling(self):
        """glm-4.6 burned 16k->131k returning empty each time; MAX_ESCALATIONS is the brake."""
        empty = ("", {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
                      "usage": {"prompt_tokens": 1, "completion_tokens": 9}})
        self.script([empty])
        mr = {"id": "m", "in": 0.1, "out": 0.1}
        txt, raw, cost, trace = RO.call_with_escalation("p", mr, 1000, 1_000_000)
        self.assertIsNone(txt, "an unusable reply must return None, never an empty 'answer'")
        self.assertEqual(len(self.calls), RO.MAX_ESCALATIONS)
        self.assertEqual(trace[-1]["outcome"], "escalation_exhausted")


class TheWallClockBoundIsREAL(unittest.TestCase):
    """urllib's timeout is per-socket-read: a call made with timeout=60 was MEASURED at 210s."""

    def setUp(self):
        self.orig = llm_api.openrouter_chat

    def tearDown(self):
        llm_api.openrouter_chat = self.orig

    def test_a_hanging_call_is_abandoned_at_the_wall_clock(self):
        import time as _t

        def hang(prompt, model, max_tokens=None, reasoning=None, timeout=None):
            _t.sleep(30)                      # far past the 1s bound below
            return "never", {}
        llm_api.openrouter_chat = hang
        t0 = _t.time()
        with self.assertRaises(llm_api.LlmError) as cm:
            RO._call_with_wallclock_bound("p", "m", 100, None, timeout=600, wall=1)
        el = _t.time() - t0
        self.assertLess(el, 5, f"the wait must be bounded; took {el:.1f}s")
        self.assertTrue(cm.exception.transport)
        self.assertEqual(cm.exception.transport_kind, "WallClockExceeded")

    def test_it_is_classified_as_retryable_transport(self):
        e = llm_api.LlmError("wall")
        e.transport, e.transport_kind = True, "WallClockExceeded"
        e.status = e.error_type = e.provider_code = e.retry_after = None
        retry, klass = RO.classify_error(e)
        self.assertTrue(retry)
        self.assertEqual(klass, "transport:WallClockExceeded")

    def test_a_fast_call_is_unaffected(self):
        llm_api.openrouter_chat = lambda *a, **k: ("ok", {"choices": []})
        txt, _ = RO._call_with_wallclock_bound("p", "m", 100, None, timeout=600, wall=5)
        self.assertEqual(txt, "ok")


class ACorruptRecordLineIsCaught(unittest.TestCase):
    """FAILURE_MODES S4: returning the readable subset would silently shrink a denominator."""

    def test_a_truncated_jsonl_line_raises_rather_than_being_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            run = os.path.join(d, "or_futurex_x")
            os.makedirs(run)
            with open(os.path.join(run, "records.jsonl"), "w") as f:
                f.write(json.dumps({"ok": True, "model": "m"}) + "\n")
                f.write('{"ok": true, "model": "trunc')          # a partial line
            with self.assertRaises(CG.ClaimError) as cm:
                CG.load_corpus(pattern=os.path.join(d, "or_futurex_*", "records.jsonl"))
            self.assertIn("malformed", str(cm.exception))



class ThePerUnitDeadlineBoundsSTACKEDAttempts(unittest.TestCase):
    """Codex C3 (BLOCKING). WALL_CLOCK bounds ONE attempt; a failed attempt is RETRIED and
    escalation adds more, so attempts STACK. Measured on the gate stages: one minimax call consumed
    840s and one glm-4.7 call 1,333s while 221 units sat finished. At 8,140 units that is ~12 hours,
    almost all of it a handful of stuck calls.
    """

    def setUp(self):
        self._chat = llm_api.openrouter_chat
        self.addCleanup(setattr, llm_api, "openrouter_chat", self._chat)
        self.calls = {"n": 0}

    def _overloaded(self, delay=0.3):
        def f(prompt, model, **kw):
            self.calls["n"] += 1
            time.sleep(delay)
            e = llm_api.LlmError("simulated overload")
            e.status, e.error_type = 503, "provider_overloaded"
            e.transport, e.retry_after, e.ratelimit = False, None, {}
            raise e
        return f

    def test_it_STOPS_retrying_once_the_unit_budget_is_gone(self):
        llm_api.openrouter_chat = self._overloaded()
        t0 = time.time()
        with self.assertRaises(Exception) as cm:
            RO._chat_with_backoff("p", "m/x", 100, None, [], tries=99, timeout=5, wall=1,
                                  deadline=time.time() + 2.0)
        self.assertLess(time.time() - t0, 6.0, "the deadline did not bound the elapsed time")
        self.assertLess(self.calls["n"], 99, "it kept retrying past the unit budget")

    def test_the_give_up_reason_is_RECORDED_as_unit_deadline(self):
        """A silent give-up is indistinguishable from a clean failure downstream."""
        llm_api.openrouter_chat = self._overloaded()
        try:
            RO._chat_with_backoff("p", "m/x", 100, None, [], tries=99, timeout=5, wall=1,
                                  deadline=time.time() + 1.5)
            self.fail("expected a give-up")
        except RO.UnitDeadlineExceeded as e:
            self.assertIn("total budget", str(e))
        except Exception as e:
            self.assertEqual(getattr(e, "gave_up_because", None), "unit_deadline")

    def test_WITHOUT_a_deadline_the_old_stacking_behaviour_is_unchanged(self):
        """The control: if it bounded things with no deadline set, it would be changing the
        retry contract for every call, not just the stuck ones."""
        llm_api.openrouter_chat = self._overloaded(delay=0.01)
        with self.assertRaises(Exception) as cm:
            RO._chat_with_backoff("p", "m/x", 100, None, [], tries=3, timeout=5, wall=1)
        self.assertEqual(self.calls["n"], 3, "all tries should be used when no deadline is set")
        self.assertEqual(getattr(cm.exception, "gave_up_because", None), "retries_exhausted")

    def test_a_single_attempt_is_never_allowed_past_the_unit_deadline(self):
        """The per-attempt wall must shrink to fit the remaining unit budget."""
        llm_api.openrouter_chat = self._overloaded(delay=5.0)
        t0 = time.time()
        with self.assertRaises(Exception):
            RO._chat_with_backoff("p", "m/x", 100, None, [], tries=99, timeout=30, wall=300,
                                  deadline=time.time() + 1.0)
        self.assertLess(time.time() - t0, 4.0,
                        "a 300s attempt wall was used despite a 1s unit budget remaining")


if __name__ == "__main__":
    unittest.main(verbosity=2)
