"""M2 acceptance — the completeness checker must produce its own verdict per failure class,
AND must be able to FAIL. A checker only ever shown passing cases proves nothing.

Run: python3 -m unittest test_completeness -v
"""
import os
import unittest

import completeness_review as CR


def rec(text, finish="stop", ptok=300, ctok=100, provider="X"):
    return {"text": text, "finish_reason": finish, "provider": provider,
            "usage": {"prompt_tokens": ptok, "completion_tokens": ctok}}


class SeededFixtures(unittest.TestCase):
    """One fixture per failure class; each must land on ITS OWN verdict, not a catch-all."""

    def test_clean_answer_goes_to_the_reader(self):
        v, _ = CR.deterministic_verdict(rec("I weighed the base rates.\n\n\\boxed{No}"))
        self.assertEqual(v, CR.UNDECIDED, "a clean, answered record must be handed to layer 2")

    def test_mid_sentence_cutoff_is_truncated(self):
        v, _ = CR.deterministic_verdict(rec("To predict whether the share of global silver"))
        self.assertEqual(v, CR.TRUNCATED)

    def test_finished_prose_without_a_marker_is_no_answer(self):
        v, _ = CR.deterministic_verdict(rec("I cannot predict future events with certainty."))
        self.assertEqual(v, CR.NO_ANSWER)

    def test_empty_completion_is_its_own_outcome_not_non_compliance(self):
        """A model returning no bytes has demonstrated NOTHING -- not non-compliance. EMPTY is
        unscoreable; NO_ANSWER (finished prose, no marker) IS scoreable as compliant=False."""
        v, _ = CR.deterministic_verdict(rec("", finish="stop"))
        self.assertEqual(v, CR.EMPTY_HTTP)
        self.assertNotIn(v, CR.SCOREABLE)

    def test_provider_error_is_not_noncompliant(self):
        """D-OR-2. finish_reason='error' arrives under HTTP 200. Scoring it as a format failure
        reported '0/8 compliance' for a model that never ran."""
        v, _ = CR.deterministic_verdict(rec("To predict whether the sha", finish="error", ptok=0, ctok=1))
        self.assertEqual(v, CR.PROVIDER_ERROR)
        self.assertNotIn(v, (CR.NO_ANSWER, CR.TRUNCATED), "a dead call is not a format failure")

    def test_zero_prompt_tokens_is_a_provider_error(self):
        v, _ = CR.deterministic_verdict(rec("some text", finish="stop", ptok=0))
        self.assertEqual(v, CR.PROVIDER_ERROR)

    def test_missing_usage_is_undecided_not_a_provider_error(self):
        """Codex C4: an OMITTED usage block is not the same claim as a reported zero."""
        r = rec("Answer.\n\\boxed{Yes}")
        r["usage"] = {}
        v, _ = CR.deterministic_verdict(r)
        self.assertEqual(v, CR.UNDECIDED)


class OrderingRegressions(unittest.TestCase):
    """The three BLOCKING findings from the Codex mechanism gate."""

    def test_empty_under_length_is_truncated_not_no_answer(self):
        """Codex C3, a CONFIRMED bug: a reasoning model can burn the whole budget and return
        nothing. That is budget exhaustion (TRUNCATED), not a refusal to answer (NO_ANSWER)."""
        v, why = CR.deterministic_verdict(rec("", finish="length", ctok=16000))
        self.assertEqual(v, CR.TRUNCATED)
        self.assertIn("budget", why.lower())

    def test_extractable_answer_then_length_is_truncated_by_explicit_choice(self):
        """Codex C1: kept as TRUNCATED, but now a decision rather than an accident of ordering."""
        v, _ = CR.deterministic_verdict(
            rec("I conclude no.\n\\boxed{No}\n\nTo elaborate, the mining", finish="length"))
        self.assertEqual(v, CR.TRUNCATED)

    def test_layer2_is_only_reached_when_an_answer_marker_exists(self):
        """Codex C2: the invariant that lets a 'stops cleanly' verdict become COMPLETE."""
        for text in ("no marker here, finished.", "cut off mid sen"):
            v, _ = CR.deterministic_verdict(rec(text))
            self.assertNotEqual(v, CR.UNDECIDED,
                                "a record with no marker must never reach the reader")


