"""Item validation rules."""
import json
import os
import unittest

import item_validate as IV
from bench_formats import FX_FORMAT_MARKER

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = json.load(open(os.path.join(HERE, "runs", "fx_smoke4.json")))


def good():
    return json.loads(json.dumps(REAL[0]))


def fired(items, rule):
    return [v for v in IV.validate(items)["violations"] if v["rule"] == rule]


class TheNegativeControl(unittest.TestCase):

    def test_a_real_futurex_item_passes(self):
        rep = IV.validate([good()])
        self.assertEqual(rep["n_violations"], 0, f"a valid item was rejected: {rep['violations']}")

    def test_the_whole_smoke_set_passes(self):
        self.assertEqual(IV.validate(REAL)["n_violations"], 0)

    def test_the_format_instruction_is_not_a_leaked_answer(self):
        it = good()
        self.assertIn(FX_FORMAT_MARKER, it["prompt"])
        self.assertIn("\\boxed", it["prompt"].split(FX_FORMAT_MARKER, 1)[1],
                      "the format block must contain the marker -- that is what it is for")
        self.assertIsNone(IV._leaked_answer(it["prompt"]))
        self.assertEqual(fired([it], "answer_leaked"), [])


class EverySeededMalformationFires(unittest.TestCase):

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
        it = good()
        head, sep, tail = it["prompt"].partition(FX_FORMAT_MARKER)
        it["prompt"] = head + "\n(The correct answer is \\boxed{Yes}.)\n" + sep + tail
        v = fired([it], "answer_leaked")
        self.assertTrue(v, "a marker in the question body must fire")
        self.assertIn("QUESTION BODY", v[0]["why"])


class ItHalts(unittest.TestCase):

    def test_require_valid_raises_and_names_the_rule(self):
        it = good(); it["prompt"] = ""
        with self.assertRaises(IV.ItemCorpusError) as cm:
            IV.require_valid([it])
        self.assertIn("prompt_empty", str(cm.exception))

    def test_require_valid_passes_a_clean_corpus(self):
        self.assertEqual(IV.require_valid(REAL)["n_violations"], 0)

    def test_a_crashing_rule_is_itself_a_violation(self):
        it = {"item_id": "x", "prompt": None, "level": 1, "end_time": "2026-06-01"}
        rep = IV.validate([it])
        self.assertTrue(rep["n_violations"], "a None prompt must produce violations, not an exception")


if __name__ == "__main__":
    unittest.main(verbosity=2)
