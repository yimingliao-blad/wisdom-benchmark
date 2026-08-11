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
