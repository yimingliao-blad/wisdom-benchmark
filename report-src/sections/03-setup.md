## Experiment setup

### Two families, two prompt architectures — they are NOT the same

This is the distinction that governs everything below. The six capability benchmarks and the two
forecasting benchmarks are asked in structurally different ways, and comparing a number across the
families would be comparing two experiments.

| | capability family | forecasting family |
|---|---|---|
| benchmarks | GPQA-Diamond, AIME, BBH, IFEval, TruthfulQA, GAIA | ForecastBench, `BTF-3` |
| prompt origin | **ours** — a thin wrapper we wrote | **published** — the benchmark authors' own templates |
| structure | the benchmark's question text, then one instruction | fielded: question / background / resolution criteria / dates |
| answer wanted | a discrete answer (letter, integer, string) | a **probability** between zero and one |
| default output rule | reasoning always requested | ForecastBench **forbids** reasoning by default |
| scoring | accuracy against gold | Brier, ROC-AUC, F1, recall against a resolved outcome |
| conditions run | `2` | `11` |

### Models

| model | engine | context | concurrency |
|---|---|---|---|
| `qwen3-8b` | vLLM | `32768` | `8` |
| `llama-3.1-8b-instruct` | vLLM | `32768` | `8` |
| `llama-2-13b-chat-gptq8` | vLLM | `4096` | `8` |

Temperature `0`, seed `0`, one local RTX `4090`. qwen3's `<think>` channel is switched **off** so it
reasons visibly like the llamas, which have no hidden channel — a private reasoning channel would make
the traces incomparable. Budgets are per model: `llama-2-13b-chat-gptq8`'s `4096`-token *total* context
is a hard ceiling, so its generation budget is sized per item to fit prompt plus output.

### Family A — the capability wrapper (two prompts)

One wrapper, appended to the benchmark's own question text. The two arms differ in a single sentence;
the answer-format sentence is byte-identical in both, so the parser target never changes.

```
<benchmark question>

[ARM 1 — simple]   Think step by step, showing your reasoning.
[ARM 2 — concise]  Reason through the necessary steps only — show the key steps of your
                   reasoning, not every detail or restatement.

Then give your final answer on the last line, by itself, with no extra words.
```

**IFEval receives no appended instruction at all.** Its prompts carry their own constraints (no commas,
word counts, N highlighted sections) and obeying them *is* the measurement; appending a reasoning
directive would add a conflicting instruction to the thing being scored.

### Family B — the forecasting prompt catalogue (eleven conditions)

Two published templates, each in three reasoning variants, plus our own wrapper, plus a no-price
control. Every one ends with a parseable probability.

| condition | origin | market price | reasoning | answer format |
|---|---|---|---|---|
| `FB-zeroshot` | ForecastBench, **verbatim** | **shown** | **forbidden** | `*0.35*` |
| `FB-cot-simple` | ForecastBench + our CoT | **shown** | step by step | `*0.35*` |
| `FB-cot-concise` | ForecastBench + our CoT | **shown** | key steps only | `*0.35*` |
| `FBnp-zeroshot` | ForecastBench, plain variant | hidden | forbidden | `*0.35*` |
| `FBnp-cot-simple` | plain variant + our CoT | hidden | step by step | `*0.35*` |
| `FBnp-cot-concise` | plain variant + our CoT | hidden | key steps only | `*0.35*` |
| `BTF-noevidence` | Bench-to-the-Future, **verbatim** | n/a | its own (a)–(e) steps | bare probability |
| `BTF-cot-simple` | BTF + our CoT | n/a | (a)–(e) + step by step | bare probability |
| `BTF-cot-concise` | BTF + our CoT | n/a | (a)–(e) + key steps | bare probability |
| `cot-simple` | **ours** | hidden | step by step | bare probability |
| `cot-concise` | **ours** | hidden | key steps only | bare probability |

**What each one is for.**

- **`FB-zeroshot`** reproduces ForecastBench's shipped prompt exactly. Its closing lines are *"Output
  your answer ... with an asterisk at the beginning and end of the decimal. Do not output anything
  else."* That ban produces a `7`-character reply — enough to score, useless as a behavioural trace.
- **`FB-cot-*`** lift **only** that ban and insert a reasoning instruction, keeping the asterisk answer
  contract. This is the change that turns a bare number into a trajectory while staying scoreable.
- **`FBnp-*`** are the same three with the market-price field removed. ForecastBench ships both a
  with-price and a plain market template; this pair is the control that separates *information in the
  prompt* from *reasoning style*, and it is the single most important comparison in this report.
- **`BTF-*`** reproduce Bench-to-the-Future's `Appendix A.1` prompt — roughly four thousand characters of
  forecasting heuristics (base rates, status quo, scope, a pre-mortem, *"think twice before forecasting
  less than three percent"*) followed by five mandatory reasoning steps (a) through (e). Its no-evidence
  variant leaves the `<research>` block empty, which is BTF's own baseline architecture for a model
  without web access.
- **`cot-*`** are our own minimal wrapper, matching Family A's instruction so the two families share one
  reasoning manipulation.

### What is specific to the forecasting data

Five things differ from the capability benchmarks, and each changes how a number must be read.

**First — The answer is a probability, not a choice.** So accuracy needs an arbitrary threshold, and ROC-AUC
— threshold-free and base-rate invariant — becomes the honest headline.

**Second — The questions carry fielded context.** Each has a *background* and explicit *resolution criteria*.
On `BTF-3` these are substantial: background is a median 2122{m: code/projects/crowd-wisdom/survey/DATASETS.md} characters and resolution
criteria 1453{m: code/projects/crowd-wisdom/survey/DATASETS.md}, against a question stem of only 125{m: code/projects/crowd-wisdom/survey/DATASETS.md}. Most of the prompt is context,
not question.

**Third — There is a date the model must reason from.** ForecastBench supplies *Today's Date*; `BTF-3`
supplies `present_date`, the pastcasting anchor that makes a resolved question answerable as though it
were still open.

**Fourth — Base rates are skewed, and differently in each set.** The ForecastBench sample resolves YES on
0.175{m: code/projects/crowd-wisdom/results/summary.csv} of questions; the `BTF-3` sample on 0.45{m: code/projects/crowd-wisdom/survey/DATASETS.md}. The first makes accuracy nearly
meaningless — always answering NO scores well — while the second is balanced enough for accuracy and F1
to be readable. The same metric means different things across the two.

**Fifth — One of them ships an expert baseline.** `BTF-3` carries `sota_forecast_probability`, a published
per-question forecast. That is a real comparator for the crowd-wisdom question of whether a committee
beats an expert; ForecastBench's equivalent is its separate human superforecaster set, not used here.

### Sampling

Capability prompts are capped at **`1,000`-character** length so every item fits the smallest
model's context. Every draw is **seeded random, never a prefix** — all source files are ordered by domain, task, index or
level, so a head-of-file slice would take one corner and report it as the benchmark.

**Fields are never truncated.** Where a prompt would not fit a model's context, the *question* is
excluded from eligibility rather than shortened — shortening would silently change what the benchmark
asks. On `BTF-3` that costs coverage honestly: 259{m: code/projects/crowd-wisdom/survey/DATASETS.md} of 1515{m: code/projects/crowd-wisdom/survey/DATASETS.md} questions have fields
small enough to pair with BTF's own long template inside the smallest model's context.

Total generations: 2970{m: code/projects/crowd-wisdom/results/summary.csv} in the capability and ForecastBench families, plus the `BTF-3` run.
