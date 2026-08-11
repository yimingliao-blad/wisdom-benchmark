"""Build a run roster from NOTHING BUT MODEL NAMES.

    python3 survey/roster_build.py --models my_models.txt --out my_roster.json

WHY THIS EXISTS (owner, 2026-08-09): "you should make the model list un-coupled with the project. we
can provide any list of models with model name to make it." The previous builder carried its 25
models as a literal in its own source, so changing the roster meant editing code -- the model list
WAS the project. Now the list is data: a text file of ids, or `--model x --model y`, or stdin.

WHAT COMES FROM WHERE, and every row says so in `field_sources` (never a silent mix):

  from the OpenRouter catalog (authoritative, re-fetched each build)
    exists         a name that does not resolve HALTS here, not as 110 failed calls later
    in / out       live per-million prices -- the spend ledger meters real money against them
    cap            max_completion_tokens, else context_length
    release        the catalog's `created` timestamp
    cutoff         `knowledge_cutoff` WHERE PUBLISHED (194 of 400 models carry it)
    weights        open iff a hugging_face_id is present
    series         parsed from the catalog display name

  declared by a human in --overrides, each entry carrying a `why`
    anything the catalog does not publish or gets wrong for your purpose: a missing cutoff,
    params_b, arch, a corrected series. An override without a `why` is refused.

  NOT INVENTED
    a cutoff that is neither published nor declared stays null. It is not guessed from the release
    date. `--anchor` is what turns a null into a HALT, and that is the STUDY's policy, not the
    roster's -- building a roster and deciding who may enter a contamination-sensitive experiment
    are two different questions and are two different flags here.

ON `weights`: hugging_face_id is a reliable POSITIVE signal and a weak negative one -- checked
against a 25-model hand-labelled list it agreed 24/25, the miss being an open-weight model the
catalog simply carries no hf id for. So absence is reported as `presumed closed`, and an override
fixes it. The derivation is never presented as a fact the catalog stated.

Offline except for one GET of the public catalog (no key required). No spend.
"""
import argparse
import datetime
import difflib
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = "https://openrouter.ai/api/v1/models"
OVERRIDABLE = ("cutoff", "series", "weights", "params_b", "arch", "release", "in", "out", "cap")
# Only these two mean "the model itself will not emit more than this". A cap derived from
# context_length is a reporting number, never a request parameter.
REAL_OUTPUT_CEILING = ("max_completion_tokens", "declared")


class RosterError(RuntimeError):
    """Refusal. Never a warning, never a default -- an invented roster field becomes a wrong table."""


def read_model_names(spec):
    """A file of ids, a JSON list, or '-' for stdin. Returns [(id, family_or_None)].

    A line may carry an optional family after a '|':

        meta-llama/llama-3.1-8b-instruct  | Llama 3.x
        meta-llama/llama-3.3-70b-instruct | Llama 3.x

    Grouping variants into a family is a JUDGEMENT (are 3.1 and 3.3 one family or two?), so it
    cannot be derived, but it also does not deserve a full override entry per model. Putting it
    beside the name keeps ONE file the owner edits, which is the point: the list is data, and the
    code never learns a model's name.
    """
    raw = sys.stdin.read() if spec == "-" else open(spec, encoding="utf-8").read()
    raw = raw.strip()
    if raw.startswith("["):
        loaded = json.loads(raw)
        pairs = [(x["id"], x.get("series")) if isinstance(x, dict) else (x, None) for x in loaded]
    else:
        pairs = []
        for ln in raw.splitlines():
            ln = ln.split("#", 1)[0].strip()
            if not ln:
                continue
            mid, _, fam = ln.partition("|")
            pairs.append((mid.strip(), fam.strip() or None))
    ids = [p[0] for p in pairs]
    dupes = sorted({n for n in ids if ids.count(n) > 1})
    if dupes:
        raise RosterError(f"the model list repeats {dupes} -- a duplicate would plan the same unit "
                          f"twice and collide on unit_id at the manifest freeze")
    if not pairs:
        raise RosterError(f"no model names found in {spec}")
    return pairs


