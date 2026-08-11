"""Recompute a run's DERIVED fields from its stored text, without re-buying a single call.

Run: python3 rederive.py runs/or_futurex_<tag> [--why "reason"]

WHY THIS EXISTS. A record has two kinds of field: OBSERVATIONS (what the provider sent -- text,
reasoning, finish_reason, usage) and DERIVATIONS (what our code concluded -- parsed, completeness,
interpretability). When a derivation bug is fixed, the observations are still perfectly good; only
the conclusions are stale. Re-buying 222 calls to recompute a regex would be absurd, and the owner's
raw-response sidecar was added for exactly this: "log the raw http response, so we can rebuild if
something is wrong without requery."

IT WRITES A NEW VERSION, NEVER AN IN-PLACE EDIT. records.jsonl stays as the original observation;
the corrected set lands in records.v<N>.jsonl with a sibling rederive.v<N>.json recording what
changed, why, and which code produced it. A silent overwrite would destroy the audit trail that
makes the earlier run reproducible -- and would quietly erase the evidence of the defect.

Offline. No network. No spend.
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_formats as BF          # noqa: E402
import completeness_review as CR    # noqa: E402

DERIVED = ("parsed", "compliant", "completeness", "completeness_by", "completeness_reason",
           "scoreable", "answer_extractable", "answer_interpretable", "answer_kind",
           "answer_value", "answer_uninterpretable_why")


def rederive_one(rec, item_prompt, bench):
    """Recompute every derived field from the record's OWN stored text. Observations untouched."""
    out = dict(rec)
    text = rec.get("text") or ""
    if rec.get("completeness_prelabel"):
        verdict, why, by = rec["completeness_prelabel"], rec.get("detail"), "runner"
    else:
        verdict, why = CR.deterministic_verdict({**rec, "bench": bench})
        by = "layer1"
        # A record whose ORIGINAL verdict came from the reader keeps that judgement, because the
        # reader cannot be re-run for free. But it is re-reconciled against the facts (D-OR-6).
        if rec.get("completeness_by", "").startswith("layer2") and verdict == CR.UNDECIDED:
            verdict, by = rec["completeness"], rec["completeness_by"]
            why = rec.get("completeness_reason")
            verdict, override = CR.reconcile_layer2({**rec, "bench": bench}, verdict, bench)
            if override:
                out["layer2_overruled"] = {"said": rec["completeness"], "reason": override}
                by, why = "layer2-overruled", override[:160]
    p = BF.futurex_parse(text) if bench == "futurex" else BF.btf_parse(text)
    out["parsed"] = p
    out["answer_extractable"] = bool(p.get("compliant"))
    out["completeness"] = verdict
    out["completeness_by"] = by
    out["completeness_reason"] = why
    out["scoreable"] = verdict in CR.SCOREABLE
    out["compliant"] = (True if verdict == CR.COMPLETE else
                        False if verdict == CR.NO_ANSWER else None)
    if bench == "futurex" and item_prompt:
        iv = BF.interpret_answer(p.get("raw_box"), item_prompt)
        out["answer_interpretable"] = iv["interpretable"]
        out["answer_kind"] = iv["kind"]
        out["answer_value"] = iv["value"]
        out["answer_uninterpretable_why"] = iv["why"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--why", default="a derivation bug was fixed; observations are unchanged")
    a = ap.parse_args()

    rd = a.run_dir
    recs = [json.loads(l) for l in open(os.path.join(rd, "records.jsonl")) if l.strip()]
    items = {i["item_id"]: i for i in json.load(open(os.path.join(rd, "items.json")))}
    mani = json.load(open(os.path.join(rd, "manifest.json")))
    bench = mani.get("bench", "futurex")

    n = 1 + len(glob.glob(os.path.join(rd, "records.v*.jsonl")))
    out_path = os.path.join(rd, f"records.v{n}.jsonl")

    new, changes = [], collections.Counter()
    diffs = []
    for r in recs:
        it = items.get(r.get("item_id")) or {}
        u = rederive_one(r, it.get("prompt"), bench)
        new.append(u)
        d = [f for f in DERIVED if r.get(f) != u.get(f)]
        if d:
            changes.update(d)
            diffs.append({"unit_id": r.get("unit_id"), "model": r.get("model"),
                          "fields": d,
                          "completeness": [r.get("completeness"), u.get("completeness")]})
    with open(out_path, "w") as f:
        for r in new:
            f.write(json.dumps(r) + "\n")

    code = {fn: hashlib.sha256(open(os.path.join(HERE, fn), "rb").read()).hexdigest()[:16]
            for fn in ("bench_formats.py", "completeness_review.py")}
    meta = {"version": n, "source": "records.jsonl", "output": os.path.basename(out_path),
            "why": a.why, "bench": bench, "n_records": len(recs),
            "n_records_changed": len(diffs), "fields_changed": dict(changes),
            "verdict_shifts": dict(collections.Counter(
                f"{d['completeness'][0]} -> {d['completeness'][1]}" for d in diffs
                if d["completeness"][0] != d["completeness"][1])),
            "code_sha": code, "examples": diffs[:5],
            "note": ("OBSERVATIONS (text, reasoning, finish_reason, usage, prompt_sha) are copied "
                     "verbatim and never recomputed. Only DERIVED fields change. The original "
                     "records.jsonl is left intact as the audit trail.")}
    json.dump(meta, open(os.path.join(rd, f"rederive.v{n}.json"), "w"), indent=1)
    print(f"  {len(recs)} records -> {out_path}")
    print(f"  changed: {len(diffs)} record(s); fields {dict(changes) or 'none'}")
    print(f"  verdict shifts: {meta['verdict_shifts'] or 'none'}")
    print(f"  original records.jsonl left intact; provenance -> rederive.v{n}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
