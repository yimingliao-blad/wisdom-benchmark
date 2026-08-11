"""M6-T15 — turn a finished run directory into the DELIVERABLE, from its own artifacts.

PLAIN ENGLISH: read everything the run wrote, build the compliance table and the provenance bundle,
and refuse to publish if the run's own records say the result is not final yet.

WHY THIS EXISTS (Codex re-gate C2). The runner produced records and stopped. `analyze` and
`provenance` were tested but never called by the paid path -- the SAME class of gap as the 11
unwired modules, one layer further out: a green run could spend $31 and still not produce the
auditable deliverable the design promises, and the E8 guarantee (hash the output table) could be
skipped entirely by simply never building a table.

THREE THINGS IT FIXES:
  C2  the analysis table and provenance bundle are produced by the lifecycle, not by hand
  C4  quarantined units become CENSORED, not MISSING -- the quarantine manifest stores
      model/item_id/arm while the census keys on unit_id, so without this conversion the promised
      five-bucket partition silently misfiles every abandoned unit
  C6  the raw sidecar is checked ONE-TO-ONE against the records, so "rebuild without requery" is
      verified rather than assumed

PUBLISHABLE vs PROVISIONAL. If any record is still `pending_review` (a layer-1 provisional COMPLETE
awaiting post-run validation), this writes `analysis_table.provisional.json` and writes NO provenance
bundle. A provenance bundle is a publication act; it must not certify unreviewed guesses.

Offline. No network. No spend.  Run: python3 finalize.py runs/or_futurex_<tag>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze as AN          # noqa: E402
import manifest as MF         # noqa: E402
import provenance as PV       # noqa: E402
import schedule as SC         # noqa: E402
import spend as SP            # noqa: E402


class FinalizeError(RuntimeError):
    """Raised when the deliverable cannot be honestly produced from what the run wrote."""


def active_records_path(run_dir):
    """The records a report must read: the highest re-derived version, else the original.

    Named and PRINTED rather than silently resolved. A run whose derivations were corrected has two
    files on disk, and a report that quietly read the stale one would be worse than one that failed.
    """
    import glob as _g
    vs = sorted(_g.glob(os.path.join(run_dir, "records.v*.jsonl")),
                key=lambda f: int(f.rsplit(".v", 1)[1].split(".")[0]))
    return vs[-1] if vs else os.path.join(run_dir, "records.jsonl")


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path) if l.strip()]


def censored_from_quarantine(run_dir, manifest):
    """C4: quarantined units are CENSORED with a reason, never silently MISSING.

    The quarantine manifest lists units as (model, item_id, arm) because that is what the runner had
    in hand; the census keys on unit_id. Converting here is what keeps the five-bucket partition
    honest -- and a unit that is not in the manifest RAISES rather than being dropped.
    """
    qp = os.path.join(run_dir, "quarantine_manifest.json")
    if not os.path.exists(qp):
        return [], {}
    q = json.load(open(qp))
    planned = {u["unit_id"] for u in manifest["units"]}
    trigger = {m["model"]: m.get("first_verdict") for m in q.get("quarantined_models", [])}
    uids, unknown = [], []
    for u in q.get("units_to_rerun", []):
        uid = MF.unit_id(u["model"], u["item_id"], u["arm"])
        (uids.append(uid) if uid in planned else unknown.append(u))
    if unknown:
        raise FinalizeError(
            f"{len(unknown)} quarantined unit(s) are not in manifest {manifest['manifest_id']}: "
            f"{unknown[:3]}. Censoring a unit that was never planned would inflate the denominator.")
    cen = SC.censor(uids, "quarantined", trigger=json.dumps(trigger, sort_keys=True)[:200])
    return cen, trigger


def check_raw_sidecar(run_dir, records):
    """C6: the raw log must be rebuildable-from, which means one row per delivered response.

    Checked, not assumed. A duplicate row means two attempts collapsed onto one key; a record with a
    delivered body and no row means that call CANNOT be re-parsed without buying it again.
    """
    raw = _load_jsonl(os.path.join(run_dir, "raw_responses.jsonl"))
    by_attempt = {}
    dupes = []
    for r in raw:
        aid = r.get("attempt_id")
        if aid is None:
            dupes.append(("NO_ATTEMPT_ID", r.get("model"), r.get("item_id")))
            continue
        (dupes.append(("DUPLICATE", aid)) if aid in by_attempt else None)
        by_attempt[aid] = r
    rec_attempts = {r.get("attempt_id") for r in records}
    orphan_rows = sorted(set(by_attempt) - rec_attempts)
    # A body arrived iff the provider reported a finish_reason. Those, and only those, must have a row.
    need_row = {r["attempt_id"] for r in records if r.get("finish_reason") is not None}
    missing_rows = sorted(need_row - set(by_attempt))
    problems = []
    if dupes:
        problems.append(f"{len(dupes)} sidecar row(s) are unusable or duplicated: {dupes[:3]}")
    if orphan_rows:
        problems.append(f"{len(orphan_rows)} sidecar row(s) match no record: {orphan_rows[:3]}")
    if missing_rows:
        problems.append(f"{len(missing_rows)} record(s) received a response but have NO raw row, so "
                        f"they cannot be re-parsed without re-buying the call: {missing_rows[:3]}")
    return {"n_rows": len(raw), "n_records_needing_a_row": len(need_row), "problems": problems,
            "ok": not problems}


def finalize(run_dir, strict=True):
    """Build the deliverable from the run's OWN artifacts. Returns a summary dict."""
    need = ["manifest.json", "schedule.json", "records.jsonl"]
    missing = [f for f in need if not os.path.exists(os.path.join(run_dir, f))]
    if missing:
        raise FinalizeError(f"{run_dir} is not a finalizable run: missing {missing}")

    mani = json.load(open(os.path.join(run_dir, "manifest.json")))
    sched = json.load(open(os.path.join(run_dir, "schedule.json")))
    rec_path = active_records_path(run_dir)
    records = _load_jsonl(rec_path)
    # A RE-DERIVED VERSION GOES STALE THE MOMENT THE RUN IS EXTENDED (found 2026-08-08 when a
    # held-out stage appended 111 units to a run whose records.v1 held only the original 222).
    # finalize would then summarise the OLD subset while the sidecar and manifest carry the new
    # units -- a quietly partial deliverable. Refuse, and say exactly what to re-run.
    base = _load_jsonl(os.path.join(run_dir, "records.jsonl"))
    if os.path.basename(rec_path) != "records.jsonl" and len(base) != len(records):
        raise FinalizeError(
            f"{os.path.basename(rec_path)} holds {len(records)} record(s) but records.jsonl now "
            f"holds {len(base)}: the run was EXTENDED after that version was derived, so the "
            f"derived set is stale and would summarise only part of the run. Re-run:\n"
            f"    python3 rederive.py {run_dir} --why \"re-derive after extending the run\"")
    if os.path.basename(rec_path) != "records.jsonl":
        print(f"  using RE-DERIVED records: {os.path.basename(rec_path)} "
              f"(the original records.jsonl is retained as the audit trail)")

    sidecar = check_raw_sidecar(run_dir, records)
    if strict and not sidecar["ok"]:
        raise FinalizeError("the raw response sidecar is not one-to-one with the records, so the "
                            "run is not rebuildable without re-buying calls:\n  - "
                            + "\n  - ".join(sidecar["problems"]))

    censored, trigger = censored_from_quarantine(run_dir, mani)
    # A run stopped by its own spend ceiling ABANDONED its remaining units deliberately. That is a
    # censoring event with a reason, not "we have not got to them yet" -- folding it into MISSING
    # would hide a budget-truncated run behind the same bucket as an unstarted one.
    qp = os.path.join(run_dir, "quarantine_manifest.json")
    if os.path.exists(qp) and json.load(open(qp)).get("halted"):
        seen = {r.get("unit_id") for r in records} | {c["unit_id"] for c in censored}
        rest = [u["unit_id"] for u in mani["units"] if u["unit_id"] not in seen]
        if rest:
            censored = list(censored) + SC.censor(rest, "spend_ceiling",
                                                  trigger=json.load(open(qp)).get("halt_reason"))

    pending = [r for r in records if r.get("pending_review")]
    table = AN.per_model_table(mani, records, censored=censored, strict=strict,
                               allow_pending=bool(pending))
    # THE SECOND HALF OF THE GOAL (M6-T21/S4). The study wants the answer AND how the model reached
    # it, so a deliverable that reports only compliance answers half the question. Split by which
    # stage supplied the reasoning -- a model that reasons only when asked is behaving differently
    # from one that always does, and a single blended rate hides exactly that.
    table["reasoning_coverage"] = AN.reasoning_coverage(
        records, models={u["model"] for u in mani["units"]})
    out = {"run_dir": run_dir, "n_records": len(records), "n_censored": len(censored),
           "n_pending_review": len(pending), "sidecar": sidecar,
           "provisional": bool(pending), "provenance": None}

    if pending:
        # A provenance bundle CERTIFIES a result. Certifying unreviewed guesses is the failure
        # C3 names, so the bundle is withheld and the table is named for what it is.
        tp = os.path.join(run_dir, "analysis_table.provisional.json")
        AN.save(table, tp)
        out["table_path"] = tp
        out["next_action"] = (f"{len(pending)} record(s) pending review -> run: "
                              f"python3 review_pending.py {rec_path}   then finalize again")
        return out

    tp = os.path.join(run_dir, "analysis_table.json")
    AN.save(table, tp)
    out["table_path"] = tp

    ledger_path = os.path.join(run_dir, "ledger.json")
    ledger = (SP.Ledger.load(ledger_path, journal=os.path.join(run_dir, "ledger.jsonl"))
              if os.path.exists(ledger_path) else None)
    bundle = PV.build(mani, sched, table, rec_path,
                      raw_path=os.path.join(run_dir, "raw_responses.jsonl"),
                      ledger=ledger, censored=censored,
                      notes=f"finalized from {os.path.basename(run_dir)}")
    bp = os.path.join(run_dir, "provenance.json")
    if os.path.exists(bp):
        os.remove(bp)          # write-once guards the BUNDLE's content; re-finalizing is legitimate
    PV.save(bundle, bp)
    v = PV.verify(bundle, table=table, records_path=rec_path)
    if not v["ok"]:
        raise FinalizeError(f"the bundle does not verify against what it just bound: {v['mismatches']}")
    out["provenance"] = {"path": bp, "bundle_id": bundle["bundle_id"], "verified": True}
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 finalize.py runs/or_futurex_<tag>")
    r = finalize(sys.argv[1])
    print(f"  records {r['n_records']}  censored {r['n_censored']}  pending {r['n_pending_review']}")
    print(f"  sidecar: {r['sidecar']['n_rows']} row(s) for "
          f"{r['sidecar']['n_records_needing_a_row']} delivered response(s) — "
          + ("one-to-one" if r["sidecar"]["ok"] else "PROBLEMS"))
    print(f"  table -> {r['table_path']}")
    if r["provisional"]:
        print(f"  PROVISIONAL, no provenance bundle written.\n  {r['next_action']}")
    else:
        print(f"  provenance {r['provenance']['bundle_id']} -> {r['provenance']['path']} (verified)")
    print()
    print(AN.render(json.load(open(r["table_path"])), top=15))


if __name__ == "__main__":
    main()
