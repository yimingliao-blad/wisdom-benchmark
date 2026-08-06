"""crowd-wisdom step 3 — capture each model's REASONING TRACE on 280 benchmark questions.

The goal is behavioural characterisation, not a leaderboard. What matters is the FULL trajectory: how the
model reasons, how long, whether it loops, whether it obeys the answer format. Accuracy is recorded where a
gold exists, but the trace is the product.

PER-MODEL BUDGETS, because the models have different hard limits (see the prompt-design artifact):
  llama-2-13b-chat-gptq8  max_tokens=2048  — its TOTAL context is 4,096 tokens
  llama-3.1-8b-instruct   max_tokens=4096  — truncates on AIME by LOOPING; doubling does not fix it

RESUMABLE per query: every completed answer is appended and fsynced, so a kill costs the in-flight item.
"""
import argparse, concurrent.futures as cf, hashlib, json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
BUDGET = {"llama-2-13b-chat-gptq8": 2900, "llama-3.1-8b-instruct": 4096, "qwen3-8b": 4096}   # 4k cap, owner 2026-08-05
COT = ("\n\nThink step by step, showing your reasoning. Then give your final answer on the last line, "
       "by itself, with no extra words.")


MARKUP = re.compile(r"[*_`$#]+")
PREFIX = re.compile(r"^\W*(the\s+)?(final|correct)?\s*answer\s*(is)?\s*[:\-]?\s*", re.I)


def clean(line):
    """Strip markdown/LaTeX decoration and an 'answer is' prefix. qwen3 returns '**Final Answer: B**'
    and llama returns 'The correct answer is B) ...' — neither obeys 'by itself, with no extra words'."""
    return PREFIX.sub("", MARKUP.sub(" ", line or "")).strip()


def answer_lines(txt, k=6):
    """The last k non-empty lines, cleaned, LAST FIRST. qwen3 can end on a bare '$$' with the answer on
    the line above, so the parser must walk back rather than trust the final line."""
    ls = [clean(l) for l in (txt or "").strip().split("\n") if l.strip()]
    return [l for l in ls[-k:][::-1] if l]


def last_line(txt):
    ls = answer_lines(txt, k=1)
    return ls[0] if ls else ""


def verdict(kind, gold, txt, finish):
    """TRUNCATED is its own outcome and is NEVER scored as wrong."""
    if finish == "length":
        return "TRUNCATED", None
    if not (txt or "").strip():
        return "EMPTY", None
    last = last_line(txt)
    if gold is None:
        return "UNSCORED", None                       # IFEval needs its official verifier; TruthfulQA a judge
    cands = answer_lines(txt)                       # last lines, cleaned, LAST FIRST
    if kind == "mcq":
        for c in cands:
            m = re.findall(r"\b([ABCD])\b", c.upper())
            if m:
                return "OK", m[-1] == gold
        m = re.findall(r"\b([ABCD])\b", txt.upper())
        return ("OK", m[-1] == gold) if m else ("NOPARSE", None)
    if kind == "integer":
        for c in cands:
            m = re.findall(r"-?\d+", c.replace(",", ""))
            if m:
                return "OK", (m[-1].lstrip("0") or "0") == (gold.lstrip("0") or "0")
        m = re.findall(r"-?\d+", txt.replace(",", ""))
        return ("OK", (m[-1].lstrip("0") or "0") == (gold.lstrip("0") or "0")) if m else ("NOPARSE", None)
    if kind == "exact":
        g = gold.strip().lower()
        return "OK", any(g == c.lower() or g in c.lower() for c in cands[:3])
    return "UNSCORED", None


def steps(txt):
    """A cheap chain-length proxy: numbered steps, or non-empty lines."""
    t = txt or ""
    n = len(re.findall(r"^\s*(?:step\s*)?\d+[\.\):]", t, flags=re.I | re.M))
    return n if n else len([l for l in t.split("\n") if l.strip()])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--sample", default=os.path.join(HERE, "runs", "sample_capped.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8,
                    help="vLLM batches; 8 is the measured optimum for these 8-13B models. "
                         "llama.cpp models would need 1 — see MODEL_THROUGHPUT.md.")
    a = ap.parse_args()
    mt = BUDGET.get(a.model)
    if mt is None:
        raise SystemExit(f"HALT: no probed budget for {a.model!r}. Probe it before running; "
                         f"known: {sorted(BUDGET)}")

    from openai import OpenAI
    cl = OpenAI(base_url="http://localhost:8000/v1", api_key="x", timeout=900)
    data = json.load(open(a.sample))
    out_path = a.out or os.path.join(HERE, "runs", f"traces_final_{a.model}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                done.add(json.loads(line)["key"])
            except Exception:
                continue
    fh = open(out_path, "a", encoding="utf-8")

    queries = [(b, it) for b, items in data["sets"].items() for it in items]
    if a.limit:
        queries = queries[:a.limit]
    t0 = time.time()
    lock = threading.Lock()
    pending = [(b, it) for b, it in queries
               if f"{a.model}|{it['id']}|{hashlib.sha256(it['prompt'].encode()).hexdigest()[:12]}" not in done]
    counter = {"n": 0}

    def work(job):
        bench, it = job
        key = f"{a.model}|{it['id']}|{hashlib.sha256(it['prompt'].encode()).hexdigest()[:12]}"
        s0 = time.time()
        try:
            kw = dict(model=a.model, temperature=0.0, max_tokens=mt, seed=0,
                      messages=[{"role": "user", "content": it["prompt"]}])
            if a.model.startswith("qwen3"):
                # PROBED 2026-08-05: with its <think> channel ON, qwen3 truncates GPQA and AIME at 4096
                # and runs 4x slower. OFF, it reasons visibly — the same condition the llamas are in,
                # which have no hidden channel. A private reasoning channel would break the comparison.
                kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            r = cl.chat.completions.create(**kw)
            c = r.choices[0]
            txt, finish, served = c.message.content or "", c.finish_reason, r.model
        except Exception as e:
            # KEEP THE FULL BODY. vLLM's 400 states the ACTUAL token count it computed, which is the only
            # ground truth for "did this prompt fit" — a chars/4 estimate was already falsified once
            # (gpqa-127 was predicted to fit at ~1,448 tokens and was rejected).
            txt, finish, served = "", f"ERROR:{type(e).__name__}", None
            err = str(e)[:600]
        else:
            err = None
        dt = time.time() - s0
        st, ok = verdict(it.get("kind"), it.get("gold"), txt, finish)
        rec = {"key": key, "model": a.model, "benchmark": bench, "id": it["id"],
               "max_tokens": mt, "status": st, "correct": ok, "finish_reason": finish,
               "served_by": served, "latency_s": round(dt, 2), "error": err,
               "trace_chars": len(txt), "chain_steps": steps(txt),
               "last_line": last_line(txt)[:200],
               "gold": (str(it.get("gold"))[:200] if it.get("gold") else None), "trace": txt}
        with lock:                                   # serialise the append so lines never interleave
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
            counter["n"] += 1
            if counter["n"] % 25 == 0:
                print(f"    {counter['n']}/{len(pending)}  {time.time()-t0:.0f}s", flush=True)

    if pending:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(work, pending))
    n = counter["n"]
    fh.close()
    print(f"OK  {out_path}  (+{n} new, {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
