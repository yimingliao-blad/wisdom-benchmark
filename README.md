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

## Phase 2 — hosted models via OpenRouter

A second harness that runs a configurable roster of hosted models against two forecasting
benchmarks, **FutureX-Past** and **BTF-3**. The model list is held as data, not code, so the roster
can be changed without touching the harness.

**The phase-2 run is still in progress and the data here is partial.** It is included so the code
has its inputs and outputs alongside it, not as a finished result.

### Running it

**Step 1 — fetch the data.** The corpora are downloaded rather than committed; see
[`docs/DATASETS-phase2.md`](docs/DATASETS-phase2.md) for sources and licences.

```bash
cd code/openrouter
./fetch_data.sh
```

FutureX-Past (`futurex-ai/Futurex-Past`, Apache-2.0) and BTF-3 (`BTF-2/BTF-3`, **CC-BY-NC-4.0 —
non-commercial use only**) are pinned to a commit and sha256-verified, the item corpora are rebuilt
from them, and the run directories are restored from `results/openrouter/`.

**Step 2 — tests** (offline, no spend):

```bash
python3 -m unittest discover -p 'test_*.py'
```

**Step 3 — run the benchmark** (this costs money):

```bash
python3 run_openrouter.py --bench futurex --items runs/fx_items_110.json \
  --models survey/roster_25.json --max-calls N --max-spend D
```

Both budget flags are required; the caps are checked before the loop.

```
code/openrouter/          the phase-2 harness and its tests
code/openrouter/survey/   the model roster, held as data
results/openrouter/       per-call records (gzipped), manifests, summary tables
```

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
