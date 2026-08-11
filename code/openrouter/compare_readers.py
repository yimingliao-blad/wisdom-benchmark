"""Prompt x model comparison for the truncation reader.  [scope or-completeness-reviewer-2026-08-08]

Owner concern: too many rules may suppress the model's natural judgement, and qwen3-8b may be too
small. Two prompts (rule-heavy B vs minimal C) x two readers, on the 60-item ground truth PLUS the
real false positive from the M5 run.
"""
import hashlib, json, os, sys, time, collections, urllib.request
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
import completeness_review as CR

LOCAL = "http://localhost:8000/v1/chat/completions"
CACHE_PATH = "runs/reader_cache.json"
_CACHE = json.load(open(CACHE_PATH)) if os.path.exists(CACHE_PATH) else {}


def _key(model, variant, text):
    return f"{model}|{variant}|{hashlib.sha256((text or '').encode()).hexdigest()[:16]}"

def ask(model, prompt, max_tokens=1500, timeout=600):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens, "temperature": 0.0}).encode()
    req = urllib.request.Request(LOCAL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    ch = (d.get("choices") or [{}])[0]
    return ((ch.get("message") or {}).get("content")) or ""

def run_cell(model, builder, items, workers, variant="?"):
    def one(g):
        # FAIR PARSING. Variant C's prompt ENDS with "verdict:" as a completion cue, so the model
        # legitimately replies "complete" with no prefix. Scoring that as unreadable would blame the
        # prompt for my parser's assumption. Strip any <think> block, then look for the bare token.
        try:
            raw = ask(model, builder(g["text"]))
        except Exception as e:
            return f"ERR:{type(e).__name__}"
        import re as _re
        v = CR.parse_verdict(raw)
        if v: return v
        body = _re.sub(r"(?s)<think>.*?</think>", "", raw or "").strip()
        m = _re.search(r"\b(complete|truncated|unclear)\b", body, _re.I)
        return CR._MAP[m.group(1).lower()] if m else None
    def cached(g):
        k = _key(model, variant, g["text"])
        if k in _CACHE:
            return _CACHE[k]
        v = one(g)
        _CACHE[k] = v
        return v
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(cached, items))
    json.dump(_CACHE, open(CACHE_PATH, "w"))
    return out

def score(items, preds):
    fp = sum(1 for g, p in zip(items, preds) if g["gt"] == "COMPLETE" and p == CR.TRUNCATED)
    tr = [(g, p) for g, p in zip(items, preds) if g["gt"] == "TRUNCATED"]
    rec = sum(1 for g, p in tr if p == CR.TRUNCATED) / len(tr) if tr else 0
    comp = [(g, p) for g, p in zip(items, preds) if g["gt"] == "COMPLETE"]
    spec = sum(1 for g, p in comp if p == CR.COMPLETE) / len(comp) if comp else 0
    bad = sum(1 for p in preds if p is None or (isinstance(p, str) and p.startswith("ERR")))
    return {"recall_TRUNC": round(rec, 3), "specificity_COMPLETE": round(spec, 3),
            "false_positives": fp, "unreadable": bad}

if __name__ == "__main__":
    GT = json.load(open("runs/gt_completeness.json"))
    R = [json.loads(l) for l in open("runs/or_futurex_M5/records.jsonl") if l.strip()]
    # The subject is the false-positive SHAPE, not a vendor: a record the layer-2 reader called
    # TRUNCATED. Name a model with --fp-model to pin a specific one; otherwise take the first, and
    # SAY which was taken, so the sample is never silently different from the last run.
    fp_model = os.environ.get("FP_MODEL")
    cand = [r for r in R if r.get("completeness") == "TRUNCATED"
            and (fp_model is None or r["model"] == fp_model)]
    if not cand:
        raise SystemExit(f"HALT: no TRUNCATED record{' for ' + fp_model if fp_model else ''} in the "
                         f"corpus, so the false-positive case cannot be assembled.")
    gem = cand[0]
    print(f"  false-positive case taken from {gem['model']} / {gem['item_id']} "
          f"({len(cand)} TRUNCATED record(s) available)")
    GT = GT + [{"gt": "COMPLETE", "how": "THE REAL M5 FALSE POSITIVE", "text": gem["text"],
                "src_model": gem["model"], "arm": gem["arm"], "item_id": gem["item_id"]}]
    models = sys.argv[1].split(",") if len(sys.argv) > 1 else ["qwen3-8b"]
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    out = {}
    for m in models:
        for name, b in (("B_rule_heavy", CR.build_tail_prompt), ("C_minimal", CR.build_minimal_prompt)):
            t0 = time.time()
            preds = run_cell(m, b, GT, w, name)
            s = score(GT, preds)
            s["secs"] = round(time.time() - t0)
            s["gemini_case"] = str(preds[-1])
            out[f"{m} / {name}"] = s
            print(f"  {m:<18} {name:<14} {s}", flush=True)
            json.dump({k: v for k, v in out.items()}, open("runs/reader_comparison.json", "w"), indent=1)
