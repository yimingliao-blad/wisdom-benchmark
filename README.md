# crowd-wisdom-bench

Behavioural fingerprinting of LLMs across **six capability benchmarks** and **eleven forecasting prompts**.
Three models, **2,970 generations, every reasoning trace retained**.

**→ Read [`REPORT.md`](REPORT.md).**

This is step 3 of a larger design ([`docs/DESIGN.md`](docs/DESIGN.md)): characterise models by *how* they
solve problems, so a diverse committee can later be assembled from behavioural distance and tested against
the best individual. It is **not** a leaderboard — see *Threats to validity* in the report.

## Three findings

1. **Nearly all apparent forecasting skill was reading a number out of the prompt.** ForecastBench's market
   prompt includes the live prediction-market price. Remove that one field and mean ROC-AUC falls
   **0.821 → 0.594**, near the 0.5 no-discrimination floor. Even with it, the models score worse than the
   price alone (Brier 0.1145 vs 0.0609).
2. **There is no single best prompt.** Verbose CoT beats concise on GPQA for qwen3 (0.467→0.651) and
   llama-2 (0.120→0.286) but *reverses* for llama-3.1 (0.342→0.250) — because its truncation nearly
   doubles. Fixing one prompt for all models would penalise the ramblers and misread it as behaviour.
3. **Instruction compliance is a cheap, stable discriminator.** Asked for a bare final answer, models
   comply 38% / 28% / 10% of the time.

## Phase 2 — 24 hosted models via OpenRouter (IN PROGRESS, partial data)

> **⚠ These results are INCOMPLETE and are published as a partial artifact.** The paid run halted at
> ~96% of its first arm when the OpenRouter organisation hit its monthly budget cap. Nothing here is a
> final result and nothing should be read as a ranking. What it *is*: a fully instrumented benchmark
> harness plus every row it has bought so far, so the accounting can be checked before the rest is run.

Phase 1 (above) ran **3 local models**. Phase 2 runs **24 hosted models** against two forecasting
benchmarks — **FutureX-Past** and **BTF-3** — with the model list held as *data*, not code.

### What is actually answered so far

| arm | planned units | answered | bought but unusable | no answer yet |
|---|---|---|---|---|
| FutureX, original prompt | 2,640 | **2,563** | 42 | 77 |
| BTF-3, original prompt | 2,640 | 180 | 14 | 2,460 |
| BTF-3, tightened prompt | 2,640 | 118 | 0 | 2,522 |

A unit is one `(model, item, arm)` call. "Planned" is the current 24-model roster × 110 items.
The 42 unusable FutureX units are 26 `UNDECIDED`, 14 `BUDGET_CAPPED` (killed mid-flight by the cap)
and 2 `TRUNCATED`. Of the 77 with nothing, 20 were attempted and the call failed; 57 were never
dispatched. They concentrate heavily: **nemotron-3-super 36 and llama-4-maverick 13 of the 77.**

The two BTF manifests still carry the **superseded 37-model roster** (4,070 units), so their own
`missing` figure counts models no longer on the list; the table above re-scopes them to the current 24.
`results/openrouter/gap_analysis.json` reports both, and flags which manifests are stale.

### One result that survived the partial run

Splitting the reasoning-presence rate **per model** rather than pooling it: **`gpt-5.4` volunteers
reasoning on only 45% of items**, where the rest of the roster volunteers it far more often. The
follow-up chain-of-thought arm is conditional per item, so it is not a uniform overhead — it is roughly
half the items for one model and a small tail for the others. The pooled rate hid this completely.
Observed on one partial arm; not yet repeated.

### The design choices worth stealing

- **A failed call is not a result.** A call that delivers no body writes a *fault event*, never a
  record. Mixing the two put 156 non-results in the results file and caused three separate defects —
  resume counted them done, the duplicate checker counted them as repeats, and a third reader crashed
  the run after every paid call had completed.
- **Identity is roster-independent.** `unit_id = sha(model, item_id, arm)`. Amending the model list
  cannot orphan calls it does not affect; a roster change is an explicit manifest **supersession**
  with lineage, and already-answered units are kept, not re-bought.
