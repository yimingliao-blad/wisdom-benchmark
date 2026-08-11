# The OpenRouter run roster — 31 variants, 21 series

> Generated 2026-08-09 by `survey/build_roster_md.py` from `survey/roster_open_only.json`.
> **Contamination anchor `2026-02-16`** — every variant's training cutoff is at or before it,
> so none can have seen the benchmark questions.
> 31 open-weight, 0 closed.
> Projected full run (100 items x 2 arms x 31 variants = 6,200 calls): **$9.73**.

## Selection rules

Applied in order, each recorded in `roster_dropped.json` so no exclusion is silent:

1. **Cutoff at or before the anchor.** Where a vendor publishes no cutoff, the release date
   stands in as a conservative bound — training always predates release, so the proxy can never
   wrongly admit a contaminated model.
2. **Cost.** Two variants were dropped for price alone; both are named below.
3. **Smallest-per-series.** For open-weight series whose variants differ by parameter count,
   the smallest was dropped. It does not fire on series that differ by *version* instead.
4. **At most 2 open-weight variants per series, counting MoE and dense separately** — so a series
   shipping both architectures keeps up to 4. Where the two largest tie on size, the second is
   swapped for the next distinct size, since a same-size pair carries no size signal.
5. **At most 3 variants per FAMILY, newest first** — across all of a vendor's series, not within
   one. GPT keeps `5.6`/`5.5`/`5.4` and drops everything older. Ordering is by release date, with
   the version number breaking ties inside a release year. This is the tightest rule and it binds
   first: it is what removed the whole Qwen3 tier and every GPT-4-era model.

Sizes and architectures come from an explicit table, never parsed from model ids: an `-a3b`
suffix marks some MoE models but not all, so inferring architecture from the name would
misclassify DeepSeek, GLM, Kimi and MiniMax.

**What rule 5 costs.** Keeping only the newest three per family pulls the roster toward recent
cutoffs: 29 of 35 sit at 2025 or later, and the only pre-2025 entries (both Gemmas, `kimi-k2`,
all three Llamas) survive because those families have no newer member. A well-before-cutoff
versus just-before-cutoff comparison is therefore thin, and rests mostly on Llama and Gemma.

## Cutoff provenance

Only some rows carry a cutoff the vendor actually published; the rest are placed by release-date
proxy. The proxy is safe in one direction only — it can never admit a contaminated model, but it
cannot say how *stale* a model is, since the true cutoff may sit far earlier than the release.
`gemini-3.1-pro` is the visible case: cutoff 2025-01, released 2026.

- **release-date proxy** — 11 variants
- **published** — 7 variants
- **release proxy, staggered** — 5 variants
- **vendor spec** — 3 variants
- **release-date proxy** — 3 variants
- **published** — 1 variants
- **release proxy, staggered** — 1 variants

## The roster, oldest cutoff first