class TheCheckerCanFail(unittest.TestCase):
    """A checker that cannot be made to fail is not evidence. Seed a defect and watch it break."""

    def test_the_two_provider_error_rules_are_independent_readers(self):
        """Two checks are TWO READERS only if a fixture can make one fail while the other passes.

        The real mistral record trips BOTH rules (finish_reason='error' AND prompt_tokens=0), so
        masking either one alone leaves it caught — my first version of this test asserted the
        verdict would change and it did not. That is defence in depth, but it also means the
        redundancy has to be PROVEN rather than assumed. These fixtures isolate each rule.
        """
        original = CR.deterministic_verdict

        # Only the finish_reason rule can catch this one: usage is perfectly plausible.
        error_only = rec("partial text", finish="error", ptok=300, ctok=50)
        self.assertEqual(original(error_only)[0], CR.PROVIDER_ERROR)

        def no_error_rule(r):
            r2 = dict(r)
            if r2.get("finish_reason") == "error":
                r2["finish_reason"] = "stop"
            return original(r2)

        self.assertNotEqual(no_error_rule(error_only)[0], CR.PROVIDER_ERROR,
                            "with the finish_reason rule disabled this record must slip through")

        # Only the usage rule can catch this one: it stopped cleanly.
        usage_only = rec("It is finished but never answers.", finish="stop", ptok=0)
        self.assertEqual(original(usage_only)[0], CR.PROVIDER_ERROR)

        def no_usage_rule(r):
            r2 = dict(r); r2["usage"] = dict(r2["usage"], prompt_tokens=999)
            return original(r2)

        self.assertNotEqual(no_usage_rule(usage_only)[0], CR.PROVIDER_ERROR,
                            "with the usage rule disabled this record must slip through")

    def test_the_real_dead_call_is_caught_by_both_rules(self):
        """The mistral-small-3.1 record trips both — deliberately recorded as belt-and-braces."""
        dead = rec("To predict whether the sha", finish="error", ptok=0, ctok=1)
        self.assertEqual(CR.deterministic_verdict(dead)[0], CR.PROVIDER_ERROR)

    def test_seeded_defect_breaks_the_truncation_rule(self):
        original = CR.deterministic_verdict

        def broken(r):
            r2 = dict(r); r2["finish_reason"] = "stop"      # pretend the budget never ran out
            return original(r2)

        cut = rec("", finish="length", ctok=16000)
        self.assertEqual(original(cut)[0], CR.TRUNCATED)
        self.assertEqual(broken(cut)[0], CR.EMPTY_HTTP,
                         "with the defect, budget exhaustion is mislabelled as an empty reply")


class ScoreabilityBoundary(unittest.TestCase):
    """The M5 smoke caught this: a clean REFUSAL is the study's negative result, not an error.

    llama-3.1-8b replied "I can't fulfill that request." in 8 tokens, finish_reason=stop. The first
    design forced compliant=None and HALTED the smoke over it -- discarding exactly the observation
    the benchmark exists to make.
    """

    def test_a_clean_refusal_is_scoreable_non_compliance(self):
        v, _ = CR.deterministic_verdict(rec("I can't fulfill that request.", ctok=8))
        self.assertEqual(v, CR.NO_ANSWER)
        self.assertIn(v, CR.SCOREABLE, "a finished refusal IS an observation of format behaviour")
        self.assertNotIn(v, CR.METHOD_DEFECT, "a refusal is the model's behaviour, not our bug")

    def test_unobserved_calls_are_never_scoreable(self):
        for r, name in ((rec("", finish="length"), "budget exhausted"),
                        (rec("cut off mid sen"), "mid-sentence"),
                        (rec("echo", finish="error", ptok=0), "dead call"),
                        (rec("", finish="stop"), "nothing returned")):
            v, _ = CR.deterministic_verdict(r)
            self.assertNotIn(v, CR.SCOREABLE, f"{name} was never observed; it cannot be scored")
            self.assertIn(v, CR.METHOD_DEFECT, f"{name} is a method defect and must halt a smoke")


