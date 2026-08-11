"""Build the FutureX-Past item corpus. Run: python3 build_futurex_corpus.py [--check]

WHY THIS EXISTS: the 110-item draw was first done as an ad-hoc script, and it FORGOT THE
CONTAMINATION FILTER. 11 of the 110 items resolved before the anchor; the item validator caught it
and halted the paid run before a single call. An ad-hoc draw is not reproducible and repeats its own
mistakes, so the draw lives here with the filter built in.

THE ORDER MATTERS: filter to post-anchor FIRST, then draw. Filtering after the draw would either
shrink the sample below the target or bias it toward whatever the excluded items have in common.

The prompt is the dataset's own `prompt` column, passed through byte-for-byte -- never rebuilt.
"""
import argparse
import collections
import hashlib
import json
import os
import random
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import item_validate as IV      # noqa: E402
import manifest as MF           # noqa: E402

PARQUET = os.path.join(HERE, "data", "futurex", "past", "data", "train-00000-of-00001.parquet")
DRAW_SEED = 20260808


def build_pool():
    fx = pd.read_parquet(PARQUET)
    pool = [{"item_id": f"{r['id']}|{r['end_time']}", "prompt": r["prompt"],
             "level": int(r["level"]), "end_time": str(r["end_time"]),
             "ground_truth": r.get("ground_truth")}
            for r in fx.to_dict("records")]
    post = [i for i in pool if str(i["end_time"])[:10] >= IV.ANCHOR]
    return pool, post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=110,
                    help="110 = 100 target + 10 spares for the expected 3-6%% unit loss")
    ap.add_argument("--seed", type=int, default=DRAW_SEED)
    ap.add_argument("--slice", type=int, default=6, help="the gated first stage, drawn from the n")
    ap.add_argument("--out", default=os.path.join(HERE, "runs", "fx_items_110.json"))
    ap.add_argument("--slice-out", default=os.path.join(HERE, "runs", "fx_smoke_slice6.json"))
    ap.add_argument("--check", action="store_true",
                    help="regenerate and assert it matches what is on disk, without writing")
    a = ap.parse_args()

    pool, post = build_pool()
    print(f"  pool {len(pool)}; resolves after the {IV.ANCHOR} anchor: {len(post)}; "
          f"excluded {len(pool) - len(post)} (a model may already know those answers)")
    IV.require_valid(post, where="FutureX post-anchor pool", bench="futurex")

    picked, gate = MF.draw_items(post, a.n, seed=a.seed)
    print(f"  BALANCE GATE PASSED on '{gate['stratum']}' at tol {gate['tol']}")
    for lv in sorted(gate["pool_fracs"]):
        got = gate["draw_counts"].get(lv, 0)
        print(f"    level {lv}: pool {gate['pool_fracs'][lv]:.3f}  draw {got/a.n:.3f} ({got})")
    IV.require_valid(picked, where="FutureX drawn corpus", bench="futurex")

    sl = random.Random(a.seed).sample(picked, a.slice)
    IV.require_valid(sl, where="FutureX gate slice", bench="futurex")

    if a.check:
        want = [i["item_id"] for i in json.load(open(a.out))]
        got = [i["item_id"] for i in picked]
        if want != got:
            print(f"  MISMATCH: {len(set(want) & set(got))}/{a.n} ids overlap")
            return 1
        print(f"  OK reproduces what is on disk exactly ({a.n}/{a.n} ids, in order)")
        return 0

    json.dump(picked, open(a.out, "w"), indent=1)
    json.dump(sl, open(a.slice_out, "w"), indent=1)
    sha = hashlib.sha256(json.dumps(sorted(i["item_id"] for i in picked)).encode()).hexdigest()[:16]
    print(f"  -> {a.out}   {len(picked)} items   items_hash {sha}")
    print(f"  -> {a.slice_out}   {len(sl)} items, levels "
          f"{dict(sorted(collections.Counter(i['level'] for i in sl).items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
