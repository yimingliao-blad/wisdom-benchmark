"""Forecasting benchmark: 4 prompt conditions x 3 models on resolved ForecastBench questions.

Two prompts are copied from the published sources (BTF Appendix A.1; ForecastBench's own repo), two are
the CoT variants we ran on the six capability benchmarks. The QUESTIONS are identical across conditions,
so PROMPT STYLE is the only variable.

SCORING is the Brier score, which both papers use: (forecast - outcome)^2. Lower is better; 0.25 is the
uninformed 0.5 forecast. An unparseable forecast is NOT scored as 0.5 or as wrong — it is its own outcome.

llama-2-13b has a 4,096-token TOTAL context and BTF's prompt runs to 6,777 chars, so its generation budget
is computed PER ITEM from the prompt length rather than fixed. A token is at least one character, so
chars/3 is a conservative-but-not-guaranteed estimate for English prose; the full error body is captured
if the server rejects one, because vLLM's 400 states the real token count.
"""
import argparse, concurrent.futures as cf, json, os, re, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forecast_prompts as FP

CTX = {"llama-2-13b-chat-gptq8": 4096, "llama-3.1-8b-instruct": 32768, "qwen3-8b": 32768}
FIXED = 4096


def budget(model, prompt):
    if CTX[model] > 8192:
        return FIXED
    est = len(prompt) // 3 + 64                      # conservative for prose; not a guarantee
    return max(256, CTX[model] - est)


def parse_prob(txt):
    """ForecastBench asks for *0.35*; BTF and our CoT variants ask for a bare final probability.
    Asterisk form first (their explicit contract), then the LAST number in [0,1] near the end."""
    if not txt:
        return None
    m = re.findall(r"\*\s*(\d*\.?\d+)\s*\*", txt)
    for x in reversed(m):
        try:
            v = float(x)
            if 0.0 <= v <= 1.0:
                return v
        except ValueError:
            pass
    tail = "\n".join([l for l in txt.strip().split("\n") if l.strip()][-4:])
    for chunk in (tail, txt):
        nums = re.findall(r"(?<![\d.])(\d*\.\d+|[01])(?![\d.])", chunk)
        for x in reversed(nums):
            try:
                v = float(x)
                if 0.0 <= v <= 1.0:
                    return v
            except ValueError:
                pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sample", default="runs/forecast_sample.json")
    a = ap.parse_args()
    qs = json.load(open(a.sample))["questions"]
    out_path = f"runs/forecast_{a.model}.jsonl"
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                done.add(json.loads(line)["key"])
            except Exception:
                pass
    from openai import OpenAI
    cl = OpenAI(base_url="http://localhost:8000/v1", api_key="x", timeout=900)
    fh = open(out_path, "a", encoding="utf-8")
    lock = threading.Lock()
    jobs = [(c, q) for c in FP.CONDITIONS for q in qs
            if f"{a.model}|{c}|{q['id']}" not in done]
    n = {"i": 0}

    def work(job):
        cond, q = job
        prompt = FP.render(cond, q)
        mt = budget(a.model, prompt)
        t = time.time()
        err = None
        try:
            kw = dict(model=a.model, temperature=0.0, max_tokens=mt, seed=0,
                      messages=[{"role": "user", "content": prompt}])
            if a.model.startswith("qwen3"):
                kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            r = cl.chat.completions.create(**kw)
            c = r.choices[0]
            txt, fin = c.message.content or "", c.finish_reason
        except Exception as e:
            txt, fin, err = "", f"ERROR:{type(e).__name__}", str(e)[:400]
        p = parse_prob(txt)
        brier = None if p is None else round((p - q["outcome"]) ** 2, 5)
        rec = {"key": f"{a.model}|{cond}|{q['id']}", "model": a.model, "condition": cond,
               "id": q["id"], "source": q["source"], "outcome": q["outcome"],
               "forecast": p, "brier": brier, "finish_reason": fin, "error": err,
               "max_tokens": mt, "prompt_chars": len(prompt), "trace_chars": len(txt),
               "latency_s": round(time.time() - t, 2), "trace": txt}
        with lock:
            fh.write(json.dumps(rec) + "\n"); fh.flush(); os.fsync(fh.fileno())
            n["i"] += 1
            if n["i"] % 25 == 0:
                print(f"    {n['i']}/{len(jobs)}", flush=True)

    if jobs:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(work, jobs))
    fh.close()
    print(f"OK  {out_path}  (+{n['i']})")


if __name__ == "__main__":
    main()