class EmptyParseIsNotNonCompliance(unittest.TestCase):
    """Codex regate finding 2 + a dead-code defect found while checking it.

    EMPTY_PARSE means the raw body HAS content but our extraction could not derive the scoreable
    text from the decided contract. It must NEVER absorb a plain missing answer marker, which is
    NO_ANSWER -- real, scoreable non-compliance. The first implementation both conflated them AND
    was unreachable: `parse_empty` required no-text, which IS http-empty, so its branch never ran.
    """

    def test_missing_marker_is_non_compliance_not_inspection(self):
        rec = {"text": "I considered it at length and reached a view."}
        self.assertIsNone(CR.empty_cross_check(rec),
                          "content with no marker is NO_ANSWER; it must not reach inspection")
        v, _ = CR.deterministic_verdict(
            {**rec, "finish_reason": "stop", "usage": {"prompt_tokens": 300}})
        self.assertEqual(v, CR.NO_ANSWER)
        self.assertIn(v, CR.SCOREABLE)

    def test_content_outside_the_canonical_channel_is_empty_parse(self):
        for rec, raw, where in (
                ({"text": "", "reasoning": "the answer is No"}, None, "reasoning"),
                ({"text": ""}, {"choices": [{"message": {"content": ""}},
                                            {"message": {"content": "No"}}]}, "second choice"),
                ({"text": ""}, {"choices": [{"message": {"content": "",
                                                         "tool_calls": [{"id": "1"}]}}]}, "tool call")):
            out = CR.empty_cross_check(rec, raw)
            self.assertIsNotNone(out, f"{where}: must be reachable")
            self.assertEqual(out[0], CR.EMPTY_PARSE)
            self.assertIn(CR.EMPTY_PARSE, CR.NEEDS_INSPECTION)

    def test_a_plain_empty_body_is_not_our_fault(self):
        self.assertIsNone(CR.empty_cross_check({"text": ""},
                                               {"choices": [{"message": {"content": ""}}]}))

    def test_the_obsolete_aggregate_state_is_gone(self):
        self.assertFalse(hasattr(CR, "EMPTY"),
                         "a stale aggregate EMPTY lets checks emit the pre-split state")


class ParserAbstains(unittest.TestCase):
    def test_abstains_rather_than_guesses(self):
        for reply in ("verdict: complete but it could be truncated",
                      "verdict: complete\nverdict: truncated",
                      "I think it's fine."):
            self.assertIsNone(CR.parse_verdict(reply), f"must abstain on {reply!r}")

    def test_reads_the_intended_verdict(self):
        self.assertEqual(CR.parse_verdict("verdict: truncated  (stops mid-sentence)"), CR.TRUNCATED)
        self.assertEqual(CR.parse_verdict("VERDICT: COMPLETE"), CR.COMPLETE)
        self.assertEqual(CR.parse_verdict("blah\nverdict: no_answer"), CR.NO_ANSWER)



