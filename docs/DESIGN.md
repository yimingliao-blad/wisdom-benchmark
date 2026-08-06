# Design of "wisdom of the agentic crowd"

> **Project north-star spec.** Authored by the owner 2026-08-05; transcribed here as the governing
> document for the `crowd-wisdom` project. Sections 1–8 are the owner's design. Section 9 is agent notes —
> verified status and open questions — kept separate so the design is never confused with commentary.

---

## 1. Basic hypothesis

1. Verify the hypothesis that a **"diverse" group of independent individuals** in a crowd can achieve good
   estimation for predicting uncertain events, **and might be better than an expert**.
2. It is difficult to create independent LLMs, as each LLM's training data has significant overlap.
   However, we might be able to find a **diverse set** of LLMs to verify the hypothesis. **Thus, the design
   of the method to identify the diversity is the critical step.**

## 2. Method — overview

1. Sample a number of well-known LLMs, e.g. **20–30**, including top open-source and closed-source ones.
2. We do not know how the internals look, so we use LLMs' **behaviours** to characterise them.
3. The behaviours are captured via their **styles of solving common problems** (benchmarks).

## 3. Benchmarks

Select a number of benchmarks and sample some questions from them (e.g. **10–20 questions per benchmark**).

| Benchmark | What it measures |
|---|---|
| GPQA Diamond | Scientific reasoning depth |
| AIME | Long mathematical reasoning |
| BBH | Diverse reasoning styles |
| IFEval | Instruction-following behaviour |
| TruthfulQA | Truthfulness & calibration |
| GAIA | Agentic planning and tool reasoning |

Ask each selected LLM to answer the questions **and show the thinking/reasoning process**. Try **50 sample
questions** first, and may extend later. **Capture all the QA data.**

## 4. Ways to capture the behaviours

### 4.1 Vectorise with a well-known embedding tool, deriving a representative vector per LLM

- **Method 1:** simple aggregation of all answers' vector representations.
- **Method 2:** groupwise (e.g. benchmark-wise) aggregation, then **concatenate** the group-level vectors.

### 4.2 Use specific behaviour features

| Behaviour | Metric |
|---|---|
| Chain length | average reasoning steps |
| Confidence | probability calibration |
| Self-correction | improvement after critique |
| Error propagation | recovery after an early mistake |
| Constraint adherence | IFEval |
| Hallucination | TruthfulQA |
| Planning depth | GAIA |
| Robustness | answer stability under paraphrasing |
| Consistency | repeated-run agreement |

## 5. Cluster the LLMs based on their representation vectors

1. Use **t-SNE** to quickly gain insight into the cluster distribution.
2. Use more formal methods to determine the **number of clusters** (e.g. the **elbow method** or
   **silhouette analysis**), then apply a common clustering algorithm.

## 6. Methods of selecting cluster representatives

1. **Centroid (or medoid)** — one selected LLM.
2. **Pair of most distant** (most dissimilar within cluster) ones — might be a few LLMs per cluster.
3. **Subcommittee** — all cluster members participate in voting to form a subcommittee decision.

## 7. Working on target predictive tasks

Questions extracted from benchmarks, separated into **training and testing** parts. Sample datasets:

- **Bench to the Future** — <https://arxiv.org/abs/2506.21558>
- **ForecastBench** — <https://arxiv.org/abs/2409.19839>

## 8. Baselines

1. **Best performing individual LLM** (best average performance on training data).
2. **Common aggregation methods** over all participant LLMs' decisions:
   - continuous output → **average**
   - discrete output → **majority voting**

---

## 9. Agent notes — status and open questions (NOT part of the design)

### 9.1 What Job 1 already delivered

All six characterisation benchmarks are downloaded, with **counts verified by counting the files**:

| benchmark | rows | version on disk |
|---|---|---|
| GPQA Diamond | **198** | `Idavidrein/gpqa` diamond CSV |
| AIME 2025 | **30** | MathArena parquet + opencompass jsonl (owner: 2025 is primary) |
| BBH | **6,511** over 27 files / 23 paper-tasks | authors' GitHub JSON = HF parquet, exactly |
| IFEval | **541**, 25 instruction types | `google/IFEval` |
| TruthfulQA | **817** (HF canonical; a GitHub CSV has a different 790) | `truthfulqa/truthful_qa` |
| GAIA | **466** = 165 validation + 301 test | `gaia-benchmark/GAIA` metadata |

Detail and publish dates: `survey/DATASETS.md`. Prompt/parser/budget design: `survey/prompt-design-*.md`.

**Only GAIA validation (165) has public answers** — test answers are withheld for the private
leaderboard. That caps what step 3 can score on GAIA.

### 9.2 The design's central empirical bet, stated plainly

Diversity is measured on **six static benchmarks**; the payoff is tested on **forecasting** datasets.
Whether behavioural diversity measured on the former predicts committee gain on the latter *is the
finding*, not a premise. Worth naming so a null result reads as an answer rather than a failure.

### 9.3 A control the design does not currently include

If a diverse committee of 3 beats the best individual, that could be **diversity** or simply **ensembling
3 models**. Separating them needs a **random committee of the same size** as a third baseline, alongside
§8's two. Offered for the owner to accept or reject — not folded in.

### 9.4 Open questions

1. **The two forecasting datasets are named but unverified.** Neither has been located, downloaded or
   specced; size, access terms, splits and answer format are unknown.
2. **Which 20–30 LLMs are reachable.** The local gateway serves ~20 generate models on one 24 GB GPU,
   **one at a time**; closed-source models need API keys and a budget not yet discussed.
3. **Which embedding model** represents reasoning traces faithfully. Seven are available locally
   (`bge-large`, `bge-base`, `bge-m3`, `e5-large-v2`, `gte-large`, `gte-qwen2-1.5b`,
   `snowflake-arctic-l`). This choice is itself a measurement decision that will move the clustering.
4. **Compute cost of §3 is multiplicative and unbounded so far:** 50 questions × 20–30 models × full
   reasoning traces, **times** repeated runs (consistency) **times** paraphrases (robustness).
5. **Four behaviour metrics in §4.2 need their own protocol**: self-correction needs a critique step,
   error propagation needs a seeded early mistake, robustness needs a paraphrase generator, calibration
   needs elicited probabilities. Each is a small experiment in its own right.
6. **Degrees of freedom.** Embedding choice × aggregation method × cluster count × representative strategy
   is a large space; picking after seeing results would fit noise. Pre-registering the primary path before
   the run is the cheap fix — the same discipline that caught three defects in Job 1's smoke design.

### 9.5 Capacity, as of 2026-08-05 12:52

Local GPU **empty, 23.5 GB free**; MLX gateway **empty**. Nothing is running.
