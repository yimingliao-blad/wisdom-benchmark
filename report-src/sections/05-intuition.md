## Intuition — what to expect before looking

**Why two CoT styles at all.** Telling a model to "show your reasoning" invites it to restate the question
and re-derive steps it already has. On a hard problem that can spiral: one trace in this run reached
`75,447` characters of the same step re-derived, and never produced an answer. Naming restatement as
unwanted should shorten traces. Whether it *helps accuracy* is the open question — a physics problem may
need the algebra written out, while a probability judgement may be harmed by talking yourself away from
your first instinct.

**Why the metric choice matters more than usual here.** The forecasting set resolves YES on roughly one
question in six. On such a set, *anything that outputs low numbers scores well* — a model that always
answers "no" gets high accuracy and a respectable Brier score while discriminating nothing at all. So:

- **accuracy alone is misleading** and is never reported here without recall beside it;
- **Brier** conflates ranking with calibration, and is always shown against the always-**base rate**
  reference, not just against `0.5`;
- **ROC-AUC** is threshold-free and base-rate invariant, which makes it the honest headline;
- **F1** is reported because it ignores the true-negative mass that inflates accuracy on this set.

**What a reader should predict.** Bigger and newer models should read the questions better. Reasoning
should help where the answer must be computed and matter less where it must be judged. And any prompt that
hands the model extra information should beat any prompt that only changes how it thinks — which is
exactly what happened, and is the finding that reframes everything else.
