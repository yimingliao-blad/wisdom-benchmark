"""Derive the CoT follow-up set from what stage 1 actually returned.

Owner, 2026-08-10: "if there is no reasoning, we have to have CoT. if there is reasoning in the
output, we can skip CoT, that is why we have two prompt for futurex."

The plan had recorded the CoT arm as globally DROPPED because ~94% of replies reason anyway. That
decides a PER-REPLY conditional with an AGGREGATE, and the minority it waves through is exactly the
population the second prompt exists to serve. This selects that minority instead.

    python3 followup_select.py --from runs/or_futurex_fxgate --out runs/cot_followup.json
    python3 run_openrouter.py --bench futurex --arms cot --only-units runs/cot_followup.json ...

WHO IS SELECTED: a unit whose stage-1 reply was COMPLETE -- the model answered and we saw its output
-- and carried NO reasoning by `completeness_review.reasoning_evidence`.

WHO IS NOT, and why each exclusion is deliberate:
  * a reply that reasoned -- including one that reasoned ONLY on the API `reasoning` channel. 29 of
    398 real records are that shape; a prose-only reader would re-buy every one of them.
  * a REFUSAL (NO_ANSWER), unless --include-no-answer. SCOREABLE is (COMPLETE, NO_ANSWER) and taking
    it whole would add 2 refusals to the 18 on the real corpus. But the second prompt exists to make
    a model that ANSWERED show its work; re-asking a refusal is a different experiment, and one such
    refusal is recorded in plan.md as the study's central negative result. The count is reported
    either way -- excluded, not dropped.
  * TRUNCATED / PROVIDER_ERROR / EMPTY_* / anything not SCOREABLE. Those are bare because the call
    failed, not because the model was terse. Re-asking them with a DIFFERENT prompt would blend a
    delivery failure into a prompt-condition result, and neither number would mean anything after.
  * a unit stage 1 never bought at all. That is missing coverage, not a terse reply, and it is
    reported rather than quietly folded in.

THE RULE IS IMPORTED, NEVER RE-IMPLEMENTED. `reasoning_evidence` lives in completeness_review and is
called from there. Sizing this by hand first, with a re-derived 120-char test, gave 15 where the real
rule gives 18 -- two readers of one definition, which is the defect this codebase keeps rediscovering.

Offline. Reads stored records. No network, no spend.
"""
import argparse
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import completeness_review as CR   # noqa: E402  the ONE definition of "did this reply reason"


class FollowupError(RuntimeError):
    """Refusal. A follow-up set derived from a partial stage silently under-covers the study."""


