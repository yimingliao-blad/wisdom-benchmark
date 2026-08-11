"""Output-completeness reviewer for the OpenRouter FutureX run.  [scope: or-completeness-reviewer-2026-08-08]

THE QUESTION THIS ASKS IS NOT ACCURACY. It asks whether a captured model output is FINISHED and
usable: does it contain an answer, and — when the arm asked for reasoning — is that reasoning
present and about the question actually posed? Whether the answer is CORRECT is never asked here
and must never be inferred from a verdict this module produces.

WHY IT EXISTS. `finish_reason` lies. Cloudflare returned `finish_reason='error'` with HTTP 200 and
a cut-off echo of the prompt; five providers exceed `max_tokens` outright. So completeness cannot
be read off the transport metadata and needs its own check.

TWO LAYERS, DELIBERATELY ORDERED:
  1. DETERMINISTIC -- transport + shape facts (provider error, implausible usage, empty content,
     missing answer marker, mid-sentence stop). Cheap, reproducible, and it decides most records.
  2. LLM -- only for what layer 1 cannot settle: is a long, well-formed output actually finished,
     and is its reasoning on-topic? Judgement, not a fact lookup.

Layer 1 runs first because a deterministic answer must never be overridden by a model's opinion.
"""
import json
import re

import bench_formats as BF

# ---------------------------------------------------------------- verdict vocabulary
#
# THE DIVIDING LINE IS "DID WE OBSERVE THE MODEL'S FINISHED OUTPUT?", NOT "IS IT GOOD?"
# (corrected 2026-08-08 after the M5 smoke; the first design got this wrong.)
#
# SCOREABLE -- the model finished, so its format behaviour was actually observed:
#   COMPLETE   finished WITH the answer marker      -> compliant = True
#   NO_ANSWER  finished WITHOUT the answer marker   -> compliant = FALSE
#     ^ this is the study's central NEGATIVE RESULT, not an error. llama-3.1-8b replied
#       "I can't fulfill that request." in 8 tokens with finish_reason=stop: a clean refusal that
#       did not follow the format. The first version forced compliant=None here, DISCARDING exactly
#       the observation the benchmark exists to make, and halted the smoke over it.
#
# NOT SCOREABLE -- we never saw what the model would have produced:
#   TRUNCATED       cut off mid-thought (budget or stream)
#   EMPTY           nothing returned at all
#   PROVIDER_ERROR  the call did not really run
#   UNDECIDED       layer 1 abstains; hand to layer 2 (or the reader was unavailable)
COMPLETE = "COMPLETE"
NO_ANSWER = "NO_ANSWER"
TRUNCATED = "TRUNCATED"
PROVIDER_ERROR = "PROVIDER_ERROR"
TRANSPORT_ERROR = "TRANSPORT_ERROR"   # the request never completed; distinct from a provider fault
SCHEMA_ERROR = "SCHEMA_ERROR"         # the body arrived but its SHAPE breaks the extraction contract
UNDECIDED = "UNDECIDED"

# TWO KINDS OF EMPTY, AND THEY MEAN OPPOSITE THINGS (owner ruling 2026-08-08):
#   "we have two empty. empty from http or empty from your parsing result. if conflicts, which is a
#    serious problem. if http is empty, then it could be networking error, retry 3 times at maximum.
#    if parsing result is empty, it means your method is wrong."
#
# EMPTY_HTTP     the response body carried no content at all -> a NETWORK/provider fault. Retry (<=3).
#                Unobserved: the model was never heard from, so nothing can be scored.
# EMPTY_PARSE    content WAS returned but our extraction produced nothing -> OUR METHOD IS SUSPECT,
#                not the model's compliance. It must never be silently scored as non-compliance;
#                it is raised for inspection, because the likeliest cause is our parser.
#
# The CONFLICT case -- http says empty while a parse found text, or the reverse -- is a serious
# inconsistency and gets its own label rather than being resolved by preference.
EMPTY_HTTP = "EMPTY_HTTP"
EMPTY_PARSE = "EMPTY_PARSE"
EMPTY_CONFLICT = "EMPTY_CONFLICT"
# NO aggregate `EMPTY` constant (Codex regate finding 1): keeping it let checks accept or emit the
# obsolete state after the split. Historical records carrying "EMPTY" are read as EMPTY_HTTP by the
# legacy reader, and nowhere else.
LEGACY_EMPTY_ALIAS = {"EMPTY": EMPTY_HTTP}

