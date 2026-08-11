"""M6-T16 — the PAID SMOKE's acceptance criteria, as an executable checker.

PLAIN ENGLISH: after the small paid smoke runs, this reads its output and says, per criterion,
whether the design survived — and it can say NO.

WHY (Codex re-gate C12). The smoke was scoped to re-measure one number: the 94.2% reasoning rate
that justified dropping the CoT arm. Codex's finding was that a smoke which only confirms the wiring
is a smoke that CANNOT invalidate the design. The criteria below are the ones that can.

The smoke Codex specified: 37 models x 2 items x the original arm = 74 real calls, real roster, real
OpenRouter, the planned worker count, smoke mode with the reader on.

EACH CRITERION IS FAIL-LOUD AND NAMED. A criterion that cannot be evaluated returns UNKNOWN, never
PASS -- an unevaluated check reported as green is the failure this whole plan exists to prevent.

Offline (reads a finished run directory). Run: python3 smoke_acceptance.py runs/or_futurex_<tag>
"""
import collections
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_formats as BF          # noqa: E402
import completeness_review as CR    # noqa: E402
import finalize as FZ               # noqa: E402
import manifest as MF               # noqa: E402
import schedule as SC               # noqa: E402

# The premise the CoT-arm cut rests on: 294/312 = 94.2% of original-arm replies already contained
# reasoning. If the smoke lands materially below this, the cut is INVALIDATED and the run doubles.
REASONING_PREMISE = 0.942
REASONING_FLOOR = 0.85          # materially below -> the premise does not hold
REASONING_MIN_CHARS = 120


def wilson_lower(k, n, z=1.96):
    """95% lower confidence bound on a proportion.

    Codex C5, and it was RIGHT: the first version of A1 compared a POINT ESTIMATE against the
    premise and passed at 97.3% vs 94.2%. But 71/73 has a 95% Wilson interval of [0.906, 0.993] --
    the lower bound sits BELOW the premise, so the smoke had not actually established the claim it
    reported as PASS. Comparing a rate to a threshold without its interval is how a small sample
    launders noise into a decision.
    """
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / d


class Result:
    __slots__ = ("id", "verdict", "detail", "evidence")

    def __init__(self, id, verdict, detail, evidence=None):
        assert verdict in ("PASS", "FAIL", "UNKNOWN", "MEASURED")
        self.id, self.verdict, self.detail, self.evidence = id, verdict, detail, evidence or {}

    def as_dict(self):
        return {"id": self.id, "verdict": self.verdict, "detail": self.detail,
                "evidence": self.evidence}


def active_records_path(run_dir):
    """The records a report must read: the highest re-derived version, else the original.

    Named and PRINTED rather than silently resolved. A run whose derivations were corrected has two
    files on disk, and a gate that quietly read the stale one would be worse than one that failed.
    """
    import glob as _g
    vs = sorted(_g.glob(os.path.join(run_dir, "records.v*.jsonl")),
                key=lambda f: int(f.rsplit(".v", 1)[1].split(".")[0]))
    return vs[-1] if vs else os.path.join(run_dir, "records.jsonl")


def _load(run_dir, name):
    p = os.path.join(run_dir, name)
    if not os.path.exists(p):
        return None
    if name.endswith(".jsonl"):
        return [json.loads(l) for l in open(p) if l.strip()]
    return json.load(open(p))


