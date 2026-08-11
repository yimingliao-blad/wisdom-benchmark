"""Summarise both benchmark families into flat CSV/JSON, with the metrics stated per prompt condition.

WHAT EACH METRIC MEANS HERE, because they are not interchangeable:
  * Brier   — (forecast - outcome)^2 for PROBABILITY output. Lower better. MUST be read against the
              base rate: on a set that is 17% yes, anything emitting low numbers scores well regardless
              of skill. The always-base-rate Brier is printed alongside for exactly this reason.
  * ROC-AUC — rank quality of the probabilities, THRESHOLD-FREE and BASE-RATE-INVARIANT. This is the
              metric that survives the imbalance: 0.5 = no discrimination, 1.0 = perfect ranking.
              It is the honest headline for forecasting; Brier conflates ranking with calibration.
  * accuracy / recall / precision — need a THRESHOLD, taken at 0.5. On a 17%-yes set a model that always
              says "no" scores 0.825 accuracy with 0.0 recall, so accuracy alone is meaningless here and
              recall is reported beside it.
  * parse / truncation rate — an unparseable or truncated answer is ITS OWN OUTCOME, never scored as
              wrong and never imputed to 0.5.
For the capability benchmarks (GPQA/AIME/BBH/GAIA) the output is a discrete answer, so accuracy is the
metric and Brier/ROC do not apply.
"""
import csv, json, glob, os, re, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util as _u
_sp=_u.spec_from_file_location("ct", os.path.join(os.path.dirname(os.path.abspath(__file__)), "capture_traces.py"))
CT=_u.module_from_spec(_sp); _sp.loader.exec_module(CT)
SAMPLE={it["id"]: it for _b, items in json.load(open("runs/sample_capped.json"))["sets"].items() for it in items}


def extracted_answer(kind, trace):
    """Re-derive the ANSWER the scorer read, so the row shows answer + gold + verdict together."""
    cands = CT.answer_lines(trace)
    if kind == "mcq":
        for c in cands:
            m = re.findall(r"\b([ABCD])\b", c.upper())
            if m: return m[-1]
        m = re.findall(r"\b([ABCD])\b", (trace or "").upper())
        return m[-1] if m else None
    if kind == "integer":
        for c in cands:
            m = re.findall(r"-?\d+", c.replace(",", ""))
            if m: return m[-1]
        m = re.findall(r"-?\d+", (trace or "").replace(",", ""))
        return m[-1] if m else None
    return cands[0] if cands else None


def roc_auc(scores, labels):
    """Rank-based AUC (Mann-Whitney U), ties averaged. None if one class is absent."""
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks, i = [0] * len(scores), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    rp = sum(r for r, l in zip(ranks, labels) if l == 1)
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


# The two forecast datasets must NEVER be pooled: base rates are 0.175 (ForecastBench) vs 0.450
# (BTF-3), so a pooled Brier/accuracy is a mixture of two different questions, not a result.
DEGENERATE = {  # (dataset, condition) -> why the cell cannot be interpreted
    ("btf3", "FB-zeroshot"): "BTF-3 has no market price; the FB price slot renders 'N/A'",
    ("btf3", "FB-cot-simple"): "BTF-3 has no market price; the FB price slot renders 'N/A'",
    ("btf3", "FB-cot-concise"): "BTF-3 has no market price; the FB price slot renders 'N/A'",
}


def dataset_of(r):
    return "btf3" if r.get("source") == "btf3" else "forecastbench"


def forecast_rows():
    out = []
    for p in sorted(glob.glob("runs/forecast_*.jsonl")):
        for line in open(p):
            r = json.loads(line)
            r["dataset"] = dataset_of(r)
            out.append(r)
    if not out:
        raise SystemExit("FATAL: no forecast rows found")
    seen = {(r["dataset"], r["condition"]) for r in out}
    unknown = {k for k in DEGENERATE if k not in seen}
    if unknown:  # fail loud rather than silently exclude nothing
        raise SystemExit(f"FATAL: DEGENERATE names cells that were never run: {sorted(unknown)}")
    return out


def capability_rows():
    out = []
    for p in sorted(glob.glob("runs/traces_final_*.jsonl")) + sorted(glob.glob("runs/traces_simple_*.jsonl")):
        arm = "concise" if "traces_final_" in p else "simple"
        for line in open(p):
            r = json.loads(line); r["arm"] = arm
            out.append(r)
    return out