# A verdict is SCOREABLE when the model's finished output was observed. Compliance may be recorded
# only for these; everything else is an unobserved call and carries compliant=None.
SCOREABLE = (COMPLETE, NO_ANSWER)
# EMPTY_PARSE is deliberately NOT scoreable and NOT a plain method-defect: it is the signal that OUR
# extraction may be wrong, so it is surfaced for inspection rather than counted either way.
NEEDS_INSPECTION = (EMPTY_PARSE, EMPTY_CONFLICT)
# These mean the METHOD is wrong (bad budget, bad request, dead endpoint) -- smoke halts on them.
# NO_ANSWER is deliberately NOT here: a refusal is the model's behaviour, not our bug.
METHOD_DEFECT = (TRUNCATED, EMPTY_HTTP, EMPTY_PARSE, EMPTY_CONFLICT, PROVIDER_ERROR,
                 TRANSPORT_ERROR, SCHEMA_ERROR, "BUDGET_CAPPED")
BUDGET_CAPPED = "BUDGET_CAPPED"

# D-OR-18. THE MODEL WAS NEVER HEARD FROM -- the call did not deliver its output, so there is nothing
# of the model's in the row. These are the ONLY verdicts that mean "buy this unit again": the fault
# was ours or the network's, the row cost $0, and re-issuing the call is the only way to obtain the
# observation. Everything else DID deliver a body and stands as evidence, including TRUNCATED (cut
# off, but the model spoke and we were billed) and EMPTY_PARSE (the body arrived; our parser is the
# suspect, and re-buying an identical call cannot fix a parser).
#
# It lives HERE, beside the verdicts, because resume and the analysis must not each carry their own
# idea of "done". That drift IS the defect: analyze.py read PROVIDER_ERROR as UNOBSERVED while
# persistence.resume_state read the same row as a completed call, so 255 units the org-budget 403
# killed were skipped by resume AND excluded from the denominator -- permanently unobserved, with the
# loss concentrated on whichever models happened to be in flight.
UNDELIVERED = (PROVIDER_ERROR, TRANSPORT_ERROR, EMPTY_HTTP)
KNOWN_VERDICTS = (COMPLETE, NO_ANSWER, TRUNCATED, PROVIDER_ERROR, TRANSPORT_ERROR, SCHEMA_ERROR,
                  UNDECIDED, EMPTY_HTTP, EMPTY_PARSE, EMPTY_CONFLICT, BUDGET_CAPPED)


class VerdictError(RuntimeError):
    """An unrecognised verdict. Raised, never defaulted -- guessing is how a fault becomes a result."""


def needs_reasoning_followup(rec, include_no_answer=False):
    """Should the CoT prompt be issued for this reply? THE single definition (M6-T21).

    Written after followup_select and analyze.reasoning_coverage were built with different notions of
    it -- one admitted COMPLETE only, the other all of SCOREABLE -- and disagreed by exactly the two
    refusals in the corpus: 18 versus 20. That is the same two-readers defect as D-OR-18, committed
    twice in one session, so the rule lives here beside the verdicts and both callers import it.

    A refusal (NO_ANSWER) is excluded by default: the second prompt exists to make a model that
    ANSWERED show its work, and re-asking a refusal is a different experiment.
    """
    admissible = SCOREABLE if include_no_answer else (COMPLETE,)
    return rec.get("completeness") in admissible and not reasoning_evidence(rec)["has"]


def delivered_a_response(rec):
    """Did the provider actually hand back the model's output for this attempt?

    This is the ONE question resume may ask. It is deliberately not "is there a row" (the D-OR-18
    bug) and not "is it scoreable" (that would re-buy every TRUNCATED reply we already paid for).
    """
    v = rec.get("completeness")
    v = LEGACY_EMPTY_ALIAS.get(v, v)
    if v is None:
        # No verdict yet. Fall back to the discriminator the raw sidecar already uses -- "a body
        # arrived iff the provider reported a finish_reason" -- rather than inventing a second rule.
        return rec.get("finish_reason") is not None
    if v not in KNOWN_VERDICTS:
        raise VerdictError(
            f"unrecognised completeness verdict {v!r} for {rec.get('model')} / "
            f"{rec.get('item_id')}. Refusing to guess whether this unit was answered: guessing "
            f"'yes' silently drops the unit, guessing 'no' silently re-buys it.")
    return v not in UNDELIVERED

