"""M6-T4 (L-K) — freeze HOW the planned units are dispatched, and record what gets abandoned.

PLAIN ENGLISH: decide in advance the order we make the calls, how many at once per provider, and
what happens to units we give up on -- so a difference between two models cannot turn out to be a
difference in how we happened to call them.

WHAT THIS CORRECTS. run_openrouter.py already interleaves by provider, which makes this look solved.
It is not: the interleaving is RECOMPUTED at runtime from whatever work list survives resume, and is
never PERSISTED. Two runs of one manifest can dispatch differently and nothing records which order
produced a given result. A schedule you cannot replay is not a schedule.

CENSORING. Quarantine removes units the schedule promised to dispatch. That is censoring, and a
censored unit is RECORDED with a reason -- never left to look like absence. Coverage then reads
    PLANNED = OBSERVED + UNOBSERVED + NEEDS_INSPECTION + CENSORED
so an abandoned unit cannot hide inside "missing".

Offline. No network. No spend.
"""
import collections
import hashlib
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_SEED = 20260808
DEFAULT_GLOBAL_WORKERS = 16
# OpenRouter publishes NO per-provider limit for paid tier, so this is a CHOSEN, RECORDED parameter
# -- not a derived one. Recording it is the point: a future reader must know it was a decision.
DEFAULT_PER_PROVIDER = 4
POLICY_VERSION = "sched-v1"


class ScheduleError(RuntimeError):
    """Raised when a schedule is unfit to run. Never returned as a value."""


def provider_of(model_id):
    return model_id.split("/")[0]


def build(manifest, seed=SCHEDULE_SEED, global_workers=DEFAULT_GLOBAL_WORKERS,
          per_provider=DEFAULT_PER_PROVIDER):
    """Seeded permutation, then provider round-robin so no provider occupies a long consecutive run.

    Two properties the tests pin down: the order is reproducible from (manifest_id, seed), and it
    covers every unit EXACTLY once. A model-grouped order -- the natural one, and the seeded defect
    in the tests -- bursts a single provider for hundreds of consecutive calls.
    """
    units = list(manifest["units"])
    if not units:
        raise ScheduleError("manifest has no units")
    rng = random.Random(f"{manifest['manifest_id']}:{seed}")
    rng.shuffle(units)                                   # break any roster/item ordering first
    queues = collections.OrderedDict()
    for u in units:
        queues.setdefault(provider_of(u["model"]), []).append(u)
    # EVEN SPREAD, not naive round-robin. Round-robin only balances while every queue is non-empty:
    # with 100 items the queues are wildly unequal (google 5 models x 100 = 500 units, x-ai 200), so
    # the short queues exhaust and the long ones run CONSECUTIVELY. Measured on the real 3,700-unit
    # manifest: naive round-robin gave a 101-call single-provider burst, while the smoke fixture (4
    # items, near-equal queues) showed 12 and the test passed -- a fixture that could not exhibit the
    # failure. Each provider is instead spread evenly across [0,1) by fractional position, so the
    # spacing is proportional to its share regardless of queue length.
    keyed = []
    for q in queues.values():
        n = len(q)
        for i, u in enumerate(q):
            keyed.append(((i + 0.5) / n, u["unit_id"]))
    keyed.sort(key=lambda t: t[0])
    order = [uid for _, uid in keyed]
    if len(order) != len(units) or len(set(order)) != len(units):
        raise ScheduleError(f"dispatch order is not a permutation of the units "
                            f"({len(order)} slots, {len(set(order))} distinct, {len(units)} units)")
    sched = {"policy_version": POLICY_VERSION, "manifest_id": manifest["manifest_id"],
             "seed": seed, "global_workers": global_workers, "per_provider": per_provider,
             "n_units": len(order), "providers": {k: len(v) for k, v in queues.items()},
             "order": order}
    sched["schedule_id"] = hashlib.sha256(
        json.dumps({k: sched[k] for k in ("policy_version", "manifest_id", "seed", "order")},
                   sort_keys=True).encode()).hexdigest()[:16]
    return sched