def btf3_expert_baseline():
    """Score BTF-3's published expert forecast on OUR sampled questions.

    MECHANISM TRAP: the column is named `sota_forecast_probability` but its values are on a
    0-100 PERCENTAGE scale (observed range 2.0-97.0), not 0-1. Scoring it as a probability
    gives Brier 2504. It is divided by 100 here, and the range is asserted so a future
    upstream change to a real 0-1 scale fails loudly instead of silently dividing twice.
    """
    import math
    qs = json.load(open("runs/btf3_sample.json"))["questions"]
    raw = [(q["sota_forecast"], q["outcome"]) for q in qs
           if isinstance(q.get("sota_forecast"), (int, float)) and not math.isnan(q["sota_forecast"])]
    if not raw:
        raise SystemExit("FATAL: no usable BTF-3 expert forecasts")
    hi = max(p for p, _ in raw)
    if hi <= 1.0:
        raise SystemExit(f"FATAL: expert forecasts look like 0-1 already (max {hi}) - scale assumption broke")
    ok = [(p / 100.0, o) for p, o in raw]
    base = statistics.mean([o for _, o in ok])
    out = {
        "n_sampled": len(qs), "n_with_expert_forecast": len(ok),
        "scale_note": "source column is 0-100 despite the name; divided by 100 here",
        "expert_brier": round(statistics.mean([(p - o) ** 2 for p, o in ok]), 4),
        "expert_roc_auc": (lambda v: round(v, 4) if v is not None else None)(
            roc_auc([p for p, _ in ok], [o for _, o in ok])),
        "expert_accuracy": round(statistics.mean(
            [1.0 if (p >= .5) == (o == 1) else 0.0 for p, o in ok]), 4),
        "base_rate": round(base, 4),
        "base_rate_only_brier": round(statistics.mean([(base - o) ** 2 for _, o in ok]), 4),
    }
    json.dump(out, open("results/btf3_expert_baseline.json", "w"), indent=2)
    return out


