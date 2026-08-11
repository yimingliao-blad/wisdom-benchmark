# The OpenRouter run roster — 25 variants, 15 series

> Generated 2026-08-10 by `survey/build_roster_md.py` from `survey/roster_25.json`.
> **Contamination anchor `2026-02-16`** — every variant's training cutoff is at or before it,
> so none can have seen the benchmark questions.
> 16 open-weight, 9 closed.
> Projected full run (110 items x 1 arms x 25 variants = 2,750 calls): **$16.06**.

## Where this list came from, and how to change it

**The owner supplied these 25 model names on 2026-08-09.** The list lives in
[`models_owner_25.txt`](models_owner_25.txt) — one id per line, with an optional family after a `|`.
To change the roster, edit that file and rebuild:

```bash
python3 survey/roster_build.py --models survey/models_owner_25.txt \
    --overrides survey/overrides_owner_25.json --anchor 2026-02-16 --out survey/roster_25.json
```

**No code names a model.** That is enforced, not just intended: `test_roster_build.py` scans every
`.py` file in the project for an OpenRouter model id and fails if it finds one, and the scanner is
itself tested against a planted id so it cannot pass vacuously. The previous builder carried all 25
names as a literal in its own source — changing the roster meant editing code — and has been deleted.

## What is derived, and what a human had to say

Everything the OpenRouter catalog publishes is re-fetched on every build; each row records its own
`field_sources`, so no field's origin is a matter of memory.

| field | source |
|---|---|
| exists | the catalog. An unresolvable name **halts the build** — the alternative is 110 failed calls with the budget already spent |
| `in` / `out` | live per-million prices. The spend ledger meters real money against these, so a stale low price would loosen `--max-spend` by exactly that factor |
| `cap` | `max_completion_tokens`, else `context_length`. No ceiling derivable ⇒ halt, never an invented one |
| `release` | the catalog's `created` timestamp |
| `cutoff` | the catalog's `knowledge_cutoff` **where published** — 13 of these 25 |
| `weights` | open iff a `hugging_face_id` is present |
| `series` | the family column in the model list, else parsed from the display name |

**The 12 declared cutoffs.** OpenRouter carries `knowledge_cutoff` for fewer than half its catalog
(194 of 400). For the 12 it is silent on, the value is stated in
[`overrides_owner_25.json`](overrides_owner_25.json), each with the reason it was needed —
seven are vendor-published figures the catalog simply does not carry, five are release-date proxies
and say so. An override without a reason is refused, as is one naming a model not in the list.

**Nothing is guessed.** An unpublished, undeclared cutoff stays `null`; the release date is sitting
right there and is deliberately not used. `--anchor 2026-02-16` is what turns a null into a halt —
and that is the *study's* admission rule, not the roster's, which is why it is a separate flag. You
can build a roster for any list of models without it.

**Where the catalog corrected us.** Five cutoffs we had previously researched by hand disagree with
the vendor's published figure, and in every case ours was a `PROXY` guess while the catalog had the
real thing: `qwen3-32b` and `qwen3-235b` 2025-02 → 2025-03-31, `qwen-2.5-72b` 2024-09 → 2024-06-30,
`deepseek-r1` 2024-12 → 2024-07-31, `deepseek-chat-v3.1` 2025-07 → 2025-03-31. Every row we had
marked `PUB` agreed exactly. All 25 remain at or before the anchor, so admission is unchanged, but
the staleness ordering in the table below is not the one we had before.

**One weights correction.** `hugging_face_id` matched a hand-labelled open/closed list 24/25; the
miss was `mistral-large-2512`, which is open-weight but carries no hf id in the catalog. So absence
is reported as *presumed* closed and is overridable — the derivation is a strong positive signal and
a weak negative one, and is never presented as something the catalog asserted.

## What the list contains

16 open-weight, 9 closed, across 15 families. Eight families carry 2–3 variants; seven carry one.

| family | variants |
|---|---|
| Claude | `claude-haiku-4.5`, `claude-sonnet-4.6`, `claude-opus-4.8` |
| GPT-5.x | `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini` |
| Gemini 3.x | `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview` |
| Llama 3.x | `llama-3.1-8b-instruct`, `llama-3.3-70b-instruct` |
| Llama 4 | `llama-4-maverick`, `llama-4-scout` |
| Qwen3 | `qwen3-32b`, `qwen3-235b-a22b` |
| DeepSeek | `deepseek-r1`, `deepseek-chat-v3.1` |
| Nemotron 3 | `nemotron-3-nano-30b-a3b`, `nemotron-3-ultra-550b-a55b` |
| single-variant | `grok-4.3`, `gemma-3-27b-it`, `qwen-2.5-72b-instruct`, `mistral-large-2512`, `glm-4.7`, `kimi-k2`, `minimax-m2.5` |

