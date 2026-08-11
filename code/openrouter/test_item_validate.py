"""M6-T2/S4 — acceptance for the item-corpus validator.

The real pool returns 0 violations across 964 items. That proves NOTHING on its own: a validator
that never fires and a validator that cannot fire look identical from the outside. Every rule below
is therefore fired deliberately with a seeded malformation.

THE NEGATIVE CONTROL IS THE MOST IMPORTANT TEST HERE. A valid FutureX item legitimately contains
`\\boxed{Yes} or \\boxed{No}` inside its format block. If the leaked-answer rule rejects that, the
validator rejects the entire benchmark -- a false positive far worse than the failure it guards.

Offline. No network. No spend.  Run: python3 -m unittest test_item_validate -v
"""
import json
import os
import unittest

import item_validate as IV
from bench_formats import FX_FORMAT_MARKER

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))


def good():
    """A real, unmodified FutureX item -- the thing that must always pass."""
    return json.loads(json.dumps(REAL[0]))


def fired(items, rule):
    return [v for v in IV.validate(items)["violations"] if v["rule"] == rule]


class TheNegativeControl(unittest.TestCase):
    """If these fail, the validator is rejecting valid benchmark items."""

    def test_a_real_futurex_item_passes(self):
        rep = IV.validate([good()])
        self.assertEqual(rep["n_violations"], 0, f"a valid item was rejected: {rep['violations']}")

    def test_the_whole_smoke_set_passes(self):
        self.assertEqual(IV.validate(REAL)["n_violations"], 0)

    def test_the_format_instruction_is_not_a_leaked_answer(self):
        """The single most dangerous false positive: the format block CONTAINS the marker by design."""
        it = good()
        self.assertIn(FX_FORMAT_MARKER, it["prompt"])
        self.assertIn("\\boxed", it["prompt"].split(FX_FORMAT_MARKER, 1)[1],
                      "the format block must contain the marker -- that is what it is for")
        self.assertIsNone(IV._leaked_answer(it["prompt"]))
        self.assertEqual(fired([it], "answer_leaked"), [])


class EverySeededMalformationFires(unittest.TestCase):
    """One deliberate defect per rule. Each MUST fire, or that rule is untested."""

    def test_missing_item_id(self):
        it = good(); it["item_id"] = ""
        self.assertTrue(fired([it], "item_id_missing"))

    def test_duplicate_item_id(self):
        a, b = good(), good()                      # same id, an aggregate-only violation
        v = fired([a, b], "item_id_duplicate")
        self.assertTrue(v)
        self.assertIn("appears 2 times", v[0]["why"])

    def test_empty_prompt(self):
        it = good(); it["prompt"] = "   "
        self.assertTrue(fired([it], "prompt_empty"))

    def test_non_string_prompt(self):
        it = good(); it["prompt"] = {"text": "not a string"}
        self.assertTrue(fired([it], "prompt_not_string"))

    def test_missing_format_marker(self):
        it = good(); it["prompt"] = it["prompt"].replace(FX_FORMAT_MARKER, "ANSWER NOW:")
        self.assertTrue(fired([it], "format_marker_missing"))

    def test_end_time_before_the_anchor(self):
        it = good(); it["end_time"] = "2025-01-01"
        self.assertTrue(fired([it], "end_time_before_anchor"))

    def test_missing_level(self):
        it = good(); it.pop("level")
        self.assertTrue(fired([it], "level_missing"))

    def test_a_leaked_answer_in_the_question_body_fires(self):
        """The rule's real target: a marker BEFORE the format block, i.e. the answer in the question."""
        it = good()
        head, sep, tail = it["prompt"].partition(FX_FORMAT_MARKER)
        it["prompt"] = head + "\n(The correct answer is \\boxed{Yes}.)\n" + sep + tail
        v = fired([it], "answer_leaked")
        self.assertTrue(v, "a marker in the question body must fire")
        self.assertIn("QUESTION BODY", v[0]["why"])


class ItHalts(unittest.TestCase):
    """A report nobody reads is not a guard. require_valid must RAISE."""

    def test_require_valid_raises_and_names_the_rule(self):
        it = good(); it["prompt"] = ""
        with self.assertRaises(IV.ItemCorpusError) as cm:
            IV.require_valid([it])
        self.assertIn("prompt_empty", str(cm.exception))

    def test_require_valid_passes_a_clean_corpus(self):
        self.assertEqual(IV.require_valid(REAL)["n_violations"], 0)

    def test_a_crashing_rule_is_itself_a_violation(self):
        """A rule that throws must not silently skip the item."""
        it = {"item_id": "x", "prompt": None, "level": 1, "end_time": "2026-06-01"}
        rep = IV.validate([it])
        self.assertTrue(rep["n_violations"], "a None prompt must produce violations, not an exception")


if __name__ == "__main__":
    unittest.main(verbosity=2)
