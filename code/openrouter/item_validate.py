"""M6-T2 (L-V) — validate the ITEM corpus before any paid call.

PLAIN ENGLISH: check the QUESTIONS before spending money asking them. A malformed item must HALT the
run, not quietly produce a junk call that later reads as a model failure.

WHICH CORPUS: the ITEM corpus (the questions we ask). M6-T1 validated the RECORD corpus (the answers
we stored). Both get called "corpus validation", so this module always says which.

WHY IT PRECEDES THE MANIFEST FREEZE (Codex audit-2 D1): the manifest is DERIVED from the validated
corpus. Freeze first and bad units are baked into the "planned universe" as though they were valid.

THE HARD RULE, and the reason this is not trivial. "A prompt containing an answer marker" cannot
simply be rejected: the FutureX prompt LEGITIMATELY contains `\\boxed{Yes} or \\boxed{No}` as its
FORMAT INSTRUCTION. The check must separate that instruction from a LEAKED ANSWER. Too permissive
and a leaked answer is asked as a question; too strict and every valid item in the benchmark is
rejected. The negative control in the test suite exists for exactly this.

Offline. No network. No spend.
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bench_formats import FX_FORMAT_MARKER, BTF_TAIL  # noqa: E402  the render contracts

ANCHOR = "2026-02-16"          # the contamination anchor; an item must resolve AFTER it
_BOXED = re.compile(r"\\boxed\s*\{([^{}]*)\}")
# SINGLE asterisks only. BTF's answer format is *0.35*; markdown BOLD is **0**, and BTF-3's
# resolution criteria use it constantly ("its seat count is treated as **0**", "resolves **No**").
# Without the lookarounds this rule fires on ordinary formatting and halts a clean corpus -- which
# it did, on 1 of 1,515 items, the first time it ran.
_ASTERISK_PROB = re.compile(r"(?<!\*)\*\s*(0?\.\d+|0|1(?:\.0+)?)\s*\*(?!\*)")
_UNFILLED = re.compile(r"\{(question|background|resolution_criteria|today)\}")
# BTF-3 ships the answer in these columns. If either ever reaches a prompt, the item states its own
# outcome. Checked by NAME as well as by content, because a template edit is how that would happen.
_BTF_ANSWER_COLUMNS = ("resolution_explanation", "sota_summary_rationale")


class ItemCorpusError(RuntimeError):
    """Raised when the item corpus is unfit to ask. Never returned as a value, never warned about."""


def _leaked_answer(prompt):
    """Distinguish the FORMAT INSTRUCTION from a LEAKED ANSWER.

    The format block is the tail of the prompt starting at FX_FORMAT_MARKER, and it is SUPPOSED to
    contain markers -- that is what tells the model how to answer. A marker in the QUESTION BODY
    (before the marker line) is a different thing: the answer, sitting in the question.

    Returns a reason string, or None when the prompt is clean.
    """
    if FX_FORMAT_MARKER not in prompt:
        return None                                  # a separate rule reports the missing marker
    body = prompt.split(FX_FORMAT_MARKER, 1)[0]
    found = _BOXED.findall(body)
    if found:
        return (f"an answer marker appears in the QUESTION BODY, before the format block: "
                f"{found[:3]!r} -- this is a leaked answer, not the format instruction")
    return None


def _btf_leaked_answer(prompt):
    """The BTF analogue of _leaked_answer: is the ANSWER sitting in the question?

    BTF's answer is a probability in asterisk form, and its format instruction is the tail line. A
    probability in asterisk form BEFORE that tail is a leaked answer, not an instruction.
    """
    if BTF_TAIL not in prompt:
        return None                                  # a separate rule reports the missing tail
    body = prompt.split(BTF_TAIL, 1)[0]
    found = _ASTERISK_PROB.findall(body)
    if found:
        return (f"a probability in the answer's asterisk form appears in the QUESTION BODY, before "
                f"the answer instruction: {found[:3]!r} -- a leaked answer, not the format")
    return None


def _btf_states_its_outcome(it):
    """The resolution columns must never reach the prompt. BTF-3's resolution_explanation literally
    explains why the question resolved as it did -- it is the answer in prose."""
    p = it.get("prompt") or ""
    for col in _BTF_ANSWER_COLUMNS:
        v = it.get(col)
        if isinstance(v, str) and v.strip() and v.strip()[:80] in p:
            return f"the {col!r} field appears inside the prompt -- the item states its own outcome"
    return None


BTF_RULES = [
    ("item_id_missing", lambda it: not str(it.get("item_id") or "").strip(),
     "item_id is empty or absent"),
    ("prompt_not_string", lambda it: not isinstance(it.get("prompt"), str),
     "prompt is not a string"),
    ("prompt_empty", lambda it: isinstance(it.get("prompt"), str) and not it["prompt"].strip(),
     "prompt is empty"),
    ("answer_tail_missing",
     lambda it: isinstance(it.get("prompt"), str) and BTF_TAIL not in it["prompt"],
     f"the prompt lacks {BTF_TAIL!r}, so the parse target is undefined"),
    ("template_unfilled",
     lambda it: isinstance(it.get("prompt"), str) and bool(_UNFILLED.search(it["prompt"])),
     "an unfilled {placeholder} remains in the rendered prompt"),
    ("answer_leaked",
     lambda it: isinstance(it.get("prompt"), str) and bool(_btf_leaked_answer(it["prompt"])),
     "a probability in asterisk form appears in the question body"),
    ("outcome_leaked", lambda it: bool(_btf_states_its_outcome(it)),
     "a resolution column appears inside the prompt"),
    ("end_time_before_anchor",
     lambda it: str(it.get("end_time") or "")[:10] < ANCHOR if it.get("end_time") else False,
     f"end_time resolves before the contamination anchor {ANCHOR}"),
    ("stratum_missing", lambda it: it.get("stratum") in (None, ""),
     "stratum is absent, so the balance gate cannot bind"),
]


RULES = [
    ("item_id_missing", lambda it: not str(it.get("item_id") or "").strip(),
     "item_id is empty or absent"),
    ("prompt_not_string", lambda it: not isinstance(it.get("prompt"), str),
     "prompt is not a string"),
    ("prompt_empty", lambda it: isinstance(it.get("prompt"), str) and not it["prompt"].strip(),
     "prompt is empty"),
    ("format_marker_missing",
     lambda it: isinstance(it.get("prompt"), str) and FX_FORMAT_MARKER not in it["prompt"],
     f"the prompt lacks {FX_FORMAT_MARKER!r}, so rendering is undefined"),
    ("answer_leaked",
     lambda it: isinstance(it.get("prompt"), str) and bool(_leaked_answer(it["prompt"])),
     "an answer marker appears in the question body"),
    ("end_time_before_anchor",
     lambda it: str(it.get("end_time") or "")[:10] < ANCHOR if it.get("end_time") else False,
     f"end_time resolves before the contamination anchor {ANCHOR}"),
    ("level_missing", lambda it: it.get("level") in (None, ""), "level is absent"),
]


RULESETS = {"futurex": None, "btf3": None}      # filled below, after both lists exist


def validate(items, bench="futurex"):
    """Return a report. Rules run over the WHOLE file: a duplicate id is only visible in aggregate.

    bench selects the rule set. The two benchmarks have DIFFERENT answer contracts, so a shared rule
    list would either check FutureX's format marker on a BTF item (always failing) or drop the check
    entirely (always passing). Both are worse than two explicit sets.
    """
    ruleset = RULESETS.get(bench)
    if ruleset is None:
        raise ItemCorpusError(f"no rule set for bench {bench!r}; expected one of "
                              f"{sorted(k for k, v in RULESETS.items() if v is not None)}")
    violations = []
    for i, it in enumerate(items):
        for rule, test, why in ruleset:
            try:
                bad = test(it)
            except Exception as e:                    # a rule that crashes is itself a violation
                violations.append({"index": i, "item_id": it.get("item_id"),
                                   "rule": f"{rule}_CRASHED", "why": f"{type(e).__name__}: {e}"})
                continue
            if bad:
                detail = why
                if rule == "answer_leaked":
                    detail = ((_leaked_answer(it["prompt"]) if bench == "futurex"
                               else _btf_leaked_answer(it["prompt"])) or why)
                if rule == "outcome_leaked":
                    detail = _btf_states_its_outcome(it) or why
                violations.append({"index": i, "item_id": it.get("item_id"),
                                   "rule": rule, "why": detail})
    # aggregate rule: duplicate ids
    seen = collections.Counter(str(it.get("item_id")) for it in items)
    for iid, n in seen.items():
        if n > 1:
            violations.append({"index": None, "item_id": iid, "rule": "item_id_duplicate",
                               "why": f"item_id appears {n} times; a unit must be uniquely addressable"})
    return {"n_items": len(items), "bench": bench, "n_violations": len(violations),
            "by_rule": dict(collections.Counter(v["rule"] for v in violations)),
            "violations": violations}


def require_valid(items, where="item corpus", bench="futurex"):
    """HALT on any violation. This is what the runner calls before the first paid call."""
    rep = validate(items, bench=bench)
    if rep["n_violations"]:
        head = "; ".join(f"{k}x{v}" for k, v in sorted(rep["by_rule"].items()))
        first = rep["violations"][:5]
        raise ItemCorpusError(
            f"{where}: {rep['n_violations']} violation(s) across {rep['n_items']} item(s) [{head}]. "
            f"Refusing to spend on a corpus that is not fit to ask. First: {first}")
    return rep


def main():
    paths = sys.argv[1:] or [os.path.join(HERE, "runs", "fx_smoke4.json")]
    for p in paths:
        items = json.load(open(p))
        rep = validate(items)
        print(f"  {os.path.basename(p):<28} {rep['n_items']:>5} items  "
              f"{rep['n_violations']:>4} violation(s)  {rep['by_rule'] or ''}")
        for v in rep["violations"][:8]:
            print(f"      {v['rule']:<24} {str(v['item_id'])[:32]:<34} {v['why'][:70]}")


if __name__ == "__main__":
    main()

RULESETS["futurex"] = RULES
RULESETS["btf3"] = BTF_RULES
