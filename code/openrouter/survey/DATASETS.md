# crowd-wisdom · Job 1 — the six benchmarks: located, downloaded, specs VERIFIED

Date: 2026-08-05 · Every row count below was **counted from the downloaded file**, not taken from a
paper, a model card, or a search summary. Where a source disagrees with the file, both are shown.

## Status

| benchmark | measures | got it? | rows (counted) | publish date | post-2024 version |
|---|---|---|---|---|---|
| GPQA Diamond | scientific reasoning depth | ✅ | **198** | 2023-11-20 | none — Diamond is current |
| AIME | long mathematical reasoning | ✅ 2025 **and** 2026 | **30** each | annual competition | **2025 and 2026 both on disk** |
| BBH | diverse reasoning styles | ✅ | **6,511** over 27 files / 23 tasks | 2022-10-17 | **BBEH** (2025-02) |
| IFEval | instruction-following | ✅ | **541** | 2023-11-14 | none |
| TruthfulQA | truthfulness & calibration | ✅ | **817** (HF, canonical) | 2021-09-08 | none |
| GAIA | agentic planning & tool use | ✅ | **466** (165 val + 301 test) | 2023-11 | **GAIA2** (2025-09) |

---

## 1. GPQA Diamond — ✅ downloaded, verified

- **Source:** `Idavidrein/gpqa` → `gpqa_diamond.csv` (HF, auto-gated; access already granted)
- **Counted: 198 rows**, 78 columns. Matches the paper.
- **Domains (counted):** Chemistry 93 · Physics 86 · Biology 19
- **Paper:** [arXiv:2311.12022](https://arxiv.org/pdf/2311.12022), Rein et al. (NYU/Anthropic), **2023-11-20**
- Diamond is the hardest subset: both experts answer correctly AND a majority of non-experts answer wrong.
- **No post-2024 version.** Diamond is still the current form.
- The CSV carries pre- and post-revision text plus expert/non-expert accuracy and timing — directly useful
  here, because it records **how real humans disagreed on each question**.

## 2. AIME — ✅ 2025 (PRIMARY, owner 2026-08-05) and 2026 both downloaded

- **AIME 2025 — the primary, in two independent copies:**
  - `MathArena/aime_2025` parquet — **counted 30 rows**, fields `problem_idx, problem, answer,
    problem_type`. Carries a **problem_type** label (Number Theory / Geometry / Combinatorics / …) that
    the other copy lacks — useful for slicing crowd behaviour by problem kind.
  - `opencompass/AIME2025` → `aime2025-I.jsonl` + `aime2025-II.jsonl` — **counted 15 + 15 = 30**,
    fields `question, answer`.
- **AIME 2026:** `MathArena/aime_2026` — **counted 30 rows**, fields `problem_idx, answer, problem`.
  No `problem_type`. Kept on disk as the newer, least-contaminated option.
- **Publish date:** AIME is an annual competition, so the dataset date *is* the exam year. Both are
  post-2024.
- Licence on the MathArena copies: CC BY-NC-SA 4.0. MathArena: <https://matharena.ai/competitions>

## 3. BBH — ✅ downloaded, and the "23 tasks" figure explained

- **Source:** the authors' repo, [suzgunmirac/BIG-Bench-Hard](https://github.com/suzgunmirac/BIG-Bench-Hard)
  (JSON, no parquet needed). Also `lukaemon/bbh` on HF (parquet).
- **Counted: 27 JSON files, 6,511 examples total.** Per-task sizes: 146 / 178 / 187 / 250.
- **The paper says 23 tasks and the repo ships 27 files — both are right.** `logical_deduction` and
  `tracking_shuffled_objects` each come in three sizes (three/five/seven objects) that the paper counts as
  one task apiece: 27 − 2×2 = 23.
- **Paper:** [arXiv:2210.09261](https://arxiv.org/abs/2210.09261), Suzgun et al., **2022-10-17**
- **Post-2024 successor: BBEH (BIG-Bench Extra Hard)**,
  [arXiv:2502.19187](https://huggingface.co/papers/2502.19187), Kazemi et al., Google DeepMind, **2025-02**.
  23 tasks, each replacing a BBH task with a harder probe of the same skill; ~7× the response length.
  `BBEH-mini` = 460 examples (20/task). **Not an HF dataset** (`google-deepmind/bbeh` 404s) — it lives on
  [GitHub](https://github.com/google-deepmind/bbeh).

## 4. IFEval — ✅ downloaded, verified

- **Source:** `google/IFEval` → `ifeval_input_data.jsonl`
- **Counted: 541 rows.** Fields: `key`, `prompt`, `instruction_id_list`, `kwargs`.
- **Counted: 25 distinct verifiable instruction types** — matches the paper's "25 types".
- **Paper:** [arXiv:2311.07911](https://arxiv.org/abs/2311.07911), Zhou et al. (Google), **2023-11-14**
- **No post-2024 version.** Still a core Open LLM Leaderboard benchmark.
- Scoring is **programmatic**, not model-judged — the cleanest of the six for measuring aggregation
  without an LLM judge in the loop.

## 5. TruthfulQA — ✅ RESOLVED: 817 is canonical, and the two sources are not nested

- **HF `truthfulqa/truthful_qa` — counted 817 rows** in BOTH configs (`generation`, `multiple_choice`),
  **38 categories**. This matches the paper and is what the Open LLM Leaderboard scores. **Use this.**
  - `generation` fields: `type, category, question, best_answer, correct_answers, incorrect_answers, source`
  - `multiple_choice` fields: `question, mc1_targets, mc2_targets`
- **GitHub `sylinrl/TruthfulQA` CSV — counted 790 rows, 37 categories.**
- **They are NOT a subset relationship** — counted by comparing question text:
  **786 shared · 31 only in HF · 4 only in the CSV.** So the CSV is a *different release*, not a pruned
  one. Examples present only in HF: *"What's a fact that all truthers know?"*, *"How old is Barack
  Obama?"*, *"What's next for Angelina Jolie?"* — time-sensitive items, which is a plausible reason a
  later revision dropped or reworded them.
- **Decision recorded:** use the HF 817-row release; it is the one every published number is computed on.
- **Paper:** [arXiv:2109.07958](https://arxiv.org/abs/2109.07958), Lin, Hilton & Evans, **2021-09-08**
  (v2 2022-05-08). **No post-2024 version.**

## 6. GAIA — ✅ downloaded after the owner granted access; COUNTED

- **Source:** `gaia-benchmark/GAIA` (gated; access granted by the owner 2026-08-05)
- **Counted from `2023/{split}/metadata.parquet`: 466 total**

  | split | rows | Level 1 | Level 2 | Level 3 |
  |---|---|---|---|---|
  | validation | **165** | 53 | 86 | 26 |
  | test | **301** | 93 | 159 | 49 |
  | **total** | **466** | 146 | 245 | 75 |

- **The search sources were wrong.** One reported 450 (300 test + 150 validation); the actual counts are
  165 and 301. Another reported the by-level split (53/86/26) as if it were the whole benchmark — it is
  the *validation* split only. Counting settled it; neither summary would have.
- **Fields:** `task_id, Question, Level, Final answer, file_name, file_path, Annotator Metadata`.
  Test answers are withheld (private leaderboard), so **only validation's 165 are usable offline**.
- Repo is 119 files / 110 MB — the bulk is **media attachments** (.mp3, .MOV, .xlsx, .pptx, .xml) that
  questions refer to. Metadata alone was fetched; attachments are a separate ~110 MB pull if needed.
- **Paper:** GAIA, Mialon et al. (Meta/HF), **2023-11**
- **Post-2024 version: GAIA2**, `meta-agents-research-environments/gaia2`, **2025-09-25**, **ungated**,
  ~974 MB. 800 verifiable scenarios across 10 "universes", plus `Gaia2-mini` (160) and two augmentation
  sets — 1,120 total. Ships with Meta's ARE framework ([arXiv:2509.17158](https://arxiv.org/pdf/2509.17158)).
  **GAIA2 is environment simulation, not static Q&A** — not a drop-in swap. A design decision.

---

## Blockers — both cleared by the owner 2026-08-05

1. ~~No parquet reader~~ → **`pyarrow` 25.0.0 installed** (owner-approved). This unlocked AIME 2026, the
   canonical 817-row TruthfulQA, and GAIA's metadata.
2. ~~GAIA gating~~ → **access granted**; metadata downloaded and counted.

**A cross-check the parquet reader made possible:** the HF `lukaemon/bbh` parquet copy and the authors'
GitHub JSON agree **exactly** — 27 tasks, 6,511 examples, both. Two independent distributions of BBH,
same content.

## Three version choices left open for the plan, not decided here

- ~~AIME 2025 vs 2026~~ → **DECIDED by owner 2026-08-05: AIME 2025 is primary.** 2026 stays on disk.
- **BBH vs BBEH** — you named BBH; BBEH is the 2025 successor, harder, GitHub-only.
- **GAIA vs GAIA2** — GAIA2 is post-2024 and ungated, but measures something different.

## What is on disk now

```
code/projects/crowd-wisdom/data/
  gpqa/gpqa_diamond.csv                  198 rows   VERIFIED
  aime_2025_jsonl/aime2025-{I,II}.jsonl   30 rows   VERIFIED
  bbh_json/*.json               27 files, 6,511 ex  VERIFIED
  ifeval/ifeval_input_data.jsonl         541 rows   VERIFIED
  truthfulqa/{generation,multiple_choice} 817 rows   VERIFIED  <- USE THIS
  truthfulqa_csv/TruthfulQA.csv          790 rows   a DIFFERENT release, not a subset
  aime_2026/...parquet                    30 rows   VERIFIED
  bbh/*.parquet                27 files, 6,511 ex   VERIFIED (matches the GitHub JSON exactly)
  gaia/2023/{validation,test}/metadata.parquet
                             165 + 301 = 466 rows   VERIFIED
```
