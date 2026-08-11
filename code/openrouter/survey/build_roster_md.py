"""Regenerate survey/ROSTER.md from roster.json + whatever the smoke run has measured so far.

Costs are MEASURED where the smoke has reached a model and ESTIMATED from the fleet average
elsewhere; every estimated row is marked, because the fleet average moves as the run progresses
(it went 536 -> 785 completion tokens as the reasoning-heavy models came in) and an unmarked
estimate would read as a measurement. Re-run this after the smoke finishes to replace every
estimate with a measured number.
"""
import collections
import datetime
import json
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
N_ITEMS, N_ARMS, ANCHOR = 100, 2, "2026-02-16"
BASIS = {"PUB": "published", "T2": "vendor spec", "PROXY": "release-date proxy",
         "PROXY-STAGGERED": "release proxy, staggered",
         # roster_build.py's vocabulary: where the CUTOFF came from, never a guess.
         "PUB-CATALOG": "published (OpenRouter catalog)",
         "DECLARED": "declared with a reason",
         "UNKNOWN": "UNKNOWN — not published, not declared"}


def load_measured(records):
    if not os.path.exists(records):
        return {}, None
    ok = [r for r in (json.loads(l) for l in open(records) if l.strip())
          if r.get("ok") and r.get("usage")]
    by = collections.defaultdict(list)
    for r in ok:
        by[r["model"]].append((r["usage"].get("prompt_tokens", 0),
                               r["usage"].get("completion_tokens", 0)))
    fleet = (st.mean([p for v in by.values() for p, _ in v]),
             st.mean([c for v in by.values() for _, c in v])) if by else None
    return by, fleet


