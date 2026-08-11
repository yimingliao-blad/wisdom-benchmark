"""M6-T7 (L-P) — duplicates and resume fidelity.

PLAIN ENGLISH: make sure one planned call cannot end up counted twice, and make sure resuming a run
neither re-buys work already done nor silently skips work never done.

WHAT THE MEASUREMENT FOUND (and how it corrected me). Across the 9 stored runs, 237 units appear
more than once. My first reading called 222 of them "disagreeing" -- that conflated a MISSING verdict
(older schema) with a DIFFERENT one. The real conflict count is 4:
    llama-3.1-8b      x3   COMPLETE vs NO_ANSWER / UNDECIDED
    gemini-3.5-flash  x1   COMPLETE vs TRUNCATED   (the known reader false positive)
Three of those are GENUINE MODEL NONDETERMINISM at temperature 0 -- the same model, the same item,
a different answer on a different day. That is a property of the subject, not a defect, and it is
exactly why a duplicate must never be resolved by picking one silently.

THE RULE, therefore, is scoped:
  * WITHIN one (manifest, run): a duplicate unit is an ERROR. The run should produce each unit once.
  * ACROSS runs: records belong to DIFFERENT observations. They are never concatenated implicitly;
    combining them is an explicit, named decision, because nondeterminism means the second
    observation is not a correction of the first.

RESUME KEYS ON unit_id, the manifest's own identity -- not on a (model, item, arm) tuple that
happens to agree with it today. Two definitions that agree and are never compared are the S5 failure.

Offline. No network. No spend.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manifest as MF  # noqa: E402
import completeness_review as CR  # noqa: E402  the verdict vocabulary, not a second copy of it


class PersistenceError(RuntimeError):
    """Raised on a duplicate within a run, or a resume key that cannot be trusted."""


def explain_gaps(manifest, records, faults=()):
    """Why is each planned unit not done? (Codex C9, M6-T23/S4.)

    Before M6-T23 a zero-delivery row accidentally answered this: a gap with a PROVIDER_ERROR row
    meant "asked, the network died", and a gap with nothing meant "never asked". Now that a failed
    call writes no record, every gap looks identical -- so something has to say which is which
    DELIBERATELY, or an operator cannot tell a correct resume from one about to re-buy paid work.

    Four kinds, and they are exhaustive over the planned set:
      done                  a delivered answer is stored
      infra_fault_unbought  a fault event names it; nothing was bought, so resume buys it
      model_paused          its model was paused, so it was never dispatched
      never_dispatched      no evidence either way -- the run stopped before reaching it
    """
    import completeness_review as CR
    planned = {u["unit_id"]: u for u in manifest["units"]}
    done = {record_unit_id(r) for r in records if CR.delivered_a_response(r)}
    faulted = {f.get("unit_id") for f in faults}
    paused = {f.get("model") for f in faults
              if (f.get("classification") or "").startswith(("api:", "transport:", "request:"))}
    out = collections.defaultdict(list)
    for uid, u in planned.items():
        if uid in done:
            out["done"].append(uid)
        elif uid in faulted:
            out["infra_fault_unbought"].append(uid)
        elif u["model"] in paused:
            out["model_paused"].append(uid)
        else:
            out["never_dispatched"].append(uid)
    counts = {k: len(v) for k, v in out.items()}
    assert sum(counts.values()) == len(planned), "the four kinds must partition the planned set"
    return {"counts": counts, "units": dict(out), "n_planned": len(planned)}


def transient_health(faults, window=None):
    """Aggregate transient rate (Codex C14, M6-T23/S4).

    The gap Codex found and I had not: many SHORT transients that each clear before the third retry
    never trigger a pause, yet can burn hours. A per-unit rule cannot see that; only a rate can.
    Reported per model and overall so a threshold can act on it.
    """
    rows = list(faults)[-window:] if window else list(faults)
    by = collections.Counter(f.get("model") for f in rows)
    kinds = collections.Counter(f.get("classification") for f in rows)
    return {"n_faults": len(rows), "by_model": dict(by.most_common()), "by_class": dict(kinds)}


def partition_by_manifest(manifest, records):
    """Split stored records against the CURRENT manifest -- the roster may have moved under them.

    Four buckets, because 'done or not' was too coarse in both directions (M6-T18):
      in_plan_answered    the unit is planned and the model's output was delivered   -> keep, skip
      in_plan_unanswered  the unit is planned but the call never delivered (D-OR-18) -> re-queue
      out_of_plan         the unit is not in the current manifest at all             -> KEEP, exclude
      misassociated       planned, but the stored prompt is not the planned one      -> always an error

    OUT_OF_PLAN is the roster-change case: records bought for a model since dropped. They are paid
    evidence of a superseded plan, so they are retained and reported, never deleted and never folded
    into a denominator they were not planned under.
    """
    by_unit = {u["unit_id"]: u for u in manifest["units"]}
    out = {"in_plan_answered": [], "in_plan_unanswered": [], "out_of_plan": [], "misassociated": []}
    for r in records:
        u = by_unit.get(record_unit_id(r))
        if u is None:
            out["out_of_plan"].append(r)
        elif r.get("prompt_sha") is not None and r.get("prompt_sha") != u["prompt_sha"]:
            out["misassociated"].append(r)
        elif CR.delivered_a_response(r):
            out["in_plan_answered"].append(r)
        else:
            out["in_plan_unanswered"].append(r)
    return out


def record_unit_id(rec):
    """The ONE key. Resume, duplicate detection and manifest lookup all use this same function, so
    they cannot drift apart the way a re-implemented tuple key would."""
    return MF.unit_id(rec.get("model"), rec.get("item_id"), rec.get("arm"))


def find_duplicates(records):
    """Return {unit_id: [records]} for every unit stored more than once. Data, never a silent dedup."""
    by = collections.defaultdict(list)
    for r in records:
        by[record_unit_id(r)].append(r)
    return {k: v for k, v in by.items() if len(v) > 1}


def bought_twice(records):
    """Units that were PAID FOR more than once -- the failure "a duplicate unit" was written to catch.

    D-OR-18 made a second row legitimate: a unit whose first attempt delivered nothing is re-queued,
    so after a resume the file can hold a PROVIDER_ERROR row and then the real answer. `find_duplicates`
    flags that, correctly, as a repeated unit -- but it is not a defect, and treating it as one would
    either fail every resumed run or push someone to delete the evidence of the failed attempt.

    The real error is paying twice. A row that never delivered cost nothing and is an ATTEMPT; only
    rows that delivered a response count toward this.

    Found 2026-08-10: the paid smoke re-queued two 403-killed units. gpt-5.5 answered on the retry
    (PROVIDER_ERROR then COMPLETE, $0.034 once); llama-3.1-8b failed again (two PROVIDER_ERRORs, $0.00
    twice). Neither was bought twice; the duplicate invariant said both were.
    """
    import completeness_review as CR   # local: keeps the module import graph acyclic
    out = {}
    for uid, rows in find_duplicates(records).items():
        delivered = [r for r in rows if CR.delivered_a_response(r)]
        if len(delivered) > 1:
            out[uid] = delivered
    return out


def verdict_conflicts(records):
    """Duplicates whose RECORDED verdicts genuinely differ -- ignoring records that carry none.

    A missing verdict is not a disagreement. Conflating the two overstated the problem 55x when I
    first measured it.
    """
    out = {}
    for uid, group in find_duplicates(records).items():
        vs = [r.get("completeness") for r in group if r.get("completeness") is not None]
        if len(vs) >= 2 and len(set(vs)) > 1:
            out[uid] = {"verdicts": sorted(set(vs)), "n": len(group),
                        "model": group[0].get("model"), "item_id": group[0].get("item_id")}
    return out


def require_unique_within_run(records, where="run"):
    """A single run must not PAY for a unit twice. (D-OR-25, fixed 2026-08-10.)

    This asserted on row-presence and was the THIRD reader of "duplicate" to do so. D-OR-22 had
    already corrected `find_duplicates`' semantics and the whole-corpus test and left this one --
    so the 2026-08-10 run crashed here after every paid call had completed, on 136 units of which
    ZERO were bought twice: 133 were an undelivered attempt followed by the answer, 3 were two
    undelivered attempts. It now calls `bought_twice`, the definition D-OR-22 established, instead
    of carrying its own.

    Legacy tolerance (Codex C10): old directories still hold zero-delivery rows, so they must be
    READABLE -- but such a row can never satisfy unit-complete, denominator membership, or this
    uniqueness check. `bought_twice` and `delivered_a_response` are what enforce that, in one place.
    """
    paid = bought_twice(records)
    if paid:
        ex = list(paid.items())[:3]
        raise PersistenceError(
            f"{where}: {len(paid)} unit(s) were PAID FOR more than once within a single run. A "
            f"delivered answer must be bought at most once; duplicates inflate any denominator "
            f"computed from it. First: {[(k, len(v)) for k, v in ex]}")
    return len(records)


def resume_state(manifest, records, strict=True):
    """What is left to do -- keyed on the manifest's own unit_id.

    strict=True (the default) REFUSES to resume when a stored record does not correspond to a planned
    unit. A record for an unplanned unit means the manifest changed under the run, and silently
    continuing would mix two different planned universes in one output file.
    """
    planned = {u["unit_id"] for u in manifest["units"]}
    done, attempted, unplanned = set(), set(), []
    for r in records:
        uid = record_unit_id(r)
        if uid not in planned:
            unplanned.append(uid)
        elif CR.delivered_a_response(r):
            done.add(uid)          # the model was heard from; never buy this again
        else:
            attempted.add(uid)     # D-OR-18: a row exists but no output came back -> still TODO
    if unplanned and strict:
        raise PersistenceError(
            f"refusing to resume: {len(unplanned)} stored record(s) are not in manifest "
            f"{manifest['manifest_id']}. The manifest changed under the run; resuming would mix two "
            f"planned universes in one output file. Start a new run directory, or supersede the "
            f"manifest deliberately.")
    return {"planned": len(planned), "done": len(done),
            "todo": sorted(planned - done), "unplanned": unplanned,
            # Reported, not buried: these units HAVE a stored row, so the old resume counted them
            # done. They are back in `todo` and the caller must be able to say how many and why.
            "requeued_undelivered": sorted(attempted - done)}


def assert_resume_key_matches_manifest(manifest, sample=None):
    """S5, stated concretely: the resume key and the manifest key agree TODAY and nothing checks it.

    This is that check. It recomputes the manifest's own unit_id from each unit's fields and asserts
    the round trip, so a change to either definition breaks loudly instead of silently skipping work.
    """
    units = manifest["units"] if sample is None else manifest["units"][:sample]
    for u in units:
        again = MF.unit_id(u["model"], u["item_id"], u["arm"])
        if again != u["unit_id"]:
            raise PersistenceError(
                f"resume key drift: manifest stores {u['unit_id']} for "
                f"({u['model']}, {u['item_id']}, {u['arm']}) but the key function now yields {again}")
    return len(units)


COMBINE_POLICIES = ("forbid", "explicit_latest", "explicit_all")


def combine_runs(record_sets, policy="forbid", note=None):
    """Combining observations from different runs is a NAMED DECISION, never a default.

    Nondeterminism means a second observation is not a correction of the first -- llama-3.1-8b
    answered one run and refused another on the same item. Concatenating silently would pick one by
    file order.
    """
    if policy not in COMBINE_POLICIES:
        raise PersistenceError(f"unknown combine policy {policy!r}; expected {COMBINE_POLICIES}")
    flat = [r for rs in record_sets for r in rs]
    if policy == "forbid":
        raise PersistenceError(
            "combining runs is forbidden by default: records from different runs are DIFFERENT "
            "observations, not corrections of one another. Choose 'explicit_latest' or "
            "'explicit_all' and record why.")
    if not note:
        raise PersistenceError(f"policy {policy!r} requires a written reason")
    if policy == "explicit_all":
        return {"records": flat, "policy": policy, "note": note, "n": len(flat)}
    keep = {}
    for r in flat:
        keep[record_unit_id(r)] = r          # last set wins, deliberately and on the record
    return {"records": list(keep.values()), "policy": policy, "note": note, "n": len(keep)}