def max_provider_run(schedule, manifest):
    """Longest consecutive stretch served by ONE provider. The burst metric the round-robin exists
    to bound; a model-grouped order scores in the hundreds."""
    by_unit = {u["unit_id"]: u for u in manifest["units"]}
    longest, cur, prev = 0, 0, None
    for uid in schedule["order"]:
        p = provider_of(by_unit[uid]["model"])
        cur = cur + 1 if p == prev else 1
        prev = p
        longest = max(longest, cur)
    return longest


def resume_order(schedule, completed_unit_ids):
    """Replay the SAME order minus what is done -- which is what makes two runs comparable."""
    done = set(completed_unit_ids)
    return [u for u in schedule["order"] if u not in done]


# ---------------------------------------------------------------- censoring
CENSOR_REASONS = ("quarantined", "spend_ceiling", "operator_stop", "escalation_exhausted")


def census(manifest, records, censored):
    """PLANNED = OBSERVED + UNOBSERVED + NEEDS_INSPECTION + CENSORED + MISSING.

    Every planned unit lands in exactly ONE bucket. A censored unit is never counted as missing, and
    missing is never used to absorb an abandonment we chose.
    """
    import completeness_review as CR
    planned = {u["unit_id"] for u in manifest["units"]}
    by_uid = {}
    import manifest as MF
    for r in records:
        by_uid[MF.unit_id(r.get("model"), r.get("item_id"), r.get("arm"))] = r
    cen = {c["unit_id"]: c for c in censored}
    # EVERY bucket present, always, even at zero. A Counter omits zero keys, so a census with no
    # unobserved units would have NO `UNOBSERVED` key -- and a consumer reading it with .get() would
    # silently conflate "none occurred" with "this census does not track that".
    buckets = collections.Counter(
        {k: 0 for k in ("OBSERVED", "UNOBSERVED", "NEEDS_INSPECTION", "CENSORED", "MISSING")})
    for uid in planned:
        if uid in by_uid:
            v = by_uid[uid].get("completeness")
            if v in CR.SCOREABLE:
                buckets["OBSERVED"] += 1
            elif v in CR.NEEDS_INSPECTION:
                buckets["NEEDS_INSPECTION"] += 1
            else:
                buckets["UNOBSERVED"] += 1
        elif uid in cen:
            buckets["CENSORED"] += 1
        else:
            buckets["MISSING"] += 1
    total = sum(buckets.values())
    if total != len(planned):
        raise ScheduleError(f"census does not partition the plan: {total} != {len(planned)}")
    return {"planned": len(planned), **dict(buckets),
            "observed_rate": round(buckets["OBSERVED"] / len(planned), 4),
            "censored_rate": round(buckets["CENSORED"] / len(planned), 4)}


def censor(unit_ids, reason, trigger=None, when=None):
    if reason not in CENSOR_REASONS:
        raise ScheduleError(f"unknown censor reason {reason!r}; expected one of {CENSOR_REASONS}")
    return [{"unit_id": u, "reason": reason, "trigger": trigger, "when": when} for u in unit_ids]


def save(schedule, path=None, replacing=None):
    """WRITE-ONCE like its manifest, and it reopens on the same terms (M6-T18).

    `replacing` is the schedule_id the caller believes is on disk; the overwrite is allowed only if
    the file really holds it. A schedule is derived from a manifest, so when a manifest supersession
    is declared the order must be rebuilt over the new plan -- there is no valid order across units
    that are no longer planned.
    """
    path = path or os.path.join(HERE, "runs", f"schedule_{schedule['schedule_id']}.json")
    if os.path.exists(path):
        if replacing is None:
            raise ScheduleError(f"{path} exists -- a schedule is WRITE-ONCE like its manifest")
        on_disk = json.load(open(path))["schedule_id"]
        if on_disk != replacing:
            raise ScheduleError(
                f"{path} holds {on_disk}, not the {replacing} this write claims to replace -- "
                f"refusing to overwrite a schedule the caller has not actually read")
    json.dump(schedule, open(path, "w"), indent=1)
    return path