## What changed against the roster the halted run used

`roster_refined.json` (37 models) is what the interrupted FutureX run was frozen against. Against it
this list **keeps 17, adds 8, drops 20** — the 20 are listed at the end of this document.

**The halted run does not need to be abandoned.** A declared supersession
(`--supersede-manifest '<why>'`) re-freezes that directory in place: the 411 calls already answered
by models still on the list are kept, the 2,339 missing units are bought, and the 608 records for
dropped models are retained as out-of-plan evidence rather than deleted or folded into a denominator
they were never planned under.

## Cutoff provenance

Every cutoff is labelled by where it came from, and none is inferred from a release date.
**published (OpenRouter catalog)** is the vendor's own `knowledge_cutoff` as served by the API.
**declared with a reason** is a human statement recorded in the roster's overrides file, each
carrying the reason it was needed — the catalog publishes a cutoff for fewer than half of all
models. **UNKNOWN** means neither, and a roster built with `--anchor` cannot contain one: the
build refuses, because a contamination anchor enforced over guessed cutoffs is not enforced.

A declared cutoff standing in for a release date can only over-estimate how recent a model's
knowledge is, so it never wrongly admits a contaminated model — but it also cannot say how
*stale* the model is, since the true cutoff may sit far earlier.

- **published (OpenRouter catalog)** — 13 variants
- **declared with a reason** — 12 variants

## The roster, oldest cutoff first

| # | model id | series | arch | params | cutoff | basis | release | $/M in | $/M out | full run |
|---:|---|---|---|---:|---|---|---|---:|---:|---:|
| 1 | `meta-llama/llama-3.1-8b-instruct` | Llama 3.x | — | — | 2023-12-31 | published (OpenRouter catalog) | 2024-07 | 0.05 | 0.08 | $0.00 |
| 2 | `meta-llama/llama-3.3-70b-instruct` | Llama 3.x | — | — | 2023-12-31 | published (OpenRouter catalog) | 2024-12 | 0.10 | 0.32 | $0.02 |
| 3 | `qwen/qwen-2.5-72b-instruct` | Qwen2.5 | — | — | 2024-06-30 | published (OpenRouter catalog) | 2024-09 | 0.36 | 0.40 | $0.08 est |
| 4 | `deepseek/deepseek-r1` | DeepSeek | — | — | 2024-07-31 | published (OpenRouter catalog) | 2025-01 | 0.70 | 2.50 | $0.54 |
| 5 | `google/gemma-3-27b-it` | Gemma 3 | — | — | 2024-08-31 | published (OpenRouter catalog) | 2025-03 | 0.08 | 0.45 | $0.03 |
| 6 | `meta-llama/llama-4-maverick` | Llama 4 | — | — | 2024-08-31 | published (OpenRouter catalog) | 2025-04 | 0.20 | 0.70 | $0.05 |
| 7 | `meta-llama/llama-4-scout` | Llama 4 | — | — | 2024-08-31 | published (OpenRouter catalog) | 2025-04 | 0.10 | 0.30 | $0.06 est |
| 8 | `moonshotai/kimi-k2` | Kimi K2 | — | — | 2024-12-31 | published (OpenRouter catalog) | 2025-07 | 0.57 | 2.30 | $0.13 |
| 9 | `google/gemini-3.1-flash-lite` | Gemini 3.x | — | — | 2025-01 | declared with a reason | 2026-05 | 0.25 | 1.50 | $0.28 est |
| 10 | `google/gemini-3.1-pro-preview` | Gemini 3.x | — | — | 2025-01 | declared with a reason | 2026-02 | 2.00 | 12.00 | $1.20 |
| 11 | `minimax/minimax-m2.5` | MiniMax M2.x | — | — | 2025-01 | declared with a reason | 2026-02 | 0.22 | 0.90 | $0.37 |
| 12 | `deepseek/deepseek-chat-v3.1` | DeepSeek | — | — | 2025-03-31 | published (OpenRouter catalog) | 2025-08 | 0.25 | 0.95 | $0.02 |
| 13 | `qwen/qwen3-235b-a22b` | Qwen3 | — | — | 2025-03-31 | published (OpenRouter catalog) | 2025-04 | 0.46 | 1.82 | $0.34 est |
| 14 | `qwen/qwen3-32b` | Qwen3 | — | — | 2025-03-31 | published (OpenRouter catalog) | 2025-04 | 0.08 | 0.28 | $0.05 est |
| 15 | `z-ai/glm-4.7` | GLM-4.x | — | — | 2025-07 | declared with a reason | 2025-12 | 0.40 | 1.75 | $0.56 |
| 16 | `openai/gpt-5.4` | GPT-5.x | — | — | 2025-08-31 | declared with a reason | 2026-03 | 2.50 | 15.00 | $0.21 |
| 17 | `openai/gpt-5.4-mini` | GPT-5.x | — | — | 2025-08-31 | published (OpenRouter catalog) | 2026-03 | 0.75 | 4.50 | $0.83 est |
| 18 | `anthropic/claude-haiku-4.5` | Claude | — | — | 2025-10 | declared with a reason | 2025-10 | 1.00 | 5.00 | $0.93 est |
| 19 | `x-ai/grok-4.3` | Grok 4.3 | — | — | 2025-11 | declared with a reason | 2026-04 | 1.25 | 2.50 | $0.26 |
| 20 | `nvidia/nemotron-3-nano-30b-a3b` | Nemotron 3 | — | — | 2025-12 | declared with a reason | 2025-12 | 0.05 | 0.20 | $0.04 est |
| 21 | `nvidia/nemotron-3-ultra-550b-a55b` | Nemotron 3 | — | — | 2025-12 | declared with a reason | 2026-06 | 0.60 | 3.60 | $1.71 |
| 22 | `openai/gpt-5.5` | GPT-5.x | — | — | 2025-12-01 | published (OpenRouter catalog) | 2026-04 | 5.00 | 30.00 | $6.02 |
| 23 | `mistralai/mistral-large-2512` | Mistral Large 3 | — | — | 2025-12-01 | declared with a reason | 2025-12 | 0.50 | 1.50 | $0.07 |
| 24 | `anthropic/claude-opus-4.8` | Claude | — | — | 2026-01 | declared with a reason | 2026-05 | 5.00 | 25.00 | $1.40 |
| 25 | `anthropic/claude-sonnet-4.6` | Claude | — | — | 2026-01 | declared with a reason | 2026-02 | 3.00 | 15.00 | $0.86 |

