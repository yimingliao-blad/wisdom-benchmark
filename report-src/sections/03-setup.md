## Experiment setup

### Models

| model | engine | context | concurrency |
|---|---|---|---|
| `qwen3-8b` | vLLM | `32768` | `8` |
| `llama-3.1-8b-instruct` | vLLM | `32768` | `8` |
| `llama-2-13b-chat-gptq8` | vLLM | `4096` | `8` |

All at temperature `0`, seed `0`, on one local RTX `4090`. qwen3's `<think>` channel is switched
**off** so it reasons visibly like the llamas, which have no hidden channel — a private reasoning
channel would make the traces incomparable. Generation budgets are per model, not global:
`llama-2-13b-chat-gptq8`'s `4096`-token *total* context is a hard ceiling, so its budget is sized
to fit prompt plus output by construction.

### Benchmarks

| benchmark | measures | pool | drawn |
|---|---|---|---|
| GPQA-Diamond | scientific reasoning depth | 198{m: code/projects/crowd-wisdom/survey/DATASETS.md} | 50{m: code/projects/crowd-wisdom/survey/DATASETS.md} |
| `AIME-2025` | long mathematical reasoning | 30{m: code/projects/crowd-wisdom/survey/DATASETS.md} | 25{m: code/projects/crowd-wisdom/survey/DATASETS.md} |
| BBH | diverse reasoning styles | 6511{m: code/projects/crowd-wisdom/survey/DATASETS.md} | 50{m: code/projects/crowd-wisdom/survey/DATASETS.md} |
| IFEval | instruction-following | 541{m: code/projects/crowd-wisdom/survey/DATASETS.md} | 50{m: code/projects/crowd-wisdom/survey/DATASETS.md} |
| TruthfulQA | truthfulness & calibration | 817{m: code/projects/crowd-wisdom/survey/DATASETS.md} | 50{m: code/projects/crowd-wisdom/survey/DATASETS.md} |
| GAIA validation | agentic planning | 165{m: code/projects/crowd-wisdom/survey/DATASETS.md} | 50{m: code/projects/crowd-wisdom/survey/DATASETS.md} |
| ForecastBench | probabilistic forecasting | 67{m: code/projects/crowd-wisdom/survey/DATASETS.md} | 40{m: code/projects/crowd-wisdom/survey/DATASETS.md} |

Every draw is **seeded random, never a prefix** — all six files are ordered by domain, task or
index, so a head-of-file slice would take one corner and report it as the benchmark. Prompts are
capped at **`1,000`-character** length so every item fits the smallest context; AIME yields
25{m: code/projects/crowd-wisdom/survey/DATASETS.md} rather than 50{m: code/projects/crowd-wisdom/survey/DATASETS.md} because the whole exam is only 30{m: code/projects/crowd-wisdom/survey/DATASETS.md} problems and
5{m: code/projects/crowd-wisdom/survey/DATASETS.md} exceed the cap.

### Conditions

Capability: **two arms** on identical items — *simple* ("Think step by step, showing your
reasoning") and *concise* ("Reason through the necessary steps only ... not every detail or
restatement"). Both end with the identical sentence requesting the final answer on the last line,
so the parser target never changes. IFEval receives **no appended instruction**, because obeying
its own instructions is the measurement.

Forecasting: **eleven conditions** over the same questions, forming a factorial in the
ForecastBench family of price {shown, hidden} by reasoning {none, simple, concise}, plus
Bench-to-the-Future's prompt in three reasoning variants and two of our own.

Total: 2970{m: code/projects/crowd-wisdom/results/summary.csv} generations.
