"""M6-T1/S1 — characterise the stored corpus: which records carry which fields.

WHY THIS IS A MEASUREMENT STEP, not a lookup. I already counted 594 full-capture and 417 pre-capture
earlier in the session. Hard-coding those numbers into a later test would make the test pass against
a corpus that had CHANGED -- the same class of error as computing a claim over records that cannot
support it. So the profile is re-derived from the files every time, and the acceptance in S3 asserts
against THIS output, never against a remembered figure.

Offline. No network. No spend.
"""
import collections
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# The fields that distinguish the two known record generations. A field that is PRESENT BUT NULL is
# treated as absent throughout: a `finish_reason: null` proves nothing about how a call finished.
PROBE_FIELDS = ["text", "raw", "reasoning", "finish_reason", "provider", "usage", "parsed",
                "completeness", "prompt_sha", "n_choices", "budget_trace", "cost"]


def has(rec, field):
    """Present AND non-empty. `usage: {}` and `finish_reason: null` both count as MISSING."""
    v = rec.get(field, None)
    if v is None:
        return False
    if isinstance(v, (str, list, dict)) and len(v) == 0:
        return False
    return True


def profile(pattern=None):
    pattern = pattern or os.path.join(HERE, "runs", "or_futurex_*", "records.jsonl")
    files = sorted(glob.glob(pattern))
    per_run, records = {}, []
    malformed = 0
    for f in files:
        rows = []
        for line in open(f):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                malformed += 1          # counted, never skipped silently
        per_run[os.path.basename(os.path.dirname(f))] = len(rows)
        records.extend(rows)

    ok = [r for r in records if r.get("ok") is True]
    # a record's SCHEMA is the set of probe fields it actually carries
    sig = collections.Counter()
    for r in ok:
        sig[tuple(sorted(f for f in PROBE_FIELDS if has(r, f)))] += 1

    field_counts = {f: sum(1 for r in ok if has(r, f)) for f in PROBE_FIELDS}
    # the two generations, defined by the field that separates them
    full = [r for r in ok if has(r, "text")]
    pre = [r for r in ok if not has(r, "text")]

    return {
        "files": len(files), "runs": per_run,
        "records_total": len(records), "records_ok": len(ok),
        "malformed_lines": malformed,
        "field_present_counts": field_counts,
        "generations": {
            "full_capture": {"n": len(full),
                             "defining_field": "text",
                             "also_carry": sorted(f for f in PROBE_FIELDS
                                                  if full and all(has(r, f) for r in full))},
            "pre_capture": {"n": len(pre),
                            "missing": sorted(f for f in PROBE_FIELDS
                                              if pre and not any(has(r, f) for r in pre))},
        },
        "distinct_schemas": [{"fields": list(k), "n": v} for k, v in sig.most_common()],
    }


def main():
    p = profile()
    out = os.path.join(HERE, "runs", "corpus_profile.json")
    json.dump(p, open(out, "w"), indent=1)
    g = p["generations"]
    print(f"  {p['records_total']} records in {p['files']} run(s); {p['records_ok']} ok; "
          f"{p['malformed_lines']} malformed line(s)")
    print(f"  full-capture : {g['full_capture']['n']:>5}  (all carry: "
          f"{', '.join(g['full_capture']['also_carry'])})")
    print(f"  pre-capture  : {g['pre_capture']['n']:>5}  (NONE carries: "
          f"{', '.join(g['pre_capture']['missing'])})")
    print(f"  distinct field-schemas: {len(p['distinct_schemas'])}")
    for s in p["distinct_schemas"]:
        print(f"      n={s['n']:<5} {', '.join(s['fields'])}")
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
