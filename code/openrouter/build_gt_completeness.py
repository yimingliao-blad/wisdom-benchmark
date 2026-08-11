"""Build the hand-checkable ground-truth set for the completeness reviewer.
   [scope: or-completeness-reviewer-2026-08-08]

WHY CONSTRUCTED CASES ARE NECESSARY AND WHAT THEY COST. The v2 corpus is 172 records with zero
truncations -- a clean corpus cannot calibrate a truncation detector, because it contains no
positives. So TRUNCATED and NO_ANSWER cases are SEEDED into real outputs by cutting or stripping
them. That is the standard way to prove a detector can fail, but it is weaker evidence than natural
positives: a cut I choose may be systematically easier to spot than a real budget cutoff. That
limitation is recorded in the artifact rather than hidden.

Sampling is seeded-random (never a prefix) and the class balance is asserted, per the subsampling rule.
"""
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20260808
N_COMPLETE, N_TRUNC, N_NOANS = 25, 25, 10
_BOXED = re.compile(r"\\boxed\s*\{[^{}]*\}")


def load_clean():
    p = os.path.join(HERE, "runs", "or_futurex_smoke35_v2", "records.jsonl")
    R = [json.loads(l) for l in open(p) if l.strip()]
    # only well-formed, answered, reasonably long records are usable as source material
    return [r for r in R if r.get("ok") and r.get("compliant")
            and len((r.get("text") or "")) > 200 and (r.get("usage") or {}).get("prompt_tokens")]


def cut_midsentence(text, rng):
    """Cut inside a sentence, never at a boundary -- that is what a budget cutoff looks like."""
    body = _BOXED.sub("", text).rstrip()
    # candidate cut points: inside the last 60% of the text, not immediately after terminal punctuation
    lo = max(80, int(len(body) * 0.4))
    for _ in range(40):
        i = rng.randrange(lo, max(lo + 1, len(body)))
        if body[i - 1] not in ".!?\n" and body[i] not in ".!?":
            return body[:i]
    return body[:lo]


def main():
    rng = random.Random(SEED)
    pool = load_clean()
    if len(pool) < N_COMPLETE + N_TRUNC + N_NOANS:
        raise SystemExit(f"HALT: only {len(pool)} usable source records; need "
                         f"{N_COMPLETE + N_TRUNC + N_NOANS}. Refusing to build a short set.")
    picked = rng.sample(pool, N_COMPLETE + N_TRUNC + N_NOANS)   # seeded random, NOT a prefix
    gt = []
    for i, r in enumerate(picked):
        base = {"src_model": r["model"], "arm": r["arm"], "item_id": r["item_id"],
                "reasoning": r.get("reasoning"), "usage": r.get("usage"),
                "provider": r.get("provider")}
        if i < N_COMPLETE:
            gt.append({**base, "gt": "COMPLETE", "how": "real unmodified output",
                       "text": r["text"], "finish_reason": r.get("finish_reason")})
        elif i < N_COMPLETE + N_TRUNC:
            gt.append({**base, "gt": "TRUNCATED", "how": "seeded: cut mid-sentence, answer removed",
                       "text": cut_midsentence(r["text"], rng), "finish_reason": "stop"})
        else:
            # finished prose, answer marker stripped: the output READS complete but never answers
            stripped = _BOXED.sub("", r["text"]).rstrip()
            if not re.search(r'[.!?)"\u201d]\s*$', stripped):
                stripped += "."
            gt.append({**base, "gt": "NO_ANSWER", "how": "seeded: answer marker removed, prose intact",
                       "text": stripped, "finish_reason": "stop"})
    # fail-loud balance gate
    from collections import Counter
    c = Counter(g["gt"] for g in gt)
    want = {"COMPLETE": N_COMPLETE, "TRUNCATED": N_TRUNC, "NO_ANSWER": N_NOANS}
    if dict(c) != want:
        raise SystemExit(f"HALT: class balance {dict(c)} != required {want}")
    out = os.path.join(HERE, "runs", "gt_completeness.json")
    json.dump(gt, open(out, "w"), indent=1)
    print(f"  wrote {out}: {len(gt)} items  {dict(c)}")
    print(f"  drawn seeded-random (seed={SEED}) from {len(pool)} usable source records")
    print(f"  source models represented: {len({g['src_model'] for g in gt})}")


if __name__ == "__main__":
    main()
