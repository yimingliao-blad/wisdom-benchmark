"""Draw the BTF-3 forecasting sample. Run: python3 build_btf3_sample.py [--check]

WHY THIS EXISTS: the shipped runs/btf3_sample.json was originally drawn ad-hoc, so the repo
could not regenerate it. This script reproduces it exactly (verified id-for-id, all 40).

TWO THINGS THAT ARE EASY TO GET WRONG HERE:

1. ELIGIBILITY, NOT TRUNCATION. BTF-3's fields are long (background median 2,122 chars). A
   question whose fields will not fit the smallest model's context is EXCLUDED WHOLE. Fields
   are never shortened -- shortening silently changes what the benchmark asks. The cost is
   coverage, and it is stated: 259 of 1,515 questions are eligible.

2. THE EXPERT COLUMN IS 0-100, NOT 0-1. `sota_forecast_probability` is named "probability"
   but ships percentages (observed 2.0-97.0). Scored as a probability it gives Brier 2504.
   It is divided by 100 here, and the range is asserted so a genuine 0-1 release fails loudly
   rather than being divided twice.

The draw is seeded random over the eligible set -- never a prefix. BTF-3 is ordered, so a
head() slice would take one corner of the question space and report it as the benchmark.
"""
import argparse
import json
import math
import random
import statistics
import sys

import pandas as pd

PARQUET = "data/btf/btf3_binary_questions_and_forecasts.parquet"
OUT = "runs/btf3_sample.json"
SEED = 20260806
N = 40
MAX_FIELD_CHARS = 3000   # question + background + resolution_criteria, the smallest context
ID_LEN = 12


def build():
    d = pd.read_parquet(PARQUET)
    d = d.assign(flen=d.question.str.len() + d.background.str.len() + d.resolution_criteria.str.len())
    el = d[d.flen <= MAX_FIELD_CHARS]
    if len(el) < N:
        raise SystemExit(f"FATAL: only {len(el)} eligible questions, need {N}")
    print(f"  eligible: {len(el)} of {len(d)} (fields <= {MAX_FIELD_CHARS} chars)")

    picked = random.Random(SEED).sample(list(el.question_id), N)
    rows = {r.question_id: r for r in el.itertuples()}

    hi = max(r.sota_forecast_probability for r in rows.values()
             if not math.isnan(r.sota_forecast_probability))
    if hi <= 1.0:
        raise SystemExit(f"FATAL: expert column looks like 0-1 already (max {hi}); "
                         "the /100 rescale below would be wrong")

    qs = []
    for qid in picked:
        r = rows[qid]
        sota = r.sota_forecast_probability
        qs.append({
            "id": str(qid)[:ID_LEN],
            "source": "btf3",
            "question": r.question,
            "background": r.background,
            "resolution_criteria": r.resolution_criteria,
            "today": str(r.present_date),
            "resolution_date": str(r.expected_resolution_date),
            "freeze_datetime": None,     # BTF-3 ships no market price -- see DEGENERATE in analyze_all.py
            "freeze_value": "N/A",
            "outcome": int(r.resolution),
            "sota_forecast": None if math.isnan(sota) else float(sota),
        })

    have = [(q["sota_forecast"] / 100.0, q["outcome"]) for q in qs if q["sota_forecast"] is not None]
    return {
        "seed": SEED, "source": "BTF-3 binary", "n": N, "questions": qs,
        "sota_available": len(have),
        "sota_brier": round(statistics.mean([(p - o) ** 2 for p, o in have]), 4) if have else None,
        "base_rate": round(statistics.mean([q["outcome"] for q in qs]), 4),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="regenerate and assert it matches the shipped sample, without writing")
    a = ap.parse_args()
    out = build()
    if a.check:
        want = json.load(open(OUT))
        got_ids = [q["id"] for q in out["questions"]]
        want_ids = [q["id"] for q in want["questions"]]
        if got_ids != want_ids:
            print(f"MISMATCH: {len(set(got_ids) & set(want_ids))}/{N} ids overlap, order-sensitive compare failed")
            sys.exit(1)
        print(f"  OK reproduces the shipped sample exactly ({N}/{N} ids, in order)")
        sys.exit(0)
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"  wrote {OUT}  n={out['n']} base_rate={out['base_rate']} "
          f"expert_brier={out['sota_brier']} on {out['sota_available']}")