def main():
    global N_ITEMS, N_ARMS
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster", default=os.path.join(HERE, "roster_refined.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "REFINED_ROSTER.md"))
    # Which run supplies the measured token counts. Default is the budget probe; pass the real
    # smoke's records once it exists so the table is costed from the locked budget, not the probe's.
    ap.add_argument("--notes", default=None,
                    help="Markdown file whose contents REPLACE the hardcoded selection-rules prose. "
                         "Without it the built-in text is used, which describes the ORIGINAL refined "
                         "roster and is wrong for any other input -- a doc that misdescribes how its "
                         "own list was chosen is worse than one with no prose at all.")
    ap.add_argument("--records", default=os.path.join(
        HERE, "..", "runs", "or_futurex_smoke_budget2000", "records.jsonl"))
    ap.add_argument("--dropped", default=os.path.join(HERE, "roster_dropped.json"),
                    help="the exclusion ledger for THIS roster -- pairing a roster with another "
                         "roster's dropped list would print exclusions that never applied to it")
    # The projected cost has to match the run actually planned. These were hardcoded 100x2, which
    # is 2.2x the current futurex plan (110 items x 1 arm) -- a projection off by that much is not
    # a budget, it is a guess wearing a dollar sign.
    ap.add_argument("--n-items", type=int, default=N_ITEMS)
    ap.add_argument("--n-arms", type=int, default=N_ARMS)
    ar = ap.parse_args()
    N_ITEMS, N_ARMS = ar.n_items, ar.n_arms
    roster = json.load(open(ar.roster))
    dropped = json.load(open(ar.dropped))
    by, fleet = load_measured(ar.records)
    if fleet is None:
        raise SystemExit("HALT: no measured calls yet — refusing to emit a table of pure guesses.")

    def cost(m):
        obs = by.get(m["id"])
        p, c = (st.mean([x for x, _ in obs]), st.mean([x for _, x in obs])) if obs else fleet
        return (p / 1e6 * m["in"] + c / 1e6 * m["out"]) * N_ITEMS * N_ARMS, bool(obs)

    total = sum(cost(m)[0] for m in roster)
    n_open = sum(1 for m in roster if m.get("weights") == "open")
    L = [f"# The OpenRouter run roster — {len(roster)} variants, "
         f"{len({m['series'] for m in roster})} series\n",
         f"> Generated {datetime.date.today()} by `survey/build_roster_md.py` from "
         f"`survey/{os.path.basename(ar.roster)}`.",
         f"> **Contamination anchor `{ANCHOR}`** — every variant's training cutoff is at or before it,",
         "> so none can have seen the benchmark questions.",
         f"> {n_open} open-weight, {len(roster) - n_open} closed.",
         f"> Projected full run ({N_ITEMS} items x {N_ARMS} arms x {len(roster)} variants = "
         f"{N_ITEMS * N_ARMS * len(roster):,} calls): **${total:,.2f}**.\n",
         *(  # the prose is per-ROSTER, not universal: the built-in text below describes the
            # ORIGINAL refined roster and is WRONG for any other input. A doc that misdescribes
            # how its own list was chosen is worse than one with no prose at all, so --notes
            # replaces it wholesale.
            (open(ar.notes).read().rstrip().split("\n") + [""]) if ar.notes else [
            "## Selection rules\n",
            "Applied in order, each recorded in `roster_dropped.json` so no exclusion is silent:\n",
            "1. **Cutoff at or before the anchor.** Where a vendor publishes no cutoff, the release date",
            "   stands in as a conservative bound — training always predates release, so the proxy can never",
            "   wrongly admit a contaminated model.",
            "2. **Cost.** Two variants were dropped for price alone; both are named below.",
            "3. **Smallest-per-series.** For open-weight series whose variants differ by parameter count,",
            "   the smallest was dropped. It does not fire on series that differ by *version* instead.",
            "4. **At most 2 open-weight variants per series, counting MoE and dense separately** — so a series",
            "   shipping both architectures keeps up to 4. Where the two largest tie on size, the second is",
            "   swapped for the next distinct size, since a same-size pair carries no size signal.",
            "5. **At most 3 variants per FAMILY, newest first** — across all of a vendor's series, not within",
            "   one. GPT keeps `5.6`/`5.5`/`5.4` and drops everything older. Ordering is by release date, with",
            "   the version number breaking ties inside a release year. This is the tightest rule and it binds",
            "   first: it is what removed the whole Qwen3 tier and every GPT-4-era model.\n",
            "Sizes and architectures come from an explicit table, never parsed from model ids: an `-a3b`",
            "suffix marks some MoE models but not all, so inferring architecture from the name would",
            "misclassify DeepSeek, GLM, Kimi and MiniMax.\n",
            "**What rule 5 costs.** Keeping only the newest three per family pulls the roster toward recent",
            "cutoffs: 29 of 35 sit at 2025 or later, and the only pre-2025 entries (both Gemmas, `kimi-k2`,",
            "all three Llamas) survive because those families have no newer member. A well-before-cutoff",
            "versus just-before-cutoff comparison is therefore thin, and rests mostly on Llama and Gemma.\n",
         ]),
         "## Cutoff provenance\n",
         "Every cutoff is labelled by where it came from, and none is inferred from a release date.",
         "**published (OpenRouter catalog)** is the vendor's own `knowledge_cutoff` as served by the API.",
         "**declared with a reason** is a human statement recorded in the roster's overrides file, each",
         "carrying the reason it was needed — the catalog publishes a cutoff for fewer than half of all",
         "models. **UNKNOWN** means neither, and a roster built with `--anchor` cannot contain one: the",
         "build refuses, because a contamination anchor enforced over guessed cutoffs is not enforced.\n",
         "A declared cutoff standing in for a release date can only over-estimate how recent a model's",
         "knowledge is, so it never wrongly admits a contaminated model — but it also cannot say how",
         "*stale* the model is, since the true cutoff may sit far earlier.\n"]
    for k, v in collections.Counter(m["basis"] for m in roster).most_common():
        L.append(f"- **{BASIS.get(k, k)}** — {v} variants")

    L += ["\n## The roster, oldest cutoff first\n",
          "| # | model id | series | arch | params | cutoff | basis | release | $/M in | $/M out | full run |",
          "|---:|---|---|---|---:|---|---|---|---:|---:|---:|"]
    for i, m in enumerate(sorted(roster, key=lambda m: (m["cutoff"], m["series"], m["id"])), 1):
        c, meas = cost(m)
        arch = m.get("arch", "—")
        prm = f"{m['params_b']}B" if m.get("params_b") else "—"
        L.append(f"| {i} | `{m['id']}` | {m['series']} | {arch} | {prm} | {m['cutoff']} | "
                 f"{BASIS.get(m['basis'], m['basis'])} | {m['release']} | {m['in']:.2f} | "
                 f"{m['out']:.2f} | ${c:.2f}{'' if meas else ' est'} |")
    L += [f"\nRows without `est` are costed from **measured** tokens in the smoke run. `est` rows use the",
          f"fleet average ({fleet[0]:.0f} prompt / {fleet[1]:.0f} completion tokens), which is still moving",
          f"as the smoke progresses — re-run this script when it finishes.\n",
          "## Cost concentration\n"]
    cr = sorted(((cost(m)[0], m) for m in roster), key=lambda x: -x[0])
    L += [f"The five priciest variants are {100 * sum(c for c, _ in cr[:5]) / total:.0f}% of the bill; "
          f"the {len(cr) - 15} cheapest come to ${sum(c for c, _ in cr[15:]):.2f}.\n",
          "| rank | model | full run | share |", "|---:|---|---:|---:|"]
    for i, (c, m) in enumerate(cr[:8], 1):
        L.append(f"| {i} | `{m['id']}` | ${c:.2f} | {100 * c / total:.1f}% |")

    L += [f"\n## Excluded ({len(dropped)})\n", "| model | reason |", "|---|---|"]
    for d, why in sorted(dropped.items()):
        L.append(f"| `{d}` | {why} |")
    open(ar.out, "w").write("\n".join(L) + "\n")
    print(f"  {os.path.basename(ar.out)}: {len(roster)} variants ({n_open} open / {len(roster) - n_open} closed), "
          f"${total:,.2f} projected, {sum(1 for m in roster if cost(m)[1])} rows measured")


if __name__ == "__main__":
    main()
