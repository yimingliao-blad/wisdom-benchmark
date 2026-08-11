"""btf3-answer-channel — recover the intended probability from a NON-COMPLIANT BTF-3 reply.

Owner 2026-08-08: "ask use qwen3.6-35B to extract the value by comprehensive understanding."

WHAT THIS IS FOR, AND WHAT IT MUST NEVER DO.
It recovers an ANSWER for the later ACCURACY pass. It must NEVER score COMPLIANCE. If a reply that
ignored the required format is rescued by an LLM and then counted as compliant, the compliance metric
becomes vacuous -- every reply "complies", because something could read it. Compliance stays measured
against the format the benchmark states. These are two questions and they get two tools.
`extract()` therefore returns no compliance field at all, and the caller cannot accidentally use it
as one.

DESIGN, from the ground truth (222 real paid replies, 40 non-compliant):
  27 gave a correct 0-1 probability and then kept writing  -> RECOVERABLE
   9 gave a percent instead of 0-1                          -> RECOVERABLE (convert)
   4 gave no figure at all                                  -> MUST ABSTAIN
The 4 are the whole reason there is an abstain path. Without them a yes-biased extractor that always
invents a number would score 36/36 and look perfect while being useless.

Prompt-design artifact: plans/openrouter-output-integrity/verification/
prompt-design-btf-answer-channel.md (scope btf3-answer-channel).

Offline against a LOCAL model. No paid calls.
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

LOCAL = "http://localhost:8000/v1/chat/completions"
MODEL = "qwen3.6-35b-gguf"
TAIL_CHARS = 2000          # generous: the figure can sit well before a long closing paragraph

# The instruction is deliberately narrow. It is an EXTRACTOR, not a forecaster: it must never form
# its own view of the question, only report what the writer committed to.
INSTRUCTION = """You are extracting a number from someone else's finished forecast.

Below is the END of a reply in which a forecaster was asked to give the probability of a future
event. Your only job is to report the final probability THE WRITER settled on.

Rules:
- Report the writer's OWN final figure. Never form your own opinion about the question.
- If the writer gave a percentage (for example 35%), convert it to a decimal (0.35).
- If the writer gave several numbers, report the one they settled on as their FINAL answer.
- If the writer did NOT commit to any probability -- they refused, hedged without a number, or only
  discussed considerations -- report NONE. Do not guess, estimate, or infer a number that the writer
  did not state. Reporting NONE is the correct answer in that case, not a failure.

Reply with exactly one line and nothing else:
PROB: <a decimal between 0 and 1>
or
PROB: NONE

--- BEGIN REPLY ---
{tail}
--- END REPLY ---"""

_LINE = re.compile(r"PROB:\s*(NONE|[01](?:\.\d+)?|\.\d+)\s*$", re.I | re.M)


class ExtractionError(RuntimeError):
    """Raised when the extractor's own output cannot be read. NEVER returned as a value."""


def build_prompt(text):
    return INSTRUCTION.format(tail=(text or "")[-TAIL_CHARS:])


def parse_reply(reply):
    """Strict. An unreadable extractor reply is an ERROR, never a quiet None that reads as ABSTAIN.

    This distinction is the whole lesson of D-OR-5: an error returned as a legitimate-looking value
    is indistinguishable downstream from a real abstain, and 60 crashed calls once read as 60 clean
    abstains printing recall 0.000.
    """
    m = _LINE.search(reply or "")
    if not m:
        raise ExtractionError(f"extractor did not emit a PROB: line -- got {(reply or '')[-200:]!r}")
    v = m.group(1)
    if v.upper() == "NONE":
        return None
    f = float(v)
    if not 0.0 <= f <= 1.0:
        raise ExtractionError(f"extractor returned {f}, outside [0,1]")
    return f


# 2500, reused from completeness_review.REVIEWER_MAX_TOKENS rather than invented. qwen3.6-35b is a
# REASONING model: it spends tokens thinking before emitting any visible content, so a small budget
# yields finish_reason=length with ZERO characters. Measured here: at max_tokens=200, 52 of 60
# extractions hit the budget before writing "PROB:". The existing reviewer had already learned this
# for the same model; reusing its number beats re-deriving it.
EXTRACTOR_MAX_TOKENS = 2500


def call(prompt, model=MODEL, max_tokens=EXTRACTOR_MAX_TOKENS, timeout=900):
    body = json.dumps({"model": model, "temperature": 0.0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(LOCAL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    ch = d["choices"][0]
    if ch.get("finish_reason") == "length":
        raise ExtractionError("extractor hit its own token budget before emitting PROB:")
    return ch["message"].get("content") or ""


def extract(text, model=MODEL):
    """Return {prob, abstained, source}. NO compliance field, deliberately -- see the module docstring."""
    reply = call(build_prompt(text), model=model)
    p = parse_reply(reply)
    return {"prob": p, "abstained": p is None, "source": "llm_extractor", "model": model,
            "raw": reply.strip()[-120:]}
