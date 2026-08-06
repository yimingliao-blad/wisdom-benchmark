## Conclusion

### What the results support

**A single reasoning prompt cannot be chosen for a mixed model set.** Verbose CoT beats concise on
GPQA-Diamond for two of three models and loses for the third, and the mediator is whether the model stops
talking before its budget runs out. For the crowd-wisdom design this matters directly: fixing one prompt
would penalise verbose models, and that penalty would then enter the behavioural representation looking
like a real difference between models rather than an artefact of our choice.

**Information in the prompt swamps reasoning style.** Removing one field — the market price — costs more
ROC-AUC than every reasoning manipulation combined. Any future claim that a prompt "improves forecasting"
has to rule this out first.

**Instruction compliance and truncation are cheap, stable, discriminating features.** They separate these
three models more reliably than accuracy does, and they cost nothing extra to collect.

### What the results do not support

Three claims are **not supported** by this data.

**Nothing here says these models can forecast.** Without market information their ROC-AUC sits near the
no-discrimination floor. The apparent competence in the headline conditions was borrowed from the prompt.

**Nothing here tests the crowd-wisdom hypothesis.** Three models cannot be clustered; the elbow and
silhouette methods in the design need far more points. This work produces the substrate — `2,970` traces
with answers, ground truth and verdicts — not the finding.

**No number here is comparable to a published leaderboard.** BBH ran zero-shot rather than the canonical
three-shot chain-of-thought, GAIA ran text-only so its attachment questions were unanswerable by
construction, and IFEval and TruthfulQA are unscored.

### What is still open

1. **`BTF-3` is downloaded and unrun** — 1515{m: code/projects/crowd-wisdom/survey/DATASETS.md}
   resolved binary questions carrying their own `present_date` and a per-question published expert
   forecast. That last column is what the first hypothesis needs to compare a committee against an expert, and it
   is the right substrate for BTF's prompt.
2. **IFEval and TruthfulQA scoring**, which would convert `100` dead rows per model per arm into two of the
   nine behaviour features the design calls for.
3. **The roster.** Steps `4` through `8` need `20` to `30` models. Measured throughput says that is roughly eight
   hours of local compute for the 8B class — the constraint is model access and API budget, not GPU time.
4. **Sample size.** Forty forecasting questions and about fifty per capability benchmark. Several patterns
   in this work reversed when a partial batch finished, so differences of a few points here should not be
   treated as real.
