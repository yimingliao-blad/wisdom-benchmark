## How this roster was chosen

**Owner-selected, 2026-08-09.** This list is not the output of the automated rule chain that produced
`REFINED_ROSTER.md`. The owner supplied a 27-model list directly, then added `x-ai/grok-4.3` and the
`Qwen3.5` series, and dropped `google/gemma-3-4b-it`. The rules below are the ones that survive as
constraints on that list — not filters that generated it.

1. **Cutoff at or before the anchor.** Every variant's training cutoff is at or before
   `2026-02-16`, so none can have seen the benchmark questions. Where a vendor publishes no cutoff,
   the release date stands in as a conservative bound — training always predates release, so the
   proxy can never wrongly admit a contaminated model. It cannot say how *stale* a model is.
2. **At most 2 open-weight variants per series, counting MoE and dense separately.** Checked and
   holding across every series in this list.

**Rules that produced the refined roster and are NOT applied here.** The 3-per-family cap is gone —
it was the tightest rule and it is what removed every GPT-4-era model and the whole Qwen3 tier. Its
absence is the main reason this roster looks different: it restores the generational axis. The
smallest-per-series rule is also not applied, except that `gemma-3-4b-it` was dropped by the owner
individually.

**What the change buys.** Multi-generation chains that the refined roster could not express:

| family | chain |
|---|---|
| GPT | `4o` / `4o-mini` (2023-10) → `4.1` / `4.1-mini` (2024-06) → `5.4` (2025) |
| Qwen | `2.5-72b` (2024-09) → `3-32b` / `3-235b` (2025-02) → `3.5-27b` / `3.5-122b` / `3.5-397b` (2026-02) |
| Claude | `sonnet-4` (2025-03) → `haiku-4.5` (2025-10) → `opus-4.6` (2026-01) |
| Llama | `3.1-8b` / `3.3-70b` (2023-12) → `4-maverick` / `4-scout` (2024-08) |
| DeepSeek | `r1` (2024-12) → `chat-v3.1` (2025-07) |

Qwen is the strongest instrument: three generations, and dense *and* MoE at the last two, so
"newer" can be separated from "bigger".

**Single points, no generational contrast:** Grok (`4.3` only), GLM (`4.7` only), Kimi (`k2` only),
MiniMax (`m2.5` only), Mistral (`large-2512` only), Gemma (`27b` only), Nemotron (`nano-30b` and
`ultra-550b`, both 2025-12 — a size ladder, not a generation one).

**Prices are the owner's figures**, which are lower than this repo's recorded values for four rows
(`llama-3.1-8b`, `llama-4-maverick`, `gemma-3-27b`, `nemotron-3-ultra`). The projection below is
therefore the optimistic figure; OpenRouter prices move and should be re-checked before the run.

**Cutoffs for the 15 rows not carried by the earlier roster are reconstructed, not vendor-published.**
Each is at or before the anchor, so none is admitted wrongly, but the staleness figures are proxies.

Sizes and architectures come from an explicit table, never parsed from model ids: an `-a3b` suffix
marks some MoE models but not all, so inferring architecture from the name would misclassify
DeepSeek, GLM, Kimi and MiniMax. Rows added by the owner have no entry in that table yet and show
`—` for arch and params.