Rows without `est` are costed from **measured** tokens in the smoke run. `est` rows use the
fleet average (267 prompt / 1641 completion tokens), which is still moving
as the smoke progresses — re-run this script when it finishes.

## Cost concentration

The five priciest variants are 70% of the bill; the 10 cheapest come to $0.41.

| rank | model | full run | share |
|---:|---|---:|---:|
| 1 | `openai/gpt-5.5` | $6.02 | 37.5% |
| 2 | `nvidia/nemotron-3-ultra-550b-a55b` | $1.71 | 10.6% |
| 3 | `anthropic/claude-opus-4.8` | $1.40 | 8.7% |
| 4 | `google/gemini-3.1-pro-preview` | $1.20 | 7.5% |
| 5 | `anthropic/claude-haiku-4.5` | $0.93 | 5.8% |
| 6 | `anthropic/claude-sonnet-4.6` | $0.86 | 5.4% |
| 7 | `openai/gpt-5.4-mini` | $0.83 | 5.2% |
| 8 | `z-ai/glm-4.7` | $0.56 | 3.5% |

## Excluded (20)

| model | reason |
|---|---|
| `anthropic/claude-sonnet-5` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `deepseek/deepseek-v3.1-terminus` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `deepseek/deepseek-v3.2` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `google/gemini-3.5-flash` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `google/gemini-3.5-flash-lite` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `google/gemma-3-12b-it` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `minimax/minimax-m2.1` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `minimax/minimax-m3` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `mistralai/mistral-medium-3.1` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `mistralai/mistral-small-3.2-24b-instruct` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `moonshotai/kimi-k2.5` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `moonshotai/kimi-k2.6` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `nvidia/nemotron-3-super-120b-a12b` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `openai/gpt-5.6-sol` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `qwen/qwen3.5-122b-a10b` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `qwen/qwen3.5-27b` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `qwen/qwen3.5-397b-a17b` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `x-ai/grok-4.5` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `z-ai/glm-4.5` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
| `z-ai/glm-5` | not in the owner's 2026-08-09 list (was in roster_refined.json) |
