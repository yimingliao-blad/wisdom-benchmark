"""M6-T17/S3 — check every stored record against the UNTOUCHED HTTP body.

OWNER INSTRUCTION (2026-08-08): "compared with the raw http result".

WHY THIS IS DIFFERENT FROM EVERY OTHER CHECK. Every other check in this project reads fields the
runner wrote and asks whether they are consistent with each other. If the runner's parse is wrong,
they are all consistently wrong together -- two readers sharing one blind spot are ONE reader, and
their agreement proves nothing. This check re-derives each field FROM THE RAW BODY the provider
actually returned, independently of the runner's extraction, and diffs.

The failure it catches: a record that misrepresents what the provider sent -- the wrong choice read,
reasoning silently dropped, a finish_reason rewritten, usage numbers that do not match the billing
the ledger was built from.

Offline. Reads a finished run directory. No network. No spend.
Run: python3 verify_against_raw.py runs/or_futurex_<tag>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def load(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


def rederive(body):
    """Pull the fields straight out of the raw envelope, WITHOUT using the runner's helpers.

    Deliberately a second implementation. Calling response_schema.extract here would just re-run the
    code under test and agree with itself.
    """
    ch = (body or {}).get("choices") or []
    m = (ch[0].get("message") or {}) if ch else {}
    return {"text": m.get("content"),
            "reasoning": m.get("reasoning"),
            "finish_reason": ch[0].get("finish_reason") if ch else None,
            "native_finish_reason": ch[0].get("native_finish_reason") if ch else None,
            "provider": (body or {}).get("provider"),
            "n_choices": len(ch),
            "prompt_tokens": ((body or {}).get("usage") or {}).get("prompt_tokens"),
            "completion_tokens": ((body or {}).get("usage") or {}).get("completion_tokens")}


COMPARE = [
    ("text", lambda r: r.get("text"), "the answer text the record claims the model produced"),
    ("reasoning", lambda r: r.get("reasoning"), "the reasoning the record claims to have captured"),
    ("finish_reason", lambda r: r.get("finish_reason"), "how the provider said generation ended"),
    ("native_finish_reason", lambda r: r.get("native_finish_reason"), "the provider's own code"),
    ("provider", lambda r: r.get("provider"), "which upstream vendor served it"),
    ("n_choices", lambda r: r.get("n_choices"), "how many choices came back"),
    ("prompt_tokens", lambda r: (r.get("usage") or {}).get("prompt_tokens"), "billed input"),
    ("completion_tokens", lambda r: (r.get("usage") or {}).get("completion_tokens"), "billed output"),
]


def verify(run_dir):
    records = load(os.path.join(run_dir, "records.jsonl"))
    raws = load(os.path.join(run_dir, "raw_responses.jsonl"))
    if not records:
        raise SystemExit(f"HALT: no records in {run_dir}")
    by_attempt = {}
    for r in raws:
        by_attempt.setdefault(r.get("attempt_id"), []).append(r)

    dupes = {k: len(v) for k, v in by_attempt.items() if len(v) > 1}
    mismatches, checked, no_raw = [], 0, []
    for rec in records:
        rows = by_attempt.get(rec.get("attempt_id"))
        if not rows:
            # A record with no body is expected when the call never returned one (transport error,
            # budget cap). It is only a problem if the record claims a finish_reason.
            if rec.get("finish_reason") is not None:
                no_raw.append(rec.get("attempt_id"))
            continue
        body = rows[0].get("response")
        truth = rederive(body)
        checked += 1
        for field, getter, meaning in COMPARE:
            claimed, actual = getter(rec), truth[field]
            if claimed != actual:
                mismatches.append({
                    "attempt_id": rec.get("attempt_id"), "model": rec.get("model"),
                    "field": field, "meaning": meaning,
                    "record_says": (claimed[:120] + "..." if isinstance(claimed, str)
                                    and len(claimed) > 120 else claimed),
                    "raw_body_says": (actual[:120] + "..." if isinstance(actual, str)
                                      and len(actual) > 120 else actual)})
        # the prompt is part of the request contract, not the response
        if rows[0].get("prompt_sha") != rec.get("prompt_sha"):
            mismatches.append({"attempt_id": rec.get("attempt_id"), "model": rec.get("model"),
                               "field": "prompt_sha", "meaning": "the request that was sent",
                               "record_says": rec.get("prompt_sha"),
                               "raw_body_says": rows[0].get("prompt_sha")})
    return {"run_dir": run_dir, "n_records": len(records), "n_raw_rows": len(raws),
            "n_compared": checked, "n_fields_per_record": len(COMPARE) + 1,
            "duplicate_attempt_rows": dupes,
            "records_claiming_a_response_with_no_raw_row": no_raw,
            "mismatches": mismatches, "n_mismatches": len(mismatches),
            "ok": not mismatches and not dupes and not no_raw}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 verify_against_raw.py runs/or_futurex_<tag>")
    rep = verify(sys.argv[1])
    print(f"  {rep['n_compared']} of {rep['n_records']} record(s) compared against their raw body, "
          f"{rep['n_fields_per_record']} fields each "
          f"({rep['n_compared'] * rep['n_fields_per_record']} comparisons)")
    if rep["duplicate_attempt_rows"]:
        print(f"  DUPLICATE raw rows: {rep['duplicate_attempt_rows']}")
    if rep["records_claiming_a_response_with_no_raw_row"]:
        print(f"  RECORDS CLAIMING A RESPONSE WITH NO RAW ROW: "
              f"{rep['records_claiming_a_response_with_no_raw_row']}")
    for m in rep["mismatches"][:20]:
        print(f"  MISMATCH {m['model']} {m['field']}: record={m['record_says']!r} "
              f"raw={m['raw_body_says']!r}")
    out = os.path.join(sys.argv[1], "verify_against_raw.json")
    json.dump(rep, open(out, "w"), indent=1)
    print(f"  {'OK — every record matches the body the provider sent' if rep['ok'] else 'FAILED'}"
          f"  -> {out}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
