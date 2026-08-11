# Model release dates and training cutoffs — evidence file

> Compiled 2026-08-06 by web research for the model-survey report. **This is a SECONDARY-SOURCE file.**
> Nothing here was measured locally; every row is what a published source states. The agent's own
> training ends 2026-05, so anything released after that is known only through these sources.
>
> **VERIFICATION TIER**, carried per row:
> - **T1** — fact-checked against API docs or a vendor template by the cited source.
> - **T2** — vendor spec or a single secondary source, not cross-checked.
> - **PROXY** — no cutoff published; the RELEASE DATE is used as the effective cutoff (see the rule below).
>
> **The single most important fact in this file: NO open-weight model publishes a training cutoff.**
> Llama 4 is the sole exception. For every other open-weight family the cutoff is UNPUB.
>
> **RULE (owner, 2026-08-07): where no cutoff is published, USE THE RELEASE DATE as the effective cutoff.**
> This is sound because it is CONSERVATIVE IN THE DIRECTION THAT MATTERS. A model's training data always
> predates its release, so `true cutoff <= release date`. Therefore:
>   * release date <= anchor  =>  true cutoff <= anchor  =>  **contamination-safe, guaranteed**.
>   * release date >  anchor  =>  says nothing; the model MAY still be safe.
> The rule can never wrongly admit a contaminated model. It can only wrongly exclude a safe one — Llama 4
> is exactly that case (released 2025-04-05, trained to 2024-08), which is why a PUBLISHED cutoff always
> takes precedence over the proxy where one exists.

## The two anchor dates

| anchor | date | what it is |
|---|---|---|
| ForecastBench | 2025-03-02 | `forecast_due_date` of the question set used; market prices frozen 2025-02-20; resolutions run 2025-03-09 → 2025-12-30 |
| BTF-3 | 2026-04-29 | earliest `present_date` in the binary set (range 2026-04-29 → 2026-05-29); resolutions 2026-05-17 → 2026-07-01 |

Both verified by counting the downloaded files, not from the papers.

## Section 1 — cutoff at or before 2025-03-02 (safe for ForecastBench)

| family | model | sizes / architecture | release | cutoff | tier |
|---|---|---|---|---|---|
| Meta Llama | Llama 3.1 | 8B, 70B, 405B dense | 2024-07 | 2023-12 | T2 |
| Meta Llama | Llama 3.3 | 70B dense | 2024-12 | 2023-12 | T2 |
| Meta Llama | Llama 4 Scout | 109B-A17B MoE (16 experts) | 2025-04-05 | **2024-08** | T1 |
| Meta Llama | Llama 4 Maverick | 400B-A17B MoE (128 experts) | 2025-04-05 | **2024-08** | T1 |
| Meta Llama | Llama 4 Behemoth | ~2T-A288B MoE (preview) | announced 2025-04 | 2024-08 | T2 |
| Alibaba Qwen | Qwen2.5 | 0.5B–72B dense | 2024-09 | **2024-09** (release, proxy) | PROXY |
| Mistral | Mistral Small 3 | 24B dense | 2025-01-30 | **2025-01-30** (release, proxy) | PROXY |
| NVIDIA | Llama-3.1-Nemotron | 70B dense (Llama-derived) | 2024-10 | inherits 2023-12 | T2 |
| OpenAI | GPT-4o | undisclosed | 2024-05 | 2023-10 | T1 |
| Anthropic | Claude 3.5 Sonnet | undisclosed | 2024-06 | 2024-04 | T1 |
| Anthropic | Claude 3 | Opus / Sonnet / Haiku | 2024-03 | 2023-08 | T1 |
| Google | Gemini 3.1 Pro | undisclosed | 2026 | **2025-01** | T1 |
| Google | Gemini 3.5 Flash | undisclosed | 2026-05 | **2025-01** | T1 |
| Moonshot | Kimi K2 (original) | 1T-A32B MoE | 2025 | 2024-12-31 | T2 |
| MiniMax | M2.5 | undisclosed | 2025 | 2025-01 | T2 |

**Best-aligned for ForecastBench: Gemini 3.1 Pro and Gemini 3.5 Flash, both cutoff 2025-01** — one month
before the 2025-02-20 freeze, so maximal context with no outcome knowledge. Notably both were *released*
long after their cutoff; release date and cutoff are decoupled and only the cutoff matters here.

## Section 2 — cutoff between 2025-03-02 and 2026-04-29 (adds coverage for BTF-3)

