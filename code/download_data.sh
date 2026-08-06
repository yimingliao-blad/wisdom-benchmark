#!/usr/bin/env bash
# Reproduce the datasets. They are NOT committed: third-party, large (BTF's web corpus alone is 737 MB),
# and variously licensed (BTF-3 is CC-BY-NC-4.0). This script fetches exactly what the runs used.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
python3 - <<'PY'
from huggingface_hub import hf_hub_download
import os, json, glob, urllib.request
D="data"
def hf(repo, fn, sub): hf_hub_download(repo_id=repo, filename=fn, repo_type="dataset", local_dir=os.path.join(D,sub))
# --- the six capability benchmarks -------------------------------------------------------------
hf("Idavidrein/gpqa","gpqa_diamond.csv","gpqa")                      # 198 rows  (auto-gated: accept terms)
hf("google/IFEval","ifeval_input_data.jsonl","ifeval")               # 541 rows
hf("truthfulqa/truthful_qa","generation/validation-00000-of-00001.parquet","truthfulqa")   # 817 rows
hf("MathArena/aime_2025","data/train-00000-of-00001.parquet","aime_2025")                  # 30 rows
for split in ("validation","test"):                                  # GAIA: 165 + 301 = 466 (GATED)
    hf("gaia-benchmark/GAIA", f"2023/{split}/metadata.parquet", "gaia")
os.makedirs(f"{D}/bbh_json", exist_ok=True)                          # BBH: 27 files, 6,511 examples
idx=json.load(urllib.request.urlopen("https://api.github.com/repos/suzgunmirac/BIG-Bench-Hard/contents/bbh"))
for e in idx:
    if e["name"].endswith(".json"):
        urllib.request.urlretrieve(e["download_url"], f"{D}/bbh_json/{e['name']}")
# --- forecasting --------------------------------------------------------------------------------
FB="forecastingresearch/forecastbench-datasets"
hf(FB,"datasets/question_sets/2025-03-02-llm.json","forecastbench")           # 997 questions
hf(FB,"datasets/resolution_sets/2025-03-02_resolution_set.json","forecastbench")  # 5,451 resolutions
hf("BTF-2/BTF-3","btf3_binary_questions_and_forecasts.parquet","btf")         # 1,515 resolved binary
print("done. NOTE: GPQA and GAIA are gated — accept their terms on huggingface.co while logged in.")
PY
