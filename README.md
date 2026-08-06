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