| family | model | sizes / architecture | release | cutoff | tier |
|---|---|---|---|---|---|
| Alibaba Qwen | Qwen3 dense | 0.6B, 1.7B, 4B, 8B, 14B, 32B | 2025-04-28 | **2025-04-28** (release, proxy) | PROXY |
| Alibaba Qwen | Qwen3 MoE | 30B-A3B, 235B-A22B | 2025-04-28 | **2025-04-28** (release, proxy) | PROXY |
| Alibaba Qwen | Qwen3 Max | undisclosed | 2025 | 2025-06-30 | T2 |
| Alibaba Qwen | Qwen3.5 dense | 2B, 9B, 27B | 2026-02-16 | **2026-02-16** (release, proxy — the stated '2026 year-level' is too coarse) | PROXY |
| Alibaba Qwen | Qwen3.5 MoE | 35B-A3B, 122B-A10B, 397B-A17B | 2026-02-16 | **2026-02-16** (release, proxy) | PROXY |
| Alibaba Qwen | Qwen3.6 MoE | 35B-A3B | 2026-04-16 | **2026-04-16** (release, proxy) | PROXY |
| Alibaba Qwen | Qwen3.6 dense | 27B | 2026-04-22 | **2026-04-22** (release, proxy) | PROXY |
| Mistral | Magistral Small / Medium | undisclosed | 2025-06-10 | **2025-06-10** (release, proxy) | PROXY |
| Mistral | Mistral Small 4 | 119B-A6B MoE | 2026-03-16 | **2026-03-16** (release, proxy) | PROXY |
| Mistral | Mistral Medium 3.5 | 128B | 2026-04-29 | **2026-04-29** (release, proxy) | PROXY |
| NVIDIA | Nemotron 3 Nano | 30B-A3.5B hybrid Mamba-Transformer MoE | 2025-12 | **2025-12** (release, proxy) | PROXY |
| NVIDIA | Nemotron 3 Super | 120B-A12B | 2026-03-11 | **2026-03-11** (release, proxy) | PROXY |
| OpenAI | GPT-5.2 | undisclosed | 2025 | 2025-08-31 | T1 |
| OpenAI | GPT-5.4 | undisclosed | 2025 | 2025-08-31 | T1 |
| OpenAI | GPT-5.5 | undisclosed | 2025-12 | 2025-12-01 | T1 |
| OpenAI | GPT-5.6 Sol / Terra / Luna | undisclosed | 2026 | **2026-02-16** | T1 |
| Anthropic | Claude Sonnet 4.6 | undisclosed | 2026 | 2026-01 training / 2025-08 reliable | T1 |
| Anthropic | Claude Opus 4.8 | undisclosed | 2026 | 2026-01 | T1 |
| Anthropic | Claude Fable 5 | undisclosed | 2026 | 2026-01 | T1 |
| Anthropic | Claude Sonnet 5 | undisclosed | 2026 | 2026-01 | T1 |
| xAI | Grok 4.5 | undisclosed | 2026 | **2026-02-01** | T1 |
| MiniMax | M3 | undisclosed | 2026 | 2026-01 | T1 |
| Moonshot | Kimi K2.6 | undisclosed | 2026 | 2025-04 | T2 |
| Moonshot | Kimi K2.5 | 1T-A32B MoE | 2026-01-27 | **2026-01-27** (release, proxy) | PROXY |
| Google | Gemma 4 | 2B–31B | 2026-04-02 | **2026-04-02** (release, proxy) | PROXY |
| Z.ai | GLM-5.1 | 754B-A40B MoE | 2026-04-07 | **2026-04-07** (release, proxy) | PROXY |
| DeepSeek | V3.2 | 671B-A37B MoE | 2026 | **2026** (release, proxy) | PROXY |
| MiniMax | M2.7 | 230B-A10B MoE | 2026-04 | **2026-04** (release, proxy) | PROXY |

**Best-aligned for BTF-3: GPT-5.6 (2026-02-16) and Grok 4.5 (2026-02-01)** — the two latest verified
cutoffs that still precede the 2026-04-29 anchor.

## Excluded by contamination

| model | cutoff | why |
|---|---|---|
| Claude Opus 5 | 2026-05 | **after** BTF-3's earliest present_date and inside its resolution window (2026-05-17 → 2026-07-01) |
| NVIDIA Nemotron 3 Ultra | 2026-06-01 (release, proxy) | released AFTER both anchors — surfaced only by applying the release-date rule |
| Qwen 3.7 Max | "2026 year-level", no release date found | too coarse to place and no release date to fall back on |
| Gemini 3.6 Flash | none (live search) | real-time retrieval defeats a fixed-cutoff design entirely |

## Already available on the local server

`gemma-4-12b`, `gemma-4-26b`, `qwen3.5-27b`, `qwen3.6-35b`, `magistral-small`, `deepseek-r1-distill-llama-8b`,
`qwen3-8b`, `qwen2.5-7b`, `llama-3.1-8b`, `llama-3.2-3b`, `llama-2-13b`, `gemma-2-9b`, `gemma-3-12b`,
`medgemma-27b`. Several 2026-era open models are therefore already runnable without new downloads — but
all carry UNPUB cutoffs.

## The standing recommendation

Because open-weight cutoffs are unpublished and the fact-check source's own conclusion is *"never trust a
model's self-reported cutoff"*, **any model entering the survey should first pass an empirical cutoff
probe**: ask about verifiable events at monthly intervals across 2025–2026 and locate where knowledge
stops. That is the only way to place an open-weight model against either anchor, and it independently
tests the contamination assumption rather than inheriting it from a vendor page.

## Sources

- https://metehan.ai/articles/llm-knowledge-cutoff-dates/ — fact-checked cutoff table, June 2026
- https://otterly.ai/blog/knowledge-cutoff/ — cutoff dates, 2026
- https://joshuaschultz.com/cheatsheets/open-weight-models-2026/ — open-weight sizes and release dates
- https://ai.meta.com/blog/llama-4-multimodal-intelligence/ — Llama 4 herd
- https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E — Scout card
- https://github.com/QwenLM/Qwen3.6 — Qwen3.6 series
- https://en.wikipedia.org/wiki/Qwen — Qwen size tables
- https://aireleasetracker.com/company/mistral — Mistral release timeline
- https://www.buildmvpfast.com/blog/nvidia-nemotron-open-source-llm-models-2026 — Nemotron 3
- https://codersera.com/blog/open-source-llms-landscape-2026/ — open-source landscape, May 2026
