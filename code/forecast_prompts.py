"""The four forecasting prompt conditions.

TWO ARE COPIED FROM THE SOURCES, NOT PARAPHRASED:
  * BTF   — Bench to the Future (arXiv 2506.21558), Appendix A.1, the "No Evidence Forecaster" variant
            (the <research> block is empty, which is their own baseline architecture for no web access).
  * FB    — ForecastBench (arXiv 2409.19839), verbatim from their repo
            src/llm_forecaster/prompts.py :: ZERO_SHOT_MARKET_WITH_FREEZE_VALUE_PROMPT.
            Their header credits Halawi et al. 2024 (arXiv 2402.18563) as the origin.

TWO ARE OURS, matching what we ran on the six capability benchmarks:
  * COT_SIMPLE  — "Think step by step..."
  * COT_CONCISE — "Reason through the necessary steps only..."

THE CONTRAST WORTH NOTING: ForecastBench's own prompt says "Do not output anything else" — it FORBIDS
reasoning. BTF's asks for five explicit reasoning steps (a)-(e) before the probability. So the two
published benchmarks sit at opposite ends of the format-pressure axis, and our two CoT variants sit
between them. That makes prompt style the single variable across four conditions on identical questions.
"""

# ---- ForecastBench, verbatim from their repository ------------------------------------------------
FB = """
You are an expert superforecaster, familiar with the work of Tetlock and others. Make a prediction of the probability that the question will be resolved as true. You MUST give a probability estimate between 0 and 1 UNDER ALL CIRCUMSTANCES. If for some reason you can't answer, pick the base rate, but return a number between 0 and 1.

Question:
{question}

Question Background:
{background}

Resolution Criteria:
{resolution_criteria}

Market value on {freeze_datetime}:
{freeze_value}

Today's Date: {today}

Question resolution date: {resolution_date}

Output your answer (a number between 0 and 1) with an asterisk at the beginning and end of the decimal.
Do not output anything else.
Answer: {{ Insert answer here }}
"""

# ---- Bench to the Future, Appendix A.1, no-evidence variant ----------------------------------------
BTF = """You are a professional forecaster interviewing for a job.

Your interview question is:

You are tasked with giving a probabilistic forecast for the following question:
<question>
{question}
</question>

Here is some background on the question that you may find helpful:
<background>
{background}
</background>

The following criteria specify precisely how the question's resolution will be determined:
<resolution-criteria>
{resolution_criteria}
</resolution-criteria>

Please use the information and research gathered by your trusted assistant below:
<research>
</research>

Today is {today}.

Here are top tips from good forecasters:

If an event was anticipated to happen in a certain timeframe, but 80% of that time has passed and there is no recent news or updates about it happening soon, then you should be skeptical that it will happen in the originally stated timeframe. It probably means that it will be delayed or plans have changed.

Think about base rates for similar events in the past. Sometimes a base rate is the best you can do, if you can't find much information about the question.

Sometimes finding a good base rate is difficult, especially when the events are relatively unique. In these cases, you need to put more weight on the "inside view" which means weighing considerations that appear specific to the situation that lead to a very different forecast than base rates would dictate. You will need to use your own judgment.

Put extra weight on the status quo outcome since the world changes slowly most of the time. This is especially true when coordination or agreement between people or organizations is required.

Think about if there are seasonal effects.

Think about what the current trend is and if it makes sense to extrapolate, or not.

Think about the scope of the question.

Think about the incentives and power of any influential people involved in the situation.

(10) Pre-mortem. Think about how you are most likely to be wrong. Imagine that you are writing a letter to your future self that you will open and read once the outcome is known. In the letter you try to explain to your future self the most likely way that your forecast will be deemed to be a poor forecast. Are you most worried about missing a key piece of information? What is the biggest uncertainty and would keep you awake at night?

(11) More general advice:
 - Even if something seems impossible, think twice before forecasting less than 3%.
 - Even if something seems certain, think twice before forecasting more than 97%.
 - Pay close attention to the exact wording and resolution source in the resolution criteria.
 - Like a good forecaster, you should use your own judgment to come to the most accurate forecast!

Before answering, as part of your reasoning, you write:
(a) The time left until the outcome to the question is known.
(b) The status quo outcome if nothing changed.
(c) Think about answering the question with different scopes to help ensure that you have a self consistent view and have considered the broader context.
(d) A brief description of a scenario that results in a No outcome.
(e) A brief description of a scenario that results in a Yes outcome.

The last thing you write is your final answer as a probability between 0 and 1.
"""

# ---- ours: the two CoT variants already used on the six capability benchmarks ----------------------
_BASE = """Question:
{question}

Question Background:
{background}

Resolution Criteria:
{resolution_criteria}

Today's Date: {today}
Question resolution date: {resolution_date}

Give the probability between 0 and 1 that this question resolves YES."""

COT_SIMPLE = _BASE + """

Think step by step, showing your reasoning. Then give your final answer on the last line, by itself, with no extra words."""

COT_CONCISE = _BASE + """

Reason through the necessary steps only — show the key steps of your reasoning, not every detail or restatement. Then give your final answer on the last line, by itself, with no extra words."""

CONDITIONS = {"FB-zeroshot": FB, "BTF-noevidence": BTF, "cot-simple": COT_SIMPLE, "cot-concise": COT_CONCISE}


