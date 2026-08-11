"""Build the BTF-3 item corpus in the SAME schema the runner and manifest already use.

Run: python3 build_btf3_corpus.py [--n 110] [--out runs/btf3_items_110.json]

WHY THIS IS NOT build_btf3_sample.py. That script drew 40 questions for an earlier forecasting-
accuracy study and emits its own shape (`questions`, `sota_forecast`, `outcome`). This one produces
the ITEM schema this project's manifest/runner/validator speak: item_id / prompt / stratum /
end_time / ground_truth, with the prompt FULLY RENDERED.

THREE THINGS THAT WOULD BE EASY TO GET WRONG, all decided from measurement rather than inherited:

1. THE 3,000-CHAR FIELD CAP IS DROPPED, DELIBERATELY. build_btf3_sample.py excludes any question
   whose fields exceed 3,000 chars, "the smallest context". That cap keeps 259 of 1,515 -- it cuts
   at the *p10* of the length distribution, so it selects the SHORTEST 17% of questions. For a
   FORMAT-COMPLIANCE study that is the easy case, and the restriction would be silent.
   MEASURED against the actual roster (OpenRouter /models, 37 of 37 found): the smallest context is
   131,072 tokens and the largest possible BTF prompt is ~3,078 tokens -- 2.3% of context. The cap
   is unnecessary here. It is NOT wrong in its original study; it is wrong for this roster.

2. THE PROMPT IS THE PAPER'S, filled but never rewritten -- Bench to the Future, Appendix A.1,
   no-evidence variant, taken from forecast_prompts.BTF. Only the four documented placeholders are
   substituted. The `<research>` block is left EMPTY, which is what the no-evidence variant means.

3. THE RESOLUTION COLUMNS NEVER TOUCH THE PROMPT. BTF-3 ships `resolution`,
   `resolution_explanation` and `sota_summary_rationale`; the explanation is the answer in prose.
   Only question / background / resolution_criteria are rendered. item_validate's `outcome_leaked`
   rule re-checks this on the built corpus rather than trusting this script.

Offline apart from nothing -- reads the local parquet. No network, no spend.
"""
import argparse
import collections
import hashlib
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import forecast_prompts as FP      # noqa: E402
import item_validate as IV         # noqa: E402
import manifest as MF              # noqa: E402

PARQUET = os.path.join(HERE, "data", "btf", "btf3_binary_questions_and_forecasts.parquet")
DRAW_SEED = 20260808
# Prompt-length bands, as TERTILE CUTS MEASURED ON THE POOL, not round numbers picked by eye.
N_LENGTH_BANDS = 3


def render(row, today):
    """The paper's template, filled. Nothing else."""
    return FP.BTF.format(question=row["question"], background=row["background"],
                         resolution_criteria=row["resolution_criteria"], today=today)


def build_pool():
    d = pd.read_parquet(PARQUET)
    d = d.assign(flen=d.question.str.len() + d.background.str.len() + d.resolution_criteria.str.len())
    cuts = [d.flen.quantile(i / N_LENGTH_BANDS) for i in range(1, N_LENGTH_BANDS)]

    def band(n):
        return sum(1 for c in cuts if n > c)          # 0 = shortest third

    pool = []
    for r in d.to_dict("records"):
        today = str(r["present_date"])[:10]
        prompt = render(r, today)
        outcome = int(r["resolution"])
        pool.append({
            "item_id": f"btf3-{r['question_id']}",
            "prompt": prompt,
            # the stratification the ANALYSIS needs: outcome (for the later accuracy read) x
            # prompt-length band (for the compliance read this study is actually making)
            "stratum": f"o{outcome}-L{band(r['flen'])}",
            "outcome": outcome,
            "length_band": band(r["flen"]),
            "field_chars": int(r["flen"]),
            "prompt_chars": len(prompt),
            "end_time": str(r["expected_resolution_date"])[:10],
            "ground_truth": outcome,
        })
    return pool, [int(c) for c in cuts]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=110,
                    help="110 = 100 target + 10 spares to absorb the expected 3-6%% unit loss "
                         "(owner 2026-08-08)")
    ap.add_argument("--seed", type=int, default=DRAW_SEED)
    ap.add_argument("--out", default=os.path.join(HERE, "runs", "btf3_items_110.json"))
    ap.add_argument("--tol", type=float, default=0.10)
    a = ap.parse_args()

    pool, cuts = build_pool()
    print(f"  pool: {len(pool)} of 1,515 binary questions (NO field cap -- see the module docstring)")
    print(f"  prompt length: min {min(i['prompt_chars'] for i in pool):,} "
          f"max {max(i['prompt_chars'] for i in pool):,} chars; tertile cuts at {cuts} field-chars")
    print(f"  strata in the pool: {dict(sorted(collections.Counter(i['stratum'] for i in pool).items()))}")

    # VALIDATE THE POOL BEFORE DRAWING. A corpus-wide defect (a leaked outcome, an unfilled
    # placeholder) must halt here, not after 110 items have been frozen on top of it.
    IV.require_valid(pool, where="BTF-3 pool", bench="btf3")
    print(f"  item validation: {len(pool)} items, 0 violations (bench=btf3, 9 rules)")

    picked, gate = MF.draw_items(pool, a.n, seed=a.seed, tol=a.tol, stratum="stratum")
    print(f"  BALANCE GATE PASSED on '{gate['stratum']}' at tol {gate['tol']}")
    for k in sorted(gate["pool_fracs"]):
        got = gate["draw_counts"].get(k, 0)
        print(f"    {k}: pool {gate['pool_fracs'][k]:.3f}  draw {got/a.n:.3f} ({got})")
    IV.require_valid(picked, where="BTF-3 drawn corpus", bench="btf3")

    json.dump(picked, open(a.out, "w"), indent=1)
    sha = hashlib.sha256(json.dumps(sorted(i["item_id"] for i in picked)).encode()).hexdigest()[:16]
    print(f"  -> {a.out}   {len(picked)} items   items_hash {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
