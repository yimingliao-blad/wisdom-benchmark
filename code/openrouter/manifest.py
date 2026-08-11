"""M6-T3 (L-M) — freeze the planned universe, and let every record prove its request.

PLAIN ENGLISH: write down exactly which calls we intend to make before making any, and give each one
a fingerprint of the precise question it will ask -- so a stored answer can be PROVEN to belong to
the call it is filed under.

TWO AUDIT FINDINGS MEET HERE
  C1  "planned" was computed at runtime from a cross-product, so "did we cover everything?" was
      answered by the same code that decided what everything was. Self-referential.
  C3  a record stored model/item/arm but nothing tying it to the prompt actually sent. A response
      filed against the wrong unit gives a WRONG TABLE with valid JSON, no lost unit, and every
      existing check passing.

`run_openrouter.py` already writes `prompt_sha`. That is DECORATION until something compares it to a
manifest -- this module is that something.

IMMUTABILITY, resolved honestly: the roster changed eight times in one day, so "immutable" cannot
mean "never changes". It means WRITE-ONCE: a change emits a NEW manifest_id carrying `supersedes`
and a reason.

Offline. No network. No spend.
"""
import collections
import hashlib
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench_formats as BF      # noqa: E402  the REAL renderer -- hashing a copy would prove nothing
import item_validate as IV      # noqa: E402

DRAW_SEED = 20260808
BALANCE_TOL = 0.10              # absolute fraction; the band is derived from the POOL, never assumed


class ManifestError(RuntimeError):
    """Raised on an unfit draw or a failed freeze. Never returned as a value."""


def _sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def unit_id(model, item_id, arm):
    """UNIT identity. The manifest is unit-level; coverage counts units."""
    return _sha(f"{model}\x00{item_id}\x00{arm}")


ATTEMPT_KINDS = ("first", "retry", "resumed", "quarantined", "duplicate", "replacement")


def attempt_id(uid, attempt_no, kind):
    """ATTEMPT identity (audit-3 E6). Spend reconciles on this; duplicates key on this.

    Conflating attempt with unit is how a retry double-charges or a duplicate inflates a denominator.
    """
    if kind not in ATTEMPT_KINDS:
        raise ManifestError(f"unknown attempt kind {kind!r}; expected one of {ATTEMPT_KINDS}")
    return f"{uid}:{int(attempt_no)}:{kind}"


def draw_items(pool, n, seed=DRAW_SEED, tol=BALANCE_TOL, stratum=None):
    """Seeded-random draw with a FAIL-LOUD balance gate whose band comes from the POOL.

    Rule 13: never a prefix. The pool is ordered by id, and a prefix would correlate with whatever
    that ordering encodes. The band is MEASURED -- FutureX's pool is 37.8/40.5/10.5/11.2 across
    levels, so a 25/25/25/25 expectation would halt on every valid draw.

    `stratum` names the field the gate binds on, because "balanced" means the stratification THE
    ANALYSIS NEEDS and the two benchmarks need different ones. FutureX stratifies on its difficulty
    `level`. BTF-3 has no levels; it stratifies on a composite of outcome x prompt-length band --
    outcome so the later accuracy read keeps the base rate, length because prompt length is the
    variable most plausibly related to FORMAT compliance, which is what this study measures.
    """
    if n > len(pool):
        raise ManifestError(f"cannot draw {n} from a pool of {len(pool)}")
    key = (lambda i: int(i["level"])) if stratum is None else (lambda i: i[stratum])
    expected = collections.Counter(key(i) for i in pool)
    exp_frac = {k: v / len(pool) for k, v in expected.items()}
    picked = random.Random(seed).sample(pool, n)      # seeded random, NOT a prefix
    got = collections.Counter(key(i) for i in picked)
    off = {lv: round(got.get(lv, 0) / n - f, 4) for lv, f in exp_frac.items()
           if abs(got.get(lv, 0) / n - f) > tol}
    if off:
        raise ManifestError(
            f"balance gate HALT: the draw is off the pool's own level distribution by more than "
            f"{tol:.0%}: {off}. pool={dict(exp_frac)} draw={ {k: v/n for k, v in got.items()} }")
    return picked, {"pool_fracs": exp_frac, "draw_counts": dict(got), "tol": tol, "seed": seed,
                    "stratum": stratum or "level"}


def build(roster, items, arms=("original",), bench="futurex", supersedes=None, reason=None):
    """Freeze the planned universe. Every unit carries the hash of the prompt it WILL send."""
    IV.require_valid(items, where="manifest item corpus", bench=bench)  # the VALIDATED corpus
    if not roster:
        raise ManifestError("empty roster")
    roster_hash = _sha(json.dumps(sorted(m["id"] for m in roster)))
    items_hash = _sha(json.dumps(sorted(i["item_id"] for i in items)))
    units = []
    for m in roster:
        for it in items:
            for arm in arms:
                prompt = (BF.futurex_render(it, arm) if bench == "futurex"
                          else BF.btf_render(it["prompt"], arm))
                uid = unit_id(m["id"], it["item_id"], arm)
                units.append({"unit_id": uid, "model": m["id"], "item_id": it["item_id"],
                              "arm": arm, "level": it.get("level"),
                              "prompt_sha": _sha(prompt), "prompt_chars": len(prompt)})
    if len({u["unit_id"] for u in units}) != len(units):
        raise ManifestError("unit_id collision -- identity is not unique, refusing to freeze")
    body = {"bench": bench, "arms": list(arms), "anchor": IV.ANCHOR,
            "roster_hash": roster_hash, "items_hash": items_hash,
            "n_models": len(roster), "n_items": len(items), "n_arms": len(arms),
            "n_units": len(units), "units": units}
    mid = _sha(json.dumps({k: body[k] for k in
                           ("bench", "arms", "roster_hash", "items_hash")}, sort_keys=True)
               + json.dumps(sorted(u["prompt_sha"] for u in units)))
    return {"manifest_id": mid, "supersedes": supersedes, "reason": reason, **body}


