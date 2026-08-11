"""Run BTF-3 / FutureX-Past items across the OpenRouter roster. Format compliance is the metric.

PAID SERVICE. Three guards, because a runaway loop here costs money rather than time:
  1. --max-calls is REQUIRED and enforced before the loop starts, not inside it.
  2. Cost is totalled from the usage the API ACTUALLY reports, never from an estimate.
  3. Per-call JSONL append + skip-done-on-relaunch, so a crash never re-buys a completed call.

The metric is COMPLIANCE, not accuracy (owner 2026-08-07). `ground_truth` is carried through untouched
for a later scoring pass; nothing here decides whether an answer is right.
"""
import argparse, collections, hashlib, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "skills", "llm-api"))
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")
import llm_api, bench_formats as BF, completeness_review as CR, response_schema as RS
# M6-T14 (L-W): the runner CALLS the leaves. Before this, 185 tests proved 13 modules that the paid
# path never executed -- the runner carried its own inline resume set, its own spend counter, and a
# naive provider round-robin that schedule.py had already replaced after it put 101 consecutive
# calls on one provider. Tested-but-unwired code buys nothing on the run that spends the money.
import manifest as MF, schedule as SC, persistence as PS, spend as SP


def verify_records(path, planned_models=None):
    """POST-RUN INVARIANT CHECK (Codex C7, BLOCKING-adjacent).

    `planned_models` scopes the check to the CURRENT plan (D-OR-21). A superseded run directory holds
    records for models the manifest no longer plans, and reading them all made a clean stage look
    broken: the 2026-08-10 smoke HALTED naming openai/gpt-5.6-sol, which is not in the roster, over a
    record inherited from the August 8 attempt. Left unscoped, real failures in the current stage
    would sit in a crowd of hundreds of inherited ones. Passing None checks everything, which is
    correct for a directory that was never superseded.

    The structural boundary stops the RUNNER creating a forbidden record, but it says nothing about
    serialization, a later migration, or an analysis script writing one. This re-reads what actually
    landed on disk and FAILS LOUD, so the premise is checked against the artifact rather than
    against the intention that produced it.
    """
    bad_compliance, complete_without_answer, missing_verdict = [], [], []
    n, skipped = 0, 0
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        if planned_models is not None and r.get("model") not in planned_models:
            skipped += 1                    # a superseded plan's record; not this stage to answer for
            continue
        n += 1
        v = r.get("completeness")
        if v is None:
            missing_verdict.append(r.get("item_id"))
        if r.get("compliant") is not None and v not in CR.SCOREABLE:
            bad_compliance.append((r.get("model"), r.get("item_id"), r.get("arm"), v))
        if v == CR.NO_ANSWER and r.get("compliant") is not False:
            bad_compliance.append((r.get("model"), r.get("item_id"), r.get("arm"),
                                   f"NO_ANSWER must score compliant=False, got {r.get('compliant')!r}"))
        if v == CR.COMPLETE and not r.get("answer_extractable"):
            complete_without_answer.append((r.get("model"), r.get("item_id"), r.get("arm")))
    problems = []
    if missing_verdict:
        problems.append(f"{len(missing_verdict)} record(s) carry NO completeness verdict")
    if bad_compliance:
        problems.append(f"{len(bad_compliance)} record(s) violate PREMISE-COMPLIANCE-ONLY-WHEN-OBSERVED "
                        f"(compliance recorded on an unobserved call, or a NO_ANSWER not scored as "
                        f"non-compliant): {bad_compliance[:3]}")
    if complete_without_answer:
        problems.append(f"{len(complete_without_answer)} record(s) are COMPLETE with no extractable "
                        f"answer: {complete_without_answer[:3]}")
    if problems:
        raise SystemExit("HALT: post-run invariant check FAILED over " + str(n) + " in-plan records"
                         + (f" ({skipped} out-of-plan record(s) from a superseded plan were not "
                            f"checked here)" if skipped else "")
                         + "\n  - " + "\n  - ".join(problems))
    print(f"  post-run invariant check OK over {n} in-plan records "
          f"(every record has a verdict; compliance only on COMPLETE; COMPLETE implies an answer)"
          + (f"; {skipped} out-of-plan record(s) from a superseded plan skipped" if skipped else ""))


def cost_of(raw, model_row):
    u = (raw or {}).get("usage") or {}
    pi = (u.get("prompt_tokens") or 0) / 1e6 * model_row["in"]
    po = (u.get("completion_tokens") or 0) / 1e6 * model_row["out"]
    return pi + po, u


# ERROR CLASSIFICATION, from OpenRouter's documented error contract (docs/api-reference/errors),
# not from substring-matching a human-readable message. Every failure is classified into exactly one
# of these and the classification is RECORDED on the record, so a run's failures are auditable
# rather than a bag of strings.
#
#   retryable   429 rate_limit_exceeded (honour Retry-After) | 503 provider_overloaded
#               | 504 timeout | 500 server | 502 provider_unavailable
#   permanent   400 invalid_request / content_policy_violation / refusal | 401 authentication
#               | 402 payment_required | 403 permission_denied | 404 | 413 | 422
#   transport   client-side: the request never completed cleanly (dropped socket, reset, or a body
#               that ended mid-JSON). ALWAYS retryable -- a truncated body is not a result.
#               Born 2026-08-08: a JSONDecodeError at char 14388 was NOT retried, then the empty
#               text was handed to the LLM reader, which shrugged "unclear" and the transport
#               failure was recorded as UNDECIDED. A network error wearing a verdict's clothes.
# ACCOUNT-LEVEL faults are RUN-FATAL, not model-level (D-OR-16, hit live 2026-08-08).
# The org monthly budget was exhausted mid-run and OpenRouter returned HTTP 403 to EVERY model.
# The per-model quarantine then fired 22 times, and the quarantine manifest recorded 22 models as
# quarantined when not one of them had done anything wrong -- the account had simply run out of
# money. A fault that affects every model equally is a property of the RUN, and attributing it to
# models corrupts the record and would have censored 2,400 units against innocent models.
# These halt the run immediately so it can be resumed after the account is fixed, with nothing
# mislabelled and nothing re-bought.
# AN OBSERVATION, NOT A BARRIER (M6-T22, owner 2026-08-10: "for practice, we should see if a model go
# beyond 12k which is already quite suspecious. no hard cap"). A completion past this is flagged and
# counted so a reader can look at it. It never halts, quarantines, truncates, retries, or changes a
# verdict -- a long answer is a thing to examine, not a failure. Measured on the 872 records of the
# halted run: 9 exceed it (1.0%), worst 61,528; three of those models are in the current roster.
SUSPICIOUS_COMPLETION_TOKENS = 12000

# D-OR-23. A model's OUTPUT ceiling and its CONTEXT window are different numbers, and for some models
# they are EQUAL -- kimi-k2.5 and kimi-k2.6 both publish max_completion_tokens = context_length =
# 262,144. Requesting the whole ceiling then leaves no room for the prompt and the provider returns
# 400 ("you requested about 262465 tokens (321 of text input, 262144 in the output)"). The published
# ceiling is the maximum output for an EMPTY prompt. This is NOT a reinstated invented cap: it is the
# arithmetic the provider itself enforces, and it only ever lowers a request that could not have been
# served. Tokens are estimated from characters, deliberately generously.
CONTEXT_SAFETY_MARGIN = 512


def fits_in_context(ceiling, context, prompt):
    """The largest output that can actually be served alongside this prompt."""
    if not ceiling or not context:
        return ceiling
    est_prompt = len(prompt) // 3 + 1          # over-estimates for English; erring large is safe here
    return max(1, min(ceiling, context - est_prompt - CONTEXT_SAFETY_MARGIN))

# ---- M6-T23/S2: ONE CLASSIFIER, THREE OUTCOMES -------------------------------------------------
# Replaces four overlapping sets (RETRYABLE_STATUS / PERMANENT_STATUS / RETRYABLE_ERROR_TYPES /
# ACCOUNT_FATAL_STATUS, in which 403 appeared twice and which were read by different code paths).
#
#   TRANSIENT         waiting could plausibly fix it        -> retry, then pause the MODEL
#   TERMINAL_ACCOUNT  the account cannot pay or authenticate -> HALT THE RUN
#   TERMINAL_REQUEST  this request will never be accepted    -> pause the MODEL, needs a human
#
# Codex C5: a 429 is NOT uniformly transient. Rate-limited-with-Retry-After clears by waiting;
# quota/budget/credit exhausted does not. The live 403 arrived as a MESSAGE STRING inside the body
# ("Org member budget limit exceeded"), not as a distinct status -- so the classifier reads the
# message and headers, not the status alone.
TRANSIENT, TERMINAL_ACCOUNT, TERMINAL_REQUEST = "TRANSIENT", "TERMINAL_ACCOUNT", "TERMINAL_REQUEST"

# Wording that means "you have run out", wherever it appears (403 body, 429 body, provider_code).
_EXHAUSTED = re.compile(r"budget|quota|credit|insufficient|spend|billing|payment|exceeded", re.I)

ACCOUNT_FATAL_STATUS = {401, 402, 403}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
PERMANENT_STATUS = {400, 401, 402, 403, 404, 405, 412, 413, 422}
RETRYABLE_ERROR_TYPES = {"rate_limit_exceeded", "provider_overloaded", "timeout", "server",
                         "provider_unavailable", "unmapped"}