# Codex C1 (verification gate): `[^{}]*` cannot match a NESTED brace, so `\boxed{\frac{1}{2}}` would
# read as NO answer at all. Not observed in FutureX (0/366 boxed texts -- its answers are option
# letters or short free text), but a parser that silently drops a valid answer shape is exactly the
# defect class this project keeps hitting, and the fix is cheap. One level of nesting is enough for
# real LaTeX answers; deeper nesting is still recorded as a parse miss rather than guessed at.
_BOXED = BF._BOXED      # ONE definition, not a second copy that can drift (see bench_formats)
# A finished sentence ends in terminal punctuation, a closing bracket, or the answer marker itself.
_TERMINAL = re.compile(r'[.!?)\]}"\u201d\u2019]\s*$')

# Codex C3 (verification gate, CONFIRMED): a refusal is often a complete sentence with NO full stop
# -- "I cannot answer", "I don't know". The punctuation test alone called those TRUNCATED, turning
# the study's central negative observation into an unscoreable record. A short reply that reads as a
# finished refusal is FINISHED; it simply did not comply.
_REFUSAL = re.compile(
    r"^\s*(i\s+(cannot|can't|can not|am unable to|won't|will not|do not|don't)\b"
    r"|sorry\b|unable to\b|no answer\b|i'm sorry\b|as an ai\b|i am an ai\b)", re.I)


def answer_markers(text, bench="futurex"):
    """The non-empty answer markers present, PER THE BENCHMARK'S OWN CONTRACT.

    Added 2026-08-08 after a BTF-3 dry run produced 40 TRUNCATED verdicts out of 40. The whole
    verdict layer was hard-wired to \\boxed{}, which is FutureX's contract. BTF-3's contract is its
    closing line -- "the last thing you write is your final answer as a probability between 0 and 1"
    -- so a perfectly compliant BTF reply ending in `0.15` had NO marker by this test, was called
    TRUNCATED, and quarantined its model on the first unit. The entire BTF half of the study would
    have produced ZERO observations. Caught offline, before any BTF call was paid for.
    """
    if bench == "btf3":
        r = BF.btf_parse(text)
        return [str(r["prob"])] if r["compliant"] else []
    return [b for b in _BOXED.findall(text) if b.strip()]


# Trailing MARKDOWN is not an unfinished sentence (D-OR-15). Models close with "**Probability: 0.30
# (30%)**" or "*(Rounded to nearest 5%.)*" -- emphasis marks after a complete clause. The punctuation
# test saw `*` as the last character and called the reply cut off. A bare figure ("12%") is likewise
# a complete thought, not a severed one.
#
# NOTE this deliberately does NOT just trust finish_reason=stop. That was the first fix and it was
# too broad: this project has direct evidence that providers mislabel -- finish_reason='error'
# arriving as HTTP 200, and mistral-small returning a cut-off echo with prompt_tokens=0. A genuinely
# mid-clause tail stays TRUNCATED even when the provider claims it stopped normally.
_TRAILING_MARKUP = re.compile(r"[*_`~\s]+$")
_ENDS_IN_FIGURE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?\s*%?$")


def looks_finished(text, bench="futurex"):
    """Terminal punctuation, a recognisable complete refusal, or a closing figure. Codex C3.

    For BTF-3, a reply that ENDS with its answer is finished by definition -- that closing
    probability is exactly what the prompt asked for, and it carries no terminal punctuation.
    """
    t = _TRAILING_MARKUP.sub("", (text or "").rstrip())
    if _ENDS_IN_FIGURE.search(t):
        return True
    if bench == "btf3" and BF.btf_parse(t)["compliant"]:
        return True
    if _TERMINAL.search(t):
        return True
    # a SHORT reply that opens like a refusal and never began an argument is finished, not cut off
    return bool(_REFUSAL.match(t)) and len(t) <= 200


