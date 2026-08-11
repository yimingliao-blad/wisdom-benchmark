"""POST-RUN VALIDATION of the records the run accepted provisionally.

WHY THESE EXIST. Reviewing every call inline made the local reader the bottleneck: throughput fell
from 50 to 1.3 calls/min, which would have made the 7,200-call run 92 hours. So the run PROBES the
first N units of each (model, benchmark); if all N are clean it trusts the model and defers the
rest here (owner ruling 2026-08-08).

WHAT DEFERRAL DOES AND DOES NOT ASSUME. A deferred record already passed layer 1 -- every transport
and shape failure ruled out -- AND its text TERMINATES in the answer marker the prompt demanded.
That is strong, but it is not proof: the reader has caught a case layer 1 could not. So these are
`pending_review`, not "done", and the run prints an explicit instruction to run this script.

THIS SCRIPT NEVER OVERWRITES THE ORIGINAL VERDICT. It writes a SIDECAR keyed by (model, item, arm),
so the provisional decision and the reviewed decision stay separately auditable and a disagreement
is visible rather than silently resolved.

Run: python3 review_pending.py runs/or_futurex_<tag>/records.jsonl [--workers 4] [--limit N]
"""
import argparse
import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import completeness_review as CR  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--workers", type=int, default=4,
                    help="Concurrency against the LOCAL reader. Small: one GPU serves them all.")
    ap.add_argument("--limit", type=int, default=0, help="0 = every pending record")
    ap.add_argument("--out", default=None, help="sidecar path (default alongside the records)")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.records) if l.strip()]
    pend = [r for r in rows if r.get("pending_review")]
    if a.limit:
        pend = pend[:a.limit]
    if not pend:
        print(f"  no pending_review records in {a.records} — nothing deferred, nothing to validate")
        return
    print(f"  {len(pend)} deferred record(s) of {len(rows)} total, across "
          f"{len({r['model'] for r in pend})} model(s)")

    def one(r):
        # A reader failure is UNKNOWN, never a pass. It must not silently confirm a provisional
        # COMPLETE (D-OR-5: an error must not wear a result's clothes).
        try:
            v, raw, _fr = CR.review(None, r.get("text") or "", None, r["arm"], tail=True)
            return {"model": r["model"], "item_id": r["item_id"], "arm": r["arm"],
                    "provisional": r.get("completeness"), "reviewed": v or "UNREADABLE",
                    "reader_reply": (raw or "")[-160:]}
        except Exception as e:
            return {"model": r["model"], "item_id": r["item_id"], "arm": r["arm"],
                    "provisional": r.get("completeness"), "reviewed": "READER_UNAVAILABLE",
                    "reader_reply": f"{type(e).__name__}: {e}"[:160]}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(one, pend))
    out = a.out or os.path.join(os.path.dirname(a.records), "post_run_review.json")
    json.dump(res, open(out, "w"), indent=1)

    agree = [x for x in res if x["reviewed"] == x["provisional"]]
    disagree = [x for x in res if x["reviewed"] != x["provisional"]]
    unavailable = [x for x in res if x["reviewed"] in ("READER_UNAVAILABLE", "UNREADABLE")]
    print(f"  reviewed {len(res)} in {time.time() - t0:.0f}s -> {out}")
    print(f"    agree with the provisional verdict : {len(agree)}")
    print(f"    DISAGREE                           : {len(disagree)}")
    print(f"    reader unavailable / unreadable    : {len(unavailable)}")
    if disagree:
        print(f"    disagreement breakdown: "
              f"{dict(collections.Counter(x['reviewed'] for x in disagree))}")
        for x in disagree[:10]:
            print(f"      {x['model']:<38} {x['arm']:<8} provisional={x['provisional']} "
                  f"reviewed={x['reviewed']}")
    # FAIL LOUD on a material disagreement rate: the deferral assumption is that trusted models stay
    # clean. If they did not, the sampling was too optimistic and the run needs re-review in full.
    checked = len(res) - len(unavailable)
    rate = (len(disagree) - len([x for x in disagree if x in unavailable])) / checked if checked else 0
    if rate > 0.05:
        raise SystemExit(f"HALT: {rate:.1%} of deferred records disagree with their provisional "
                         f"verdict (threshold 5%). The probe-then-trust sampling was too optimistic "
                         f"for this run — review every record before publishing any result.")
    print(f"  disagreement rate {rate:.1%} (threshold 5%) — deferral held")


if __name__ == "__main__":
    main()