def m1_reasoning_rate(records, **_):
    """A REPORTED MEASUREMENT, NOT A GATE (owner decision 2026-08-08).

    WHY IT STOPPED GATING, stated plainly so this is not mistaken for a gate weakened because it
    failed. A1 existed to test one premise: "94.2% of replies already contain reasoning, therefore
    dropping the CoT arm is safe." That premise was EVIDENCE FOR A DECISION. The owner has now made
    that decision on a different and stronger basis -- run each benchmark with its NATIVE prompt,
    exactly as published -- so there is no CoT arm to justify dropping, and the premise no longer
    needs to hold for the design to be right.

    Verified before this change: FutureX's native prompt asks for NO reasoning (it demands only the
    boxed answer) in 110/110 drawn items; BTF-3's native prompt REQUIRES reasoning, enumerating
    (a)-(e) before the answer, in 110/110. Adding a CoT arm to BTF-3 would have duplicated an
    instruction the benchmark already gives.

    It is still MEASURED and reported, because the owner's goal is an answer PLUS the model's
    reasoning ("we want to answer but also tell model how they did with answer"). It just does not
    decide go/no-go.
    """
    obs = [r for r in records if r.get("completeness") in CR.SCOREABLE]
    if not obs:
        return Result("M1", "UNKNOWN", "no observed replies to measure a reasoning rate over")
    def has_reasoning(r):
        return (len(r.get("reasoning") or "") >= REASONING_MIN_CHARS
                or len(r.get("text") or "") >= REASONING_MIN_CHARS)
    n = sum(1 for r in obs if has_reasoning(r))
    rate = n / len(obs)
    lower = wilson_lower(n, len(obs))
    n_items = len({r.get("item_id") for r in obs})
    ev = {"rate": round(rate, 4), "wilson_lower_95": round(lower, 4), "n_with_reasoning": n,
          "n_observed": len(obs), "n_distinct_items": n_items,
          "premise": REASONING_PREMISE, "floor": REASONING_FLOOR,
          "bare_models": sorted({r["model"] for r in obs if not has_reasoning(r)})}
    return Result("M1", "MEASURED",
                  f"reasoning present in {rate:.1%} of {len(obs)} observed replies "
                  f"(95% CI lower bound {lower:.1%}), over {n_items} item(s)", ev)


def a2_sidecar_one_to_one(records, run_dir=None, **_):
    """C6: every delivered response is re-parseable offline, so nothing must be re-bought."""
    s = FZ.check_raw_sidecar(run_dir, records)
    return Result("A2", "PASS" if s["ok"] else "FAIL",
                  "raw sidecar is one-to-one with the records" if s["ok"]
                  else "; ".join(s["problems"]), s)


def a3_ledger_reconciles(records, run_dir=None, **_):
    """C1: what the ledger says was paid must match what the records say was bought."""
    led = _load(run_dir, "ledger.json")
    journal = _load(run_dir, "ledger.jsonl") or []
    if led is None and journal:
        # The summary is written at the END of a run. A run that halted before it -- which is what a
        # loud failure looks like -- still has the per-charge JOURNAL, and that journal is the whole
        # reason C1 exists. Refusing to reconcile here would report "spend unknown" for a run whose
        # every charge is on disk, and would make a halted run un-auditable exactly when it matters.
        led = {"ceiling": None, "total": round(sum(e["actual"] for e in journal), 8),
               "entries": journal, "from": "journal"}
    if led is None:
        return Result("A3", "UNKNOWN",
                      "neither ledger.json nor ledger.jsonl; spend cannot be reconciled")
    paid = {e["attempt_id"] for e in led["entries"]} | {e["attempt_id"] for e in journal}
    billed = {r["attempt_id"] for r in records if r.get("cost")}
    missing = sorted(billed - paid)
    rec_total = round(sum(r.get("cost") or 0.0 for r in records), 8)
    gap = abs(rec_total - led["total"])
    ev = {"ledger_total": led["total"], "records_total": rec_total, "gap": round(gap, 8),
          "n_ledger": len(paid), "n_billed_records": len(billed), "unledgered": missing[:5],
          "source": led.get("from", "ledger.json")}
    if missing:
        return Result("A3", "FAIL", f"{len(missing)} billed call(s) are absent from the ledger; the "
                                    f"spend ceiling was understated by that much", ev)
    if gap > 1e-6:
        return Result("A3", "FAIL", f"ledger total ${led['total']:.4f} disagrees with the records' "
                                    f"${rec_total:.4f}", ev)
    src = "" if led.get("from") != "journal" else " (reconstructed from the per-charge journal, " \
                                                   "which is what it exists for)"
    return Result("A3", "PASS",
                  f"ledger reconciles with the records at ${led['total']:.4f}{src}", ev)


def a4_no_unhandled_schema(records, **_):
    """C12: a provider whose envelope breaks the contract must surface HERE, not in the full run."""
    bad = [r for r in records if r.get("completeness") == "SCHEMA_ERROR"]
    multi = [r for r in records if (r.get("n_choices") or 1) > 1]
    ev = {"n_schema_error": len(bad), "n_multi_choice": len(multi),
          "models": sorted({r["model"] for r in bad + multi})}
    if bad or multi:
        return Result("A4", "FAIL", f"{len(bad)} schema error(s) and {len(multi)} multi-choice "
                                    f"envelope(s): the contract does not cover these providers", ev)
    return Result("A4", "PASS", "every envelope satisfied the response contract", ev)