def deterministic_verdict(rec, bench=None):
    """Layer 1. Returns (verdict, reason). Only facts -- no judgement, no model call.

    `bench` selects the answer contract; it defaults to the record's own `bench` field, then to
    futurex. Passing the wrong one silently mislabels every record, so it is read from the record
    rather than assumed by the caller wherever possible.

    Order matters: a provider failure outranks a shape problem, because a call that never ran
    cannot be said to lack an answer; and a BUDGET stop outranks emptiness, because an empty
    completion under finish_reason=length is exhaustion, not refusal.

    METHODOLOGICAL CHOICE, MADE EXPLICITLY (Codex C1, BLOCKING). A response that emits a parseable
    \\boxed{} answer and THEN runs into the length ceiling is labelled TRUNCATED, even though the
    answer is extractable. Two reasons: the benchmark's own prompt requires the reply to END with the
    marker, so a reply that continued past it did not satisfy the format; and a cut-off reply is an
    INCOMPLETE OBSERVATION -- there is no way to know what final answer the model would have settled
    on. `answer_extractable` is recorded on every such record, so this choice can be revisited from
    the stored data WITHOUT re-buying a single call. Previously this behaviour was accidental rather
    than chosen.
    """
    bench = bench or rec.get("bench") or "futurex"
    if rec.get("finish_reason") == "error":
        return PROVIDER_ERROR, f"finish_reason=error from provider {rec.get('provider')!r}"
    u = rec.get("usage") or {}
    # Codex C4: distinguish a provider that REPORTS zero prompt tokens (a transport defect, since the
    # benchmark always sends a non-empty question) from one that OMITS usage entirely.
    if "prompt_tokens" not in u:
        return UNDECIDED, "provider reported no usage block -- cannot judge transport; needs a reader"
    if not u.get("prompt_tokens"):
        return PROVIDER_ERROR, (f"prompt_tokens={u.get('prompt_tokens')!r} for a non-empty prompt -- "
                                f"the call did not really run")
    text = rec.get("text") or ""
    truncated_by_budget = rec.get("finish_reason") == "length"
    # Codex C3 (BLOCKING, CONFIRMED BUG): the budget check MUST precede the empty check. An empty
    # completion under finish_reason=length is BUDGET EXHAUSTION -- the reasoning tokens ate the whole
    # allowance -- which is TRUNCATED, not "the model declined to answer". The previous order returned
    # NO_ANSWER while its own comment described budget exhaustion: the right cause, the wrong label.
    if truncated_by_budget:
        return TRUNCATED, ("finish_reason=length with an empty completion -- the budget was consumed "
                           "before any visible output" if not text.strip() else
                           "finish_reason=length -- the budget cut the output off")
    if not text.strip():
        # No bytes in the HTTP body. The model was never heard from, so nothing can be scored --
        # this is NOT non-compliance. Owner ruling: treat as a possible network fault, retry <=3.
        return EMPTY_HTTP, "no content in the HTTP response -- the model produced nothing"
    # Codex C2 (CONFIRMED): `\boxed{}` matched the empty capture, so a marker with NO answer inside
    # could be promoted to COMPLETE. An answer marker only counts when it CONTAINS something.
    boxed = answer_markers(text, bench)
    # THE PROVIDER'S OWN STOP SIGNAL OUTRANKS A PUNCTUATION HEURISTIC (D-OR-15, found in the BTF
    # native gate). finish_reason=length was already handled above and returns TRUNCATED, so by this
    # point the generation was NOT cut off by the budget. If the provider also says it stopped
    # normally, the reply is FINISHED -- and calling it TRUNCATED because its last character is a
    # markdown asterisk contradicts a fact with a guess.
    #
    # Measured: all 13 "truncations" in the BTF native gate had finish_reason=stop, 0 escalations,
    # and complete text ending in trailing markdown -- "**Probability: 0.30 (30%)**", "12%",
    # "*(Rounded to nearest 5% for calibration.)*". Every one was a finished, non-compliant reply
    # wrongly removed from the denominator, which INFLATED the compliance rate.
    tail_ok = looks_finished(text, bench)
    if not boxed:
        # No answer marker. Distinguish "stopped mid-thought" from "finished but never answered":
        # a mid-sentence tail means the output was cut off, which is TRUNCATED, not a format failure.
        want = "closing probability" if bench == "btf3" else "\\boxed{}"
        return (TRUNCATED, "no answer marker and the text ends mid-sentence") if not tail_ok else \
               (NO_ANSWER, f"text is finished but contains no {want} answer")
    # Codex C2 (BLOCKING): reaching layer 2 must GUARANTEE an extractable answer marker, so that a
    # "stops cleanly" verdict can be promoted to COMPLETE. That was true only implicitly; assert it.
    assert boxed, "invariant: layer 2 is only consulted when an answer marker is present"
    if bench == "btf3":
        # the marker IS the closing line, so its presence already proves the reply ended on it
        return COMPLETE, "reply ends with its final probability, as BTF-3's prompt requires"
    if not tail_ok and not text.rstrip().endswith("}"):
        return UNDECIDED, "answer marker present but the text does not end cleanly -- needs a reader"
    return UNDECIDED, CLEAN_SHAPE


