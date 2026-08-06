# LLM forecasting benchmarks — ForecastBench and Bench to the Future

> **Source:** the two papers read directly, plus the authors' own code and the downloaded datasets.
> Every size below was **counted from the file**, not taken from a paper or a search summary.
> Written 2026-08-05 for `code/projects/crowd-wisdom/` (see its `ROADMAP.md`).

**🔔 Fire this when** you need a forecasting benchmark with **resolved** questions, a probability-output
prompt, or a published expert baseline to compare a model or a committee against.

## The two, at a glance

| | ForecastBench | Bench to the Future (BTF) |
|---|---|---|
| paper | [arXiv:2409.19839](https://arxiv.org/abs/2409.19839), ICLR 2025 | [arXiv:2506.21558](https://arxiv.org/abs/2506.21558), Jun 2025 |
| authors | Forecasting Research Institute (Karger, Tetlock et al.) | FutureSearch |
| design | **prospective** — questions unresolved at submission | **pastcasting** — resolution already known |
| contamination defence | by construction (future events) | frozen web corpus + `present_date` |
| data | [HF `forecastingresearch/forecastbench-datasets`](https://huggingface.co/datasets/forecastingresearch/forecastbench-datasets) | [HF `BTF-2/BTF-3`](https://huggingface.co/datasets/BTF-2/BTF-3) |
| code | [github forecastingresearch/forecastbench](https://github.com/forecastingresearch/forecastbench) | no public repo found |
| metric | Brier score | Brier score (weighted for correlated splits) |

**Headline finding of each.** ForecastBench: expert (super)forecasters **beat the top LLM**, p < 0.001 —
LLMs land near a survey of the untrained public. BTF: forecasting accuracy rises steadily with model
release, and **agentic ReAct > chain-of-thought evidence pipeline > no-evidence baseline**.

## Prompts — how each actually asks the question

**They sit at OPPOSITE ends of the reasoning axis, which is the most useful thing about having both.**

### ForecastBench — *forbids* reasoning
From their repo, `src/llm_forecaster/prompts.py`, `ZERO_SHOT_MARKET_PROMPT` (verbatim):

```
You are an expert superforecaster, familiar with the work of Tetlock and others. Make a prediction of
the probability that the question will be resolved as true. You MUST give a probability estimate between
0 and 1 UNDER ALL CIRCUMSTANCES. If for some reason you can't answer, pick the base rate, but return a
number between 0 and 1.

Question: {question}
Question Background: {background}
Resolution Criteria: {resolution_criteria}
Today's Date: {today_date}
Question resolution date: {resolution_date}

Output your answer (a number between 0 and 1) with an asterisk at the beginning and end of the decimal.
Do not output anything else.
Answer: {{ Insert answer here }}
```

- Three variants: market · market-with-freeze-value (adds the live market price) · dataset (multiple
  resolution horizons at once).
- Their header credits **Halawi et al. 2024** ([arXiv:2402.18563](https://arxiv.org/abs/2402.18563)).
- A **separate `FORECAST_EXTRACTION_PROMPT`** runs a second LLM call purely to pull numbers out, with
  rules like *"Do not revise, smooth, calibrate, average, or replace any probabilities"* and *"If you
  cannot identify exactly {n} final-answer probabilities, return []"*. Extraction is a distinct step from
  forecasting — worth copying.
- **Measured consequence of "Do not output anything else": a 6-character reply (`*0.35*`).** Fine for a
  Brier score, useless as a behavioural trace.

### BTF — *demands* reasoning
Paper Appendix A.1, in full. Structure: `<question>`, `<background>`, `<resolution-criteria>`,
`<research>` (empty in the no-evidence variant), `Today is {present_date}`, then ~4,000 characters of
forecasting heuristics — base rates, inside view, status-quo weighting, seasonality, trend
extrapolation, scope, incentives, a **pre-mortem**, and *"think twice before forecasting less than 3%"*
/ *"more than 97%"*. Then five mandatory steps:

```
(a) The time left until the outcome to the question is known.
(b) The status quo outcome if nothing changed.
(c) ... different scopes to ensure a self-consistent view ...
(d) A brief description of a scenario that results in a No outcome.
(e) A brief description of a scenario that results in a Yes outcome.

The last thing you write is your final answer as a probability between 0 and 1.
```

Their four architectures: **ReAct** (agent + tools) · **Fixed Evidence** (~30 pre-sourced facts) ·
**Variable Evidence** (CoT retrieval pipeline) · **No Evidence** (prompt only). The last is the one
reproducible without web access — and it is their **weakest**, by design.

## Datasets — verified locations and counts

### ForecastBench (public, updated nightly)
```
datasets/question_sets/<date>-llm.json        e.g. 2025-03-02: 997 questions
datasets/resolution_sets/<date>_resolution_set.json   e.g. 2025-03-02: 5,451 resolutions
datasets/forecast_sets/2024-07-21/…           human_public_individual + human_super_individual
leaderboards/csv/…
```
- 9 sources: manifold, metaculus, infer, polymarket (**market**) · acled, dbnomics, fred, wikipedia,
  yfinance (**dataset/time-series**).
- Question fields: `id, source, question, background, resolution_criteria, freeze_datetime,
  freeze_datetime_value, resolution_dates, source_intro, url`.
- Resolution fields: `id, source, direction, resolution_date, resolved_to, resolved`.
- **The human forecast sets are the expert baseline** — public individual vs superforecaster.

### BTF-3 (public, CC-BY-NC-4.0, ungated)
```
btf3_binary_questions_and_forecasts.parquet    1,515 rows, 12 cols     6.5 MB
btf3_numeric_questions_and_forecasts.parquet     392 rows              1.1 MB
aux/scraped_pages.parquet                                            737.1 MB   ← the RetroSearch corpus
```
- Binary fields: `question_id, question, resolution_criteria, background, present_date,
  date_cutoff_start, date_cutoff_end, expected_resolution_date, resolution (0.0/1.0),
  resolution_explanation, sota_forecast_probability, sota_summary_rationale`.
- **`present_date`** is the pastcasting anchor — the date the model is told it is.
- **`sota_forecast_probability` is a published per-question expert baseline**, which is exactly what a
  "can a crowd beat an expert" comparison needs.
- The arXiv paper describes **299** questions (BTF-1); the public release is **BTF-3, 1,907**. Different
  editions — cite whichever you used.

## FOUR RETRIEVAL TRAPS (each cost real time)

1. **HuggingFace's search index does not return `BTF-2/BTF-3`** for `BTF`, `pastcasting`, `bench to the
   future`, or `futuresearch`. Only a **direct repo lookup** finds it. I concluded from a negative search
   that the dataset was not public, and that was **wrong**. *A negative search result is not evidence of
   absence — try the direct id.*
2. **`latest-llm.json` is a POINTER**, a bare filename string (`2025-12-21-llm.json`), not JSON data.
   Parsing it raises `Extra data: line 1 column 5`. Resolve it, then fetch the named file.
3. **ForecastBench ids are heterogeneous.** 501 are strings (single questions); **496 are LISTS** —
   combination questions asking for a joint probability over two. `{q["id"]: q}` raises
   `TypeError: unhashable type: 'list'`. Filter by `isinstance(id, str)` for single questions.
4. **`google-deepmind/bbeh` is not an HF dataset** (404) despite appearing in search results as though it
   were; BBEH lives on GitHub. Same class of error as trap 1, opposite direction.

## Scoring

**Brier score** = `(forecast − outcome)²`, lower better. Reference points that must be reported alongside
any Brier number, or it cannot be read:

- **0.25** = the uninformed 0.5 forecast.
- **the base rate of the question set** — on an imbalanced set (e.g. 17% yes), *anything that outputs low
  probabilities scores well regardless of reasoning quality*. Always compare against a constant-base-rate
  forecaster before attributing a Brier difference to skill.

BTF additionally **down-weights correlated questions** (those split from one multiple-choice or numeric
question) by `weight_i = log₂(N_i + 1) / (N_i + 1)`, giving 299 raw questions an **effective size of
178.8**. Splitting one question into many does not multiply the evidence.

## Why this matters to crowd-wisdom

- Both give **resolved binary questions with probability outputs** — the substrate for aggregating a
  committee and scoring it.
- Both ship an **expert baseline**: ForecastBench's human superforecaster sets, BTF's per-question
  `sota_forecast_probability`. Hypothesis 1 ("a diverse crowd may beat an expert") is testable against
  real numbers rather than an assumed reference.
- The **two prompts are a free format-pressure contrast**: one forbids reasoning, one requires it, on the
  same task. Any claim about reasoning helping or hurting forecasting can be tested across both without
  designing a prompt from scratch.
