"""M6-T12 (L-A) — the deliverable: a per-model format-compliance table with THREE denominators.

PLAIN ENGLISH: turn the stored records into the table this whole project exists to produce, and make
it impossible to quote a rate over the wrong denominator.

WHY THREE DENOMINATORS (audit D4). "Compliance rate" is ambiguous, and a rate over the wrong
denominator is a wrong number that passes every structural check:

  PLANNED           every unit in the frozen manifest              -> coverage
  OBSERVED          the model finished, so its format behaviour was actually seen
                    (COMPLETE + NO_ANSWER)                         -> THE ONLY VALID denominator
                                                                      for a compliance rate
  UNOBSERVED        TRUNCATED / EMPTY_HTTP / PROVIDER_ERROR /
                    TRANSPORT_ERROR / SCHEMA_ERROR / BUDGET_CAPPED
                    / UNDECIDED                                    -> reported, never folded in
  NEEDS_INSPECTION  EMPTY_PARSE / EMPTY_CONFLICT                   -> our method is suspect
  CENSORED          abandoned by quarantine, with a reason         -> never hides inside MISSING

An UNOBSERVED unit must never become NO_ANSWER, which means "finished and did not comply".

RULE 12 (downstream-usability): this module must compute from the run's ACTUAL emitted output. A run
that finishes green but cannot build its planned analysis is an incomplete design -- discovered after
the money is spent. The test therefore builds the table from REAL stored records, not fixtures.

Offline. No network. No spend.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import claim_gate as CG          # noqa: E402
import completeness_review as CR  # noqa: E402
import manifest as MF            # noqa: E402


class _EmptyResult:
    """The zero-record case: nothing admitted, nothing rejected, no fields missing."""
    admitted, admitted_n, rejected_n, missing_field_counts = [], 0, 0, {}


class AnalysisError(RuntimeError):
    """Raised when a table cannot be honestly computed. Never a silently-wrong number."""


# the fields a compliance claim REQUIRES; the gate refuses records lacking them
COMPLIANCE_REQUIRES = ["model", "item_id", "arm", "completeness"]


def bucket(verdict):
    if verdict in CR.SCOREABLE:
        return "OBSERVED"
    if verdict in CR.NEEDS_INSPECTION:
        return "NEEDS_INSPECTION"
    return "UNOBSERVED"


def per_model_table(manifest, records, censored=(), strict=True, allow_pending=False):
    """The deliverable. Every planned unit lands in exactly one bucket, per model.

    strict=True refuses to build a table from records that are not in the manifest -- a table over an
    unplanned set is not a table of the planned experiment.

    allow_pending=False (Codex C3) refuses to build a PUBLISHABLE table while any record is still
    flagged pending_review. In real mode a layer-1 provisional COMPLETE is written with
    completeness=COMPLETE and compliant=True and only a printed reminder that it is provisional --
    so without this gate a table of unreviewed guesses is indistinguishable from a final result.
    Pass allow_pending=True deliberately for an interim look; it stamps the table as provisional.
    """
    # NO RECORDS AT ALL is a different situation from "records exist but none are admissible".
    # The claim gate's zero-evidence rule is about the latter -- it refuses to compute a rate from
    # nothing. But a table over an all-censored or not-yet-started run IS meaningful: it says every
    # unit is MISSING or CENSORED and no rate exists. Handling that here keeps the gate strict for
    # the case it was written for, instead of weakening it to accommodate this one.
    if not records:
        res = _EmptyResult()
    else:
        res = CG.Claim("per-model format compliance", requires=COMPLIANCE_REQUIRES).admit(records)
    admitted = res.admitted

    planned = collections.defaultdict(set)
    unit_model = {}
    for u in manifest["units"]:
        planned[u["model"]].add(u["unit_id"])
        unit_model[u["unit_id"]] = u["model"]

    pending = [r for r in admitted if r.get("pending_review")]
    if pending and not allow_pending:
        raise AnalysisError(
            f"{len(pending)} record(s) are still flagged pending_review: they were accepted "
            f"PROVISIONALLY by layer 1 and deferred to post-run validation. Publishing them as "
            f"COMPLETE would present unreviewed guesses as results. Run review_pending.py first, or "
            f"pass allow_pending=True for an explicitly provisional table. "
            f"Examples: {[(r.get('model'), r.get('item_id')) for r in pending[:3]]}")

    cen = {c["unit_id"] for c in censored}
    seen, unplanned = {}, []
    for r in admitted:
        uid = MF.unit_id(r.get("model"), r.get("item_id"), r.get("arm"))
        (seen.__setitem__(uid, r) if uid in unit_model else unplanned.append(uid))
    # D-OR-19. Out-of-plan records are an ERROR when the plan never changed, and EXPECTED when it
    # did. The discriminator is the manifest's own lineage: a manifest that declares `supersedes` is
    # saying, on the record, that its planned set moved -- so paid records for models the new plan
    # does not plan are evidence of the superseded plan, not corruption. Without that declaration
    # they still refuse, because then nobody said the universe changed and the denominator is
    # unknowable. Either way they are EXCLUDED from every rate and REPORTED as their own line: a
    # denominator that quietly absorbs them is the C1 finding, and a table that silently drops them
    # tells the reader nothing was paid for.
    if unplanned and strict and not manifest.get("supersedes"):
        raise AnalysisError(
            f"{len(unplanned)} record(s) are not in manifest {manifest['manifest_id']}. A table over "
            f"an unplanned set is not a table of the planned experiment. If the plan was deliberately "
            f"changed, the manifest must say so (MF.supersede -> `supersedes`), and then these are "
            f"reported as retained out-of-plan evidence instead of refused.")
    out_of_plan = [r for r in admitted
                   if MF.unit_id(r.get("model"), r.get("item_id"), r.get("arm")) not in unit_model]

    rows = {}
    for model, uids in planned.items():
        b = collections.Counter({k: 0 for k in
                                 ("OBSERVED", "UNOBSERVED", "NEEDS_INSPECTION", "CENSORED", "MISSING")})
        complied = 0
        for uid in uids:
            r = seen.get(uid)
            if r is None:
                b["CENSORED" if uid in cen else "MISSING"] += 1
                continue
            k = bucket(r.get("completeness"))
            b[k] += 1
            if k == "OBSERVED" and r.get("compliant") is True:
                complied += 1
        n_planned = len(uids)
        if sum(b.values()) != n_planned:
            raise AnalysisError(f"{model}: buckets sum to {sum(b.values())} != planned {n_planned}")
        rows[model] = {
            "planned": n_planned, **dict(b), "complied": complied,
            # THE ONLY valid denominator for a compliance rate
            "compliance_rate": round(complied / b["OBSERVED"], 4) if b["OBSERVED"] else None,
            # Codex C7: a missing rate must READ as "never observed", never as an absent field that
            # a downstream reader can coerce to zero.
            "rate_basis": "OBSERVED" if b["OBSERVED"] else "no_rate:nothing_observed",
            # Codex C11: the strongest argument against conditioning on OBSERVED is that provider
            # and transport failures may be MODEL-CORRELATED -- a model with 1 observed compliant
            # answer and 99 provider failures scores 1.000. So the planned-denominator LOWER BOUND
            # is published beside the primary rate, and coverage says how far apart they can be.
            # The primary rate stays over OBSERVED; this is disclosure, not a replacement.
            # None when nothing was observed: a printed 0.000 there reads as "complied never",
            # which is the same conflation the OBSERVED denominator exists to prevent.
            "compliance_lower_bound": (round(complied / n_planned, 4) if b["OBSERVED"] else None),
            "coverage_rate": round(b["OBSERVED"] / n_planned, 4),
            "inspection_rate": round(b["NEEDS_INSPECTION"] / n_planned, 4),
        }
    return {"manifest_id": manifest["manifest_id"],
            "supersedes": manifest.get("supersedes"),
            "provisional": bool(pending),
            "n_pending_review": len(pending),
            "n_models": len(rows), "n_planned": sum(r["planned"] for r in rows.values()),
            # D-OR-19: this counts records that are IN THIS PLAN. It used to be every admitted
            # record, so a superseded run reported 1,131 beside a planned 2,750 -- reading as 41%
            # coverage where the truth was 401/2,750. Out-of-plan records get their own line rather
            # than inflating this one or vanishing from the report entirely.
            "admitted_records": res.admitted_n - len(out_of_plan),
            "out_of_plan_records": len(out_of_plan),
            "out_of_plan_by_model": dict(collections.Counter(
                r.get("model") for r in out_of_plan).most_common()),
            "out_of_plan_note": (
                "records bought under a superseded plan, for models the current manifest does not "
                "plan. Retained as paid evidence, excluded from every rate and from every "
                "denominator." if out_of_plan else None),
            "rejected_records": res.rejected_n,
            "rejected_missing_fields": res.missing_field_counts,
            "rows": rows, "totals": _totals(rows)}


def _totals(rows):
    t = collections.Counter()
    for r in rows.values():
        for k in ("planned", "OBSERVED", "UNOBSERVED", "NEEDS_INSPECTION", "CENSORED",
                  "MISSING", "complied"):
            t[k] += r[k]
    obs = t["OBSERVED"]
    return {**dict(t),
            "compliance_rate": round(t["complied"] / obs, 4) if obs else None,
            "rate_basis": "OBSERVED" if obs else "no_rate:nothing_observed",
            "compliance_lower_bound": (round(t["complied"] / t["planned"], 4)
                                       if t["planned"] and obs else None),
            "coverage_rate": round(obs / t["planned"], 4) if t["planned"] else None,
            "inspection_rate": round(t["NEEDS_INSPECTION"] / t["planned"], 4) if t["planned"] else None}


def render(table, top=None):
    rows = sorted(table["rows"].items(), key=lambda kv: -(kv[1]["compliance_rate"] or -1))
    if top:
        rows = rows[:top]
    out = [f"  manifest {table['manifest_id']}   {table['n_models']} models, "
           f"{table['n_planned']} planned units",
           f"  {'model':<42} {'planned':>7} {'obs':>5} {'compl':>6} {'rate':>7} {'lower':>7} "
           f"{'unobs':>6} {'insp':>5} {'cens':>5} {'miss':>5}"]
    for m, r in rows:
        rate = "n/a" if r["compliance_rate"] is None else f"{r['compliance_rate']:.3f}"
        lower = "n/a" if r["compliance_lower_bound"] is None else f"{r['compliance_lower_bound']:.3f}"
        out.append(f"  {m:<42} {r['planned']:>7} {r['OBSERVED']:>5} {r['complied']:>6} {rate:>7} "
                   f"{lower:>7} "
                   f"{r['UNOBSERVED']:>6} {r['NEEDS_INSPECTION']:>5} {r['CENSORED']:>5} "
                   f"{r['MISSING']:>5}")
    t = table["totals"]
    trate = "n/a" if t["compliance_rate"] is None else f"{t['compliance_rate']:.3f}"
    tlower = "n/a" if t["compliance_lower_bound"] is None else f"{t['compliance_lower_bound']:.3f}"
    out.append(f"  {'TOTAL':<42} {t['planned']:>7} {t['OBSERVED']:>5} {t['complied']:>6} "
               f"{trate:>7} {tlower:>7} "
               f"{t['UNOBSERVED']:>6} {t['NEEDS_INSPECTION']:>5} "
               f"{t['CENSORED']:>5} {t['MISSING']:>5}")
    out.append(f"  rate is over OBSERVED (the only valid compliance denominator); 'lower' is the "
               f"same numerator over PLANNED, the bound if every unobserved call had failed to "
               f"comply. Coverage {t['coverage_rate']} says how far apart they can be.")
    rc = table.get("reasoning_coverage")
    if rc and rc["totals"].get("units"):
        t2 = rc["totals"]
        rate = ("n/a" if t2["reasoning_rate_over_asked"] is None
                else f"{t2['reasoning_rate_over_asked']:.3f}")
        out.append(f"  REASONING: {t2.get('from_base', 0)} unprompted, "
                   f"{t2.get('after_followup', 0)} only after the CoT follow-up, "
                   f"{t2.get('absent_after_both', 0)} absent after both, "
                   f"{t2.get('followup_not_run', 0)} follow-up not run (work not done, NOT a "
                   f"negative result). Rate over what was ASKED: {rate}.")
    if table.get("out_of_plan_records"):
        out.append(f"  RETAINED OUT-OF-PLAN: {table['out_of_plan_records']:,} paid record(s) for "
                   f"{len(table['out_of_plan_by_model'])} model(s) the current plan does not plan "
                   f"(superseded from {table['supersedes']}). Excluded from every rate above and "
                   f"from every denominator; kept because they were bought. "
                   f"{table['out_of_plan_by_model']}")
    if table.get("provisional"):
        out.append(f"  ** PROVISIONAL: {table['n_pending_review']} record(s) are pending review **")
    return "\n".join(out)


def reasoning_coverage(records, followup_arm="cot", base_arm="original", models=None):
    """WHERE the reasoning came from, per model -- never one blended rate (M6-T21/S4).

    The study wants the answer AND how the model reached it. With a conditional second prompt, a
    single "reasoning coverage 99%" would hide the thing that matters: whether a model reasons on
    its own or only when told to. Those are different behaviours and the figure must keep them apart.

    Four states per (model, item):
      from_base            the original prompt already produced reasoning -- nothing was re-asked
      after_followup       the original was bare; the CoT prompt got reasoning
      absent_after_both    the CoT prompt was issued and STILL no reasoning -- a real finding
      followup_not_run     the original was bare and no CoT record exists. NOT counted as either a
                           success or a failure; it is work not done, and merging it into
                           'absent' would report an unasked question as a negative result.
    """
    by_unit = {}
    for r in records:
        # Out-of-plan records are excluded here for the same reason they are excluded from every
        # rate above: they belong to a superseded plan. Counting them would report reasoning for
        # models the current plan does not run.
        if models is not None and r.get("model") not in models:
            continue
        if r.get("completeness") not in CR.SCOREABLE:
            continue
        by_unit.setdefault((r.get("model"), r.get("item_id")), {})[r.get("arm")] = r
    rows = collections.defaultdict(lambda: collections.Counter())
    for (model, _item), arms in by_unit.items():
        base = arms.get(base_arm)
        if base is None:
            continue                       # a follow-up with no base is not a coverage statement
        # THE SAME predicate the follow-up selector uses (CR.needs_reasoning_followup). Written
        # separately at first, these disagreed by the 2 refusals in the corpus -- 18 vs 20 -- so the
        # deliverable would have reported follow-ups the selector never intended to run.
        if not CR.needs_reasoning_followup(base):
            rows[model]["from_base" if CR.reasoning_evidence(base)["has"]
                        else "not_a_followup_candidate"] += 1
            continue
        fu = arms.get(followup_arm)
        if fu is None:
            rows[model]["followup_not_run"] += 1
        elif CR.reasoning_evidence(fu)["has"]:
            rows[model]["after_followup"] += 1
        else:
            rows[model]["absent_after_both"] += 1
    out = {}
    for model, c in rows.items():
        base_n = sum(c.values())
        got = c["from_base"] + c["after_followup"]
        # The denominator is what was ASKED, not what was planned: a unit whose follow-up was never
        # run cannot say whether reasoning was obtainable, so it is excluded from the rate and
        # reported beside it.
        asked = base_n - c["followup_not_run"]
        out[model] = {**{k: c[k] for k in ("from_base", "after_followup", "absent_after_both",
                                           "followup_not_run")},
                      "units": base_n,
                      "reasoning_rate_over_asked": round(got / asked, 4) if asked else None,
                      "unprompted_rate": round(c["from_base"] / base_n, 4) if base_n else None}
    totals = collections.Counter()
    for c in rows.values():
        totals.update(c)
    asked_t = sum(totals.values()) - totals["followup_not_run"]
    return {"rows": dict(sorted(out.items())),
            "totals": {**dict(totals), "units": sum(totals.values()),
                       "reasoning_rate_over_asked":
                           round((totals["from_base"] + totals["after_followup"]) / asked_t, 4)
                           if asked_t else None},
            "note": "unprompted_rate is the share that reasoned WITHOUT being asked. A model with a "
                    "high overall rate and a low unprompted rate reasons only on request, which is "
                    "a finding about the model, not a defect in the run."}


def save(table, path):
    json.dump(table, open(path, "w"), indent=1)
    return path