CLEAN_SHAPE = "shape is clean; completeness/relevance still needs a reader"
_ENDS_BOXED = re.compile(r"\\boxed\s*\{((?:[^{}]|\{[^{}]*\})*)\}\s*$")


# D-OR-17. Punctuation and markup that may FOLLOW the answer without meaning the reply continued.
# A model that writes `\boxed{H}.` has finished; the full stop is typography, not content. The set is
# deliberately narrow -- terminators, closing delimiters and markdown emphasis, nothing that could be
# a word -- so `I think \boxed{A} is wrong.` still fails: strip the stop and it ends in "is wrong",
# which is prose after the answer and means the reply did NOT end with it.
# `$` and `\` are here for LaTeX delimiters: models wrap the answer as `$\boxed{B}$` or
# `\[ \boxed{...} \]`. Both END with the answer; only the maths markup trails it. `}` is deliberately
# NOT in the set -- stripping it would let `\boxed{A}\text{ and more}` read as a finished reply.
_TRAILING_CLOSERS = re.compile(r"[\s*_`~.!?,;:\"')\]”’$\\]+$")


def ends_with_answer(rec):
    """True when the text TERMINATES in a NON-EMPTY answer marker -- the strongest cheap evidence of
    a finished reply, since the benchmark's prompt requires the answer to come last. Codex C2: the
    emptiness check is essential, or `\boxed{}` alone would license a provisional COMPLETE.

    D-OR-17: a trailing full stop used to defeat this. 10 records ending `\boxed{H}.` were left
    UNDECIDED, and in --no-review mode an UNDECIDED verdict counts toward quarantining the model --
    so a typographic period could get a well-behaved model excluded from the run.
    """
    text = _TRAILING_CLOSERS.sub("", (rec.get("text") or "").rstrip())
    m = _ENDS_BOXED.search(text)
    return bool(m and m.group(1).strip())


# ---------------------------------------------------------------- the REASONING evidence rule
# Owner 2026-08-08: "our goal is not replicate the benchmark, but we want to answer but also tell
# model how they did with answer." The study wants the ANSWER **and how the model reached it**, so
# reasoning is DATA to capture in both arms -- not a compliance condition only one arm can meet.
#
# TWO SOURCES, both authoritative for PRESENCE (the answer itself still comes only from
# choices[0].message.content -- reasoning is never the answer):
#   1. `message.reasoning`  the API's own reasoning channel (thinking models)
#   2. visible prose in `content` before the answer marker
#
# REQUIRED vs OBSERVED:
#   cot arm       the prompt ASKS for reasoning, so its absence is a real deficiency
#   original arm  the prompt asks ONLY for the boxed answer, so absence is CORRECT behaviour and
#                 presence is a FINDING. Measured: 294/312 original-arm replies reason anyway
#                 (165 on the reasoning channel, 264 as prose). Scoring that arm's 18 terse replies
#                 as deficient would mark correct behaviour as a failure.
REASONING_MIN_CHARS = 120


def reasoning_evidence(rec):
    """Return {has, source, chars} -- PRESENCE only, never used to extract the answer."""
    field = str(rec.get("reasoning") or "")
    text = rec.get("text") or ""
    prose = re.split(r"\\boxed", text)[0].strip()
    src = []
    if field.strip():
        src.append("reasoning_field")
    if len(prose) >= REASONING_MIN_CHARS:
        src.append("visible_prose")
    return {"has": bool(src), "source": src,
            "chars": max(len(field.strip()), len(prose) if len(prose) >= REASONING_MIN_CHARS else 0)}


def reasoning_required(arm):
    """Only the arm whose prompt ASKS for reasoning can be deficient for lacking it."""
    return arm == "cot"