def load_catalog(cache=None):
    if cache and os.path.exists(cache):
        return {m["id"]: m for m in json.load(open(cache))["data"]}
    with urllib.request.urlopen(CATALOG, timeout=60) as fh:
        body = json.load(fh)
    if cache:
        json.dump(body, open(cache, "w"))
    return {m["id"]: m for m in body["data"]}


def derive_series(entry):
    """'Anthropic: Claude Haiku 4.5' -> 'Claude Haiku 4.5'; 'Qwen: Qwen3 32B' -> 'Qwen3 32B'.

    A GROUPING HINT, not a taxonomy. Whether two variants belong to one family is a judgement the
    analysis may care about (llama-3.1 and llama-3.3 as 'Llama 3.x'), and judgement is what
    --overrides is for. Deriving something reasonable beats HALTing on every new model.
    """
    name = entry.get("name") or entry["id"]
    return name.split(":", 1)[1].strip() if ":" in name else name.strip()


def month(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m") if ts else None


def build_row(mid, entry, override, family=None):
    src = {}
    pricing = entry.get("pricing") or {}
    try:
        p_in = float(pricing["prompt"]) * 1e6
        p_out = float(pricing["completion"]) * 1e6
    except (KeyError, TypeError, ValueError):
        raise RosterError(f"{mid}: the catalog publishes no usable price. The spend ledger meters "
                          f"real money per token; refusing to plan a call it cannot cost.")
    # A CONTEXT WINDOW IS NOT AN OUTPUT CEILING (M6-T22). It counts the prompt too, so requesting it
    # as max_tokens asks for an output the size of the whole context. The fallback is kept because a
    # roster row still needs a number for reporting, but the consumer must be able to tell the two
    # apart -- `catalog:max_completion_tokens_or_context` could not be told apart, so the runner had
    # no way to know whether it was holding a real limit or a context window.
    mx = (entry.get("top_provider") or {}).get("max_completion_tokens")
    ctx = entry.get("context_length")
    cap = mx or ctx
    cap_basis = "max_completion_tokens" if mx else "context_length"
    if not cap:
        raise RosterError(f"{mid}: neither max_completion_tokens nor context_length is published, so "
                          f"there is no ceiling to escalate a truncated answer against. Declare "
                          f"'cap' in --overrides, with a reason, or drop the model.")
    hf = (entry.get("hugging_face_id") or "").strip()
    row = {"id": mid,
           "series": derive_series(entry),
           "weights": "open" if hf else "closed",
           "in": round(p_in, 6), "out": round(p_out, 6),
           "cap": cap, "cap_basis": cap_basis,
           # D-OR-23: the OUTPUT ceiling and the CONTEXT window are different numbers, and for some
           # models they are equal -- asking for the whole ceiling then leaves no room for the
           # prompt and the provider returns 400. The consumer needs both to size a request.
           "context": ctx,
           "release": month(entry.get("created")),
           "cutoff": entry.get("knowledge_cutoff") or None}
    src.update({"series": "catalog:name", "in": "catalog:pricing", "out": "catalog:pricing",
                "context": "catalog:context_length",
                "cap": f"catalog:{cap_basis}"
                       + ("" if cap_basis == "max_completion_tokens"
                          else " -- A CONTEXT WINDOW, NOT AN OUTPUT CEILING: no max_tokens should be "
                               "derived from it"),
                "release": "catalog:created",
                "weights": f"catalog:hugging_face_id={'present' if hf else 'absent -> PRESUMED closed'}",
                "cutoff": "catalog:knowledge_cutoff" if row["cutoff"] else "UNKNOWN -- not published"})
    if family:
        row["series"], src["series"] = family, "declared in the model list"
    for k, v in (override or {}).items():
        if k == "why":
            continue
        if k not in OVERRIDABLE:
            raise RosterError(f"{mid}: '{k}' is not an overridable field {OVERRIDABLE}")
        row[k], src[k] = v, f"declared: {override['why']}"
        if k == "cap":
            row["cap_basis"] = "declared"
    row["basis"] = ("PUB-CATALOG" if src.get("cutoff", "").startswith("catalog")
                    else "DECLARED" if str(src.get("cutoff", "")).startswith("declared")
                    else "UNKNOWN")
    row["field_sources"] = src
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--models", help="file of model ids (one per line, # comments), a JSON list, "
                                     "or '-' for stdin")
    ap.add_argument("--model", action="append", default=[], help="a single id; repeatable")
    ap.add_argument("--overrides", default=None,
                    help="JSON {model_id: {field: value, why: '...'}} -- the ONLY place a human "
                         "states what the catalog does not publish. A 'why' is mandatory.")
    ap.add_argument("--out", default=None, help="write the roster here (default: stdout)")
    ap.add_argument("--anchor", default=None, metavar="YYYY-MM-DD",
                    help="STUDY POLICY, not roster policy: HALT if any model's cutoff is unknown or "
                         "falls after this date. Omit to build a roster with no admission rule.")
    ap.add_argument("--catalog-cache", default=None,
                    help="read/write the catalog here, so a build is reproducible offline")
    a = ap.parse_args()

    pairs = [(m, None) for m in a.model]
    if a.models:
        pairs = read_model_names(a.models) + pairs
    names = [p[0] for p in pairs]
    families = {mid: fam for mid, fam in pairs if fam}
    if not names:
        raise RosterError("give --models FILE or at least one --model ID")

    cat = load_catalog(a.catalog_cache)
    unknown = [n for n in names if n not in cat]
    if unknown:
        hint = {u: difflib.get_close_matches(u, cat, n=3, cutoff=0.6) for u in unknown}
        raise RosterError(
            "these ids are not served by OpenRouter, so every call to them would fail:\n  "
            + "\n  ".join(f"{u}   did you mean: {', '.join(h) or '(no near match)'}"
                          for u, h in hint.items()))

    overrides = json.load(open(a.overrides)) if a.overrides else {}
    stray = [k for k in overrides if k not in names]
    if stray:
        raise RosterError(f"--overrides names models that are not in the list: {stray}. An override "
                          f"for a model you are not running is a stale instruction, not a no-op.")
    for mid, ov in overrides.items():
        if not str(ov.get("why", "")).strip():
            raise RosterError(f"override for {mid} has no 'why'. An undocumented override is how a "
                              f"guess becomes a fact three sessions later.")

    roster = [build_row(n, cat[n], overrides.get(n), families.get(n)) for n in names]

    no_cutoff = [r["id"] for r in roster if not r["cutoff"]]
    if a.anchor:
        late = [(r["id"], r["cutoff"]) for r in roster if r["cutoff"] and r["cutoff"] > a.anchor]
        if no_cutoff or late:
            raise RosterError(
                f"--anchor {a.anchor} refuses this roster.\n"
                + (f"  cutoff UNKNOWN (not published, not declared): {no_cutoff}\n" if no_cutoff else "")
                + (f"  cutoff AFTER the anchor: {late}\n" if late else "")
                + "  Declare each in --overrides with a reason, or drop the model. A contamination "
                  "anchor enforced on guessed cutoffs is not enforced at all.")

    n_open = sum(1 for r in roster if r["weights"] == "open")
    presumed = [r["id"] for r in roster if "PRESUMED" in r["field_sources"]["weights"]]
    print(f"  {len(roster)} models · {n_open} open / {len(roster) - n_open} closed · "
          f"{len({r['series'] for r in roster})} series", file=sys.stderr)
    print(f"  cutoff: {sum(1 for r in roster if r['basis'] == 'PUB-CATALOG')} published, "
          f"{sum(1 for r in roster if r['basis'] == 'DECLARED')} declared, {len(no_cutoff)} unknown"
          + ("" if a.anchor else " (no --anchor given, so unknown is allowed)"), file=sys.stderr)
    if presumed:
        print(f"  weights PRESUMED closed (no hugging_face_id -- a weak negative signal; override if "
              f"wrong): {presumed}", file=sys.stderr)
    if a.out:
        json.dump(roster, open(a.out, "w"), indent=1)
        print(f"  WROTE {a.out}", file=sys.stderr)
    else:
        json.dump(roster, sys.stdout, indent=1)


if __name__ == "__main__":
    try:
        main()
    except RosterError as e:
        raise SystemExit(f"HALT: {e}")
