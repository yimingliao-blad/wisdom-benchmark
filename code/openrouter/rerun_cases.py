"""Re-run ONLY the units that failed, to verify a fix — not the whole smoke.

Owner 2026-08-08: "run the error cases only. It is not necessary to run all items."

The main runner works on a model x item x arm cross-product, which cannot express "just these five
units". Re-running 296 calls to re-test 5 is waste; it also re-buys ~290 calls that already
succeeded. This takes an explicit case list and runs exactly those, through the SAME code path
(call_with_escalation -> deterministic_verdict -> reader), so a pass here is evidence about the real
pipeline and not about a bespoke test harness.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/ra/Projects/claude/skills/llm-api")
import bench_formats as BF          # noqa: E402
import completeness_review as CR    # noqa: E402
import run_openrouter as RO         # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, help="JSON list of {model, item_id, arm}")
    ap.add_argument("--items", default=os.path.join(HERE, "runs", "fx_smoke4.json"))
    ap.add_argument("--models", default=os.path.join(HERE, "survey", "roster_refined.json"))
    ap.add_argument("--caps", default=os.path.join(HERE, "survey", "model_caps.json"))
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--max-spend", type=float, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=1,
                    help="Run each case N times. A transient failure needs repeats to show it is "
                         "fixed rather than merely absent this once.")
    ap.add_argument("--review", action="store_true", default=True)
    ap.add_argument("--out", default=os.path.join(HERE, "runs", "error_case_rerun.json"))
    a = ap.parse_args()

    cases = json.load(open(a.cases))
    items = {i["item_id"]: i for i in json.load(open(a.items))}
    roster = {m["id"]: m for m in json.load(open(a.models))}
    caps = json.load(open(a.caps))

    work = []
    for c in cases:
        if c["model"] not in roster:
            print(f"  SKIP {c['model']} — not in the current roster (already replaced/excluded)")
            continue
        if c["item_id"] not in items:
            raise SystemExit(f"HALT: item {c['item_id']} is not in {a.items}")
        for rep in range(a.repeats):
            work.append((c, rep))
    if not work:
        print("  nothing to re-run"); return
    print(f"  re-running {len(work)} unit(s) = {len(work)//max(1,a.repeats)} case(s) "
          f"x {a.repeats} repeat(s), spend ceiling ${a.max_spend:.2f}")

    spent = [0.0]

    def one(job):
        c, rep = job
        mr, it = roster[c["model"]], items[c["item_id"]]
        prompt = BF.futurex_render(it, c["arm"])
        rec = {"model": mr["id"], "item_id": it["item_id"], "arm": c["arm"], "repeat": rep,
               "was": c.get("verdict"), "was_error": c.get("error")}
        t0 = time.time()
        try:
            txt, raw, cost, trace = RO.call_with_escalation(prompt, mr, a.max_tokens, caps[mr["id"]])
            spent[0] += cost
            rec.update({"cost": cost, "budget_trace": trace, "secs": round(time.time() - t0, 1)})
            if txt is None:
                rec.update({"ok": False, "completeness": "BUDGET_CAPPED",
                            "detail": trace[-1].get("detail")})
            else:
                ch0 = ((raw or {}).get("choices") or [{}])[0]
                u = (raw or {}).get("usage") or {}
                rec.update({"ok": True, "text": txt, "chars": len(txt), "usage": u,
                            "finish_reason": ch0.get("finish_reason"),
                            "provider": (raw or {}).get("provider"),
                            "parsed": BF.futurex_parse(txt)})
                v, why = CR.deterministic_verdict(rec)
                by = "layer1"
                if v == CR.UNDECIDED and a.review:
                    lv, rawreply, _ = CR.review(None, txt, None, c["arm"], tail=True)
                    v, by, why = (lv or CR.UNDECIDED), "layer2", (rawreply or "")[-100:]
                rec.update({"completeness": v, "completeness_by": by,
                            "completeness_reason": str(why)[:160]})
        except Exception as e:
            retryable, klass = RO.classify_error(e)
            rec.update({"ok": False, "completeness": "TRANSPORT_ERROR"
                        if getattr(e, "transport", False) else "PROVIDER_ERROR",
                        "error": type(e).__name__, "failure_class": getattr(e, "failure_class", klass),
                        "attempts_made": getattr(e, "attempts_made", None),
                        "gave_up_because": getattr(e, "gave_up_because", None),
                        "detail": str(e)[:220], "secs": round(time.time() - t0, 1)})
        print(f"    {rec['model']:<32} {rec['arm']:<5} rep{rep}  was={str(rec['was']):<14} "
              f"now={str(rec.get('completeness')):<15} {rec.get('secs')}s", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(one, work))
    json.dump(res, open(a.out, "w"), indent=1)
    fixed = [r for r in res if r.get("completeness") in CR.SCOREABLE]
    print(f"\n  ${spent[0]:.4f} spent -> {a.out}")
    print(f"  now SCOREABLE: {len(fixed)}/{len(res)}")
    for r in res:
        if r.get("completeness") not in CR.SCOREABLE:
            print(f"    STILL FAILING  {r['model']:<30} {r['arm']:<5} {r.get('completeness')} "
                  f"{str(r.get('detail'))[:90]}")


if __name__ == "__main__":
    main()