def main():
    os.makedirs("results", exist_ok=True)

    # ---------- FORECASTING ----------
    F = forecast_rows()
    with open("results/forecast_rows.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "condition", "dataset", "question_id", "source",
                    "ANSWER_forecast", "GROUND_TRUTH_outcome", "COMPARISON_brier",
                    "correct@0.5", "finish_reason", "truncated", "parsed",
                    "REASONING_preview", "reasoning_chars", "prompt_chars", "latency_s"])
        for r in F:
            f = r["forecast"]
            corr = None if f is None else int((f >= .5) == (r["outcome"] == 1))
            w.writerow([r["model"], r["condition"], r["dataset"], r["id"], r["source"],
                        f, r["outcome"], r["brier"], corr, r["finish_reason"],
                        int(r["finish_reason"] == "length"), int(f is not None),
                        (r["trace"] or "").replace("\n", " ⏎ ")[:400],
                        r["trace_chars"], r["prompt_chars"], r["latency_s"]])
    with open("results/forecast_full.jsonl", "w") as fh:
        for r in F:
            fh.write(json.dumps({"model": r["model"], "condition": r["condition"],
                                 "dataset": r["dataset"], "question_id": r["id"],
                                 "answer_forecast": r["forecast"], "ground_truth": r["outcome"],
                                 "brier": r["brier"], "reasoning": r["trace"]}) + "\n")

    summ = []
    outs = {}
    for r in F:
        outs.setdefault((r["model"], r["dataset"], r["condition"]), []).append(r)
    for (m, d, c), rows in sorted(outs.items()):
        ok = [x for x in rows if x["forecast"] is not None]
        y = [x["outcome"] for x in ok]
        f = [x["forecast"] for x in ok]
        tp = sum(1 for a, b in zip(f, y) if a >= .5 and b == 1)
        fp = sum(1 for a, b in zip(f, y) if a >= .5 and b == 0)
        fn = sum(1 for a, b in zip(f, y) if a < .5 and b == 1)
        tn = sum(1 for a, b in zip(f, y) if a < .5 and b == 0)
        base = statistics.mean(y) if y else None
        summ.append({
            "family": "forecast", "model": m, "dataset": d, "condition": c,
            # A degenerate cell is REPORTED AND MARKED, never dropped — its numbers exist but
            # measure a prompt whose price slot rendered "N/A", so they are not comparable.
            "status": "DEGENERATE-EXCLUDED" if (d, c) in DEGENERATE else "ok",
            "exclusion_reason": DEGENERATE.get((d, c), ""),
            "n": len(rows),
            "parsed": len(ok), "parse_rate": round(len(ok) / len(rows), 4),
            "truncated": sum(1 for x in rows if x["finish_reason"] == "length"),
            "truncation_rate": round(sum(1 for x in rows if x["finish_reason"] == "length") / len(rows), 4),
            "errors": sum(1 for x in rows if x.get("error")),
            "brier": round(statistics.mean([x["brier"] for x in ok]), 4) if ok else None,
            "brier_base_rate_ref": round(statistics.mean([(base - o) ** 2 for o in y]), 4) if ok else None,
            "roc_auc": (lambda v: round(v, 4) if v is not None else None)(roc_auc(f, y)),
            "mean_forecast": round(statistics.mean(f), 4) if ok else None,
            "accuracy@0.5": round((tp + tn) / len(ok), 4) if ok else None,
            "recall@0.5": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "precision@0.5": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "f1@0.5": (lambda pr, rc: round(2 * pr * rc / (pr + rc), 4) if (pr and rc) else 0.0)(
                (tp / (tp + fp)) if (tp + fp) else 0.0, (tp / (tp + fn)) if (tp + fn) else 0.0),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "median_trace_chars": statistics.median([x["trace_chars"] for x in rows]),
            "median_latency_s": round(statistics.median([x["latency_s"] for x in rows]), 2),
        })

    # ---------- CAPABILITY ----------
    C = capability_rows()
    with open("results/capability_rows.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "arm", "benchmark", "question_id", "kind",
                    "ANSWER_extracted", "ANSWER_last_line", "GROUND_TRUTH_gold", "COMPARISON_correct",
                    "status", "finish_reason", "truncated",
                    "REASONING_preview", "reasoning_chars", "chain_steps", "latency_s"])
        for r in C:
            it = SAMPLE.get(r["id"], {})
            ans = extracted_answer(it.get("kind"), r.get("trace"))
            w.writerow([r["model"], r["arm"], r["benchmark"], r["id"], it.get("kind"),
                        ans, r["last_line"], r["gold"], r["correct"],
                        r["status"], r["finish_reason"], int(r["finish_reason"] == "length"),
                        (r.get("trace") or "").replace("\n", " ⏎ ")[:400],
                        r["trace_chars"], r["chain_steps"], r["latency_s"]])
    with open("results/capability_full.jsonl", "w") as fh:
        for r in C:
            it = SAMPLE.get(r["id"], {})
            fh.write(json.dumps({"model": r["model"], "arm": r["arm"], "benchmark": r["benchmark"], "question_id": r["id"],
                                 "question": it.get("q"), "kind": it.get("kind"),
                                 "answer_extracted": extracted_answer(it.get("kind"), r.get("trace")),
                                 "answer_last_line": r["last_line"], "ground_truth": r["gold"],
                                 "correct": r["correct"], "status": r["status"],
                                 "reasoning": r.get("trace")}) + "\n")
    grp = {}
    for r in C:
        grp.setdefault((r["model"], f'{r["benchmark"]}|{r["arm"]}'), []).append(r)
    for (m, b), rows in sorted(grp.items()):
        sc = [x for x in rows if x["correct"] is not None]
        summ.append({
            "family": "capability", "model": m, "condition": b, "n": len(rows),
            "parsed": len(sc), "parse_rate": round(len(sc) / len(rows), 4),
            "truncated": sum(1 for x in rows if x["status"] == "TRUNCATED"),
            "truncation_rate": round(sum(1 for x in rows if x["status"] == "TRUNCATED") / len(rows), 4),
            "errors": sum(1 for x in rows if str(x["finish_reason"]).startswith("ERROR")),
            "brier": None, "brier_base_rate_ref": None, "roc_auc": None, "mean_forecast": None,
            "accuracy@0.5": round(sum(1 for x in sc if x["correct"]) / len(sc), 4) if sc else None,
            "recall@0.5": None, "precision@0.5": None, "f1@0.5": None,
            "tp": None, "fp": None, "fn": None, "tn": None,
            "median_trace_chars": statistics.median([x["trace_chars"] for x in rows]),
            "median_latency_s": round(statistics.median([x["latency_s"] for x in rows]), 2),
        })

    with open("results/summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summ[0].keys()))
        w.writeheader()
        w.writerows(summ)
    json.dump(summ, open("results/summary.json", "w"), indent=1)
    print(f"  results/forecast_rows.csv    {len(F):,} rows")
    print(f"  results/capability_rows.csv  {len(C):,} rows")
    print(f"  results/forecast_full.jsonl  {len(F):,} rows WITH full reasoning")
    print(f"  results/capability_full.jsonl {len(C):,} rows WITH full reasoning")
    eb = btf3_expert_baseline()
    print(f"  results/summary.csv|json     {len(summ)} model x condition cells")
    print(f"  results/btf3_expert_baseline.json  expert Brier {eb['expert_brier']} "
          f"AUC {eb['expert_roc_auc']} on {eb['n_with_expert_forecast']}/{eb['n_sampled']}")


if __name__ == "__main__":
    main()
