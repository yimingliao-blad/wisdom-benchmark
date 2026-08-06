"""Find the generation budget at which truncation stops — MEASURED, not assumed.

Re-runs the items that truncated, at a budget near the model's context ceiling, and reports the
completion-length distribution. The budget for the real run is then set from the observed maximum plus
slack, NOT from a guess.

Items that still hit the cap at the ceiling do not terminate at all (repetition loops); those are a
countable residual to report as a rate, not a budget problem to spend more on.

RUN THIS ALONE. The gateway holds ONE model at a time; a probe fired while another job is switching
models returns 409 'a model switch is already in progress' and any answer it does return is suspect.
"""
import argparse, json, os, statistics, sys, time

CEILING = {"llama-3.1-8b-instruct": 30000,      # max_model_len 32,768
           "llama-2-13b-chat-gptq8": 2600}      # max_model_len  4,096 — HARD, prompts take ~1,450

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--traces", default=None)
    ap.add_argument("--sample", default="runs/sample_300.json")
    ap.add_argument("--n", type=int, default=12, help="worst truncated items to re-run")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cap = CEILING[a.model]
    traces = a.traces or f"runs/traces_{a.model}.jsonl"
    rows = [json.loads(l) for l in open(traces)]
    trunc = [r for r in rows if r["status"] == "TRUNCATED"]
    print(f"{a.model}: {len(trunc)}/{len(rows)} truncated ({100*len(trunc)/len(rows):.1f}%)")
    if not trunc:
        print("  nothing truncated — the current budget already suffices"); return
    byid = {it["id"]: it for _b, items in json.load(open(a.sample))["sets"].items() for it in items}
    worst = sorted(trunc, key=lambda r: -r["trace_chars"])[:a.n]

    from openai import OpenAI
    import concurrent.futures as cf
    cl = OpenAI(base_url="http://localhost:8000/v1", api_key="x", timeout=3600)

    def run(r):
        it = byid[r["id"]]
        t = time.time()
        try:
            rr = cl.chat.completions.create(model=a.model, temperature=0.0, max_tokens=cap, seed=0,
                                            messages=[{"role": "user", "content": it["prompt"]}])
            c = rr.choices[0]
            return r, c.finish_reason, len(c.message.content or ""), time.time() - t
        except Exception as e:
            return r, f"ERROR:{type(e).__name__}", 0, time.time() - t

    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(run, worst))
    print(f"\n  re-ran the {len(res)} longest truncated items at max_tokens={cap}:")
    for r, fin, ch, dt in sorted(res, key=lambda x: -x[2]):
        print(f"    {r['benchmark']:<16} {r['trace_chars']:>7}ch@{r['max_tokens']} -> {ch:>7}ch  "
              f"{fin:<8} {dt:6.0f}s")
    done = [x for x in res if x[1] == "stop"]
    still = [x for x in res if x[1] == "length"]
    print(f"\n  COMPLETED at {cap}: {len(done)}/{len(res)}")
    if done:
        L = sorted(x[2] for x in done)
        print(f"    completed chars: min={L[0]} median={statistics.median(L):.0f} max={L[-1]}")
        print(f"    => a budget covering the observed max needs ~{L[-1]//4} tokens + slack")
    print(f"  STILL CAPPED at {cap}: {len(still)}  <- these do NOT terminate; more budget cannot fix them")
    json.dump([{"id": r["id"], "benchmark": r["benchmark"], "finish": fin, "chars": ch, "sec": round(dt,1)}
               for r, fin, ch, dt in res], open(f"runs/budget_probe_{a.model}.json", "w"), indent=1)

if __name__ == "__main__":
    main()