class TheVerdictLayerKnowsBOTHBenchmarks(unittest.TestCase):
    """THE DEFECT (found 2026-08-08 by a BTF-3 dry run, before any BTF call was paid for):
    deterministic_verdict was hard-wired to \\boxed{}, which is FutureX's contract. BTF-3's contract
    is its closing line -- "the last thing you write is your final answer as a probability between
    0 and 1". A perfectly compliant BTF reply ending in `0.15` therefore had no answer marker, was
    labelled TRUNCATED, and quarantined its model on the very first unit. 40 of 40 records came back
    TRUNCATED; the entire BTF half of the study would have produced ZERO observations.
    """

    BTF = {"bench": "btf3", "finish_reason": "stop",
           "usage": {"prompt_tokens": 1800, "completion_tokens": 140}}

    def btf(self, text):
        return CR.deterministic_verdict({**self.BTF, "text": text})

    def test_a_BTF_reply_ending_in_its_probability_is_COMPLETE(self):
        v, why = self.btf("(a) four months remain.\n(b) status quo holds.\nWeighing that,\n0.15")
        self.assertEqual(v, CR.COMPLETE)
        self.assertIn("probability", why)

    def test_a_BTF_REFUSAL_is_NO_ANSWER_not_TRUNCATED(self):
        """The study's central negative result must survive on BOTH benchmarks."""
        v, _ = self.btf("I cannot predict the future.")
        self.assertEqual(v, CR.NO_ANSWER)
        self.assertIn(v, CR.SCOREABLE)

    def test_a_BTF_reply_cut_off_mid_sentence_is_TRUNCATED(self):
        v, _ = self.btf("The status quo suggests that the")
        self.assertEqual(v, CR.TRUNCATED)

    def test_a_BTF_reply_with_a_number_but_TRAILING_PROSE_is_not_COMPLETE(self):
        """BTF asks for the probability LAST. Prose after it did not satisfy the format."""
        v, _ = self.btf("My answer is 0.8. But note this is highly uncertain.")
        self.assertNotEqual(v, CR.COMPLETE)

    def test_the_bench_is_read_from_the_RECORD_not_assumed(self):
        """Passing the wrong contract silently mislabels every record, so it is read from the data."""
        text = "Weighing that,\n0.15"
        self.assertEqual(CR.deterministic_verdict({**self.BTF, "text": text})[0], CR.COMPLETE)
        as_fx = CR.deterministic_verdict({**self.BTF, "bench": "futurex", "text": text})[0]
        self.assertNotEqual(as_fx, CR.COMPLETE, "under FutureX's contract this has no answer marker")

    def test_FUTUREX_behaviour_is_UNCHANGED(self):
        fx = {"bench": "futurex", "finish_reason": "stop", "usage": {"prompt_tokens": 300},
              "text": "I predict yes.\n\\boxed{Yes}"}
        self.assertEqual(CR.deterministic_verdict(fx)[0], CR.UNDECIDED)
        self.assertEqual(CR.deterministic_verdict({**fx, "text": "I cannot answer."})[0],
                         CR.NO_ANSWER)

    def test_answer_markers_uses_each_benchmarks_OWN_contract(self):
        self.assertEqual(CR.answer_markers("x\n0.15", "btf3"), ["0.15"])
        self.assertEqual(CR.answer_markers("x\n0.15", "futurex"), [])
        self.assertEqual(CR.answer_markers("\\boxed{Yes}", "futurex"), ["Yes"])
        self.assertEqual(CR.answer_markers("\\boxed{Yes}", "btf3"), [])


