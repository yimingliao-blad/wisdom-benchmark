"""Local, free iteration on BTF-3's final-answer instruction. NO paid calls.

Owner 2026-08-08: "check with codex, and see if a simple update on 'The last thing you write is your
final answer as a probability between 0 and 1.' can help with it. since we have llama-3.1-8b on
local, we can use it to do prompt design iteration"

CANDIDATES ARE FROZEN IN THIS FILE BEFORE ANY RUN (Codex C5). Editing them after seeing results and
re-running would be fitting the prompt to the sample, which is the failure this whole discipline
exists to prevent.

CODEX C5 CONSTRAINTS, implemented rather than summarised:
  * MORE THAN ONE MODEL. Tuning until llama-3.1-8b passes designs around one weak model's quirks, so
    the panel spans strata: a native-compliant model, a partial failure, and the 0/6 severe failure.
  * IDENTICAL DECODING across arms; the only thing that varies is the one instruction line.
  * THE SAME PARSER for every arm -- all candidates still require the reply to END with the number,
    so no arm gets a bespoke extractor that flatters it.
  * FALSIFIERS ARE DECLARED UP FRONT (see FALSIFIERS below) and checked in the report.

Run: python3 prompt_iterate_btf.py [--n 6] [--reps 2]
"""
import argparse
import collections
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_formats as BF      # noqa: E402

LOCAL = "http://localhost:8000/v1/chat/completions"

NATIVE = "The last thing you write is your final answer as a probability between 0 and 1."

# FROZEN 2026-08-08, before the first run. Authored by Codex (job task-msl2wybv-nwe353).
CANDIDATES = {
    "native": NATIVE,
    "A": ("The last thing you write must be a single decimal probability between 0 and 1, "
          "with no percent sign and no text after it."),
    "B": ("The last line of your response must contain only your final answer: "
          "a number from 0 to 1 inclusive."),
    "C": ("End your response with exactly one line in this format: "
          "`Final answer: <number between 0 and 1>`. Do not write anything after that line."),
}

# STRATA, NOT A CONVENIENCE SAMPLE (Codex C5). Each was CHOSEN for its measured score on the paid
# BTF gate, so the panel can detect the failure modes Codex named -- not just "some local models":
#   llama-3.1-8b-instruct  0/6 on the paid gate -> the severe-failure case, the identical model
#   qwen3.5-27b-gguf       6/6 on the paid gate -> THE CONTROL. Falsifier 1 is "a candidate helps
#                          the weak model but HARMS one that already complied". Without a
#                          natively-compliant model on the panel that falsifier cannot fire at all.
#   llama-3.2-3b-instruct  untested, deliberately weaker -> guards against a fix that only works
#                          above some capability floor
# NARROWED (owner 2026-08-08): "you do not have to test all model locally. we just to confirm that
# if we can have a prompt to make the model output the right number."
# So the question is binary and one model answers it: can ANY minimal rewrite move the worst case?
# llama-3.1-8b-instruct scored 0/6 on the paid gate and 1/12 here on the native prompt, so it
# reproduces the failure and is the right subject.
#
# THE COST OF NARROWING, STATED: with no natively-compliant model on the panel, Codex's falsifier 1
# -- "helps the weak model but HARMS one that already complied" -- cannot fire. That check is not
# dropped, it is DEFERRED: if a candidate wins here, it is run against qwen3.5-27b-gguf (6/6 on the
# paid gate) before anything is adopted. Cheap, and it keeps the falsifier alive.
PANEL = ["llama-3.1-8b-instruct"]

FALSIFIERS = [
    "a candidate improves llama-3.1-8b but REDUCES compliance for any model that already complied",
    "trailing prose falls but percent-answers or missing-answers rise",
    "the winner beats native by less than the spread across repeats (inside the noise)",
]


def call(model, prompt, max_tokens=2048, full=False):
    """2048, not a tight budget: BTF's prompt demands (a)-(e) reasoning BEFORE the answer, so a
    small budget would cut replies off before the final line and confound truncation with
    non-compliance -- the exact conflation this project already hit once."""
    body = json.dumps({"model": model, "temperature": 0.0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(LOCAL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.load(r)
    ch = d["choices"][0]
    txt = ch["message"].get("content") or ""
    return (txt, ch.get("finish_reason"), d.get("usage") or {}) if full else txt


def classify(text, finish_reason=None):
    """Compliance by the SAME rule for every arm, plus WHY it failed.

    TRUNCATION IS ITS OWN OUTCOME and is checked FIRST. A reply cut off by the token budget did not
    "fail to comply" -- it never finished. Scoring it as a content class is the defect this project
    has hit before, and this harness reintroduced it: qwen3.5-27b-gguf is a reasoning model that ate
    all 2048 tokens on internal reasoning and returned ZERO visible characters, and the first version
    of this function recorded that as `no_figure`, i.e. as a refusal. It was a budget failure.
    """
    if finish_reason == "length":
        return "TRUNCATED_budget", None
    if not (text or "").strip():
        return "EMPTY", None
    p = BF.btf_parse(text)
    if p["compliant"]:
        return "compliant", p["prob"]
    t = (text or "").rstrip()
    tail = t[-400:]
    import re
    if re.search(r"\d{1,3}(?:\.\d+)?\s*%", tail):
        return "percent", None
    if re.search(r"(?<![\d.])(0?\.\d+|0|1(?:\.0+)?)(?![\d.])", tail):
        return "prose_after_number", None
    return "no_figure", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="items from the BTF gate slice")
    ap.add_argument("--reps", type=int, default=2, help="repeats, to size the noise floor")
    ap.add_argument("--out", default=os.path.join(HERE, "runs", "prompt_iter_btf.json"))
    a = ap.parse_args()

    items = json.load(open(os.path.join(HERE, "runs", "btf3_smoke_slice6.json")))[:a.n]
    print(f"  {len(items)} items x {len(PANEL)} models x {len(CANDIDATES)} arms x {a.reps} reps "
          f"= {len(items)*len(PANEL)*len(CANDIDATES)*a.reps} LOCAL calls (free)\n")

    rows = []
    for arm, line in CANDIDATES.items():
        for model in PANEL:
            for it in items:
                prompt = it["prompt"].replace(NATIVE, line)
                assert (line in prompt) and (arm == "native" or NATIVE not in prompt), \
                    "the instruction swap did not apply cleanly"
                for rep in range(a.reps):
                    try:
                        txt, fr, _u = call(model, prompt, full=True)
                        kind, prob = classify(txt, fr)
                    except Exception as e:
                        kind, prob, txt = f"ERROR:{type(e).__name__}", None, str(e)[:200]
                    rows.append({"arm": arm, "model": model, "item_id": it["item_id"], "rep": rep,
                                 "kind": kind, "prob": prob, "tail": (txt or "")[-160:]})
            done = sum(1 for r in rows if r["arm"] == arm and r["model"] == model)
            ok = sum(1 for r in rows if r["arm"] == arm and r["model"] == model
                     and r["kind"] == "compliant")
            print(f"    {arm:<7} {model:<26} {ok}/{done}")

    json.dump({"candidates": CANDIDATES, "panel": PANEL, "falsifiers": FALSIFIERS, "rows": rows},
              open(a.out, "w"), indent=1)
    print(f"\n  -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
