# Behavioural fingerprinting of LLMs across six capability benchmarks and eleven forecasting prompts

**Three models · 2,970 generations · every reasoning trace retained.**  Run 2026-08-05 on a local
RTX 4090 (vLLM, 8 concurrent) plus a llama.cpp path for the 13B.

This is **step 3 of the crowd-wisdom design** (`docs/DESIGN.md`): characterise models by *how* they
solve common problems, so that a diverse committee can later be assembled from behavioural distance.
It is **not** a leaderboard, and none of these numbers are comparable to published results — see
*Threats to validity*.

---
## 1. What was run

| family | items | conditions | per model | source |
|---|---|---|---|---|
| capability | 275 | 2 (simple / concise CoT) | 550 | GPQA-Diamond, AIME-2025, BBH, IFEval, TruthfulQA, GAIA |
| forecasting | 40 | 11 prompt variants | 440 | ForecastBench 2025-03-02, resolved binary market questions |
| | | | **990 × 3 = 2,970** | |

Questions are drawn by **seeded random sample, never a prefix** — all six source files are ordered by
domain, task or index, so `head(n)` would draw one corner and report it as the benchmark. Prompts are
capped at 1,000 characters so every item fits llama-2's 4,096-token *total* context.

## 2. Headline: capability

| model | arm | accuracy | scored | truncated | median trace | GPU-min |
|---|---|---|---|---|---|---|
| qwen3-8b | concise | **0.442** | 163/275 | 12 (4.4%) | 668 ch | —  |
| qwen3-8b | simple | **0.500** | 154/275 | 21 (7.6%) | 1536 ch | —  |
| llama-3.1-8b-instruct | concise | **0.272** | 151/275 | 25 (9.1%) | 968 ch | —  |
| llama-3.1-8b-instruct | simple | **0.291** | 134/275 | 47 (17.1%) | 1422 ch | —  |
| llama-2-13b-chat-gptq8 | concise | **0.172** | 174/275 | 1 (0.4%) | 899 ch | —  |
| llama-2-13b-chat-gptq8 | simple | **0.208** | 173/275 | 2 (0.7%) | 1135 ch | —  |

**Per benchmark (accuracy, concise / simple):**

| benchmark | qwen3-8b | llama-3.1-8b | llama-2-13b |
|---|---|---|---|
| GPQA-Diamond | 0.4667 / 0.6512 | 0.3415 / 0.25 | 0.12 / 0.2857 |
| AIME-2025 | 0.2778 / 0.25 | 0.0 / 0.0 | 0.0 / 0.0 |
| BBH | 0.8 / 0.875 | 0.449 / 0.5714 | 0.36 / 0.32 |
| IFEval | — / — | — / — | — / — |
| TruthfulQA | — / — | — / — | — / — |
| GAIA-validation | 0.12 / 0.0638 | 0.1163 / 0.0652 | 0.12 / 0.12 |

IFEval and TruthfulQA are **captured but unscored**: IFEval needs Google's official verifier,
TruthfulQA needs a judge. Faking either would have produced a number with no meaning.

## 3. Headline: forecasting

40 resolved binary questions, base rate **0.175 yes**. References: always-0.5 Brier **0.2500** ·
always-base-rate **0.1444** · **the market price alone 0.0609**.

| condition | price in prompt | reasoning | Brier ↓ | ROC-AUC ↑ | parse | median trace |
|---|---|---|---|---|---|---|
| `FBnp-zeroshot` | no | none | 0.1836 | **0.582** | 100% | 6 ch |
| `FBnp-cot-simple` | no | simple | 0.1831 | **0.565** | 100% | 1992 ch |
| `FBnp-cot-concise` | no | concise | 0.1754 | **0.636** | 100% | 1500 ch |
| `FB-zeroshot` | **YES** | none | 0.1098 | **0.825** | 100% | 7 ch |
| `FB-cot-simple` | **YES** | simple | 0.1198 | **0.831** | 99% | 2273 ch |
| `FB-cot-concise` | **YES** | concise | 0.1139 | **0.807** | 100% | 1398 ch |
| `BTF-noevidence` | no | (a)-(e) | 0.2584 | **0.550** | 79% | 2560 ch |
| `BTF-cot-simple` | no | simple | 0.2983 | **0.554** | 90% | 3848 ch |
| `BTF-cot-concise` | no | concise | 0.3005 | **0.535** | 89% | 2260 ch |
| `cot-simple` | no | simple | 0.2099 | **0.663** | 92% | 1877 ch |
| `cot-concise` | no | concise | 0.2078 | **0.701** | 92% | 1204 ch |

**ROC-AUC is the honest headline here.** It is threshold-free and base-rate invariant. On a 17%-yes
set, Brier rewards anything that emits low numbers whether or not it discriminates, and accuracy@0.5
is near-meaningless — a model that always says "no" scores 0.825 accuracy with 0.0 recall.

## 4. Findings

### 4.1 Nearly all apparent forecasting skill was reading a number out of the prompt

