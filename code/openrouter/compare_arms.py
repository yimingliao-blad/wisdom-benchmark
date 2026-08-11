"""Paired comparison of two arms — with the missingness check that makes the delta trustworthy.

Run: python3 compare_arms.py <native_run_dir> <other_run_dir>

CODEX C12, the gap none of the prior audits caught: if the two arms have DIFFERENT unobserved or
censored patterns by model, item or provider, the delta between their compliance rates can be biased
even when each arm's rate is correctly computed over its own observed records. "Arm B is better"
then partly means "arm B happened to make different cells observable".

So the delta is only reported over cells observed in BOTH arms, and DISCORDANT MISSINGNESS -- a cell
observed in one arm and not the other -- is counted and surfaced rather than quietly dropped.

Offline. No network. No spend.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import completeness_review as CR      # noqa: E402

MAX_DISCORDANT = 0.05     # predeclared: above this the paired delta is not reportable


def load(run_dir):
    import glob
    vs = sorted(glob.glob(os.path.join(run_dir, "records.v*.jsonl")),
                key=lambda f: int(f.rsplit(".v", 1)[1].split(".")[0]))
    p = vs[-1] if vs else os.path.join(run_dir, "records.jsonl")
    return {(r["model"], r["item_id"]): r for r in
            (json.loads(l) for l in open(p) if l.strip())}


def compare(a_dir, b_dir, a_name="native", b_name="other"):
    A, B = load(a_dir), load(b_dir)
    cells = sorted(set(A) & set(B))
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))

    def obs(r):
        return r.get("completeness") in CR.SCOREABLE

    both_obs = [c for c in cells if obs(A[c]) and obs(B[c])]
    disc = [c for c in cells if obs(A[c]) != obs(B[c])]
    rate = MAX_DISCORDANT + 1 if not cells else len(disc) / len(cells)

    def comp(r):
        return r.get("compliant") is True
    a_ok = sum(1 for c in both_obs if comp(A[c]))
    b_ok = sum(1 for c in both_obs if comp(B[c]))
    fixed = [c for c in both_obs if not comp(A[c]) and comp(B[c])]
    broke = [c for c in both_obs if comp(A[c]) and not comp(B[c])]

    # WHY a cell is discordant matters. A cell UNOBSERVED in A but observed in B contributes
    # nothing to a paired format comparison -- A never saw it -- but it is not evidence of bias
    # either when the sample DELIBERATELY oversampled A's failures, as this one did. So the two
    # claims are separated instead of collapsing into one refusal:
    #   * the CONCORDANT delta (cells observed in both) is a valid paired comparison
    #   * the WHOLE-SAMPLE delta is not, and the discordant cells are reported on their own
    a_unobs_b_obs = [c for c in disc if not obs(A[c]) and obs(B[c])]
    a_obs_b_unobs = [c for c in disc if obs(A[c]) and not obs(B[c])]
    rep = {"a": a_name, "b": b_name, "cells_in_common": len(cells),
           "discordant_a_unobserved": len(a_unobs_b_obs),
           "discordant_b_unobserved": len(a_obs_b_unobs),
           "only_in_a": len(only_a), "only_in_b": len(only_b),
           "observed_in_both": len(both_obs),
           "discordant_missingness": len(disc), "discordant_rate": round(rate, 4),
           "max_discordant": MAX_DISCORDANT,
           "a_compliant": a_ok, "b_compliant": b_ok,
           "a_rate": round(a_ok / len(both_obs), 4) if both_obs else None,
           "b_rate": round(b_ok / len(both_obs), 4) if both_obs else None,
           "fixed": len(fixed), "broke": len(broke),
           "broke_examples": broke[:5],
           "discordant_by_model": dict(collections.Counter(m for m, _ in disc)),
           # the paired delta over concordant cells is valid regardless of how many cells were
           # discordant; what the cap governs is whether the WHOLE-SAMPLE delta may be quoted
           "concordant_delta_reportable": bool(both_obs),
           "whole_sample_delta_reportable": bool(both_obs) and rate <= MAX_DISCORDANT}
    return rep


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: python3 compare_arms.py <native_run_dir> <other_run_dir>")
    r = compare(sys.argv[1], sys.argv[2])
    print(f"  cells in common: {r['cells_in_common']}  (only in A: {r['only_in_a']}, "
          f"only in B: {r['only_in_b']})")
    print(f"  observed in BOTH arms: {r['observed_in_both']}")
    print(f"  discordant missingness: {r['discordant_missingness']} "
          f"({r['discordant_rate']:.1%}, cap {r['max_discordant']:.0%})")
    if r["discordant_by_model"]:
        print(f"    by model: {r['discordant_by_model']}")
    print(f"  PAIRED over the cells observed in both:")
    print(f"    {r['a']:<8} {r['a_compliant']}/{r['observed_in_both']} = {r['a_rate']}")
    print(f"    {r['b']:<8} {r['b_compliant']}/{r['observed_in_both']} = {r['b_rate']}")
    print(f"    fixed {r['fixed']}   broke {r['broke']}")
    print(f"  CONCORDANT delta (n={r['observed_in_both']}): REPORTABLE — a valid paired comparison")
    if r["whole_sample_delta_reportable"]:
        print("  WHOLE-SAMPLE delta: reportable")
    else:
        print(f"  WHOLE-SAMPLE delta: NOT reportable — {r['discordant_missingness']} cell(s) "
              f"({r['discordant_rate']:.1%}) are observed in one arm only, of which "
              f"{r['discordant_a_unobserved']} were UNOBSERVED in {r['a']}. Those cannot show a "
              f"format effect: {r['a']} never saw them. Report them separately.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
