# The OpenRouter run roster — 30 variants, 21 series

> Generated 2026-08-09 by `survey/build_roster_md.py` from `survey/roster_final.json`.
> **Contamination anchor `2026-02-16`** — every variant's training cutoff is at or before it,
> so none can have seen the benchmark questions.
> 19 open-weight, 11 closed.
> Projected full run (100 items x 2 arms x 30 variants = 6,000 calls): **$21.00**.

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

## Cutoff provenance

Only some rows carry a cutoff the vendor actually published; the rest are placed by release-date
proxy. The proxy is safe in one direction only — it can never admit a contaminated model, but it
cannot say how *stale* a model is, since the true cutoff may sit far earlier than the release.
`gemini-3.1-pro` is the visible case: cutoff 2025-01, released 2026.

- **published** — 9 variants
- **published** — 7 variants
- **release-date proxy** — 4 variants
- **release proxy, staggered** — 4 variants
- **release-date proxy** — 3 variants
- **vendor spec** — 2 variants
- **release proxy, staggered** — 1 variants

## The roster, oldest cutoff first

| # | model id | series | arch | params | cutoff | basis | release | $/M in | $/M out | full run |
|---:|---|---|---|---:|---|---|---|---:|---:|---:|
| 1 | `openai/gpt-4o` | GPT-4o | — | — | 2023-10 | published | 2024-05 | 2.50 | 10.00 | $1.87 est |
| 2 | `openai/gpt-4o-mini` | GPT-4o | — | — | 2023-10 | published | 2024-05 | 0.15 | 0.60 | $0.11 est |
| 3 | `meta-llama/llama-3.1-8b-instruct` | Llama 3.x | dense | 8B | 2023-12 | published | 2024-07..2024-12 | 0.02 | 0.04 | $0.01 est |
| 4 | `meta-llama/llama-3.3-70b-instruct` | Llama 3.x | dense | 70B | 2023-12 | published | 2024-07..2024-12 | 0.10 | 0.32 | $0.06 est |
| 5 | `openai/gpt-4.1` | GPT-4.1 | — | — | 2024-06 | published | 2025-04 | 2.00 | 8.00 | $1.50 est |
| 6 | `openai/gpt-4.1-mini` | GPT-4.1 | — | — | 2024-06 | published | 2025-04 | 0.40 | 1.60 | $0.30 est |
| 7 | `google/gemma-3-27b-it` | Gemma 3 | dense | 27B | 2024-08 | vendor spec | 2025-03 | 0.08 | 0.16 | $0.03 est |
| 8 | `meta-llama/llama-4-maverick` | Llama 4 | MoE | 400B | 2024-08 | published | 2025-04-05 | 0.20 | 0.70 | $0.13 est |
| 9 | `meta-llama/llama-4-scout` | Llama 4 | — | — | 2024-08 | published | 2025-04-05 | 0.10 | 0.30 | $0.06 est |
| 10 | `qwen/qwen-2.5-72b-instruct` | Qwen2.5 | — | — | 2024-09 | release-date proxy | 2024-09 | 0.36 | 0.40 | $0.09 est |
| 11 | `deepseek/deepseek-r1` | DeepSeek R1 | MoE | 671B | 2024-12 | vendor spec | 2025-01 | 0.70 | 2.50 | $1.54 |
| 12 | `moonshotai/kimi-k2` | Kimi K2 | MoE | 1000B | 2024-12-31 | published | 2025 | 0.57 | 2.30 | $0.43 est |
| 13 | `google/gemini-3.1-flash-lite` | Gemini 3.x | — | — | 2025-01 | published | 2026-01 | 0.25 | 1.50 | $0.27 est |
| 14 | `google/gemini-3.1-pro-preview` | Gemini 3.x | — | — | 2025-01 | published | 2026 | 2.00 | 12.00 | $2.18 est |
| 15 | `minimax/minimax-m2.5` | MiniMax M2.5 | MoE | 230B | 2025-01 | published | 2025 | 0.22 | 0.90 | $0.17 est |
| 16 | `qwen/qwen3-235b-a22b` | Qwen3 | — | — | 2025-02 | release-date proxy | 2025-04-28 | 0.46 | 1.82 | $0.34 est |
| 17 | `qwen/qwen3-32b` | Qwen3 | — | — | 2025-02 | release-date proxy | 2025-04-28 | 0.08 | 0.28 | $0.05 est |
| 18 | `anthropic/claude-sonnet-4` | Claude Sonnet 4 | — | — | 2025-03 | published | 2025-05 | 3.00 | 15.00 | $1.77 |
| 19 | `deepseek/deepseek-chat-v3.1` | DeepSeek V3.1 | MoE | 671B | 2025-07 | release-date proxy | 2025 | 0.25 | 0.95 | $0.14 |
| 20 | `z-ai/glm-4.7` | GLM-4.x | MoE | 355B | 2025-07 | release-date proxy | 2025 | 0.40 | 1.75 | $0.33 est |
| 21 | `openai/gpt-5.4` | GPT-5.2/5.4 | — | — | 2025-08-31 | published | 2025 | 2.50 | 15.00 | $2.73 est |
| 22 | `anthropic/claude-haiku-4.5` | Claude Haiku 4.5 | — | — | 2025-10 | published | 2025-10 | 1.00 | 5.00 | $0.57 |
| 23 | `x-ai/grok-4.3` | Grok 4.3 | — | — | 2025-11 | release-date proxy | 2025 | 1.25 | 2.50 | $0.51 est |
| 24 | `nvidia/nemotron-3-nano-30b-a3b` | Nemotron 3 | — | — | 2025-12 | release proxy, staggered | 2025-12..2026-06 | 0.05 | 0.20 | $0.04 est |
| 25 | `nvidia/nemotron-3-ultra-550b-a55b` | Nemotron 3 | MoE | 550B | 2025-12 | release proxy, staggered | 2025-12..2026-06 | 0.50 | 2.20 | $0.41 est |
| 26 | `mistralai/mistral-large-2512` | Mistral Large | dense | — | 2025-12-01 | release-date proxy | 2025-12-01 | 0.50 | 1.50 | $0.29 est |
| 27 | `anthropic/claude-opus-4.6` | Claude Opus 4.6 | — | — | 2026-01 | published | 2026-02-05 | 5.00 | 25.00 | $3.93 |
| 28 | `qwen/qwen3.5-122b-a10b` | Qwen3.5 | MoE | 122B | 2026-02-16 | release proxy, staggered | 2026-02-16..2026-04 | 0.29 | 2.40 | $0.43 est |
| 29 | `qwen/qwen3.5-27b` | Qwen3.5 | dense | 27B | 2026-02-16 | release proxy, staggered | 2026-02-16..2026-04 | 0.20 | 1.56 | $0.28 est |
| 30 | `qwen/qwen3.5-397b-a17b` | Qwen3.5 | MoE | 397B | 2026-02-16 | release proxy, staggered | 2026-02-16..2026-04 | 0.39 | 2.34 | $0.43 est |

