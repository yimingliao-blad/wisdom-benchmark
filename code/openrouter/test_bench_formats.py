"""Per-benchmark prompt and answer formats."""
import json
import os
import unittest

import collections

import bench_formats as BF
import forecast_prompts as FP
import item_validate as IV

HERE = os.path.dirname(os.path.abspath(__file__))


class FutureXUsesThePapersPromptVerbatim(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.items = json.load(open(os.path.join(HERE, "runs", "fx_items_110.json")))

    def test_the_original_arm_is_the_dataset_field_BYTE_FOR_BYTE(self):
        for it in self.items[:20]:
            self.assertEqual(BF.futurex_render(it, "original"), it["prompt"])

    def test_every_item_carries_the_benchmarks_own_format_marker(self):
        missing = [i["item_id"] for i in self.items if BF.FX_FORMAT_MARKER not in i["prompt"]]
        self.assertEqual(missing, [], "an item without the format block cannot be scored for format")

    def test_the_CoT_arm_INSERTS_and_leaves_the_parse_target_byte_identical(self):
        it = self.items[0]
        orig, cot = BF.futurex_render(it, "original"), BF.futurex_render(it, "cot")
        self.assertNotEqual(orig, cot)
        head_o, _, tail_o = orig.partition(BF.FX_FORMAT_MARKER)
        head_c, _, tail_c = cot.partition(BF.FX_FORMAT_MARKER)
        self.assertEqual(tail_o, tail_c, "the answer-format block MOVED; the parse target must not")
        self.assertTrue(head_c.startswith(head_o))

    def test_an_unknown_arm_RAISES(self):
        with self.assertRaises(ValueError):
            BF.futurex_render(self.items[0], "freestyle")


class FutureXComplianceRequiresTheBox(unittest.TestCase):
    def test_a_boxed_answer_is_compliant(self):
        self.assertTrue(BF.futurex_parse("I predict yes.\n\\boxed{Yes}")["compliant"])

    def test_an_answer_with_NO_box_is_NOT_compliant(self):
        r = BF.futurex_parse("I predict yes.")
        self.assertFalse(r["compliant"])

    def test_the_LAST_box_wins(self):
        r = BF.futurex_parse("Maybe \\boxed{A}, but on reflection \\boxed{B}")
        self.assertEqual(r["raw_box"], "B")


class BTFComplianceIsTheCLOSINGLINE(unittest.TestCase):

    def test_a_bare_probability_as_the_last_line_is_COMPLIANT(self):
        r = BF.btf_parse("I think this is unlikely.\n0.2")
        self.assertTrue(r["compliant"], "this is EXACTLY what BTF-3's prompt asks for")
        self.assertEqual(r["prob"], 0.2)

    def test_a_labelled_or_decorated_final_line_is_COMPLIANT(self):
        for t in ("Reasoning...\nFinal answer: 0.35", "Reasoning...\n**0.35**",
                  "my estimate is *0.35*", "Probability: 1.0"):
            self.assertTrue(BF.btf_parse(t)["compliant"], t)

    def test_WRONG_CONTRACT_1_a_refusal_containing_odds_is_NOT_compliant(self):
        r = BF.btf_parse("There is roughly a 0.3 chance of X and a 0.7 chance of Y. "
                         "I cannot give a final figure.")
        self.assertFalse(r["compliant"])
        self.assertEqual(r["prob"], 0.7, "still EXTRACTED for the later accuracy pass")
        self.assertEqual(r["source"], "number_not_final")

    def test_WRONG_CONTRACT_1_a_refusal_mentioning_zero_is_NOT_compliant(self):
        self.assertFalse(BF.btf_parse("I have 0 confidence in any estimate and "
                                      "decline to answer.")["compliant"])

    def test_WRONG_CONTRACT_2_the_ASTERISK_form_is_NOT_required(self):
        self.assertNotIn("asterisk", FP.BTF.lower(),
                         "BTF-3's prompt must not be asking for asterisks")
        self.assertIn("asterisk", FP.FB.lower(), "ForecastBench is the one that does")
        self.assertTrue(BF.btf_parse("Final answer: 0.35")["compliant"],
                        "a plain probability with no asterisks must comply")

    def test_TRAILING_PROSE_after_the_number_is_NOT_compliant(self):
        self.assertFalse(BF.btf_parse("My answer is 0.8. But note this is highly "
                                      "uncertain.")["compliant"])

    def test_a_flat_refusal_yields_no_answer_at_all(self):
        r = BF.btf_parse("I cannot predict the future.")
        self.assertFalse(r["compliant"])
        self.assertIsNone(r["prob"])

    def test_it_does_not_mistake_a_TRAILING_DATE_for_a_forecast(self):
        self.assertFalse(BF.btf_parse("The event resolves as of 2026-06-01")["compliant"])

    def test_a_PERCENT_is_not_a_probability_in_0_to_1(self):
        self.assertFalse(BF.btf_parse("I estimate a 35% chance.")["compliant"])

    def test_the_parser_DISCRIMINATES(self):
        yes = ["0.35", "Final answer: 0.9", "reasoning\n**0**", "p = 1.0"]
        no = ["I cannot answer.", "roughly 0.4 to 0.6, unclear",
              "I decline. 0 chance I would guess it.", "0.5 is my guess, but I am unsure."]
        self.assertTrue(all(BF.btf_parse(t)["compliant"] for t in yes))
        self.assertFalse(any(BF.btf_parse(t)["compliant"] for t in no))

    def test_the_CoT_arm_leaves_the_answer_tail_intact(self):
        base = "Some question.\n" + BF.BTF_TAIL
        cot = BF.btf_render(base, "cot")
        self.assertIn(BF.BTF_TAIL, cot)
        self.assertNotEqual(base, cot)

    def test_a_prompt_missing_its_tail_RAISES_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            BF.btf_render("a prompt with no answer tail", "cot")


class TheTIGHTENEDAnswerChannel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.items = json.load(open(os.path.join(HERE, "runs", "btf3_items_110.json")))

    def test_it_replaces_ONLY_the_answer_line(self):
        for it in self.items[:10]:
            o = BF.btf_render(it["prompt"], "original")
            t = BF.btf_render(it["prompt"], "tight")
            self.assertEqual(o[:o.index(BF.BTF_TAIL)], t[:t.index(BF.BTF_TIGHT)], it["item_id"])

    def test_the_native_line_does_NOT_survive_the_swap(self):
        for it in self.items[:10]:
            self.assertNotIn(BF.BTF_TAIL, BF.btf_render(it["prompt"], "tight"))

    def test_a_prompt_missing_its_tail_RAISES_rather_than_rendering_a_hybrid(self):
        with self.assertRaises(ValueError):
            BF.btf_render("a prompt with no answer tail", "tight")

    def test_the_tight_format_PARSES_with_the_SAME_parser(self):
        r = BF.btf_parse("...weighing the status quo.\n\nFinal answer: 0.15")
        self.assertTrue(r["compliant"])
        self.assertEqual(r["prob"], 0.15)

    def test_the_arms_are_DISTINGUISHABLE(self):
        it = self.items[0]
        self.assertNotEqual(BF.btf_render(it["prompt"], "original"),
                            BF.btf_render(it["prompt"], "tight"))


class TheBTF3CorpusIsFitToAsk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = json.load(open(os.path.join(HERE, "runs", "btf3_items_110.json")))

    def test_the_corpus_passes_its_OWN_benchmarks_rules(self):
        IV.require_valid(self.items, where="btf3 test", bench="btf3")

    def test_every_prompt_carries_the_answer_tail(self):
        for it in self.items:
            self.assertIn(BF.BTF_TAIL, it["prompt"], it["item_id"])

    def test_no_unfilled_placeholder_survived_rendering(self):
        for it in self.items:
            self.assertNotRegex(it["prompt"], r"\{(question|background|resolution_criteria|today)\}")

    def test_the_resolution_columns_never_reach_the_prompt(self):
        for it in self.items:
            self.assertNotIn("resolution_explanation", it["prompt"])
            self.assertIsNotNone(it.get("ground_truth"))

    def test_it_is_110_items_with_the_spare_margin(self):
        self.assertEqual(len(self.items), 110, "100 target + 10 spares (owner 2026-08-08)")
        self.assertEqual(len({i["item_id"] for i in self.items}), 110)

    def test_the_draw_is_STRATIFIED_not_a_prefix(self):
        strata = collections.Counter(i["stratum"] for i in self.items)
        self.assertGreaterEqual(len(strata), 6, f"only {len(strata)} strata present: {dict(strata)}")
        self.assertEqual({i["outcome"] for i in self.items}, {0, 1})
        self.assertEqual({i["length_band"] for i in self.items}, {0, 1, 2})

    def test_the_LONG_prompts_were_not_silently_excluded(self):
        self.assertGreater(max(i["field_chars"] for i in self.items), 3000,
                           "every drawn item fits the old cap, so the cap is still in force")


if __name__ == "__main__":
    unittest.main(verbosity=2)
