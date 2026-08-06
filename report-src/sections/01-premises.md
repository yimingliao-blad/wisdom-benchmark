## Premises

What is assumed true before any of this work means anything, and what would falsify each.

**P1 — A model's *reasoning trace* carries information its *answer* does not.**
The whole design rests on this. If two models produced identical traces and differed only in accuracy,
there would be nothing to fingerprint and clustering would be pointless.
*Falsified if:* traces are indistinguishable across models once benchmark and item are controlled for.

**P2 — The benchmarks are closed-book.** No model gets web access, tool use, or retrieval. A question is
answered from the prompt and the weights alone.
*Falsified if:* any condition leaks external information into the prompt. **This premise was violated and
the violation became a finding** — see Results §R1.

**P3 — The answer parser reads what a careful human would read.** Scores mean nothing if the extractor
misreads the model.
*Falsified if:* a hand-check of parsed answers against traces disagrees. Checked; the parser was rebuilt
twice after real disagreements (markdown wrappers, a trailing LaTeX delimiter).

**P4 — Truncation is not a wrong answer.** A reply cut off mid-reasoning has no answer to score.
*Falsified if:* truncated items were scored as incorrect, which would make a rambling model look wrong
rather than unfinished.

**P5 — The models are independent instruments here.** They share pretraining data, so this is the weakest
premise and the one the wider crowd-wisdom design exists to test rather than assume.
