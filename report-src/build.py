"""Build the crowd-wisdom benchmark report.  Run: python3 reports/crowd-wisdom-benchmarks/build.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "code", "tools", "report-builder"))
import model, render, svg_chart      # noqa: E402

S = "code/projects/crowd-wisdom/results/summary.csv"

CHARTS = {
    "auc": svg_chart.bars(
        "forecast-auc-by-condition",
        "Forecasting discrimination (ROC-AUC, mean over three models) — threshold-free and base-rate invariant",
        [("FB-cot-simple · price shown", "0.831", S),
         ("FB-zeroshot · price shown", "0.825", S),
         ("FB-cot-concise · price shown", "0.807", S),
         ("cot-concise · no price", "0.701", S),
         ("cot-simple · no price", "0.663", S),
         ("FBnp-cot-concise · no price", "0.636", S),
         ("FBnp-zeroshot · no price", "0.582", S),
         ("FBnp-cot-simple · no price", "0.565", S),
         ("BTF-cot-simple · no price", "0.554", S),
         ("BTF-noevidence · no price", "0.550", S),
         ("BTF-cot-concise · no price", "0.535", S)],
        maximum=1.0,
        highlight={"FB-cot-simple · price shown", "FB-zeroshot · price shown",
                   "FB-cot-concise · price shown"},
        note=("Higher is better; <span class=\"num\" data-src=\"" + S + "\">0.5</span> is no "
              "discrimination. The three highlighted bars are the only conditions that put the live "
              "market price in the prompt. Every prompt WITHOUT it sits between chance and "
              "<span class=\"num\" data-src=\"" + S + "\">0.70</span>, whatever its reasoning "
              "style — so the separation is information, not reasoning."),
    ),
    "gpqa": svg_chart.bars(
        "gpqa-cot-reversal",
        "GPQA-Diamond accuracy — the CoT arm that wins depends on the model",
        [("qwen3-8b · simple", "0.651", S),
         ("qwen3-8b · concise", "0.467", S),
         ("llama3.1-8b · concise", "0.341", S),
         ("llama2-13b · simple", "0.286", S),
         ("llama3.1-8b · simple", "0.250", S),
         ("llama2-13b · concise", "0.120", S)],
        maximum=0.7,
        highlight={"llama3.1-8b · concise", "llama3.1-8b · simple"},
        note=("Verbose reasoning helps <code>qwen3-8b</code> and <code>llama-2-13b</code> and HURTS "
              "<code>llama-3.1-8b</code> (highlighted). "
              "Its truncation rate nearly doubles under the verbose instruction, so it runs past its "
              "budget before reaching an answer."),
    ),
}


def main():
    try:
        path, res = render.render(HERE, charts=CHARTS)
    except model.ReportError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
    print(f"OK  {path}  ({os.path.getsize(path):,} bytes)")
    print(f"    sourced measurements: {res.annotations}")
    print(f"    auto-classed: {res.auto_classed}")
    print(f"    reader disagreements: {len(res.disagreements)}")


if __name__ == "__main__":
    main()