- **No invented token cap.** Each model is asked its own published ceiling, or nothing at all when it
  publishes none; a ceiling is lowered only to fit the model's context window.
- **Three denominators, never one.** `PLANNED = OBSERVED + UNOBSERVED + NEEDS_INSPECTION + CENSORED +
  MISSING`. Truncation, refusal and infrastructure failure are separate outcomes, never folded
  into "wrong".

### Honest limits

- **Unverified against the live API.** The infrastructure-fault policy is proven on a stubbed
  transport through the real dispatch path. Real provider behaviour is not yet confirmed.
- **Three known defects are open**, listed in `code/openrouter/DEFECTS.md`.
- **Single observation per unit.** No repeats, so per-model rates on small cells are observations,
  not stable frequencies.

```
code/openrouter/      34 tools + 25 tests      the phase-2 harness
code/openrouter/survey/                        roster built from a plain model list (roster_build.py)
results/openrouter/   records.jsonl.gz         every scored row, one per call, gzipped
                      manifest.json            the frozen plan each run was bought against
                      summary.csv              per model x run: complete/no_answer/truncated/missing
                      gap_analysis.json        planned vs answered vs unusable, per arm
```

### Running it

**Step 1 — fetch the data.** The corpora are downloaded rather than committed, and the item files
rebuilt from them — see [`docs/DATASETS-phase2.md`](docs/DATASETS-phase2.md) for full provenance,
licences and how each corpus is derived:

```bash
cd code/openrouter
./fetch_data.sh
```

It pulls FutureX-Past (`futurex-ai/Futurex-Past`, Apache-2.0) and BTF-3 (`BTF-2/BTF-3`,
**CC-BY-NC-4.0 — non-commercial use only**) **pinned to a commit and sha256-verified**, re-runs the seeded draws to rebuild the
exact 110-item corpora, restores the run directories from the committed
`results/openrouter/*.jsonl.gz`, and then checks the rebuild is byte-identical to what the published
records were bought against — halting if it is not.

The pin matters: **the FutureX parquet changed upstream after these runs** (252,921 → 257,915 bytes).
An unpinned fetch would silently give you a different pool and a different sample.

**Step 2 — run the tests** (offline, no spend):

```bash
python3 -m unittest discover -p 'test_*.py'      # 452 of 454 pass from a fresh clone
```

The 2 that fail drive a planning-document generator against a file in a private repo; see
[`code/openrouter/TESTING.md`](code/openrouter/TESTING.md).

**Step 3 — run the benchmark** (this costs money):

```bash
python3 run_openrouter.py --bench futurex --items runs/fx_items_110.json \
  --models survey/roster_25.json --max-calls N --max-spend D
```

Both budget flags are **required** — it is a paid API and the caps are checked before the loop.

## Layout

```
REPORT.md                     the write-up
code/       5 scripts         capture, forecast, prompts, budget probe, analysis
            download_data.sh  reproduces every dataset (none are committed)
results/    2,970 rows        summary + per-row CSV + full reasoning traces (JSONL)
samples/    seeded draws      the exact questions used, for reproducibility
docs/                         examples, dataset provenance, benchmark reference, design
```

Datasets are **not committed**: third-party, large (one web corpus is 737 MB), and variously licensed
(BTF-3 is CC-BY-NC-4.0). `code/download_data.sh` fetches exactly what these runs used.

## Models

| model | engine | context | concurrency |
|---|---|---|---|
| qwen3-8b | vLLM | 32,768 | 8 |
| llama-3.1-8b-instruct | vLLM | 32,768 | 8 |
| llama-2-13b-chat-gptq8 | vLLM | **4,096** | 8 |

Budgets are per-model, not global: llama-2's 4,096-token *total* context is a hard constraint, so its
generation budget is sized so prompt + output fits by construction.

## Sources

- GPQA-Diamond · AIME-2025 · BBH · IFEval · TruthfulQA · GAIA — see [`docs/DATASETS.md`](docs/DATASETS.md)
- ForecastBench — [arXiv:2409.19839](https://arxiv.org/abs/2409.19839), ICLR 2025
- Bench to the Future — [arXiv:2506.21558](https://arxiv.org/abs/2506.21558)
