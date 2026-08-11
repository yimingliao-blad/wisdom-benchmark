"""M6-T5/S4 — acceptance for the response-envelope validator and extraction contract.

THESE ARE CONTRACT TESTS, NOT BEHAVIOURAL EVIDENCE. There are no real raw bodies to test against:
0 of 1,018 stored records carry one, and raw_responses.jsonl began today with no paid call since.
The fixtures are constructed from the documented envelope. They prove the validator matches the
contract; they do NOT prove any provider emits these shapes. Recording that distinction here because
blurring it is a mistake this project has made before.

Offline. No network. No spend.  Run: python3 -m unittest test_response_schema -v
"""
import unittest

import response_schema as RS


def envelope(content="Reasoned.\n\n\\boxed{No}", **over):
    """A well-formed body of the shape the stored records imply."""
    msg = {"content": content, "role": "assistant"}
    msg.update(over.pop("message", {}))
    e = {"choices": [{"message": msg, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 300, "completion_tokens": 40}, "provider": "X"}
    e.update(over)
    return e


def rules(raw, **kw):
    return {v["rule"] for v in RS.validate_envelope(raw, **kw)[1]}


class TheNegativeControl(unittest.TestCase):
    """If a well-formed body fails, the validator would reject the real run."""

    def test_a_well_formed_envelope_passes(self):
        ok, v = RS.validate_envelope(envelope())
        self.assertTrue(ok, f"a valid envelope was rejected: {v}")

    def test_a_reasoning_channel_does_not_make_it_invalid(self):
        ok, _ = RS.validate_envelope(envelope(message={"reasoning": "thinking..."}))
        self.assertTrue(ok)

    def test_null_content_is_allowed_by_the_SHAPE_check(self):
        """An empty reply is a COMPLETENESS question (EMPTY_HTTP), not a shape violation. The two
        layers must not duplicate each other's judgement."""
        ok, _ = RS.validate_envelope(envelope(content=None))
        self.assertTrue(ok)


class EveryMalformationIsRejected(unittest.TestCase):
    def test_no_choices_key(self):
        self.assertIn("choices_missing", rules({"usage": {}}))

    def test_choices_not_a_list(self):
        self.assertIn("choices_not_list", rules({"choices": {}}))

    def test_empty_choices(self):
        self.assertIn("choices_empty", rules({"choices": []}))

    def test_more_choices_than_requested_is_FATAL(self):
        """Reading [0] of a 3-choice reply silently discards two (audit C5)."""
        e = envelope()
        e["choices"] = e["choices"] * 3
        self.assertIn("choices_count_unexpected", rules(e))
        self.assertFalse(RS.validate_envelope(e)[0])

    def test_message_missing(self):
        self.assertIn("message_missing", rules({"choices": [{"finish_reason": "stop"}]}))

    def test_content_absent(self):
        e = envelope(); del e["choices"][0]["message"]["content"]
        self.assertIn("content_missing", rules(e))

    def test_content_as_a_PARTS_ARRAY_is_flagged_not_joined(self):
        """Joining parts would invent a string the model never emitted."""
        e = envelope(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        r = rules(e)
        self.assertIn("content_is_parts_array", r)

    def test_content_not_a_string(self):
        self.assertIn("content_not_string", rules(envelope(content=123)))

    def test_finish_reason_absent(self):
        e = envelope(); del e["choices"][0]["finish_reason"]
        self.assertIn("finish_reason_missing", rules(e))

    def test_tool_calls_are_non_scoreable(self):
        e = envelope(content="", message={"tool_calls": [{"id": "1"}]})
        self.assertIn("tool_calls_present", rules(e))

    def test_usage_wrong_type(self):
        self.assertIn("usage_not_object", rules(envelope(usage="none")))

    def test_a_violation_names_its_json_path(self):
        _, v = RS.validate_envelope(envelope(content=123))
        self.assertEqual(v[0]["path"], RS.SCOREABLE_PATH)


class ExtractionHonoursTheContract(unittest.TestCase):
    def test_extract_refuses_an_invalid_envelope(self):
        with self.assertRaises(ValueError):
            RS.extract({"choices": []})

    def test_the_answer_comes_only_from_the_canonical_channel(self):
        e = envelope(content="the answer \\boxed{No}",
                     message={"reasoning": "\\boxed{Yes} is what I first thought"})
        out = RS.extract(e)
        self.assertIn("\\boxed{No}", out["text"])
        self.assertNotIn("\\boxed{Yes}", out["text"],
                         "reasoning must never leak into the answer channel")
        self.assertIsNotNone(out["reasoning"], "but reasoning IS returned, as context")

    def test_n_choices_is_reported(self):
        self.assertEqual(RS.extract(envelope())["n_choices"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