| # | model id | series | arch | params | cutoff | basis | release | $/M in | $/M out | full run |
|---:|---|---|---|---:|---|---|---|---:|---:|---:|
| 1 | `meta-llama/llama-3.1-8b-instruct` | Llama 3.x | dense | 8B | 2023-12 | published | 2024-07..2024-12 | 0.05 | 0.08 | $0.02 est |
| 2 | `meta-llama/llama-3.3-70b-instruct` | Llama 3.x | dense | 70B | 2023-12 | published | 2024-07..2024-12 | 0.10 | 0.32 | $0.06 est |
| 3 | `google/gemma-3-12b-it` | Gemma 3 | dense | 12B | 2024-08 | vendor spec | 2025-03 | 0.05 | 0.15 | $0.03 est |
| 4 | `google/gemma-3-27b-it` | Gemma 3 | dense | 27B | 2024-08 | vendor spec | 2025-03 | 0.08 | 0.45 | $0.08 est |
| 5 | `meta-llama/llama-4-maverick` | Llama 4 | MoE | 400B | 2024-08 | published | 2025-04-05 | 0.20 | 0.80 | $0.15 est |
| 6 | `meta-llama/llama-4-scout` | Llama 4 | — | — | 2024-08 | published | 2025-04-05 | 0.10 | 0.30 | $0.06 est |
| 7 | `qwen/qwen-2.5-72b-instruct` | Qwen2.5 | — | — | 2024-09 | release-date proxy | 2024-09 | 0.36 | 0.40 | $0.09 est |
| 8 | `deepseek/deepseek-r1` | DeepSeek R1 | MoE | 671B | 2024-12 | vendor spec | 2025-01 | 0.70 | 2.50 | $1.54 |
| 9 | `moonshotai/kimi-k2` | Kimi K2 | MoE | 1000B | 2024-12-31 | published | 2025 | 0.57 | 2.30 | $0.43 est |
| 10 | `minimax/minimax-m2.5` | MiniMax M2.5 | MoE | 230B | 2025-01 | published | 2025 | 0.22 | 0.90 | $0.17 est |
| 11 | `mistralai/mistral-small-3.2-24b-instruct` | Mistral Small 3.x | dense | 24B | 2025-01-30 | release-date proxy | 2025-01-30 | 0.09 | 0.25 | $0.05 est |
| 12 | `qwen/qwen3-235b-a22b` | Qwen3 | — | — | 2025-02 | release-date proxy | 2025-04-28 | 0.46 | 1.82 | $0.34 est |
| 13 | `qwen/qwen3-32b` | Qwen3 | — | — | 2025-02 | release-date proxy | 2025-04-28 | 0.08 | 0.28 | $0.05 est |
| 14 | `moonshotai/kimi-k2.6` | Kimi K2.6 | MoE | 1000B | 2025-04 | published | 2026 | 0.58 | 2.44 | $0.45 est |
| 15 | `deepseek/deepseek-chat-v3.1` | DeepSeek V3.1 | MoE | 671B | 2025-07 | release-date proxy | 2025 | 0.25 | 0.95 | $0.14 |
| 16 | `deepseek/deepseek-v3.1-terminus` | DeepSeek V3.1 | MoE | 671B | 2025-07 | release-date proxy | 2025 | 0.27 | 1.00 | $0.10 |
| 17 | `z-ai/glm-4.5` | GLM-4.x | MoE | 355B | 2025-07 | release-date proxy | 2025-07 | 0.50 | 2.00 | $1.55 |
| 18 | `z-ai/glm-4.7` | GLM-4.x | MoE | 355B | 2025-07 | release-date proxy | 2025 | 0.40 | 1.75 | $0.33 est |
| 19 | `mistralai/mistral-medium-3.1` | Mistral Medium | dense | — | 2025-08-13 | release-date proxy | 2025-08-13 | 0.40 | 2.00 | $0.37 est |
| 20 | `minimax/minimax-m2.1` | MiniMax M2.x | MoE | 230B | 2025-09 | release-date proxy | 2025 | 0.30 | 1.20 | $0.22 est |
| 21 | `nvidia/nemotron-3-nano-30b-a3b` | Nemotron 3 | — | — | 2025-12 | release proxy, staggered | 2025-12..2026-06 | 0.05 | 0.20 | $0.04 est |
| 22 | `nvidia/nemotron-3-super-120b-a12b` | Nemotron 3 | MoE | 120B | 2025-12 | release proxy, staggered | 2025-12..2026-06 | 0.08 | 0.40 | $0.07 est |
| 23 | `nvidia/nemotron-3-ultra-550b-a55b` | Nemotron 3 | MoE | 550B | 2025-12 | release proxy, staggered | 2025-12..2026-06 | 0.60 | 3.60 | $0.65 est |
| 24 | `mistralai/mistral-large-2512` | Mistral Large | dense | — | 2025-12-01 | release-date proxy | 2025-12-01 | 0.50 | 1.50 | $0.29 est |
| 25 | `deepseek/deepseek-v3.2` | DeepSeek V3.2 | MoE | 671B | 2026-01 | release-date proxy | 2026 | 0.26 | 0.38 | $0.05 |
| 26 | `z-ai/glm-5` | GLM-5 | MoE | 744B | 2026-01 | release-date proxy | 2026-01 | 0.95 | 2.55 | $0.50 est |
| 27 | `minimax/minimax-m3` | MiniMax M3 | MoE | 230B | 2026-01 | published | 2026 | 0.30 | 1.20 | $0.22 est |
| 28 | `moonshotai/kimi-k2.5` | Kimi K2.5 | MoE | 1000B | 2026-01-27 | release-date proxy | 2026-01-27 | 0.57 | 2.85 | $0.52 est |
| 29 | `qwen/qwen3.5-122b-a10b` | Qwen3.5 | MoE | 122B | 2026-02-16 | release proxy, staggered | 2026-02-16..2026-04 | 0.29 | 2.40 | $0.43 est |
| 30 | `qwen/qwen3.5-27b` | Qwen3.5 | dense | 27B | 2026-02-16 | release proxy, staggered | 2026-02-16..2026-04 | 0.20 | 1.56 | $0.28 est |
| 31 | `qwen/qwen3.5-397b-a17b` | Qwen3.5 | MoE | 397B | 2026-02-16 | release proxy, staggered | 2026-02-16..2026-04 | 0.39 | 2.34 | $0.43 est |

Rows without `est` are costed from **measured** tokens in the smoke run. `est` rows use the
fleet average (316 prompt / 856 completion tokens), which is still moving
as the smoke progresses — re-run this script when it finishes.

## Cost concentration

The five priciest variants are 49% of the bill; the 16 cheapest come to $1.39.

| rank | model | full run | share |
|---:|---|---:|---:|
| 1 | `z-ai/glm-4.5` | $1.55 | 16.0% |
| 2 | `deepseek/deepseek-r1` | $1.54 | 15.9% |
| 3 | `nvidia/nemotron-3-ultra-550b-a55b` | $0.65 | 6.7% |
| 4 | `moonshotai/kimi-k2.5` | $0.52 | 5.4% |
| 5 | `z-ai/glm-5` | $0.50 | 5.1% |
| 6 | `moonshotai/kimi-k2.6` | $0.45 | 4.7% |
| 7 | `moonshotai/kimi-k2` | $0.43 | 4.4% |
| 8 | `qwen/qwen3.5-122b-a10b` | $0.43 | 4.4% |

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