ForecastBench ships two market prompts; the one we used first includes `freeze_datetime_value`, the
live prediction-market price. `FBnp-*` are byte-identical without that field. Removing it:

```
mean ROC-AUC   FB with price 0.821  ->  FB no price 0.594
mean Brier     FB with price 0.1145 ->  FB no price 0.1807
```
0.594 is close to the 0.5 no-discrimination floor. And even *with* the price, the models score worse
than the price by itself (0.1145 vs 0.0609) — they are handed a good forecast and degrade it.
**Without market information, none of these three 8-13B models forecasts meaningfully better than chance.**

### 4.2 There is no single best prompt — it depends on whether the model terminates

On GPQA-Diamond, simple CoT beats concise for qwen3 (0.467 → 0.651) and llama-2 (0.120 → 0.286), but
**reverses for llama-3.1** (0.342 → 0.250). The mediator is truncation: llama-3.1's rate nearly doubles
under the verbose instruction (9.1% → 17.1% overall), so it talks past its budget and never reaches an
answer. Fixing one prompt for all models would penalise the ramblers — and that penalty would then
appear in a diversity representation as a genuine behavioural difference when it is an artefact of the
prompt choice.

### 4.3 BTF's prompt is actively harmful on a low-base-rate set

Worst Brier (0.2858 mean), ROC-AUC at chance (0.546), and it breaks llama-2: **52-70% parse rate**,
Brier 0.44-0.49, AUC 0.375 — *below* chance. Its ~4,000 characters of heuristics plus "think twice
before forecasting less than 3%" inflate probabilities on a set that is 17% yes, and its length leaves
a 4k-context model no room. BTF's own paper ranks No-Evidence as its weakest architecture, so this
reproduces their finding rather than contradicting it.

### 4.4 Instruction compliance is low and highly model-dependent

Told to give the final answer "on the last line, by itself, with no extra words", models comply
**38% / 28% / 10%** of the time (qwen3 / llama-3.1 / llama-2). That is a stable, cheap, discriminating
behavioural feature — and it means an output-only parser must never assume the instruction was obeyed.

### 4.5 Reasoning length is driven by the item, not the model

Within-benchmark spread in chain length was **1.3x the between-benchmark spread** (29.3 vs 22.6), with
steps ranging 1-223. "Average reasoning steps" as a per-model scalar is therefore mostly item noise;
it only becomes informative differenced **per item** across models.

## 5. Threats to validity

1. **Not comparable to published numbers.** BBH is run zero-shot, not the canonical 3-shot CoT. GAIA is
   text-only, so its attachment questions are structurally unanswerable. IFEval and TruthfulQA are unscored.
2. **n is small.** 40 forecasting questions, ~50 per capability benchmark. Differences of a few points
   are not resolvable. Several patterns in this work reversed when a partial batch was completed.
3. **Base-rate imbalance.** 0.175 yes. Brier alone is not readable on this set; ROC-AUC is reported for
   that reason and the base-rate reference sits in every row of `summary.csv`.
4. **BTF's prompt was applied to ForecastBench questions**, because BTF's own dataset was found late.
   BTF-3 (1,515 resolved binary questions with `present_date` and a per-question expert baseline) is
   downloaded but **not yet run** — that is the better substrate.
5. **Three models cannot be clustered.** Steps 4-8 of the design need 20-30. Nothing here tests the
   crowd-wisdom hypothesis itself; this is the behavioural substrate for it.

## 6. Reproducing

```bash
bash code/download_data.sh                 # fetches all datasets (GPQA + GAIA are gated)
python3 code/capture_traces.py --model qwen3-8b --workers 8 \
        --sample samples/sample_capped.json --out runs/traces_final_qwen3-8b.jsonl
python3 code/run_forecast.py  --model qwen3-8b --workers 8
python3 code/analyze_all.py                # writes results/
```
Runs are **resume-keyed** on `(model, condition, item, prompt-hash)`: a kill costs the in-flight query,
and a changed prompt re-runs rather than silently reusing a stale answer.

## 7. Files

| path | rows | contents |
|---|---|---|
| `results/summary.csv` \| `.json` | 69 | model × condition: accuracy, Brier, ROC-AUC, recall, precision, parse & truncation rates |
| `results/capability_rows.csv` | 1,650 | answer · gold · correct · status · reasoning preview |
| `results/forecast_rows.csv` | 1,320 | forecast · outcome · Brier · correct@0.5 · reasoning preview |
| `results/*_full.jsonl` | 2,970 | the same rows **with complete reasoning traces** |
| `docs/EXAMPLES.md` | — | each benchmark: question, prompt, real traces, measured effect |
| `docs/DATASETS.md` | — | provenance and verified counts for all six benchmarks |
| `docs/llm-forecasting-benchmarks.md` | — | ForecastBench and BTF: prompts, data, four retrieval traps |
| `docs/DESIGN.md` | — | the crowd-wisdom design this feeds |