# ---- CoT VARIANTS OF THE SOURCE PROMPTS (ours, clearly derived) -------------------------------------
# WHY: ForecastBench's own prompt ends "Do not output anything else" and yields a 6-CHARACTER reply
# ("*0.35*"). That is fine for a Brier score and USELESS as a behavioural fingerprint — crowd-wisdom needs
# the reasoning TRAJECTORY, not just the number.
#
# EACH VARIANT MUST YIELD BOTH: the reasoning AND a parseable answer in the SOURCE'S OWN answer format.
# So FB keeps its asterisk contract (*0.35*) and BTF keeps its closing final-answer line; only the
# "do not output anything else" ban is lifted and a reasoning instruction added. The question, framing and
# field order are untouched, so reasoning style is the single variable.

_SIMPLE = "Think step by step, showing your reasoning."
_CONCISE = ("Reason through the necessary steps only — show the key steps of your reasoning, not every "
            "detail or restatement.")

# FB: lift ONLY the ban, keep the asterisk answer format on the last line.
_FB_BAN = "Do not output anything else.\nAnswer: {{ Insert answer here }}\n"
assert _FB_BAN in FB, "ForecastBench ban/answer tail not found — the source prompt changed"
_FB_KEEP = "Output your answer (a number between 0 and 1) with an asterisk at the beginning and end of the decimal.\n"
assert _FB_KEEP in FB, "ForecastBench asterisk instruction not found"

def _fb_cot(style):
    # reasoning FIRST, then their asterisk answer LAST — both present
    out = FB.replace(_FB_KEEP + _FB_BAN,
                     style + "\nThen, on the last line, output your answer (a number between 0 and 1) "
                     "with an asterisk at the beginning and end of the decimal, e.g. *0.35*\n")
    assert "asterisk" in out and style in out
    return out

FB_COT_SIMPLE = _fb_cot(_SIMPLE)
FB_COT_CONCISE = _fb_cot(_CONCISE)

# BTF: already demands reasoning steps (a)-(e) and already ends with a final-answer line. KEEP that line;
# insert the style modifier just before it.
_BTF_TAIL = "The last thing you write is your final answer as a probability between 0 and 1.\n"
assert _BTF_TAIL in BTF, "BTF final-answer line not found — the source prompt changed"
BTF_COT_SIMPLE = BTF.replace(_BTF_TAIL, _SIMPLE + "\n\n" + _BTF_TAIL)
BTF_COT_CONCISE = BTF.replace(_BTF_TAIL, _CONCISE + "\n\n" + _BTF_TAIL)

CONDITIONS.update({
    "FB-cot-simple": FB_COT_SIMPLE,
    "FB-cot-concise": FB_COT_CONCISE,
    "BTF-cot-simple": BTF_COT_SIMPLE,
    "BTF-cot-concise": BTF_COT_CONCISE,
})


# ---- FB WITHOUT THE MARKET PRICE (the fair comparison) ---------------------------------------------
# ForecastBench ships TWO market prompts. The one used above (WITH_FREEZE_VALUE) hands the model the live
# prediction-market price. Measured on this sample the price ALONE scores Brier 0.0609 — better than every
# model in every condition — so any FB-vs-BTF comparison using it is an information asymmetry, not a prompt
# comparison. ZERO_SHOT_MARKET_PROMPT is their plain variant; these three restore the fair test.
FB_NOPRICE = """
You are an expert superforecaster, familiar with the work of Tetlock and others. Make a prediction of the probability that the question will be resolved as true. You MUST give a probability estimate between 0 and 1 UNDER ALL CIRCUMSTANCES. If for some reason you can't answer, pick the base rate, but return a number between 0 and 1.

Question:
{question}

Question Background:
{background}

Resolution Criteria:
{resolution_criteria}

Today's Date: {today}

Question resolution date: {resolution_date}

Output your answer (a number between 0 and 1) with an asterisk at the beginning and end of the decimal.
Do not output anything else.
Answer: {{ Insert answer here }}
"""
_NP_BAN = "Do not output anything else.\nAnswer: {{ Insert answer here }}\n"
_NP_KEEP = "Output your answer (a number between 0 and 1) with an asterisk at the beginning and end of the decimal.\n"
assert _NP_BAN in FB_NOPRICE and _NP_KEEP in FB_NOPRICE


def _fbnp_cot(style):
    return FB_NOPRICE.replace(_NP_KEEP + _NP_BAN,
                              style + "\nThen, on the last line, output your answer (a number between 0 and 1) "
                              "with an asterisk at the beginning and end of the decimal, e.g. *0.35*\n")


CONDITIONS.update({
    "FBnp-zeroshot": FB_NOPRICE,
    "FBnp-cot-simple": _fbnp_cot(_SIMPLE),
    "FBnp-cot-concise": _fbnp_cot(_CONCISE),
})



def render(cond, q):
    t = CONDITIONS[cond]
    return t.format(question=q["question"], background=q["background"],
                    resolution_criteria=q["resolution_criteria"], today=q["today"],
                    resolution_date=q["resolution_date"], freeze_datetime=q["freeze_datetime"],
                    freeze_value=q["freeze_value"])
