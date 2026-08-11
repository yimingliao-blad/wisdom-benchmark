"""M6-T5 (L-S) — validate the RAW response envelope before anything reads an answer out of it.

PLAIN ENGLISH: check the shape of what the API sent back, and decide once -- in code -- exactly
which part of the reply counts as the answer.

THE EXTRACTION CONTRACT, DECIDED (audit E7 asked for a decision, not a description):

  * `choices[0].message.content` is the ONLY scoreable channel.
  * `message.reasoning` is CONTEXT and presence-evidence. NEVER the answer, even when it contains
    one -- 0/134 records ever had the answer only there, and promoting it would make the answer
    channel model-dependent, which is the variable under study.
  * `n_choices > 1` is FATAL unless the manifest requested it. We never request n>1, so more than
    one choice means the request was not what we believe it was.
  * tool-call payloads are NON-SCOREABLE. A tool call is not an answer to a forecasting question.
  * a `content` ARRAY (message parts) is NOT silently joined. Joining invents a string the model did
    not emit; it is a distinct, flagged shape.

HONEST LIMITATION. There are no real raw bodies to test against: 0 of 1,018 stored records carry
one, and `raw_responses.jsonl` began today. The fixtures are built from the documented envelope, so
this module is proven as a CONTRACT -- it is not evidence about how these 12 providers behave.

Offline. No network. No spend.
"""

SCOREABLE_PATH = "choices[0].message.content"
CONTEXT_PATHS = ("choices[0].message.reasoning", "choices[0].message.reasoning_details")
NON_SCOREABLE_PATHS = ("choices[0].message.tool_calls", "choices[0].message.function_call")


class SchemaViolation(dict):
    """A named violation with the JSON path that broke, so a failure points at a location."""

    def __init__(self, rule, path, detail):
        super().__init__(rule=rule, path=path, detail=detail)


def validate_envelope(raw, expect_choices=1):
    """Return (ok, [violations]). Never raises on a bad body -- a bad body is data, not an accident.

    `expect_choices` comes from the request the manifest planned. Anything else is a violation,
    because it means the request that was sent is not the request we think we sent.
    """
    v = []
    if not isinstance(raw, dict):
        return False, [SchemaViolation("envelope_not_object", "$", f"got {type(raw).__name__}")]

    ch = raw.get("choices")
    if ch is None:
        v.append(SchemaViolation("choices_missing", "choices", "no choices key"))
        return False, v
    if not isinstance(ch, list):
        v.append(SchemaViolation("choices_not_list", "choices", f"got {type(ch).__name__}"))
        return False, v
    if len(ch) == 0:
        v.append(SchemaViolation("choices_empty", "choices", "zero choices"))
        return False, v
    if len(ch) != expect_choices:
        # FATAL, not a warning: reading [0] of a multi-choice reply silently discards the rest.
        v.append(SchemaViolation("choices_count_unexpected", "choices",
                                 f"got {len(ch)}, the request planned {expect_choices}"))

    c0 = ch[0]
    if not isinstance(c0, dict):
        v.append(SchemaViolation("choice_not_object", "choices[0]", f"got {type(c0).__name__}"))
        return False, v

    if "finish_reason" not in c0:
        v.append(SchemaViolation("finish_reason_missing", "choices[0].finish_reason",
                                 "cannot tell how generation ended"))

    msg = c0.get("message")
    if not isinstance(msg, dict):
        v.append(SchemaViolation("message_missing", "choices[0].message",
                                 f"got {type(msg).__name__}"))
        return False, v

    if "content" not in msg:
        v.append(SchemaViolation("content_missing", SCOREABLE_PATH, "the scoreable channel is absent"))
    else:
        content = msg["content"]
        if isinstance(content, list):
            # a parts array: NOT joined. Joining would invent a string the model did not emit.
            v.append(SchemaViolation("content_is_parts_array", SCOREABLE_PATH,
                                     f"{len(content)} part(s); this shape is flagged, never joined"))
        elif content is not None and not isinstance(content, str):
            v.append(SchemaViolation("content_not_string", SCOREABLE_PATH,
                                     f"got {type(content).__name__}"))

    if msg.get("tool_calls"):
        v.append(SchemaViolation("tool_calls_present", "choices[0].message.tool_calls",
                                 "tool calls are non-scoreable; a tool call is not an answer"))

    u = raw.get("usage")
    if u is not None and not isinstance(u, dict):
        v.append(SchemaViolation("usage_not_object", "usage", f"got {type(u).__name__}"))

    return (len(v) == 0), v


def extract(raw):
    """The ONLY place an answer is taken from a response. Validate first, or this raises.

    Returns {text, reasoning, finish_reason, n_choices}. `reasoning` is returned as CONTEXT; callers
    must not treat it as the answer.
    """
    ok, v = validate_envelope(raw)
    if not ok:
        raise ValueError(f"refusing to extract from an invalid envelope: {v}")
    msg = raw["choices"][0].get("message") or {}
    return {"text": msg.get("content") or "",
            "reasoning": msg.get("reasoning"),
            "finish_reason": raw["choices"][0].get("finish_reason"),
            "n_choices": len(raw["choices"])}