def empty_cross_check(rec, raw=None):
    """Reconcile the TWO empties (owner ruling 2026-08-08; corrected per Codex regate finding 2).

    EMPTY_PARSE is NOT "the model produced no answer marker" -- that is NO_ANSWER, a genuine and
    scoreable non-compliance. EMPTY_PARSE means the RAW BODY CONTAINS SOMETHING but the pipeline
    could not derive the scoreable text from the decided extraction contract
    (`choices[0].message.content`). That is a fault in OUR method, not the model's behaviour.

    Two defects were fixed here at once:
      * the old predicate required "no box AND no text", and no-text IS http_empty, so the
        EMPTY_PARSE branch was UNREACHABLE -- the state existed only on paper;
      * conflating it with a missing marker would have shunted real non-compliance into
        inspection, hiding exactly the negative result the study exists to record.

    Returns (verdict, reason) or None when neither empty applies.
    """
    text = (rec.get("text") or "")
    canonical_empty = not text.strip()          # nothing in choices[0].message.content

    # is there content ANYWHERE ELSE in the raw body? reasoning, another choice, a tool call
    other = []
    if raw:
        for i, ch in enumerate((raw.get("choices") or [])):
            msg = ch.get("message") or {}
            if i > 0 and str(msg.get("content") or "").strip():
                other.append(f"choices[{i}].content")
            if str(msg.get("reasoning") or "").strip():
                other.append(f"choices[{i}].reasoning")
            if msg.get("tool_calls"):
                other.append(f"choices[{i}].tool_calls")
    elif str(rec.get("reasoning") or "").strip():
        other.append("reasoning")

    if canonical_empty and other:
        # the body carried content, just not where the contract says to look -> OUR METHOD
        return EMPTY_PARSE, (f"the canonical channel is empty but the body carries content in "
                             f"{sorted(set(other))} -- extraction is the prime suspect, not the model")
    if canonical_empty:
        return None                              # a plain empty body; layer 1 already calls it EMPTY_HTTP

    # content IS present in the canonical channel. A missing answer marker here is NO_ANSWER,
    # decided by layer 1 -- never routed to inspection.
    return None


def empty_conflict(http_reported_empty, text):
    """A serious inconsistency: the transport says empty while text exists, or the reverse.

    Never resolved by preferring one side -- preferring one is how a real disagreement disappears.
    """
    if bool(http_reported_empty) != (not (text or "").strip()):
        return EMPTY_CONFLICT, (f"http-empty={bool(http_reported_empty)} disagrees with "
                                f"text-empty={not (text or '').strip()}")
    return None


def provisional_complete(rec, verdict, reason):
    """SAMPLED REVIEW (owner ruling 2026-08-08): once a model has passed its per-model probe, a
    clean-shaped record that ENDS in the answer marker is accepted provisionally and reviewed later
    in a batch, instead of blocking the run on a per-call LLM verdict.

    Why this is safe enough to defer: layer 1 already ruled out every transport and shape failure,
    and the text terminates in the marker the prompt demanded. Why it is still only PROVISIONAL:
    the reader caught a case layer 1 could not (gemini-3.5-flash), and the reader itself produced a
    false positive on exactly this shape -- so neither is trusted alone. Records carry
    pending_review=True and are re-examined by review_pending.py before any result is published.
    """
    return verdict == UNDECIDED and reason == CLEAN_SHAPE and ends_with_answer(rec)


# ---------------------------------------------------------------- layer 2: the prompt
# ONE instruction, ONE output, ONE question -- each appears exactly once (PA.structural_check).
# The reviewer is shown the output only, never the gold answer, so it CANNOT drift into grading
# correctness even if it wanted to.
INSTR = (
    "You are checking whether a language model's response is FINISHED. You are NOT checking "
    "whether it is correct. A confidently wrong but complete answer is COMPLETE.\n\n"
    "Reply with exactly one line:\n"
    "verdict: complete\n"
    "verdict: truncated\n"
    "verdict: no_answer\n"
    "verdict: unclear\n\n"
    "Use `truncated` if the text stops mid-sentence, mid-word, or mid-argument, or promises a "
    "conclusion it never reaches.\n"
    "Use `no_answer` if the text is finished but never states a final answer.\n"
    "Use `complete` if it reaches a final answer and reads as finished.\n"
    "Use `unclear` if you genuinely cannot tell. Do not guess."
)