def supersede(prior, roster, items, arms=("original",), bench="futurex", reason=None):
    """Re-freeze a plan IN PLACE when the roster (or item set) changes, carrying the lineage.

    The module docstring settled the policy at the start -- write-once, not immutable, "a change
    emits a NEW manifest_id carrying `supersedes` and a reason" -- and `build` has taken those two
    arguments all along. Nothing ever called it that way, so the runner's only offer on a mismatch
    was "use a new --tag", i.e. abandon every call already bought. That is what this fixes.

    What does NOT change, and is the reason this is safe: a record proves itself by `unit_id` +
    `prompt_sha`, neither of which involves the roster. A call to model M on item X is the same unit
    in both plans. Only the PLANNED DENOMINATOR moves -- and that must move, or the coverage
    arithmetic would describe a plan nobody is running.

    The reason is REQUIRED. The guard exists so two planned universes never share one records file
    silently; a supersession with no stated reason is exactly as silent, and re-freezing on every
    accidental roster edit is the failure mode this must not enable.
    """
    if not (reason or "").strip():
        raise ManifestError(
            "a supersession needs a written reason -- an undeclared re-freeze is precisely what the "
            "run-directory guard exists to prevent, and a blank reason is undeclared")
    new = build(roster, items, arms=arms, bench=bench,
                supersedes=prior["manifest_id"], reason=reason)
    if new["manifest_id"] == prior["manifest_id"]:
        raise ManifestError(
            f"refusing to supersede {prior['manifest_id']} with an identical plan -- same bench, "
            f"arms, roster and items. Nothing changed, so there is nothing to declare.")
    # The chain is readable from the current file alone; a reader should never need the run's git
    # history to learn that the denominator moved under it.
    new["history"] = list(prior.get("history", [])) + [
        {"manifest_id": prior["manifest_id"], "n_units": prior["n_units"],
         "n_models": prior["n_models"], "n_items": prior["n_items"],
         "reason": prior.get("reason")}]
    return new


VERDICTS = ("MATCH", "MISASSOCIATED", "UNPLANNED", "MISSING")


def verify_records_against(manifest, records):
    """Does every record PROVE its request, and does the run cover the plan?

    MISASSOCIATED is the finding this exists for: the unit is planned, but the prompt that produced
    the stored answer is NOT the prompt planned for it. Reported per record, never summarised away.
    """
    by_unit = {u["unit_id"]: u for u in manifest["units"]}
    seen, out = set(), collections.Counter()
    detail = []
    for r in records:
        uid = unit_id(r.get("model"), r.get("item_id"), r.get("arm"))
        u = by_unit.get(uid)
        if u is None:
            out["UNPLANNED"] += 1
            detail.append({"verdict": "UNPLANNED", "model": r.get("model"),
                           "item_id": r.get("item_id"), "arm": r.get("arm")})
            continue
        seen.add(uid)
        got = r.get("prompt_sha")
        if got is None:
            out["NO_HASH"] += 1
            detail.append({"verdict": "NO_HASH", "unit_id": uid, "model": r.get("model")})
        elif got != u["prompt_sha"]:
            out["MISASSOCIATED"] += 1
            detail.append({"verdict": "MISASSOCIATED", "unit_id": uid, "model": r.get("model"),
                           "item_id": r.get("item_id"), "arm": r.get("arm"),
                           "planned_sha": u["prompt_sha"], "record_sha": got})
        else:
            out["MATCH"] += 1
    missing = [u for uid, u in by_unit.items() if uid not in seen]
    out["MISSING"] = len(missing)
    return {"counts": dict(out), "detail": detail,
            "missing_units": [{"unit_id": u["unit_id"], "model": u["model"],
                               "item_id": u["item_id"], "arm": u["arm"]} for u in missing[:50]],
            "n_planned": len(by_unit), "n_records": len(records),
            "clean": out.get("MISASSOCIATED", 0) == 0 and out.get("UNPLANNED", 0) == 0}


def save(manifest, path=None, replacing=None):
    """WRITE-ONCE, with one door: a manifest that DECLARES it supersedes the one on disk.

    `replacing` is the manifest_id the caller believes is at `path`. The overwrite is allowed only
    when the file really holds that id AND the new manifest names it in `supersedes` -- so the write
    is checked against the lineage rather than merely permitted by a flag. Without that, write-once
    would have to be either absolute (and a roster change could never be recorded in place, which was
    the whole defect) or advisory (and any stray write could quietly replace the plan a run's
    coverage arithmetic is computed against).
    """
    path = path or os.path.join(HERE, "runs", f"manifest_{manifest['manifest_id']}.json")
    if os.path.exists(path):
        if replacing is None:
            raise ManifestError(
                f"{path} exists -- a manifest is WRITE-ONCE; supersede it with a new id")
        on_disk = json.load(open(path))["manifest_id"]
        if on_disk != replacing:
            raise ManifestError(
                f"{path} holds {on_disk}, not the {replacing} this write claims to replace -- "
                f"refusing to overwrite a manifest the caller has not actually read")
        if manifest.get("supersedes") != on_disk:
            raise ManifestError(
                f"refusing to overwrite {on_disk}: the new manifest declares supersedes="
                f"{manifest.get('supersedes')!r}. An in-place replacement must name what it "
                f"replaces, or the lineage is broken at exactly the point it matters")
    json.dump(manifest, open(path, "w"), indent=1)
    return path
