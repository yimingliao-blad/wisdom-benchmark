## Hypotheses

Each is stated so it could come out false, and each did or did not.

**H1 — Reasoning style changes measured capability.**
Predicts: accuracy differs between a "think step by step" prompt and a "necessary steps only" prompt on
identical items. **Supported, with a reversal** — the direction is model-dependent.

**H2 — A single reasoning prompt is best for all models.**
Predicts: whichever CoT style wins, wins everywhere. **Falsified.**

**H3 — More reasoning improves probabilistic forecasting.**
Predicts: CoT conditions beat the no-reasoning condition on ROC-AUC. **Not supported** — the dominant
factor turned out to be information in the prompt, not reasoning.

**H4 — Truncation is incidental.**
Predicts: truncation rates are low and similar across models and prompts, so they can be ignored.
**Falsified** — truncation is differential by model and by prompt, and it mediates H1's reversal.

**H5 — Published forecasting prompts transfer.**
Predicts: a prompt designed for a forecasting benchmark works on that benchmark's own question type.
**Not supported for one of the two.**