class ALayer2ReaderMayJudgeButNotContradictAFact(unittest.TestCase):
    """D-OR-6, the paid smoke's only non-clean record.

    google/gemma-3-27b-it: finish_reason=stop, 554 completion tokens, coherent reasoning, and a
    parsed compliant answer ENDING the reply -- and the reader called it TRUNCATED. It was most
    likely misled by the model echoing three lines of the prompt's own instruction block just
    before the box, which makes the tail read as cut off.

    TRUNCATED is a claim about two observable facts, not an opinion. When both are false, the
    reader is overruled and the disagreement is recorded.
    """

    GEMMA = {"bench": "futurex", "finish_reason": "stop",
             "usage": {"prompt_tokens": 1200, "completion_tokens": 554},
             "text": ("Comparing Option B and C, the most likely scenario is a hold.\n"
                      "Your task is to identify all the correct option(s) based on your analysis.\n"
                      "Your final answer MUST end with this exact format:\n\n\\boxed{C}")}

    def test_the_real_gemma_shape_is_OVERRULED_to_COMPLETE(self):
        v, note = CR.reconcile_layer2(self.GEMMA, CR.TRUNCATED)
        self.assertEqual(v, CR.COMPLETE)
        self.assertIn("may judge, not contradict a fact", note)

    def test_the_disagreement_is_RECORDED_not_silently_swallowed(self):
        _, note = CR.reconcile_layer2(self.GEMMA, CR.TRUNCATED)
        self.assertIn("layer 2 said TRUNCATED", note)
        self.assertIn("D-OR-6", note)

    def test_a_GENUINE_budget_truncation_is_still_TRUNCATED(self):
        """finish_reason=length is the fact that makes truncation true."""
        v, note = CR.reconcile_layer2({**self.GEMMA, "finish_reason": "length"}, CR.TRUNCATED)
        self.assertEqual(v, CR.TRUNCATED)
        self.assertIsNone(note)

    def test_a_reply_with_NO_answer_marker_is_still_TRUNCATED(self):
        v, _ = CR.reconcile_layer2({**self.GEMMA, "text": "reasoning that just stops mid-sen"},
                                   CR.TRUNCATED)
        self.assertEqual(v, CR.TRUNCATED)

    def test_a_marker_NOT_at_the_end_is_still_TRUNCATED(self):
        """The benchmark requires the reply to END on the answer; prose after it is not clean."""
        v, _ = CR.reconcile_layer2({**self.GEMMA, "text": "\\boxed{C} and then more prose follows."},
                                   CR.TRUNCATED)
        self.assertEqual(v, CR.TRUNCATED)

    def test_it_does_NOT_touch_any_other_reader_verdict(self):
        """The reader keeps every judgement it is actually for."""
        for verdict in (CR.NO_ANSWER, CR.UNDECIDED, CR.COMPLETE):
            v, note = CR.reconcile_layer2(self.GEMMA, verdict)
            self.assertEqual(v, verdict)
            self.assertIsNone(note)

    def test_it_works_for_BTF3_too(self):
        btf = {"bench": "btf3", "finish_reason": "stop",
               "usage": {"prompt_tokens": 1800}, "text": "Weighing the status quo,\n0.15"}
        v, note = CR.reconcile_layer2(btf, CR.TRUNCATED)
        self.assertEqual(v, CR.COMPLETE)
        self.assertIsNotNone(note)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class ATrailingFullStopDoesNotUnfinishAReply(unittest.TestCase):
    """D-OR-17 regression.

    `ends_with_answer` anchored on `\\boxed{...}\\s*$`, so a reply ending `\\boxed{H}.` did not count
    as ending in the answer. Ten real records were left UNDECIDED by it — and in --no-review mode an
    UNDECIDED verdict counts toward quarantining the model, so a typographic full stop could get a
    well-behaved model dropped from the run.

    The widening must stay NARROW: only terminators, closing delimiters, markdown emphasis and LaTeX
    maths markup may follow the answer. Anything word-like after the box still means the reply did
    not end with it.
    """

    def ends(self, text):
        return CR.ends_with_answer({"text": text})

    def test_the_exact_reported_shape(self):
        self.assertTrue(self.ends(r"The final answer is \boxed{H}."))

    def test_other_typography_after_the_answer(self):
        for t in [r"\boxed{H}", r"\boxed{H} ", r"\boxed{H}.", r"\boxed{H}!", r"\boxed{H}?",
                  r"**\boxed{A, F, G}**", r"\boxed{B})", r'\boxed{B}"', r"\boxed{B}’"]:
            self.assertTrue(self.ends(t), t)

    def test_latex_delimiters_count_as_markup_not_content(self):
        for t in [r"$\boxed{B}$", r"\[\boxed{X}\]", "\\[\n\\boxed{X}\n\\]"]:
            self.assertTrue(self.ends(t), t)

    def test_a_real_newline_after_the_stop(self):
        self.assertTrue(self.ends("\\boxed{H}.\n"))

    def test_PROSE_after_the_answer_still_means_it_did_not_end_there(self):
        for t in [r"I think \boxed{A} is wrong.", r"\boxed{A} but maybe B",
                  r"\boxed{A}\text{ and more}", r"\boxed{A}. However I am unsure"]:
            self.assertFalse(self.ends(t), t)

    def test_an_EMPTY_box_is_still_not_an_answer(self):
        """Codex C2: without this, `\\boxed{}` would license a provisional COMPLETE."""
        for t in [r"\boxed{}", r"\boxed{ }", r"\boxed{}.", r"$\boxed{}$"]:
            self.assertFalse(self.ends(t), t)

    def test_it_clears_every_UNDECIDED_record_in_the_real_corpus(self):
        import json as _json
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "runs", "_frozen_fxgate_2026-08-08", "records.jsonl")
        if not os.path.exists(p):
            self.skipTest("the fxgate corpus is not present")
        with open(p, encoding="utf-8") as fh:
            und = [r for r in (_json.loads(l) for l in fh if l.strip())
                   if r.get("completeness") == "UNDECIDED"]
        self.assertEqual(len(und), 10)
        self.assertEqual(sum(CR.ends_with_answer(r) for r in und), 10)