Rows without `est` are costed from **measured** tokens in the smoke run. `est` rows use the
fleet average (316 prompt / 856 completion tokens), which is still moving
as the smoke progresses — re-run this script when it finishes.

## Cost concentration

The five priciest variants are 59% of the bill; the 15 cheapest come to $2.04.

| rank | model | full run | share |
|---:|---|---:|---:|
| 1 | `anthropic/claude-opus-4.6` | $3.93 | 18.7% |
| 2 | `openai/gpt-5.4` | $2.73 | 13.0% |
| 3 | `google/gemini-3.1-pro-preview` | $2.18 | 10.4% |
| 4 | `openai/gpt-4o` | $1.87 | 8.9% |
| 5 | `anthropic/claude-sonnet-4` | $1.77 | 8.4% |
| 6 | `deepseek/deepseek-r1` | $1.54 | 7.3% |
| 7 | `openai/gpt-4.1` | $1.50 | 7.1% |
| 8 | `anthropic/claude-haiku-4.5` | $0.57 | 2.7% |

## Excluded (33)

| model | reason |
|---|---|
| `anthropic/claude-3-haiku` | dropped by owner, 2026-08-07 |
| `anthropic/claude-fable-5` | dropped on cost — $10/$50 per M and ~1000 output tokens per call, 22.5% of the whole run by itself (owner, 2026-08-07) |
| `anthropic/claude-haiku-4.5` | over the 3-per-family cap for Claude (released 2025-10); kept claude-sonnet-5, claude-opus-4.8, claude-sonnet-4.6 |
| `anthropic/claude-opus-4` | dropped on cost — $15/$75 per M, priciest per-token in the roster, only a vendor-spec 2025-03 cutoff (owner, 2026-08-07) |
| `anthropic/claude-opus-4.1` | dropped on cost — $15/$75 per M, priciest per-token in the roster, only a vendor-spec 2025-03 cutoff (owner, 2026-08-07) |
| `anthropic/claude-opus-4.5` | over the 3-per-family cap for Claude (released 2025-11-24); kept claude-sonnet-5, claude-opus-4.8, claude-sonnet-4.6 |
| `anthropic/claude-opus-4.6` | over the 3-per-family cap for Claude (released 2026-02-05); kept claude-sonnet-5, claude-opus-4.8, claude-sonnet-4.6 |
| `anthropic/claude-sonnet-4` | over the 3-per-family cap for Claude (released 2025-05); kept claude-sonnet-5, claude-opus-4.8, claude-sonnet-4.6 |
| `google/gemini-3.1-flash-lite` | over the 3-per-family cap for Gemini (released 2026-01); kept gemini-3.5-flash, gemini-3.5-flash-lite, gemini-3.1-pro-preview |
| `google/gemma-3-4b-it` | smallest of Gemma 3 (4B); series keeps 12B, 27B |
| `meta-llama/llama-3.1-70b-instruct` | over the 2-per-architecture cap for Llama 3.x (dense, 70B); kept 70B llama-3.3-70b-instruct + 8B llama-3.1-8b-instruct |
| `meta-llama/llama-3.2-1b-instruct` | smallest of Llama 3.x (1B); series keeps 3B, 8B, 70B, 70B |
| `meta-llama/llama-3.2-3b-instruct` | over the 2-per-architecture cap for Llama 3.x (dense, 3B); kept 70B llama-3.3-70b-instruct + 8B llama-3.1-8b-instruct |
| `meta-llama/llama-4-scout` | smallest of Llama 4 (109B); series keeps 400B |
| `minimax/minimax-m2` | over the 3-per-family cap for MiniMax (released 2025-10); kept minimax-m3, minimax-m2.5, minimax-m2.1 |
| `mistralai/mistral-small-3.1-24b-instruct` | UNUSABLE on OpenRouter — its only provider (Cloudflare) returns finish_reason=error with prompt_tokens=0 and a cut-off echo of the question; reproducible 2/2, and excluding that provider 404s because no other serves this model (verified 2026-08-08) |
| `nvidia/nemotron-3-nano-30b-a3b` | smallest of Nemotron 3 (30B); series keeps 120B, 550B |
| `openai/gpt-4.1` | over the 3-per-family cap for GPT (released 2025-04); kept gpt-5.6-sol, gpt-5.5, gpt-5.4 |
| `openai/gpt-4.1-mini` | over the 3-per-family cap for GPT (released 2025-04); kept gpt-5.6-sol, gpt-5.5, gpt-5.4 |
| `openai/gpt-4.1-nano` | over the 3-per-family cap for GPT (released 2025-04); kept gpt-5.6-sol, gpt-5.5, gpt-5.4 |
| `openai/gpt-4o` | over the 3-per-family cap for GPT (released 2024-05); kept gpt-5.6-sol, gpt-5.5, gpt-5.4 |
| `openai/gpt-4o-mini` | over the 3-per-family cap for GPT (released 2024-05); kept gpt-5.6-sol, gpt-5.5, gpt-5.4 |
| `openai/gpt-5.2` | over the 3-per-family cap for GPT (released 2025-06); kept gpt-5.6-sol, gpt-5.5, gpt-5.4 |
| `qwen/qwen-2.5-72b-instruct` | over the 3-per-family cap for Qwen (released 2024-09); kept qwen3.5-397b-a17b, qwen3.5-122b-a10b, qwen3.5-27b |
| `qwen/qwen-2.5-7b-instruct` | smallest of Qwen2.5 (7B); series keeps 72B |
| `qwen/qwen3-14b` | over the 3-per-family cap for Qwen (released 2025-04-28); kept qwen3.5-397b-a17b, qwen3.5-122b-a10b, qwen3.5-27b |
| `qwen/qwen3-235b-a22b` | over the 3-per-family cap for Qwen (released 2025-04-28); kept qwen3.5-397b-a17b, qwen3.5-122b-a10b, qwen3.5-27b |
| `qwen/qwen3-30b-a3b` | over the 3-per-family cap for Qwen (released 2025-04-28); kept qwen3.5-397b-a17b, qwen3.5-122b-a10b, qwen3.5-27b |
| `qwen/qwen3-32b` | over the 3-per-family cap for Qwen (released 2025-04-28); kept qwen3.5-397b-a17b, qwen3.5-122b-a10b, qwen3.5-27b |
| `qwen/qwen3-8b` | smallest of Qwen3 (8B); series keeps 14B, 30B, 32B, 235B |
| `qwen/qwen3.5-35b-a3b` | over the 2-per-architecture cap for Qwen3.5 (MoE, 35B); kept 397B qwen3.5-397b-a17b + 122B qwen3.5-122b-a10b |
| `qwen/qwen3.5-9b` | smallest of Qwen3.5 (9B); series keeps 27B, 35B, 122B, 397B |
| `z-ai/glm-4.6` | replaced by glm-4.5 (owner 2026-08-08): reproducibly returns 0 visible chars on one (item, cot) pair after consuming 16k->131k tokens; 13/14 healthy otherwise, but the failing unit cost ~1h of wall-clock before the escalation cap was added |