def build_prompt(question, response_text, reasoning=None, arm="original"):
    """Render the EXACT string sent to the reviewer. Sections appear once, in a fixed order."""
    parts = [INSTR, "", "=== THE QUESTION THE MODEL WAS ASKED ===", question.strip(), ""]
    if arm == "cot" and reasoning:
        parts += ["=== THE MODEL'S REASONING ===", reasoning.strip(), ""]
    parts += ["=== THE MODEL'S RESPONSE ===", response_text.strip(), "",
              "=== YOUR VERDICT ==="]
    return "\n".join(parts)


# ---------------------------------------------------------------- variant B: the TAIL reader
# Owner insight (2026-08-08): truncation is a property of HOW THE TEXT ENDS, not of the whole
# response. Variant A showed exactly why that matters -- given the full output the reader reasons
# "it worked through the problem and reached a conclusion, so it is complete" and TALKS ITSELF PAST
# a mid-sentence stop. Measured: recall 0.760, six false-COMPLETEs, every one of them arguing from
# the body rather than the ending. Showing only the ending removes the material it rationalises from.
TAIL_INSTR = (
    "Below is the LAST PART of a language model's response. Decide only one thing: does the text "
    "STOP CLEANLY, or is it CUT OFF mid-thought?\n\n"
    "Ignore whether the content is correct, sensible, or well-argued. Judge only the ending.\n\n"
    "Reply with exactly one line:\n"
    "verdict: complete    - the last sentence finishes; the text comes to a natural stop\n"
    "verdict: truncated   - the last sentence breaks off mid-word, mid-clause, or mid-thought\n"
    "verdict: unclear     - you genuinely cannot tell. Do not guess."
)
TAIL_CHARS = 400


def build_tail_prompt(response_text, tail_chars=TAIL_CHARS):
    """Show ONLY the ending. No question, no reasoning, no body to rationalise from."""
    t = (response_text or "").rstrip()
    tail = t[-tail_chars:]
    lead = "...(earlier text omitted)...\n" if len(t) > tail_chars else ""
    return "\n".join([TAIL_INSTR, "", "=== THE END OF THE RESPONSE ===", lead + tail, "",
                      "=== YOUR VERDICT ==="])


# ---------------------------------------------------------------- variant C: MINIMAL
# Owner concern (2026-08-08): "if you put too many rules on the llm, then it lost the ability to
# heuristic analyze the natural language form of answer".
#
# Variant B tells the reader what a finished text LOOKS LIKE -- "the last sentence finishes". That
# framing is about SENTENCES, and the thing these replies actually end with is `\boxed{No}`, which
# is not a sentence. The reader's own words on the false positive were "a new sentence starts, it's
# likely cut off": it applied my rule correctly and reached the wrong answer.
#
# Variant C states the QUESTION and nothing else, leaving the judgement to the model.
MINIMAL_INSTR = (
    "Here is the end of a text. Did it finish, or was it cut off?\n\n"
    "Reply with one line only:\n"
    "verdict: complete\n"
    "verdict: truncated\n"
    "verdict: unclear"
)


def build_minimal_prompt(response_text, tail_chars=TAIL_CHARS):
    t = (response_text or "").rstrip()
    tail = t[-tail_chars:]
    lead = "...(earlier text omitted)...\n" if len(t) > tail_chars else ""
    return "\n".join([MINIMAL_INSTR, "", lead + tail, "", "verdict:"])


# ---------------------------------------------------------------- layer 2: the parser
# Anchored at line start, allows a trailing parenthetical, ABSTAINS when a line offers two verdicts
# or lines disagree. Inherited from D-CCP-S8-JUDGE-EOL: an earlier reader scored a correct reply
# UNREADABLE because the prompt's own parenthetical followed the verdict token.
_V = re.compile(r"^\s*verdict:\s*(complete|truncated|no_answer|unclear)\b(?P<rest>.*)$", re.I | re.M)
_OTHER = re.compile(r"\b(complete|truncated|no_answer|unclear)\b", re.I)
_MAP = {"complete": COMPLETE, "truncated": TRUNCATED, "no_answer": NO_ANSWER, "unclear": UNDECIDED}


def parse_verdict(text):
    """Return a verdict constant, or None when the reply is unreadable/ambiguous (never a guess)."""
    hits = []
    for m in _V.finditer(text or ""):
        rest = m.group("rest")
        if _OTHER.search(rest) and not re.match(r"\s*\(.*\)\s*$", rest):
            return None                       # a second verdict on the same line -> ambiguous
        hits.append(m.group(1).lower())
    if not hits or len(set(hits)) != 1:
        return None                           # none found, or lines disagree
    return _MAP[hits[0]]