def select(records, roster_ids=None, include_no_answer=False):
    """Return (pairs, report). `pairs` is runner-ready; `report` explains every exclusion.

    NO_ANSWER IS EXCLUDED BY DEFAULT, and this is a judgement, not an oversight. SCOREABLE is
    (COMPLETE, NO_ANSWER), so taking it whole adds refusals to the follow-up set -- on the real
    corpus, 2 of 20. But the two prompts exist to make a model that ANSWERED show its work. A
    refusal gave no answer at all; re-asking it with a different prompt is a different experiment
    ("does prompting change refusal behaviour?"), and plan.md treats one such refusal as the study's
    central negative result. Folding them in silently would change what the follow-up set means and
    re-roll a negative finding. The count is REPORTED either way, so the choice is visible rather
    than buried, and --include-no-answer runs the other experiment deliberately.
    """
    counts = collections.Counter()
    pairs, seen = [], set()
    admissible = CR.SCOREABLE if include_no_answer else (CR.COMPLETE,)
    for r in records:
        model, item = r.get("model"), r.get("item_id")
        if roster_ids is not None and model not in roster_ids:
            counts["excluded_not_in_roster"] += 1
            continue
        verdict = r.get("completeness")
        if verdict not in admissible:
            key = ("excluded_refusal_NO_ANSWER" if verdict == CR.NO_ANSWER
                   else f"excluded_not_scoreable:{verdict}")
            counts[key] += 1
            if verdict == CR.NO_ANSWER and not CR.reasoning_evidence(r)["has"]:
                counts["refusals_that_were_also_bare"] += 1
            continue
        counts["scoreable"] += 1
        ev = CR.reasoning_evidence(r)
        if not CR.needs_reasoning_followup(r, include_no_answer):   # the ONE definition
            counts["excluded_already_reasoned:" + "+".join(ev["source"])] += 1
            continue
        key = (model, item)
        if key in seen:
            counts["excluded_duplicate_unit"] += 1
            continue
        seen.add(key)
        pairs.append({"model": model, "item_id": item,
                      "selected_because": "stage-1 reply was SCOREABLE and carried no reasoning "
                                          "(reasoning_evidence.has == false)"})
    n_scoreable = counts["scoreable"]
    report = {
        "rule": ("stage-1 reply is COMPLETE"
                 + (" or NO_ANSWER" if include_no_answer else " (refusals EXCLUDED -- see below)")
                 + " AND completeness_review.reasoning_evidence(rec).has is false. Non-scoreable "
                   "replies are delivery failures, not terse models, and are never followed up."),
        "no_answer_policy": ("INCLUDED by --include-no-answer" if include_no_answer else
                             "EXCLUDED by default: a refusal gave no answer, so re-prompting it is a "
                             "different experiment from asking an answerer to show its work. The "
                             "count of bare refusals is reported below, not dropped."),
        "reasoning_min_chars": CR.REASONING_MIN_CHARS,
        "scoreable_records": n_scoreable,
        "selected": len(pairs),
        "already_reasoned": n_scoreable - len(pairs),
        "reasoning_rate": round((n_scoreable - len(pairs)) / n_scoreable, 4) if n_scoreable else None,
        "per_model_selected": dict(collections.Counter(p["model"] for p in pairs).most_common()),
        "exclusions": {k: v for k, v in sorted(counts.items()) if k != "scoreable"},
    }
    return pairs, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True,
                    help="a completed stage's run directory, or its records.jsonl")
    ap.add_argument("--out", required=True, help="the --only-units file for the follow-up stage")
    ap.add_argument("--roster", default=None,
                    help="restrict to the models in this roster; without it, every model in the "
                         "records is considered")
    ap.add_argument("--include-no-answer", action="store_true",
                    help="also follow up REFUSALS (NO_ANSWER). Off by default -- that is a different "
                         "experiment, and one such refusal is recorded in plan.md as the study's "
                         "central negative result.")
    ap.add_argument("--allow-partial", action="store_true",
                    help="derive a follow-up set even though stage 1 has unbought units. Off by "
                         "default: a set derived from a partial stage under-covers, and the gap is "
                         "invisible in the output.")
    a = ap.parse_args()

    src = a.src if a.src.endswith(".jsonl") else os.path.join(a.src, "records.jsonl")
    if not os.path.exists(src):
        raise FollowupError(f"{src} does not exist -- there is no stage-1 evidence to select from")
    records = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    roster_ids = ({m["id"] for m in json.load(open(a.roster))} if a.roster else None)

    # Completeness of the source stage, checked BEFORE selecting. A follow-up derived from half a
    # run looks exactly like one derived from a whole run.
    mpath = os.path.join(os.path.dirname(src), "manifest.json")
    if os.path.exists(mpath):
        import persistence as PS
        mani = json.load(open(mpath))
        rs = PS.resume_state(mani, records, strict=False)
        if rs["todo"]:
            msg = (f"stage 1 has {len(rs['todo']):,} of {rs['planned']:,} units still unbought"
                   + (f" ({len(rs['requeued_undelivered']):,} of them have a row but never "
                      f"delivered)" if rs["requeued_undelivered"] else "") + ".")
            if not a.allow_partial:
                raise FollowupError(
                    msg + " A follow-up set derived from a partial stage silently under-covers: the "
                          "units never asked cannot be known to have reasoned or not. Finish stage 1, "
                          "or pass --allow-partial and accept that the follow-up covers only what "
                          "was observed.")
            print(f"  PARTIAL SOURCE (accepted): {msg}")

    pairs, report = select(records, roster_ids, a.include_no_answer)
    report["source"] = os.path.relpath(src, HERE)
    report["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    json.dump(pairs, open(a.out, "w"), indent=1)
    json.dump(report, open(a.out + ".provenance.json", "w"), indent=1)

    print(f"  scoreable stage-1 replies: {report['scoreable_records']:,}")
    print(f"  already reasoned: {report['already_reasoned']:,} "
          f"({report['reasoning_rate']:.1%})" if report["reasoning_rate"] is not None else "")
    print(f"  SELECTED for the CoT follow-up: {len(pairs):,}"
          + (f" -> {report['per_model_selected']}" if pairs else " (nothing to follow up)"))
    print(f"  WROTE {a.out} (+ .provenance.json recording the rule and every exclusion)")


if __name__ == "__main__":
    try:
        main()
    except FollowupError as e:
        raise SystemExit(f"HALT: {e}")