def a5_provider_errors_are_classified(records, **_):
    """The HTTP-200-with-finish_reason=error case, and every transport failure, must be TYPED."""
    unclassified = [r for r in records
                    if r.get("ok") is False and not (r.get("failure_class")
                                                     or r.get("completeness_prelabel"))]
    undecided = [r for r in records if r.get("completeness") == CR.UNDECIDED]
    ev = {"n_unclassified": len(unclassified), "n_undecided": len(undecided),
          "by_class": dict(collections.Counter(r.get("failure_class") for r in records
                                               if r.get("ok") is False))}
    if unclassified:
        return Result("A5", "FAIL", f"{len(unclassified)} failure(s) carry no classification -- an "
                                    f"error with no type cannot be acted on", ev)
    if undecided:
        return Result("A5", "FAIL", f"{len(undecided)} record(s) are UNDECIDED after the reader ran; "
                                    f"the smoke is where these get resolved, not the paid run", ev)
    return Result("A5", "PASS", "every failure is classified and nothing is UNDECIDED", ev)


def a6_per_provider_cap_held(records, run_dir=None, **_):
    """C5: the frozen cap must have bound the real run, not just the fixture."""
    sched = _load(run_dir, "schedule.json")
    if not sched:
        return Result("A6", "UNKNOWN", "no schedule.json; the dispatch policy cannot be checked")
    timed = [r for r in records if r.get("started_at") and r.get("ended_at")]
    if not timed:
        return Result("A6", "UNKNOWN",
                      "records carry no timestamps, so real overlap cannot be reconstructed")
    # Reconstruct the true maximum overlap per provider from the intervals themselves -- a sweep
    # over start/end events. This checks the cap on the run that actually happened, rather than
    # trusting that the semaphore was wired in.
    cap = sched["per_provider"]
    peak = {}
    by_prov = collections.defaultdict(list)
    for r in timed:
        by_prov[r.get("provider_group") or SC.provider_of(r["model"])].append(r)
    for prov, rs in by_prov.items():
        events = sorted([(r["started_at"], 1) for r in rs] + [(r["ended_at"], -1) for r in rs])
        cur = 0
        for _, delta in events:
            cur += delta
            peak[prov] = max(peak.get(prov, 0), cur)
    over = {p: n for p, n in peak.items() if n > cap}
    durs = sorted(r["duration_s"] for r in timed if r.get("duration_s") is not None)
    ev = {"per_provider_cap": cap, "observed_peak": peak, "global_workers": sched["global_workers"],
          "p50_s": durs[len(durs) // 2] if durs else None,
          "p95_s": durs[int(len(durs) * 0.95)] if durs else None,
          "max_s": durs[-1] if durs else None}
    if over:
        return Result("A6", "FAIL", f"the per-provider cap of {cap} was BREACHED on the real run: "
                                    f"{over}", ev)
    return Result("A6", "PASS", f"per-provider cap {cap} held on the real run (peak {peak}); "
                                f"latency p50 {ev['p50_s']}s p95 {ev['p95_s']}s max {ev['max_s']}s",
                  ev)


def a7_pending_review_resolved(records, **_):
    """C3: the smoke runs the reader on every unit, so nothing should remain provisional."""
    pend = [r for r in records if r.get("pending_review")]
    if pend:
        return Result("A7", "FAIL", f"{len(pend)} record(s) are still pending review after a smoke "
                                    f"that was supposed to validate every unit",
                      {"n": len(pend), "models": sorted({r["model"] for r in pend})[:5]})
    return Result("A7", "PASS", "no record is left provisional")


def a8_quarantine_became_censored(records, run_dir=None, **_):
    """C4: the promised five-bucket partition must hold on the real output."""
    t = (_load(run_dir, "analysis_table.json")
         or _load(run_dir, "analysis_table.provisional.json"))
    q = _load(run_dir, "quarantine_manifest.json") or {}
    if not t:
        return Result("A8", "UNKNOWN", "no analysis table was produced; the deliverable does not exist")
    tot = t["totals"]
    parts = (tot["OBSERVED"] + tot["UNOBSERVED"] + tot["NEEDS_INSPECTION"] + tot["CENSORED"]
             + tot["MISSING"])
    ev = {"partition": parts, "planned": tot["planned"], "CENSORED": tot["CENSORED"],
          "units_to_rerun": q.get("units_to_rerun_count", 0)}
    if parts != tot["planned"]:
        return Result("A8", "FAIL", f"the buckets sum to {parts} but {tot['planned']} were planned", ev)
    if q.get("units_to_rerun_count", 0) != tot["CENSORED"]:
        return Result("A8", "FAIL", f"{q.get('units_to_rerun_count')} unit(s) were quarantined but "
                                    f"{tot['CENSORED']} are CENSORED -- the rest are hiding in "
                                    f"MISSING", ev)
    return Result("A8", "PASS", f"the partition holds and {tot['CENSORED']} censored unit(s) are "
                                f"accounted for", ev)


def a9_deliverable_exists(records, run_dir=None, **_):
    """C2: a run that cannot produce its own table and bundle is an incomplete design."""
    t = os.path.exists(os.path.join(run_dir, "analysis_table.json"))
    b = os.path.exists(os.path.join(run_dir, "provenance.json"))
    if t and b:
        return Result("A9", "PASS", "the analysis table and a verified provenance bundle exist")
    if os.path.exists(os.path.join(run_dir, "analysis_table.provisional.json")):
        return Result("A9", "FAIL", "only a PROVISIONAL table exists: review_pending.py has not run, "
                                    "so nothing is publishable yet")
    return Result("A9", "FAIL", f"deliverable missing (table={t}, bundle={b})")


def a10_records_prove_their_request(records, run_dir=None, **_):
    """Misassociation: an answer filed against a question it was not asked."""
    mani = _load(run_dir, "manifest.json")
    if not mani:
        return Result("A10", "UNKNOWN", "no frozen manifest to check against")
    vr = MF.verify_records_against(mani, records)
    c = vr["counts"]
    if c.get("MISASSOCIATED") or c.get("UNPLANNED") or c.get("NO_HASH"):
        return Result("A10", "FAIL", f"{c}", c)
    return Result("A10", "PASS", f"every record proves its request ({c})", c)


def a11_verdicts_are_not_self_contradictory(records, **_):
    """Codex C1/C2: NOTHING in A1-A10 checked whether a verdict is CORRECT, so the smoke could clear
    with a broken detector -- and did. google/gemma-3-27b-it was labelled TRUNCATED while carrying
    finish_reason=stop, 554 completion tokens, coherent reasoning, and a parsed compliant answer.

    This does not measure verdict accuracy in general (that needs adjudication). It catches the
    contradictions a verdict can have with the record's OWN fields, which is cheap, deterministic,
    and would have caught the real defect.
    """
    bad = []
    for r in records:
        v = r.get("completeness")
        parsed_ok = bool((r.get("parsed") or {}).get("compliant"))
        stopped = r.get("finish_reason") == "stop"
        if v == "TRUNCATED" and stopped and parsed_ok:
            bad.append({"model": r.get("model"), "unit_id": r.get("unit_id"), "verdict": v,
                        "why": "finish_reason=stop AND a parsed compliant answer, yet TRUNCATED",
                        "decided_by": r.get("completeness_by")})
        if v == "NO_ANSWER" and parsed_ok:
            bad.append({"model": r.get("model"), "unit_id": r.get("unit_id"), "verdict": v,
                        "why": "an answer WAS extracted, yet NO_ANSWER",
                        "decided_by": r.get("completeness_by")})
        if v == "COMPLETE" and not parsed_ok:
            bad.append({"model": r.get("model"), "unit_id": r.get("unit_id"), "verdict": v,
                        "why": "COMPLETE with no extractable answer",
                        "decided_by": r.get("completeness_by")})
        if v in ("EMPTY_HTTP",) and (r.get("text") or "").strip():
            bad.append({"model": r.get("model"), "unit_id": r.get("unit_id"), "verdict": v,
                        "why": "EMPTY_HTTP with non-empty text",
                        "decided_by": r.get("completeness_by")})
    ev = {"n_contradictions": len(bad), "cases": bad[:5],
          "by_decider": dict(collections.Counter(b["decided_by"] for b in bad))}
    if bad:
        return Result("A11", "FAIL",
                      f"{len(bad)} verdict(s) contradict the record's own fields -- the detector is "
                      f"wrong on these, and no other criterion would notice", ev)
    return Result("A11", "PASS", "no verdict contradicts its own record's fields", ev)


def a12_answers_are_INTERPRETABLE(records, run_dir=None, **_):
    """Owner ruling 2026-08-08: the answer's evaluation is part of validation. An uninterpretable
    result is a BAD result, not a pass.

    Compliance asks "was it in the demanded shape". This asks "does it say anything". A model can
    emit a perfectly-formatted \boxed{maybe}, or name an option the question never offered, and
    satisfy every other criterion here.

    Re-derived from the run's own items.json rather than trusting the runner's stamp, and the two
    are compared -- a disagreement means one of them is broken.
    """
    mani = _load(run_dir, "manifest.json") or {}
    bench = mani.get("bench", "futurex")
    if bench == "btf3":
        # BTF's answer is a probability, not a boxed option -- a different question (Codex C2).
        done = [r for r in records if r.get("completeness") == "COMPLETE"]
        if not done:
            return Result("A12", "UNKNOWN", "no COMPLETE replies to evaluate")
        bad = []
        for r in done:
            v = BF.interpret_btf_answer(r.get("parsed"))
            if not v["interpretable"]:
                bad.append({"model": r.get("model"), "why": v["why"]})
        ev = {"n_complete": len(done), "n_uninterpretable": len(bad), "cases": bad[:5],
              "by_kind": {"probability": len(done)}}
        if bad:
            return Result("A12", "FAIL", f"{len(bad)} of {len(done)} COMPLETE replies do not carry a "
                                         f"usable probability: {[b['why'] for b in bad[:2]]}", ev)
        return Result("A12", "PASS", f"all {len(done)} COMPLETE replies carry a probability in [0,1]",
                      ev)
    items = _load(run_dir, "items.json")
    if not items:
        return Result("A12", "UNKNOWN",
                      "no items.json in the run dir, so answers cannot be re-checked against the "
                      "questions they answer")
    by_id = {i["item_id"]: i for i in items}
    done = [r for r in records if r.get("completeness") == "COMPLETE"]
    if not done:
        return Result("A12", "UNKNOWN", "no COMPLETE replies to evaluate")
    bad, disagree = [], []
    for r in done:
        it = by_id.get(r.get("item_id"))
        if not it:
            bad.append({"model": r.get("model"), "why": "item not in the run's own corpus"})
            continue
        v = BF.interpret_answer((r.get("parsed") or {}).get("raw_box"), it["prompt"])
        if not v["interpretable"]:
            bad.append({"model": r.get("model"), "item_id": r.get("item_id"),
                        "box": (r.get("parsed") or {}).get("raw_box"), "why": v["why"]})
        if r.get("answer_interpretable") is not None and \
                r["answer_interpretable"] != v["interpretable"]:
            disagree.append({"model": r.get("model"), "stamped": r["answer_interpretable"],
                             "rederived": v["interpretable"]})
    ev = {"n_complete": len(done), "n_uninterpretable": len(bad), "cases": bad[:5],
          "n_stamp_disagreements": len(disagree), "disagreements": disagree[:3],
          "by_kind": dict(collections.Counter(
              BF.expected_answer_type(by_id[r["item_id"]]["prompt"])
              for r in done if r.get("item_id") in by_id))}
    if disagree:
        return Result("A12", "FAIL", f"{len(disagree)} record(s) where the runner's stamp and the "
                                     f"re-derivation disagree -- one of them is broken", ev)
    if bad:
        return Result("A12", "FAIL",
                      f"{len(bad)} of {len(done)} COMPLETE replies are NOT interpretable as answers "
                      f"to their question: {[b['why'] for b in bad[:2]]}", ev)
    return Result("A12", "PASS", f"all {len(done)} COMPLETE replies are interpretable answers "
                                 f"({ev['by_kind']})", ev)


# PREDECLARED, not chosen after seeing the numbers (Codex C4). A run that loses too much of its
# planned denominator cannot support a compliance rate, however clean the survivors look.
MIN_COVERAGE = 0.95            # OBSERVED / attempted-in-this-stage
MAX_MODEL_LOSS = 0.34          # no single model may lose more than a third of its attempted units


def a13_denominator_loss_is_bounded(records, run_dir=None, **_):
    """Codex C4/C9: a spend ceiling protects dollars; it does not protect the DENOMINATOR.

    If a ceiling or a stall censors units mid-run, coverage silently drops and the surviving
    compliance rate is computed over whatever happened to finish -- which can be model-correlated.
    The 0.809 vs 0.982 gap is exactly the size of effect that unequal loss could manufacture, so the
    loss is bounded explicitly rather than inspected after the fact.
    """
    if not records:
        return Result("A13", "UNKNOWN", "no records")
    by_model = collections.defaultdict(lambda: {"n": 0, "obs": 0})
    for r in records:
        b = by_model[r.get("model")]
        b["n"] += 1
        b["obs"] += 1 if r.get("completeness") in CR.SCOREABLE else 0
    tot_n = sum(b["n"] for b in by_model.values())
    tot_o = sum(b["obs"] for b in by_model.values())
    cov = tot_o / tot_n if tot_n else 0.0
    worst = sorted(((b["obs"] / b["n"], m) for m, b in by_model.items()))[:3]
    lossy = [(m, round(1 - r, 3)) for r, m in ((b["obs"] / b["n"], m)
                                               for m, b in by_model.items())
             if (1 - r) > MAX_MODEL_LOSS]
    ev = {"coverage": round(cov, 4), "min_coverage": MIN_COVERAGE, "attempted": tot_n,
          "observed": tot_o, "worst_models": [(m, round(r, 3)) for r, m in worst],
          "models_over_loss_cap": lossy, "max_model_loss": MAX_MODEL_LOSS}
    if cov < MIN_COVERAGE:
        return Result("A13", "FAIL", f"only {cov:.1%} of attempted units were observed, below the "
                                     f"predeclared {MIN_COVERAGE:.0%} floor", ev)
    if lossy:
        return Result("A13", "FAIL", f"loss is MODEL-CORRELATED: {lossy} exceed the "
                                     f"{MAX_MODEL_LOSS:.0%} per-model cap, so the surviving rate is "
                                     f"not comparable across models", ev)
    return Result("A13", "PASS", f"coverage {cov:.1%} of attempted; worst model "
                                 f"{worst[0][1]} at {worst[0][0]:.1%}", ev)


CRITERIA = [a2_sidecar_one_to_one, a3_ledger_reconciles, a4_no_unhandled_schema,
            a5_provider_errors_are_classified, a6_per_provider_cap_held, a7_pending_review_resolved,
            a8_quarantine_became_censored, a9_deliverable_exists, a10_records_prove_their_request,
            a11_verdicts_are_not_self_contradictory, a12_answers_are_INTERPRETABLE,
            a13_denominator_loss_is_bounded]


# Reported every run, never gating. Kept apart from CRITERIA so a measurement can never be mistaken
# for a passed gate, and a gate can never be quietly demoted into a measurement.
MEASUREMENTS = [m1_reasoning_rate]


def evaluate(run_dir):
    rec_path = active_records_path(run_dir)
    records = _load(run_dir, os.path.basename(rec_path))
    if records is None:
        raise SystemExit(f"HALT: no records in {run_dir}")
    results = [f(records, run_dir=run_dir) for f in CRITERIA]
    measured = [f(records, run_dir=run_dir) for f in MEASUREMENTS]
    fails = [r for r in results if r.verdict == "FAIL"]
    unknown = [r for r in results if r.verdict == "UNKNOWN"]
    return {"run_dir": run_dir, "records_file": os.path.basename(rec_path),
            "n_records": len(records),
            "results": [r.as_dict() for r in results],
            "measurements": [m.as_dict() for m in measured],
            "n_pass": sum(1 for r in results if r.verdict == "PASS"),
            "n_fail": len(fails), "n_unknown": len(unknown),
            # An UNKNOWN is NOT a pass. Clearing the smoke requires every criterion evaluated.
            "cleared": not fails and not unknown}


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python3 smoke_acceptance.py runs/or_futurex_<tag>")
    rep = evaluate(sys.argv[1])
    print(f"  reading {rep['records_file']}")
    for r in rep["results"]:
        mark = {"PASS": "ok  ", "FAIL": "FAIL", "UNKNOWN": "????"}[r["verdict"]]
        print(f"  [{mark}] {r['id']:<4} {r['detail']}")
    for m in rep.get("measurements", []):
        print(f"  [ -- ] {m['id']:<4} {m['detail']}   (reported, not a gate)")
    print(f"\n  {rep['n_pass']} pass, {rep['n_fail']} fail, {rep['n_unknown']} unevaluated")
    print("  SMOKE CLEARED — the full run may proceed" if rep["cleared"] else
          "  SMOKE NOT CLEARED — an unevaluated criterion is NOT a pass; fix and re-run the smoke")
    json.dump(rep, open(os.path.join(sys.argv[1], "smoke_acceptance.json"), "w"), indent=1)
    return 0 if rep["cleared"] else 1


if __name__ == "__main__":
    sys.exit(main())