# ---------------------------------------------------------------- layer 2: the call
LOCAL = "http://localhost:8000/v1/chat/completions"
REVIEWER_MODEL = "qwen3.6-35b-gguf"   # owner 2026-08-08, on a measured 2x2 grid:
#   qwen3-8b  + rule-heavy : recall 0.920  specificity 0.962  1 FP   gemini case WRONG
#   qwen3-8b  + minimal    : recall 1.000  specificity 0.308  16 FP  (the 8B has no judgement to
#                            fall back on -- the rules were COMPENSATING for a weak reader)
#   qwen3.6-35b + rule-heavy: recall 1.000 specificity 0.962  0 FP   gemini case RIGHT  <- ADOPTED
#   qwen3.6-35b + minimal  : recall 1.000  specificity 0.808  5 FP
# Codex, blind on 14 of the same items: 13/14, zero false negatives, gemini case RIGHT.
# Stripping the rules made things WORSE on both readers; changing the MODEL fixed them.
# The reviewer emits ONE line. 512 is ~50x the longest valid reply, so it can never be forced to
# choose between thinking and emitting its verdict (prompt-design 5c).
REVIEWER_MAX_TOKENS = 2500   # 35b reasons longer; 1500 left 1/61 replies unreadable. Raised from 512: qwen3-8b emits a <think> block first and 8/60
                             # replies hit finish_reason=length, parsing to a false abstain.


def review(question, response_text, reasoning=None, arm="original", model=REVIEWER_MODEL,
           max_tokens=REVIEWER_MAX_TOKENS, timeout=300, tail=False):
    """Layer 2. Returns (verdict_or_None, raw_reply, finish_reason).

    RAISES on transport failure -- a reviewer that cannot be reached is an UNKNOWN, never an
    abstain. Collapsing "the server is down" into "the reader was unsure" is how 60 failed calls
    once read as 60 clean abstains.
    """
    import urllib.request
    prompt = build_tail_prompt(response_text) if tail else \
        build_prompt(question, response_text, reasoning, arm)
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens, "temperature": 0.0}).encode()
    req = urllib.request.Request(LOCAL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    ch = (d.get("choices") or [{}])[0]
    raw = ((ch.get("message") or {}).get("content")) or ""
    return parse_verdict(raw), raw, ch.get("finish_reason")


def reconcile_layer2(rec, l2_verdict, bench=None):
    """Layer 2 may JUDGE, but it may not CONTRADICT a fact layer 1 established.

    Returns (verdict, note). `note` is non-empty only when the reader was overruled.

    BORN FROM D-OR-6, the paid smoke's only non-clean record. google/gemma-3-27b-it returned
    finish_reason=stop, 554 completion tokens, ~2,300 characters of coherent reasoning, and a
    parsed compliant answer that ENDED the reply. The reader called it TRUNCATED -- most likely
    because the model echoed three lines of the prompt's own instruction block just before the box,
    which makes the tail read as though it were cut off mid-instruction.

    TRUNCATED is not an opinion. It is a claim about two observable facts: the provider said the
    generation stopped, and the text ends on its answer marker. When both hold, "truncated" is
    false regardless of how the tail reads, so the reader's verdict is refused and recorded.

    This does NOT muzzle the reader on anything it is actually for: it may still return NO_ANSWER,
    or leave the record UNDECIDED. It may only not assert a cut-off that the record disproves.
    """
    bench = bench or rec.get("bench") or "futurex"
    if l2_verdict != TRUNCATED:
        return l2_verdict, None
    if rec.get("finish_reason") != "stop":
        return l2_verdict, None
    text = (rec.get("text") or "").rstrip()
    markers = answer_markers(text, bench)
    if not markers:
        return l2_verdict, None
    ends_on_answer = (text.endswith("}") if bench != "btf3"
                      else BF.btf_parse(text)["compliant"])
    if not ends_on_answer:
        return l2_verdict, None
    return COMPLETE, (
        f"layer 2 said TRUNCATED, but finish_reason=stop AND the reply ends on a non-empty answer "
        f"marker ({markers[-1]!r}). A reader may judge, not contradict a fact -- verdict overruled "
        f"to COMPLETE and the disagreement recorded (D-OR-6).")