def classify_fault(e):
    """Return (policy, klass) where policy is TRANSIENT | TERMINAL_ACCOUNT | TERMINAL_REQUEST.

    ONE place decides; every caller reads this and nothing re-derives it. The question it answers is
    the owner's: *is it purely lagging?* -- not "which HTTP bucket is this".

    Codex C8, the boundary that would otherwise rebuild the original category error inside this
    function: a PROTOCOL parse failure (non-JSON, truncated transport, HTML error page) is a
    TRANSIENT infrastructure fault. An ANSWER parse failure -- a valid response whose answer text
    will not parse -- is MODEL BEHAVIOUR and never reaches here at all; it is a result.
    """
    st = getattr(e, "status", None)
    et = getattr(e, "error_type", None)
    body = f"{getattr(e, 'provider_code', '') or ''} {e}"

    # Transport: the request did not complete. Always plausibly self-correcting.
    if getattr(e, "transport", False):
        return TRANSIENT, f"transport:{getattr(e, 'transport_kind', 'unknown')}"

    # The account itself. 401 auth, 402 payment, 403 forbidden-or-budget. Also a 429 whose text says
    # the allowance is GONE rather than momentarily exceeded -- waiting will not restore it.
    if st in ACCOUNT_FATAL_STATUS:
        return TERMINAL_ACCOUNT, f"account:{st}"
    if st == 429 and _EXHAUSTED.search(body) and getattr(e, "retry_after", None) is None:
        return TERMINAL_ACCOUNT, "account:429-exhausted"

    # A request this endpoint will never accept as written. Fixable, but by a human or a code
    # change, never by waiting (Codex C7) -- so it must not be retried and must not halt the account.
    if st in (400, 404, 405, 412, 413, 422):
        return TERMINAL_REQUEST, f"request:{et or st}"

    # Everything else that is a server-side or throttling condition: wait and try again.
    if st in RETRYABLE_STATUS or (isinstance(et, str) and et in RETRYABLE_ERROR_TYPES):
        return TRANSIENT, f"api:{et or st}"

    # Unknown. Treated as TRANSIENT so a retry can settle it, but named so it is visible -- an
    # unrecognised fault silently classified TERMINAL would stop a run for no stated reason.
    return TRANSIENT, f"api:unclassified:{et or st or type(e).__name__}"


def classify_error(e):
    """Back-compat shim: (retryable, klass). Retained because tests and the trace still read it."""
    policy, klass = classify_fault(e)
    return policy == TRANSIENT, klass

# DETECTION BUDGET, not a generosity budget. A healthy call here finishes in seconds (p95 completion
# ~7,300 tokens), so exceeding this is a SIGNAL. The library default of 600s x 6 escalation attempts
# let one glm-4.6 unit consume ~an hour in silence: the failure was real on the first attempt and
# only visible after the last.
#
# HONEST LIMIT: urllib's `timeout` is PER SOCKET OPERATION, not total elapsed. A slowly-streaming
# response keeps resetting it, so this does NOT bound wall-clock per call -- measured: a call made
# with timeout=60 ran 210s. MAX_ESCALATIONS is therefore the load-bearing brake (3 attempts instead
# of 6, roughly halving the worst case). A true wall-clock bound needs a future-level timeout and is
# NOT implemented; do not read CALL_TIMEOUT as a guarantee.
CALL_TIMEOUT = 120
# The TRUE bound. CALL_TIMEOUT is per-socket-read and does not limit elapsed time; this does.
# Generous relative to a healthy call (p95 completion ~7,300 tokens) so it fires only on a hang.
WALL_CLOCK = 300
MAX_ESCALATIONS = 3
# PER-UNIT ELAPSED BUDGET (Codex C3, BLOCKING). WALL_CLOCK bounds a single ATTEMPT; a failed attempt
# is RETRIED, and escalation adds more, so attempts STACK. Measured on the gate stages: one
# minimax call consumed 840s and one glm-4.7 call 1,333s while 221 other units sat finished. Four to
# five calls in 222 exceed 300s every time, and they -- not throughput -- set the run's wall clock.
# Extrapolated to 8,140 units that is roughly 12 hours, almost all of it a handful of stuck calls.
#
# This caps the TOTAL elapsed time one unit may consume across every attempt and escalation. On
# exhaustion the unit stops being retried and is recorded TRANSPORT_ERROR with gave_up_because=
# unit_deadline -- an honest UNOBSERVED unit, which the census and the quarantine/rerun path already
# handle, rather than a silent 22-minute stall.
UNIT_WALL_CLOCK = 900


