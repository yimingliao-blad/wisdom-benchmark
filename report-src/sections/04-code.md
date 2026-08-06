## Sample code and example

The prompt builder, verbatim from `code/forecast_prompts.py`. Two of the eleven conditions are copied
from published sources; the CoT variants change the output instruction and nothing else:

```python
_SIMPLE  = "Think step by step, showing your reasoning."
_CONCISE = ("Reason through the necessary steps only — show the key steps of your reasoning, "
            "not every detail or restatement.")

# ForecastBench: lift ONLY the "do not output anything else" ban, keep their asterisk answer format.
_FB_BAN = "Do not output anything else.\nAnswer: {{ Insert answer here }}\n"
assert _FB_BAN in FB, "ForecastBench ban/answer tail not found — the source prompt changed"

def _fb_cot(style):
    return FB.replace(_FB_KEEP + _FB_BAN,
                      style + "\nThen, on the last line, output your answer (a number between 0 and 1) "
                      "with an asterisk at the beginning and end of the decimal, e.g. *0.35*\n")
```

The `assert` is deliberate: if either published prompt ever changes, the build fails loudly instead of
silently drifting away from the source it claims to reproduce.

### A worked example — one real GPQA item, one real trace

Question drawn by seeded sample (options shuffled per item, so the correct answer is not always A):

```
Find KE of product particles in, Pi(+) = mu(+) + nu
here Pi(+) is stationary. Rest mass of Pi(+) & mu(+) is 139.6 MeV & 105.7 MeV respectively.

A) 3.52 MeV, 20.8 MeV      B) 4.12 MeV, 29.8 MeV
C) 2.84 MeV, 26.8 MeV      D) 7.2 MeV, 32.8 MeV

Answer with the single letter A, B, C or D.

Reason through the necessary steps only — show the key steps of your reasoning, not every detail
or restatement. Then give your final answer on the last line, by itself, with no extra words.
```

Ground truth is **B**. The three models returned last lines `C`, a mid-sentence fragment
(status TRUNCATED, so unscored), and `A) 3.52 MeV, 20.8 MeV`. Only the last shows why the parser cannot
assume compliance: it must take the trailing standalone letter out of a verbose line. Full traces for all
2970{m: code/projects/crowd-wisdom/results/summary.csv} generations are in `results/*_full.jsonl`; more worked
examples in `docs/EXAMPLES.md`.

### Extraction — what the renderer is given

The report you are reading is itself built by `render.py`, which refuses to emit HTML while any
number lacks a declared class. Every figure below therefore carries its source.


```python
def answer_lines(txt, k=6):
    """Last k non-empty lines, cleaned, LAST FIRST. qwen3 can end on a bare '$$' with the answer
    on the line above, so the parser must walk back rather than trust the final line."""
    ls = [clean(l) for l in (txt or "").strip().split("\n") if l.strip()]
    return [l for l in ls[-k:][::-1] if l]
```

Substring matching was **rejected** for exact-answer benchmarks: with gold `False`, any trace containing
the word "false" would score correct regardless of its conclusion — a checker that cannot fail.