def _call_with_wallclock_bound(prompt, model, budget, reasoning, timeout, wall):
    """A TRUE wall-clock bound, which urllib's `timeout` is not.

    urllib's timeout is PER SOCKET OPERATION: a slowly-streaming response keeps resetting it, so a
    call made with timeout=60 was MEASURED at 210s. Running the call in a worker and abandoning the
    wait after `wall` seconds bounds the elapsed time for real.

    HONEST LIMIT, stated rather than implied: abandoning the wait does not cancel the HTTP request --
    Python cannot kill a blocked socket read from outside. The thread may run on (daemon, so it
    cannot hold the process open) and the provider may still bill for the generation. What this
    bounds is OUR WAIT, not their work. That is the difference between a run that finishes and one
    that hangs for an hour, which is the failure it exists to prevent.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(llm_api.openrouter_chat, prompt, model,
                    max_tokens=budget, reasoning=reasoning, timeout=timeout)
    try:
        return fut.result(timeout=wall)
    except FTimeout:
        err = llm_api.LlmError(
            f"wall-clock bound of {wall}s exceeded for {model} (the socket timeout is per-read and "
            f"does not bound total elapsed time)")
        err.status = err.error_type = err.provider_code = err.retry_after = None
        err.ratelimit = {}
        err.transport = True
        err.transport_kind = "WallClockExceeded"
        raise err
    finally:
        ex.shutdown(wait=False)


class UnitDeadlineExceeded(RuntimeError):
    """The unit consumed its total elapsed budget across attempts. Recorded, never retried past."""


def _chat_with_backoff(prompt, model, budget, reasoning, trace, tries=3, timeout=CALL_TIMEOUT,
                       wall=None, deadline=None):
    """Retry a THROTTLED or transient call instead of losing it. THREE attempts (owner 2026-08-10:
    "retry 3 times, if still failed halt") -- was 5, which is retry budget spent on a fault that has
    already told us twice it is not clearing.

    Concurrency is spread across providers, but a burst can still hit an upstream vendor's own
    rate limit. A 429 is not a result -- dropping it would silently shrink the sample for exactly
    the busiest providers, biasing the run toward whoever answers first.
    """
    delay = 2.0
    for attempt in range(tries):
        if deadline is not None and time.time() >= deadline:
            raise UnitDeadlineExceeded(
                f"unit exceeded its {UNIT_WALL_CLOCK}s total budget after {attempt} attempt(s); "
                f"refusing to retry further")
        # Never let one attempt run past the unit's own deadline either.
        room = None if deadline is None else max(1.0, deadline - time.time())
        this_wall = min(wall or WALL_CLOCK, room) if room is not None else (wall or WALL_CLOCK)
        try:
            return _call_with_wallclock_bound(prompt, model, budget, reasoning, timeout, this_wall)
        except llm_api.LlmTruncated:
            raise                                    # a real outcome; the caller escalates the budget
        except UnitDeadlineExceeded:
            raise
        except Exception as e:
            retryable, klass = classify_error(e)
            last = attempt == tries - 1
            if not retryable or last:
                # Record the classification ON the exception so the runner logs WHY it gave up,
                # not just that it did.
                e.failure_class = klass
                e.attempts_made = attempt + 1
                e.gave_up_because = "retries_exhausted" if (retryable and last) else "permanent"
                raise
            # Honour Retry-After when the server sends it -- the docs say to, and a served value
            # beats a guessed one. Fall back to exponential backoff only when it is absent.
            wait = getattr(e, "retry_after", None) or delay
            if deadline is not None and time.time() + wait >= deadline:
                e.failure_class = klass
                e.attempts_made = attempt + 1
                e.gave_up_because = "unit_deadline"
                raise
            trace.append({"budget": budget, "outcome": "retry", "attempt": attempt + 1,
                          "failure_class": klass, "status": getattr(e, "status", None),
                          "error_type": getattr(e, "error_type", None),
                          "provider_code": getattr(e, "provider_code", None),
                          "detail": str(e)[:160], "sleep": wait,
                          "from_header": getattr(e, "retry_after", None) is not None,
                          "ratelimit": getattr(e, "ratelimit", {})})
            time.sleep(wait)
            delay *= 2


def call_with_escalation(prompt, mr, start_tokens, cap, reasoning=None, deadline=None):
    """Double the token budget until the answer is not truncated, bounded by the model's own ceiling.

    Reasoning tokens are billed as completion tokens and count against max_tokens, so a reasoning
    model can burn the whole budget and return NOTHING visible. Both outcomes -- an explicit
    finish_reason=length and a silent empty completion -- are TRUNCATION, and both escalate.

    Returns (text, raw, spent, trace) where trace records every attempt, so any correlation between
    the budget a call ended up with and its content is auditable afterwards rather than invisible.
    A call that is still truncated AT the model's ceiling returns text=None -- reported as
    BUDGET_CAPPED, never scored as a wrong or non-compliant answer.
    """
    budget, spent, trace = start_tokens, 0.0, []
    attempts = 0
    # The unit's TOTAL elapsed budget spans escalations too, not just retries within one attempt.
    deadline = deadline if deadline is not None else (time.time() + UNIT_WALL_CLOCK)
    while True:
        # A HANG IS ITS OWN OUTCOME, DETECTED IN SECONDS -- NOT AFTER AN HOUR (owner 2026-08-08).
        # The library default is a 600s per-call timeout, and escalation can make SIX attempts, so
        # one unit could occupy an hour with no signal. glm-4.6 did exactly that: it returned empty
        # at 16k, 32k, 64k, 128k and twice at 131072, burning the whole ceiling silently.
        # Two brakes: a short per-call timeout, and a cap on escalation attempts.
        if attempts >= MAX_ESCALATIONS:
            trace.append({"budget": budget, "outcome": "escalation_exhausted",
                          "detail": f"{attempts} attempts without a usable reply -- stopping rather "
                                    f"than climbing to the ceiling"})
            return None, None, spent, trace
        attempts += 1
        try:
            txt, raw = _chat_with_backoff(prompt, mr["id"], budget, reasoning, trace,
                                          timeout=CALL_TIMEOUT, deadline=deadline)
            c, u = cost_of(raw, mr)
            spent += c
            empty = not (txt or "").strip()
            trace.append({"budget": budget, "completion_tokens": u.get("completion_tokens"),
                          "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                          "chars": len(txt or ""), "outcome": "empty" if empty else "ok"})
            if not empty:
                return txt, raw, spent, trace
            reason = "empty completion"
        except llm_api.LlmTruncated as e:
            trace.append({"budget": budget, "outcome": "truncated", "detail": str(e)[:160]})
            spent += 0.0  # a truncated call still bills, but usage is not returned on this path
            reason = "finish_reason=length"
        # NO CEILING TO CLIMB TO (M6-T22). budget is None when the model publishes no completion
        # limit, so we asked with none and the provider applied its own default. There is nothing to
        # double and nothing to escalate against: a truncation here is the PROVIDER's default doing
        # the truncating, which is a finding about the provider, not a budget we chose too small.
        if budget is None or cap is None:
            trace.append({"budget": None, "outcome": "capped",
                          "detail": f"still truncated ({reason}) with NO max_tokens requested -- the "
                                    f"provider's own default bounded this, not a budget we set"})
            return None, None, spent, trace
        if budget >= cap:
            trace.append({"budget": budget, "outcome": "capped",
                          "detail": f"still truncated ({reason}) at the model ceiling {cap}"})
            return None, None, spent, trace
        budget = min(budget * 2, cap)


def AN_render(table_path, top=15):
    import analyze as AN
    return AN.render(json.load(open(table_path)), top=top)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--bench", required=True, choices=["futurex", "btf3"])
    ap.add_argument("--arms", default="original",
                    help="SINGLE ARM by default (owner 2026-08-08): the CoT arm was dropped on "
                         "measured grounds -- 294/312 original-arm replies already contain "
                         "reasoning. The default said 'original,cot' for hours after the design "
                         "said otherwise, and a concurrency fixture caught it by producing 36 "
                         "records where 18 were planned.")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--max-calls", type=int, required=True,
                    help="HARD ceiling, checked before the loop. A paid run gets an explicit budget.")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="OPT-IN OVERRIDE, off by default (owner 2026-08-10: 'there is no cap, which "
                         "is your hallucination. the fix cap is the model's own max_token... do not "
                         "trap by the non-sense barrier'). Left unset, each model is asked for its "
                         "own PUBLISHED ceiling, and a model that publishes none is asked with no "
                         "limit at all. Set this only to run a deliberate budget experiment; it then "
                         "applies to every model and IS part of the condition.")
    ap.add_argument("--max-spend", type=float, required=True,
                    help="HARD dollar ceiling. Required because budget escalation makes a call-count "
                         "cap insufficient to bound cost.")
    # The owner's 25-model list of 2026-08-09 supersedes roster_refined.json (37 models), which the
    # halted or_futurex_fxgate run was frozen against. The default moves with it: leaving it on the
    # superseded roster would make the NEXT run quietly buy the old list. Resuming a run frozen
    # against the old roster now trips the manifest guard, which is the intended behaviour -- use a
    # new --tag, or pass --models survey/roster_refined.json to continue the old experiment.
    ap.add_argument("--models", default=os.path.join(HERE, "survey", "roster_25.json"))
    ap.add_argument("--caps", default=os.path.join(HERE, "survey", "model_caps.json"))
    ap.add_argument("--supersede-manifest", default=None, metavar="REASON",
                    help="DECLARE that the plan moved (a roster or item change) and re-freeze THIS "
                         "run directory, keeping every call already answered by a model still in "
                         "the plan and buying only what is missing. Without it a changed roster "
                         "still HALTs. The reason is written into the manifest lineage.")
    ap.add_argument("--only-items", default=None,
                    help="STAGED RUN (owner 2026-08-08: the smoke is absorbed into the full test, "
                         "so it costs nothing extra). Freeze the manifest over ALL items, then run "
                         "only this subset as the gated first stage. The full stage later reuses "
                         "the SAME manifest and resume skips every unit already bought.")
    ap.add_argument("--only-units", default=None,
                    help="Restrict this stage to an explicit list of {model,item_id} pairs. Needed "
                         "for a PAIRED re-run: the units that failed are scattered (model,item) "
                         "cells, not a clean cross product, so --only-items cannot express them.")
    ap.add_argument("--require-cleared", action="store_true",
                    help="Refuse to start unless this run dir's smoke_acceptance.json says cleared. "
                         "This is what makes the gate a gate rather than a report.")
    ap.add_argument("--per-provider", type=int, default=4,
                    help="Max concurrent calls to ONE upstream provider. ENFORCED by a semaphore, "
                         "not merely recorded: the account has no rate limit but each vendor does, "
                         "and without this the global worker count is the only real bound, so N "
                         "workers can still land on one vendor at once. Frozen into the schedule.")
    ap.add_argument("--workers", type=int, default=16,
                    help="Concurrent in-flight calls. These are network-bound waits, so a sequential "
                         "loop idles ~83s per call: 7,200 calls would take 166 hours at --workers 1.")
    ap.add_argument("--mode", choices=["smoke", "real"], required=True,
                    help="smoke: an error HALTS the run, because an error means the METHOD is wrong "
                         "and is fixed here. real: an error QUARANTINES that model -- its remaining "
                         "units are skipped, every other model finishes, and the manifest lists what "
                         "to re-run once the method is fixed in smoke. (owner ruling 2026-08-08)")
    ap.add_argument("--no-review", dest="review", action="store_false",
                    help="Deterministic layer only, even in smoke. Records layer 1 cannot settle "
                         "stay UNDECIDED and carry NO compliance value.")
    ap.add_argument("--review", action="store_true", default=True,
                    help="SMOKE ONLY: run the LLM reader on every unit. The real run never validates "
                         "live -- the smoke is the harness. (owner ruling 2026-08-08)")
    ap.add_argument("--quarantine-after", type=int, default=1,
                    help="Consecutive non-COMPLETE verdicts from one model before it is quarantined "
                         "in real mode. Default 1: an error is a method defect, not bad luck.")
    a = ap.parse_args()

    roster = json.load(open(a.models))
    # THE ROSTER CARRIES ITS OWN CEILINGS (M6-T19). They are derived per model by
    # survey/roster_build.py from the catalog, or declared in its overrides with a reason -- so a new
    # model needs no edit to any file that lists models by name. `--caps` remains as a legacy
    # side-file for a roster built before this, and is consulted only for a model whose row has none.
    caps = json.load(open(a.caps)) if a.caps and os.path.exists(a.caps) else {}
    caps = {m["id"]: (m.get("cap") or caps.get(m["id"])) for m in roster}
    nocap = [mid for mid, c in caps.items() if not c]
    if nocap:
        raise SystemExit(f"HALT: no output ceiling for {nocap}. Escalation needs a real limit per "
                         f"model; refusing to invent one. Rebuild the roster with "
                         f"survey/roster_build.py, which derives a ceiling or refuses to emit the row.")
    # M6-T22: which of those numbers is a REAL output ceiling. A row whose cap came from
    # `context_length` has a reporting number, not a limit the model will honour, and nothing may be
    # requested from it. A legacy roster with no cap_basis is treated as real, which is what it
    # meant before the field existed.
    cap_is_real = {m["id"]: m.get("cap_basis", "max_completion_tokens") != "context_length"
                   for m in roster}
    ctx_by_model = {m["id"]: m.get("context") for m in roster}
    squeezed = [m["id"] for m in roster
                if cap_is_real[m["id"]] and m.get("context") and m["cap"] >= m["context"]]
    if squeezed:
        print(f"  CEILING EQUALS THE CONTEXT WINDOW for {len(squeezed)} model(s) — the request is "
              f"lowered to leave room for the prompt, or the provider returns 400 (D-OR-23): "
              f"{squeezed}")
    unbounded = sorted(mid for mid, ok in cap_is_real.items() if not ok)
    if unbounded:
        print(f"  NO PUBLISHED OUTPUT CEILING for {len(unbounded)} model(s) — they will be called "
              f"with NO max_tokens, so the provider's own default applies. Their roster `cap` is a "
              f"context window and is deliberately not used as a request limit: {unbounded}")
    items = json.load(open(a.items))
    arms = a.arms.split(",")
    planned = len(roster) * len(items) * len(arms)
    # NOTE: the --max-calls ceiling is enforced AFTER staging and resume, against the units this
    # invocation will ACTUALLY buy -- see the check below the work list. Checking the whole manifest
    # here would make a staged run impossible to cap: a 6-item gate stage out of a 110-item plan
    # would have to declare --max-calls 4070 to buy 222 calls, which is the opposite of a ceiling.
    print(f"  plan: {len(roster)} models x {len(items)} items x {len(arms)} arm(s) = {planned:,} units")

    out = os.path.join(HERE, "runs", f"or_{a.bench}_{a.tag}")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "records.jsonl")

    # ---- FREEZE THE PLAN (M6-T3) ---------------------------------------------------------------
    # MF.build validates the item corpus first (a leaked answer or a missing format marker HALTS
    # here, before any money is spent) and stamps every unit with the sha of the prompt it WILL
    # send, which is what makes misassociation detectable afterwards.
    mani = MF.build(roster, items, arms=tuple(arms), bench=a.bench)
    # The run dir keeps its OWN copy of the item corpus. Without it, nothing downstream can check
    # whether an answer was INTERPRETABLE, because that question needs the question text.
    ipath = os.path.join(out, "items.json")
    if not os.path.exists(ipath):
        json.dump(items, open(ipath, "w"), indent=1)
    mpath_manifest = os.path.join(out, "manifest.json")
    superseded_from = None
    if os.path.exists(mpath_manifest):
        prior = json.load(open(mpath_manifest))
        if prior["manifest_id"] != mani["manifest_id"]:
            if not a.supersede_manifest:
                raise SystemExit(
                    f"HALT: this run directory was frozen against manifest {prior['manifest_id']} "
                    f"but the current roster/items/arms produce {mani['manifest_id']}. Resuming "
                    f"would mix two different planned experiments in one records file. Either use "
                    f"a new --tag, or DECLARE the change with "
                    f"--supersede-manifest '<why the plan moved>' -- which re-freezes this "
                    f"directory, keeps every call already answered by a model still in the plan, "
                    f"and buys only what is missing.")
            # A DECLARED change re-freezes in place. manifest.py's policy from day one: write-once
            # with a lineage, not immutable. The prior manifest is archived, never overwritten away.
            mani = MF.supersede(prior, roster, items, arms=tuple(arms), bench=a.bench,
                                reason=a.supersede_manifest)
            superseded_from = prior["manifest_id"]
            with open(os.path.join(out, "manifest.history.jsonl"), "a") as fh:
                fh.write(json.dumps(prior) + "\n")
            MF.save(mani, mpath_manifest, replacing=superseded_from)
            print(f"  MANIFEST SUPERSEDED {superseded_from} -> {mani['manifest_id']}: "
                  f"{a.supersede_manifest}")
            print(f"    planned {prior['n_units']:,} -> {mani['n_units']:,} units "
                  f"({prior['n_models']} -> {mani['n_models']} models); prior archived to "
                  f"manifest.history.jsonl")
    else:
        MF.save(mani, mpath_manifest)

    # ---- RESUME (M6-T7) ------------------------------------------------------------------------
    # PS.resume_state is STRICT: a record that is not in the manifest, or a duplicate unit, raises
    # rather than being counted as done. The old inline version swallowed every malformed line with
    # `except Exception: pass`, so a corrupt record silently became work-to-redo.
    prior_records = []
    if os.path.exists(path):
        prior_records = [json.loads(l) for l in open(path) if l.strip()]
    PS.assert_resume_key_matches_manifest(mani)   # the resume key and the manifest key must agree
    # After a DECLARED supersession the stored file legitimately contains records for units the new
    # plan does not plan (a dropped model). Strict resume would refuse them -- correctly, when the
    # change was never declared. Here it was, so they are partitioned out and REPORTED rather than
    # either raising or being quietly absorbed into a denominator they were not planned under.
    if superseded_from:
        part = PS.partition_by_manifest(mani, prior_records)
        if part["misassociated"]:
            raise SystemExit(
                f"HALT: {len(part['misassociated'])} stored record(s) are planned units whose stored "
                f"prompt is NOT the planned prompt. A supersession does not excuse a misassociated "
                f"record -- the per-record proof is independent of the roster.")
        print(f"    records: {len(part['in_plan_answered']):,} answered and kept, "
              f"{len(part['in_plan_unanswered']):,} re-queued (a row exists but no output came "
              f"back), {len(part['out_of_plan']):,} retained OUT-OF-PLAN and excluded from every "
              f"rate (they belong to the superseded plan)")
        rs = PS.resume_state(mani, prior_records, strict=False)
    else:
        rs = PS.resume_state(mani, prior_records)
    if rs["requeued_undelivered"]:
        # D-OR-18. Loud, because the previous behaviour was to count these as done and move on.
        print(f"  D-OR-18: {len(rs['requeued_undelivered']):,} unit(s) have a stored row but the "
              f"model was never heard from (provider/transport/empty-HTTP). They are TODO, not done.")
    done_uids = {u["unit_id"] for u in mani["units"]} - set(rs["todo"])
    print(f"  OUTPUT {out}   manifest {mani['manifest_id']}   planned {mani['n_units']:,} units   "
          f"resumed {len(done_uids):,}   cap {a.max_calls:,}")

    # ---- DISPATCH ORDER (M6-T4) ----------------------------------------------------------------
    # EVEN-SPREAD, not naive round-robin. Round-robin only balances while every queue is non-empty;
    # on the real 3,700-unit manifest it produced a 101-call single-provider burst, and the 4-item
    # smoke fixture showed 12 and passed. resume_order replays the SAME order minus what is done,
    # which is what makes a resumed run comparable to an uninterrupted one.
    sched = SC.build(mani, global_workers=a.workers, per_provider=a.per_provider)
    spath = os.path.join(out, "schedule.json")
    if os.path.exists(spath):
        # WRITE-ONCE, like the manifest. On resume the schedule must be the SAME one, or the run
        # would replay a different order and stop being comparable to the interrupted attempt.
        prior_s = json.load(open(spath))
        # schedule_id hashes only (policy_version, manifest_id, seed, order) -- NOT the concurrency
        # policy (Codex C5). Comparing ids alone would let a resumed run change global_workers or
        # per_provider silently, which changes the load the providers actually see.
        pol = {k: (prior_s.get(k), sched.get(k)) for k in ("policy_version", "global_workers",
                                                           "per_provider")
               if prior_s.get(k) != sched.get(k)}
        if pol:
            raise SystemExit(f"HALT: the dispatch POLICY changed on resume: {pol}. The schedule id "
                             f"does not cover concurrency, so this would silently alter the load "
                             f"placed on each provider. Use a new --tag.")
        if prior_s["schedule_id"] != sched["schedule_id"]:
            # The schedule is DERIVED from the manifest (its id hashes manifest_id), so a declared
            # supersession necessarily rebuilds it. That is not the drift this guard is for: the
            # guard exists to stop an order silently changing while the PLAN stayed the same. When
            # the plan itself was declared to have moved, the order must follow it -- there is no
            # order over units that are no longer planned. The policy check above still applies, so
            # concurrency cannot ride in on the back of a roster change.
            if not superseded_from:
                raise SystemExit(
                    f"HALT: this run dispatched under schedule {prior_s['schedule_id']} but the "
                    f"current settings rebuild it as {sched['schedule_id']}. Resuming would replay "
                    f"a different order. Use a new --tag, or declare a plan change with "
                    f"--supersede-manifest.")
            with open(os.path.join(out, "schedule.history.jsonl"), "a") as fh:
                fh.write(json.dumps(prior_s) + "\n")
            SC.save(sched, spath, replacing=prior_s["schedule_id"])
            print(f"    schedule rebuilt {prior_s['schedule_id']} -> {sched['schedule_id']} over the "
                  f"superseded plan; prior archived to schedule.history.jsonl")
        else:
            sched = prior_s
    else:
        SC.save(sched, spath)
    todo_uids = SC.resume_order(sched, done_uids)
    stage_ids = set()
    if a.only_units:
        want = json.load(open(a.only_units))
        pairs = {(u["model"], u["item_id"]) for u in want}
        by_uid_pair = {u["unit_id"]: (u["model"], u["item_id"]) for u in mani["units"]}
        stray = pairs - set(by_uid_pair.values())
        if stray:
            raise SystemExit(f"HALT: --only-units names {len(stray)} (model,item) pair(s) not in the "
                             f"frozen manifest: {sorted(stray)[:3]}")
        todo_uids = [u for u in todo_uids if by_uid_pair[u] in pairs]
        print(f"  STAGE: restricted to {len(pairs)} explicit unit(s) ({len(todo_uids)} still to buy). "
              f"The manifest still covers all {mani['n_units']}.")
    if a.only_items:
        stage_ids = {i["item_id"] for i in json.load(open(a.only_items))}
        planned_ids = {u["item_id"] for u in mani["units"]}
        stray = stage_ids - planned_ids
        if stray:
            raise SystemExit(f"HALT: --only-items names {len(stray)} item(s) not in the frozen "
                             f"manifest, so this stage is not a subset of the plan: "
                             f"{sorted(stray)[:3]}")
        by_uid_item = {u["unit_id"]: u["item_id"] for u in mani["units"]}
        todo_uids = [u for u in todo_uids if by_uid_item[u] in stage_ids]
        print(f"  STAGE: restricted to {len(stage_ids)} of {mani['n_items']} items "
              f"({len(todo_uids)} units). The manifest still covers all "
              f"{mani['n_units']} — the rest resume later with nothing re-bought.")
    by_uid = {MF.unit_id(mr["id"], it["item_id"], arm): (mr, it, arm)
              for mr in roster for it in items for arm in arms}
    work = [by_uid[u] for u in todo_uids]
    print(f"  dispatch {sched['schedule_id']}: {len(work):,} units, "
          f"max consecutive single-provider run {SC.max_provider_run(sched, mani)} "
          f"across {len(sched['providers'])} providers")

    # THE CEILING, enforced on what THIS invocation will buy: after the stage restriction and after
    # resume has removed everything already paid for. A paid loop does not get to decide its budget.
    if len(work) > a.max_calls:
        raise SystemExit(
            f"HALT: this invocation would make {len(work):,} calls but --max-calls is "
            f"{a.max_calls:,}. (The frozen plan is {mani['n_units']:,} units; {len(done_uids):,} are "
            f"already bought"
            + (f"; this stage is restricted to {len(stage_ids)} item(s)" if a.only_items else "")
            + ".) Raise it deliberately or narrow the run.")

    # ---- THE GATE (owner 2026-08-08) -----------------------------------------------------------
    # The staged design only protects anything if the second stage CANNOT start until the first has
    # been judged. A printed warning would not be a gate.
    if a.require_cleared:
        gpath = os.path.join(out, "smoke_acceptance.json")
        if not os.path.exists(gpath):
            raise SystemExit(
                f"HALT: --require-cleared but {gpath} does not exist. Run the smoke stage, then "
                f"`python3 smoke_acceptance.py {out}`, before buying the remainder.")
        rep = json.load(open(gpath))
        if not rep.get("cleared"):
            fails = [r["id"] for r in rep.get("results", []) if r["verdict"] != "PASS"]
            raise SystemExit(
                f"HALT: the smoke stage did NOT clear ({rep.get('n_fail')} failed, "
                f"{rep.get('n_unknown')} unevaluated; {fails}). Refusing to buy the remaining units "
                f"on a method that has not passed its own gate. Fix, re-run the smoke stage, "
                f"re-evaluate.")
        print(f"  gate: smoke stage CLEARED ({rep['n_pass']} criteria) — proceeding")

    # ---- SPEND (M6-T9) -------------------------------------------------------------------------
    # The ceiling is enforced on ACTUAL reported spend, never on a max_tokens estimate: five
    # providers exceed max_tokens outright, worst observed 24.6x. The ledger is keyed on the SAME
    # attempt identity as the records, so a resumed run cannot pay twice for one attempt.
    ledger_path = os.path.join(out, "ledger.json")
    ledger_journal = os.path.join(out, "ledger.jsonl")
    if os.path.exists(ledger_path):
        # Compare the ceiling ON DISK against the flag BEFORE loading: passing ceiling=a.max_spend
        # into load() overrides the stored value, which would make the mismatch check below compare
        # the flag against itself and always pass.
        stored_ceiling = json.load(open(ledger_path)).get("ceiling")
        if stored_ceiling is not None and abs(stored_ceiling - a.max_spend) > 1e-9:
            raise SystemExit(f"HALT: the ledger on disk has ceiling ${stored_ceiling:.2f} but "
                             f"--max-spend is ${a.max_spend:.2f}. Refusing to silently re-scope a "
                             f"paid run's budget.")
    if os.path.exists(ledger_path) or os.path.exists(ledger_journal):
        # The JOURNAL WINS (Codex C1): if the previous run died after paid calls but before writing
        # the summary, the journal is the only record of what was actually bought.
        ledger = (SP.Ledger.load(ledger_path, ceiling=a.max_spend, journal=ledger_journal)
                  if os.path.exists(ledger_path)
                  else SP.Ledger.rebuild_from_journal(ledger_journal, ceiling=a.max_spend))
        ledger.journal, ledger._jfh = ledger_journal, open(ledger_journal, "a", buffering=1)
        if getattr(ledger, "recovered_from_journal", 0):
            print(f"  ledger RECOVERED {ledger.recovered_from_journal} attempt(s) from the journal "
                  f"that the summary file had not yet recorded — a crash mid-run")
    else:
        ledger = SP.Ledger(ceiling=a.max_spend, prices=SP.price_snapshot(roster),
                           journal=ledger_journal)
    if ledger.total:
        print(f"  ledger resumed: ${ledger.total:.4f} already spent, ${ledger.remaining():.4f} left")

    fh = open(path, "a", buffering=1)
    # RAW HTTP LOG (owner ruling 2026-08-08): "you should both log the raw http response, so we can
    # rebuild if something is wrong without requery." Every paid call's FULL response body is kept,
    # verbatim, in a sidecar. It is a sidecar rather than inline so records.jsonl stays scannable --
    # a single reasoning response has reached 98,349 tokens. Keyed by (model, item_id, arm, attempt)
    # so any record can be re-derived, re-parsed, or re-verdicted offline for free.
    raw_path = os.path.join(out, "raw_responses.jsonl")
    rawfh = open(raw_path, "a", buffering=1)
    # M6-T23/S1 (Codex C3): a call that delivered NO BODY is not a result and gets no record. It
    # gets a FAULT EVENT here instead. What that preserves is OPERATIONAL AUDIT data -- when, which
    # model, which provider if known, what status, how many attempts, what Retry-After said, whether
    # anything was billed. "The log holds it" was a hand-wave: a text log is not indexed by
    # run/model/unit and is not part of the resume artifact set. This file is both.
    faults_path = os.path.join(out, "faults.jsonl")
    faultfh = open(faults_path, "a", buffering=1)
    lock = threading.Lock()          # guards the JSONL append AND the shared counters
    # PER-PROVIDER CONCURRENCY IS ENFORCED, not just recorded (Codex C5). The schedule froze a
    # per_provider cap; without a semaphore the only real limit is the global worker count, so N
    # workers can still land on one upstream vendor at once -- the exact pattern the even-spread
    # order exists to avoid. Recording a cap that nothing enforces is a false assurance.
    prov_sem = collections.defaultdict(lambda: threading.Semaphore(sched["per_provider"]))
    prov_live = collections.Counter()        # observable so a test can assert the cap held
    prov_peak = collections.Counter()
    state = {"spent": 0.0, "n": 0, "halted": False, "halt_reason": None,
             "quarantined": {}, "bad": {}, "attempted": set(), "probe": {},
             # M6-T23/S3: models paused by an infrastructure fault, distinct from `quarantined`,
             # which is about a model returning BAD MATERIAL (Codex C11 -- these must never share a
             # mechanism again; conflating them is how D-OR-16 and D-OR-24 happened).
             "paused": {}, "faults": []}
    t0 = time.time()

    def run_one(unit):
        mr, it, arm = unit
        # The spend ceiling is read under the lock: with N threads in flight the check and the
        # increment must not interleave, or the run can overshoot by up to N calls' worth of cost.
        uid = MF.unit_id(mr["id"], it["item_id"], arm)
        aid = MF.attempt_id(uid, 1, "first")
        with lock:
            if state["halted"]:
                return
            try:
                ledger.check_before()          # RAISES; a spend check that can be ignored is not a
            except SP.SpendError as e:         # ceiling. Halt the whole run, do not skip quietly.
                state["halted"] = True
                state["halt_reason"] = str(e)
                return
            # A quarantined model's remaining units are NOT attempted. They are not lost: the
            # manifest enumerates every one of them (Codex C6, no silent drops).
            if mr["id"] in state["quarantined"]:
                return
            # M6-T23/S3: a PAUSED model is one whose infrastructure faults did not clear. Its units
            # stay un-bought and every other model keeps running (owner ruling on Codex C1/C15).
            if mr["id"] in state["paused"]:
                return
            state["attempted"].add((mr["id"], it["item_id"], arm))
        prompt = BF.futurex_render(it, arm) if a.bench == "futurex" else BF.btf_render(it["prompt"], arm)
        raw_seen = {"body": None}
        provider = SC.provider_of(mr["id"])
        rec = {"model": mr["id"], "series": mr["series"], "cutoff": mr["cutoff"],
               "item_id": it["item_id"], "arm": arm, "bench": a.bench,
               "level": it.get("level"), "end_time": it.get("end_time"),
               # ONE identity space for records, ledger and manifest (audit D6). Two identity
               # spaces is how a resumed run pays twice for the same attempt.
               "unit_id": uid, "attempt_id": aid, "attempt_no": 1, "attempt_kind": "first",
               "manifest_id": mani["manifest_id"]}
        sem = prov_sem[provider]
        sem.acquire()
        with lock:
            prov_live[provider] += 1
            prov_peak[provider] = max(prov_peak[provider], prov_live[provider])
        # Timestamps make the per-provider cap CHECKABLE AFTER THE FACT from the records alone
        # (smoke criterion A6) and give the latency tail. Without them the cap is only ever proven
        # on a fixture, never on the run that spent the money.
        t_start = time.time()
        rec["started_at"] = t_start
        try:
            # NO INVENTED CAP (M6-T22, owner 2026-08-10: "there is no cap... the fix cap is the
            # model's own max_token"). This was min(64000, ceiling) -- 64,000 has no source, and for
            # a model whose real ceiling is 128,000 it silently halved what the model could produce.
            # Now: ask the model's PUBLISHED ceiling; if it publishes none, ask with NO limit and let
            # the provider apply its documented default. `cap_basis == "context_length"` means the
            # roster only has a CONTEXT WINDOW, which counts the prompt and is not an output ceiling
            # -- deriving max_tokens from it would be inventing a number out of the wrong field.
            ceiling = caps[mr["id"]] if cap_is_real[mr["id"]] else None
            ceiling = fits_in_context(ceiling, ctx_by_model.get(mr["id"]), prompt)
            start = a.max_tokens if a.max_tokens else ceiling   # --max-tokens is an opt-in override
            # D-OR-20: STAMP THE REQUEST BEFORE MAKING IT. These used to be written after the call
            # returned, so a call that RAISED carried neither field -- and read with .get() they came
            # back None/False, which is indistinguishable from the genuine "no ceiling published, so
            # asked with no limit" case. The 2026-08-10 smoke produced 5 such records; kimi-k2 read as
            # unbounded when its ceiling is 100,352. What was requested is known before the call and
            # is true whether or not it succeeds, so it belongs here.
            rec["requested_max_tokens"] = start
            rec["unbounded_request"] = start is None
            txt, raw, c, trace = call_with_escalation(prompt, mr, start, ceiling)
            # the exact prompt that produced this response -- PREMISE-EVERY-RECORD-PROVES-ITS-REQUEST
            rec["prompt_sha"] = hashlib.sha256(prompt.encode()).hexdigest()[:16]
            rec["prompt_chars"] = len(prompt)
            rec.update({"cost": c, "budget_trace": trace,
                        "final_budget": trace[-1]["budget"], "escalations": len(trace) - 1})
            # The 12k observation. Recorded with its ACTUAL count, so the reader judges the number
            # rather than trusting a label, and nothing downstream branches on it.
            _ct = ((raw or {}).get("usage") or {}).get("completion_tokens") or 0
            rec["completion_tokens"] = _ct
            rec["suspicious_length"] = _ct > SUSPICIOUS_COMPLETION_TOKENS
            if rec["suspicious_length"]:
                state.setdefault("long", []).append((mr["id"], it["item_id"], _ct))
            if txt is None:
                # Still unusable after the escalation cap. A BUDGET outcome, never a wrong answer.
                # It is stamped as a VERDICT here so it can never reach the reader and come back as
                # "unclear" -- glm-4.6 surfaced as UNDECIDED for exactly that reason, hiding a hard
                # budget failure behind an LLM's shrug.
                rec.update({"ok": False, "error": "BUDGET_CAPPED", "compliant": None,
                            "completeness_prelabel": "BUDGET_CAPPED",
                            "detail": trace[-1].get("detail")})
            else:
                raw_seen["body"] = raw            # keep the FULL body for the raw log
                # M6-T5: VALIDATE THE ENVELOPE BEFORE READING IT. A body whose shape breaks the
                # contract is a SCHEMA_ERROR -- runner-stamped, so it never reaches the completeness
                # reader and never becomes a compliance value. Same posture as the transport fix: an
                # unreadable reply is not an opinion about the model.
                env_ok, env_v = RS.validate_envelope(raw)
                if not env_ok:
                    rec.update({"ok": False, "error": "SCHEMA_ERROR", "compliant": None,
                                "completeness_prelabel": "SCHEMA_ERROR",
                                "schema_violations": env_v,
                                "detail": f"envelope violates the contract: "
                                          f"{[x['rule'] for x in env_v]}"})
                u = (raw or {}).get("usage") or {}
                ch0 = ((raw or {}).get("choices") or [{}])[0]
                # audit C5: record how many choices came back; the normalizer reads only [0]
                rec["n_choices"] = len((raw or {}).get("choices") or [])
                msg = ch0.get("message") or {}
                p = BF.futurex_parse(txt) if a.bench == "futurex" else BF.btf_parse(txt)
                # STORE THE COMPLETE RESPONSE. Truncating what we keep makes every later question
                # ("why did this not parse?", "what did it reason?") unanswerable without re-buying
                # the call. Reasoning arrives in its OWN field, is billed, and is invisible in
                # `content` -- dropping it loses most of what a thinking model actually produced.
                rec.update({"ok": True, "text": txt, "chars": len(txt),
                            "reasoning": msg.get("reasoning"),
                            "reasoning_details": msg.get("reasoning_details"),
                            "reasoning_chars": len(msg.get("reasoning") or ""),
                            "finish_reason": ch0.get("finish_reason"),
                            "native_finish_reason": ch0.get("native_finish_reason"),
                            "provider": (raw or {}).get("provider"),
                            "parsed": p, "compliant": p["compliant"], "usage": u})
                # A provider that bills no prompt tokens did not really run the call. Observed on
                # mistral-small-3.1: prompt_tokens=0, completion_tokens=1, a cut-off echo of the
                # question. That is BROKEN, and must never be scored as a format failure.
                # finish_reason=='error' is an UPSTREAM FAILURE delivered with HTTP 200 -- OpenRouter's
                # docs note a mid-stream provider error arrives this way, not as a 4xx/5xx. Observed on
                # mistral-small-3.1 via Cloudflare: a cut-off echo of the question, reproducible.
                if ch0.get("finish_reason") == "error":
                    rec.update({"ok": False, "error": "PROVIDER_ERROR", "compliant": None,
                                "detail": f"finish_reason=error from provider "
                                          f"{(raw or {}).get('provider')!r} after {len(txt)} chars"})
                elif not u.get("prompt_tokens"):
                    rec.update({"ok": False, "error": "BROKEN_USAGE", "compliant": None,
                                "detail": f"provider billed prompt_tokens={u.get('prompt_tokens')!r}, "
                                          f"completion_tokens={u.get('completion_tokens')!r} for "
                                          f"{len(txt)} chars — the call did not really run"})
        except UnitDeadlineExceeded as e:
            # NOT a model failure and NOT a silent drop: the unit hit its total elapsed budget.
            # Recorded as an UNOBSERVED transport outcome, which the census and the rerun manifest
            # already know how to carry (Codex C3).
            c = 0.0
            rec["_no_body"] = True                      # M6-T23/S1: nothing came back
            rec["fault_policy"] = TRANSIENT             # a stall is plausibly self-correcting
            rec.update({"ok": False, "error": "UNIT_DEADLINE", "detail": str(e)[:300],
                        "compliant": None, "failure_class": "transport:UnitDeadlineExceeded",
                        "gave_up_because": "unit_deadline",
                        "completeness_prelabel": "TRANSPORT_ERROR"})
        except Exception as e:
            c = 0.0
            policy, klass = classify_fault(e)
            retryable = policy == TRANSIENT
            rec["_no_body"] = True                      # M6-T23/S1: nothing came back
            rec["fault_policy"] = policy
            rec["retry_after_seen"] = getattr(e, "retry_after", None)
            rec.update({"ok": False, "error": type(e).__name__, "detail": str(e)[:300],
                        "compliant": None,
                        "failure_class": getattr(e, "failure_class", klass),
                        "http_status": getattr(e, "status", None),
                        "error_type": getattr(e, "error_type", None),
                        "provider_code": getattr(e, "provider_code", None),
                        "attempts_made": getattr(e, "attempts_made", None),
                        "gave_up_because": getattr(e, "gave_up_because", None),
                        # STAMP A VERDICT. A call that failed has no text; sending it to the reader
                        # produced "unclear" and disguised a network error as reader uncertainty.
                        "completeness_prelabel": "TRANSPORT_ERROR" if getattr(e, "transport", False)
                                                 else "PROVIDER_ERROR"})
        finally:
            rec["ended_at"] = time.time()
            rec["duration_s"] = round(rec["ended_at"] - t_start, 3)
            rec["provider_group"] = provider
            with lock:
                prov_live[provider] -= 1
            sem.release()

        # ---- COMPLETENESS, decided immediately after the call (owner item 2/5) ----------------
        # PREMISE-NO-SILENT-INCOMPLETE is enforced HERE and only here: `compliant` survives only
        # when the verdict is COMPLETE. Everywhere else it is forced to None, so a truncated,
        # empty or provider-errored record CANNOT represent a compliance value at all.
        if rec.get("completeness_prelabel"):
            verdict, why, by = rec["completeness_prelabel"], rec.get("detail"), "runner"
        else:
            verdict, why = CR.deterministic_verdict(rec)
            by = "layer1"
        # ---- WHERE VALIDATION HAPPENS (owner ruling 2026-08-08) -----------------------------
        # THE SMOKE IS THE HARNESS. Everything is validated there, with the LLM reader on EVERY
        # unit, because that is the run whose job is to establish the method. The REAL run does NO
        # live LLM validation at all: it was measured at 1.3 calls/min inline (92 hours for 7,400
        # calls) and it buys nothing the smoke has not already proven. Real-run records that layer 1
        # cannot settle are accepted PROVISIONALLY and validated in a post-run batch.
        if verdict == CR.UNDECIDED:
            if a.mode == "smoke" and a.review:
                try:
                    lv, raw_reply, _fr = CR.review(None, rec.get("text") or "", None, arm, tail=True)
                    verdict, by = (lv or CR.UNDECIDED), "layer2"
                    why = (raw_reply or "")[-120:]
                    # A reader may judge, but not contradict a fact layer 1 established (D-OR-6).
                    verdict, override = CR.reconcile_layer2(rec, verdict, a.bench)
                    if override:
                        rec["layer2_overruled"] = {"said": lv, "reason": override}
                        by, why = "layer2-overruled", override[:160]
                except Exception as e:
                    # An unreachable reader is UNKNOWN, never "clean". It must not silently promote
                    # a record (D-OR-5: an error must not wear a result's clothes).
                    verdict, by = CR.UNDECIDED, "layer2-unavailable"
                    why = f"{type(e).__name__}: {e}"[:160]
            elif CR.provisional_complete(rec, verdict, why):
                # Layer 1 cleared every transport and shape failure AND the text terminates in a
                # non-empty answer marker. Accepted provisionally; the post-run pass decides.
                verdict, by, why = CR.COMPLETE, "layer1-deferred", "deferred to post-run validation"
                rec["pending_review"] = True

        # C1: recorded on EVERY record so the truncated-but-extractable choice can be revisited
        # from stored data without re-buying a single call.
        rec["answer_extractable"] = bool((rec.get("parsed") or {}).get("compliant"))
        # ANSWER EVALUATION IS PART OF VALIDATION (owner ruling 2026-08-08): "if the result is not
        # interpretable, that is a bad result." Format compliance and interpretability are different
        # questions -- \boxed{maybe} satisfies the format and answers nothing -- so both are
        # recorded per item rather than collapsed into one flag.
        if a.bench == "futurex":
            _iv = BF.interpret_answer((rec.get("parsed") or {}).get("raw_box"), prompt)
            rec["answer_interpretable"] = _iv["interpretable"]
            rec["answer_kind"] = _iv["kind"]
            rec["answer_value"] = _iv["value"]
            rec["answer_uninterpretable_why"] = _iv["why"]
        rec["completeness"] = verdict
        rec["completeness_by"] = by
        rec["completeness_reason"] = why
        rec["scoreable"] = verdict in CR.SCOREABLE
        # COMPLETE -> complied (marker present). NO_ANSWER -> DID NOT comply, and that is a real
        # measurement, not an error: the model finished and chose not to follow the format.
        # Anything else -> the finished output was never observed, so nothing can be scored.
        rec["compliant"] = (True if verdict == CR.COMPLETE else
                            False if verdict == CR.NO_ANSWER else None)

        # M6-T23/S1: THE RESULT / NON-RESULT BOUNDARY. Keyed on the BODY, never on billing --
        # Codex C4: cost is often UNKNOWN at call time, and forcing that uncertainty into the
        # denominator is the very thing this fixes. No body => a fault event, and the unit stays
        # un-bought so resume buys it. Body present => a RESULT, recorded whatever it cost.
        # OVER-REACH GUARD: TRUNCATED, EMPTY_HTTP, NO_ANSWER and a billed empty completion all HAVE
        # a body or a billed response; they are model behaviour and fall through to be recorded.
        no_body = rec.pop("_no_body", False)
        if no_body:
            fault = {"ts": rec.get("ended_at"), "run": a.tag, "manifest_id": mani["manifest_id"],
                     "unit_id": uid, "attempt_id": aid, "model": mr["id"], "item_id": it["item_id"],
                     "arm": arm, "provider_group": provider,
                     "provider": None,                 # unknown: no response came back
                     "phase": "dispatch",
                     "classification": rec.get("failure_class"),
                     "http_status": rec.get("http_status"),
                     "error_type": rec.get("error_type"),
                     "error": rec.get("error"),
                     "attempts_made": rec.get("attempts_made"),
                     "gave_up_because": rec.get("gave_up_because"),
                     "retry_after_seen": rec.get("retry_after_seen"),
                     "body_present": False,
                     # D-OR-20 carried forward: what was REQUESTED is known before the call and
                     # stays true when it fails. When the record disappeared, this had to come with
                     # it, or a failed call would again be indistinguishable from an unbounded one.
                     "requested_max_tokens": rec.get("requested_max_tokens"),
                     "unbounded_request": rec.get("unbounded_request"),
                     "cost_known": (c is not None),
                     "cost": c or 0.0,
                     "detail": str(rec.get("detail"))[:300]}
            with lock:
                faultfh.write(json.dumps(fault) + "\n")
                state["n"] += 1
                state["faults"].append((mr["id"], rec.get("failure_class")))
                # ---- M6-T23/S3: THE DECISION. One place, three outcomes. -------------------
                policy = rec.get("fault_policy") or TRANSIENT
                if policy == TERMINAL_ACCOUNT and not state["halted"]:
                    # Affects every model equally, so no model is blamed and nothing continues.
                    state["halted"] = True
                    state["halt_reason"] = {
                        "kind": "TERMINAL_ACCOUNT", "classification": rec.get("failure_class"),
                        "http_status": rec.get("http_status"), "phase": "mid-run",
                        "detail": str(rec.get("detail"))[:300],
                        "spent_so_far": round(ledger.total, 4), "units_bought": state["n"],
                        "paused_models": dict(state["paused"]),
                        "resume_recommendation":
                            "the ACCOUNT cannot pay or authenticate; no retry will clear it. Raise "
                            "the limit or supply another key, then resume -- delivered answers are "
                            "not re-bought and un-bought units are simply missing.",
                    }
                    print(f"\n  HALT — ACCOUNT fault ({rec.get('failure_class')}): "
                          f"{str(rec.get('detail'))[:160]}\n  This is the ACCOUNT's, not any "
                          f"model's. Nothing is quarantined and nothing else is attempted.",
                          flush=True)
                elif policy in (TRANSIENT, TERMINAL_REQUEST) and mr["id"] not in state["paused"]:
                    why = ("its transient faults did not clear in 3 attempts" if policy == TRANSIENT
                           else "this endpoint will not accept the request as written")
                    state["paused"][mr["id"]] = {
                        "kind": policy, "classification": rec.get("failure_class"),
                        "http_status": rec.get("http_status"), "why": why,
                        "detail": str(rec.get("detail"))[:300]}
                    print(f"  PAUSED {mr['id']} — {why} ({rec.get('failure_class')}). Its remaining "
                          f"units stay UN-BOUGHT; every other model continues.", flush=True)
            return                                     # NO record: the unit was never answered

        with lock:
            # One write() of one line, under the lock -- concurrent appends would otherwise
            # interleave mid-record and corrupt the JSONL.
            fh.write(json.dumps(rec) + "\n")
            if raw_seen.get("body") is not None:
                # SAME IDENTITY AS THE RECORD (Codex C6). Keyed on model/item/arm alone, a retry or
                # a replacement attempt cannot be told from the first, so "rebuild without requery"
                # silently degrades to "rebuild the wrong attempt".
                rawfh.write(json.dumps({"unit_id": uid, "attempt_id": aid,
                                        "manifest_id": mani["manifest_id"],
                                        "model": mr["id"], "item_id": it["item_id"], "arm": arm,
                                        "prompt_sha": rec.get("prompt_sha"),
                                        "prompt": prompt,
                                        "response": raw_seen["body"]}) + "\n")
            # Idempotent per attempt_id, so a resumed run cannot pay twice for one attempt.
            ledger.charge(aid, mr["id"], actual=(c or 0.0), unit_id=uid)
            state["spent"] = ledger.total
            state["n"] += 1
            # ---- QUARANTINE (owner ruling) ----------------------------------------------------
            # SCOPE, narrowed by M6-T23 (Codex C11): this path now only ever sees records that HAVE
            # a body. An infrastructure fault delivers none, returns earlier, and is handled by the
            # single pause/halt decision there -- so the account-fatal branch that used to live here
            # is GONE rather than duplicated. Two readers of one decision is the defect this project
            # keeps re-committing (D-OR-18/22/25); one is being removed here on purpose.
            # What remains is genuinely different: a model that ANSWERED and answered badly.
            if verdict in CR.METHOD_DEFECT or verdict == CR.UNDECIDED:
                bad = state["bad"].setdefault(mr["id"], [])
                bad.append({"item_id": it["item_id"], "arm": arm, "verdict": verdict,
                            "reason": str(why)[:160]})
                if a.mode == "smoke":
                    # RUN THE WHOLE SMOKE, THEN LOOK AT EVERY ERROR (owner 2026-08-08).
                    # Halting on the FIRST defect means one error per run and a fix-rerun-repeat
                    # cycle that only ever reveals one class at a time -- and it cost ~230 already
                    # bought calls each time. The smoke's job is to surface EVERY error class in one
                    # pass; they are then fixed together and the ledger records all of them.
                    print(f"  smoke error ({verdict}) on {mr['id']} {it['item_id']}/{arm} "
                          f"— recorded, continuing", flush=True)
                elif len(bad) >= a.quarantine_after:
                    if mr["id"] not in state["quarantined"]:
                        state["quarantined"][mr["id"]] = verdict
                        print(f"  QUARANTINED {mr['id']} after {len(bad)} non-COMPLETE "
                              f"({verdict}) — its remaining units are skipped; other models continue",
                              flush=True)
            if state["n"] % 20 == 0:
                el = time.time() - t0
                print(f"    {state['n']}/{len(work)}  ${state['spent']:.4f}  {el:.0f}s  "
                      f"{state['n'] / el * 60:.1f} calls/min  quarantined={len(state['quarantined'])}",
                      flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(run_one, work))
    fh.close(); rawfh.close(); faultfh.close()
    el = time.time() - t0

    # ---- QUARANTINE MANIFEST (Codex C6) -----------------------------------------------------
    # NO SILENT DROPS: every unit not attempted because its model was quarantined is enumerated
    # here with everything needed to reproduce the re-run exactly.
    cfg = {"bench": a.bench, "arms": arms, "items": os.path.abspath(a.items),
           "models": os.path.abspath(a.models), "max_tokens": a.max_tokens,
           "workers": a.workers, "mode": a.mode, "quarantine_after": a.quarantine_after}
    cfg_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]
    skipped = [{"model": mr["id"], "provider_hint": mr["id"].split("/")[0], "item_id": it["item_id"],
                "arm": arm} for (mr, it, arm) in work
               if mr["id"] in state["quarantined"] and (mr["id"], it["item_id"], arm) not in state["attempted"]]
    qmanifest = {"run_config": cfg, "run_config_hash": cfg_hash,
                 "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "quarantined_models": [
                     {"model": m, "first_verdict": v, "failures": state["bad"].get(m, []),
                      "attempts": len(state["bad"].get(m, []))}
                     for m, v in sorted(state["quarantined"].items())],
                 "units_to_rerun": skipped, "units_to_rerun_count": len(skipped),
                 "halted": state["halted"], "halt_reason": state.get("halt_reason")}
    # FAILURE LEDGER: every non-clean call, classified, so a run's failures are documented rather
    # than being a count. Written even when the run is clean (an empty ledger is itself a claim).
    # D-OR-21: the ledger describes THIS PLAN. A superseded directory holds records for models the
    # manifest no longer plans, and counting them made a clean stage read as broken -- the 2026-08-10
    # smoke reported 277 non-clean records of which 255 were api:403 rows inherited from the halted
    # August 8 attempt, against 5 genuine failures in the stage that had just run. Inherited noise
    # does not just mislead; it is where a real failure would hide.
    planned_models = {u["model"] for u in mani["units"]}
    failures, out_of_plan_rows = [], 0
    for line in open(path):
        if not line.strip():
            continue
        rr = json.loads(line)
        if rr.get("model") not in planned_models:
            out_of_plan_rows += 1
            continue
        if rr.get("ok") is False or rr.get("completeness") not in (CR.COMPLETE, CR.NO_ANSWER):
            failures.append({k: rr.get(k) for k in
                             ("model", "item_id", "arm", "completeness", "completeness_by",
                              "error", "failure_class", "http_status", "error_type",
                              "provider_code", "attempts_made", "gave_up_because", "detail")})
    retries = []
    for line in open(path):
        if not line.strip():
            continue
        rr = json.loads(line)
        for t in (rr.get("budget_trace") or []):
            if t.get("outcome") == "retry":
                retries.append({"model": rr.get("model"), "arm": rr.get("arm"),
                                "attempt": t.get("attempt"), "failure_class": t.get("failure_class"),
                                "sleep": t.get("sleep"), "from_header": t.get("from_header")})
    manifest_failures = {"failures": failures, "n_failures": len(failures),
                         "by_class": dict(collections.Counter(f.get("failure_class") or
                                                              f.get("completeness") for f in failures)),
                         "retries_that_succeeded": retries, "n_retries": len(retries),
                         "retry_classes": dict(collections.Counter(r["failure_class"] for r in retries))}
    json.dump(manifest_failures, open(os.path.join(out, "failure_ledger.json"), "w"), indent=1)
    print(f"  failure ledger: {len(failures)} non-clean IN-PLAN record(s) "
          f"{manifest_failures['by_class'] or ''}; {len(retries)} retry/retries that recovered "
          f"{manifest_failures['retry_classes'] or ''}"
          + (f"; {out_of_plan_rows} out-of-plan record(s) from a superseded plan excluded"
             if out_of_plan_rows else ""))

    # THE 12k OBSERVATION -- reported, never enforced. Nothing above or below this line branches on
    # it; it exists so a runaway generation is visible instead of merely expensive.
    long_calls = state.get("long", [])
    if long_calls:
        by_model = collections.Counter(m for m, _i, _t in long_calls)
        worst = max(long_calls, key=lambda x: x[2])
        print(f"  SUSPICIOUS LENGTH (>{SUSPICIOUS_COMPLETION_TOKENS:,} completion tokens): "
              f"{len(long_calls)} call(s) across {len(by_model)} model(s); worst {worst[2]:,} tokens "
              f"from {worst[0]}. Reported only — no call was blocked, retried or re-verdicted. "
              f"{dict(by_model.most_common())}")
    else:
        print(f"  suspicious length (>{SUSPICIOUS_COMPLETION_TOKENS:,} completion tokens): none")

    mpath = os.path.join(out, "quarantine_manifest.json")
    json.dump(qmanifest, open(mpath, "w"), indent=1)

    print(f"  DONE {state['n']} calls, ${state['spent']:.4f} actual spend, {el / 60:.1f} min, "
          f"{state['n'] / el * 60:.1f} calls/min, {a.workers} workers, mode={a.mode}"
          + ("  [HALTED]" if state["halted"] else ""))
    if state["quarantined"]:
        print(f"  QUARANTINED {len(state['quarantined'])} model(s); {len(skipped)} units to re-run "
              f"-> {mpath}")
        for m, v in sorted(state["quarantined"].items()):
            print(f"      {m:<40} {v}  ({len(state['bad'].get(m, []))} failures)")
    pend = sum(1 for l in open(path) if l.strip() and json.loads(l).get("pending_review"))
    if pend:
        print(f"  {pend} record(s) PROVISIONALLY accepted and DEFERRED to post-run review "
              f"-> run: python3 review_pending.py {path}")
    verify_records(path, planned_models={u['model'] for u in mani['units']})

    # ---- CLOSING INTEGRITY CHECKS (M6-T3 / M6-T7 / M6-T9) ---------------------------------------
    # These run on the run's OWN emitted output. Isolated unit tests prove the checkers work; only
    # this proves they were applied to the records the run actually produced.
    SP.Ledger.save(ledger, ledger_path) if hasattr(SP.Ledger, "save") else None
    recon = ledger.reconcile()
    print(f"  ledger: ${recon['total']:.4f} of ${ledger.ceiling:.2f} over {recon['n_attempts']} "
          f"attempt(s); estimate/actual ratio surfaced per model in {ledger_path}")

    final = [json.loads(l) for l in open(path) if l.strip()]
    PS.require_unique_within_run(final, where=out)          # RAISES on a duplicate unit
    vr = MF.verify_records_against(mani, final)
    print(f"  manifest check: {vr['counts']}")
    if vr["counts"].get("MISASSOCIATED"):
        raise SystemExit(
            f"HALT: {vr['counts']['MISASSOCIATED']} record(s) carry a prompt_sha that does not match "
            f"the manifest -- an answer is filed against a question it was not asked. "
            f"Examples: {vr['misassociated'][:3]}")
    if vr["counts"].get("UNPLANNED"):
        raise SystemExit(f"HALT: {vr['counts']['UNPLANNED']} record(s) are not in the frozen plan.")
    if vr["counts"].get("NO_HASH"):
        print(f"  NOTE {vr['counts']['NO_HASH']} record(s) carry no prompt_sha and CANNOT prove "
              f"their request; they are not misassociation-checkable.")

    # ---- PRODUCE THE DELIVERABLE (Codex C2) -----------------------------------------------------
    # The run does not end at "records exist". Until this ran, analyze and provenance were tested
    # but never called by the paid path, so a $31 run could finish green and produce no table and no
    # bundle -- and the E8 guarantee (hash the published table) could be skipped by never building
    # one. Quarantined and budget-abandoned units become CENSORED here (C4), and the raw sidecar is
    # checked one-to-one against the records (C6).
    ledger.close()
    import finalize as FZ
    fin = FZ.finalize(out)
    print(f"  deliverable: {fin['n_records']} record(s), {fin['n_censored']} censored, "
          f"sidecar {'one-to-one' if fin['sidecar']['ok'] else 'PROBLEMS'} -> {fin['table_path']}")
    if fin["provisional"]:
        print(f"  PROVISIONAL — no provenance bundle. {fin['next_action']}")
    else:
        print(f"  provenance {fin['provenance']['bundle_id']} verified -> {fin['provenance']['path']}")
    print(AN_render(fin["table_path"]))


if __name__ == "__main__":
    main()
