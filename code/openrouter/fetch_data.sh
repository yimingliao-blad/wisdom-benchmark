#!/usr/bin/env bash
# Fetch the phase-2 benchmark corpora and rebuild the exact item files the runs used.
#
# The datasets are fetched rather than committed. This is a CHOICE, not a licence bar:
#   FutureX-Past  futurex-ai/Futurex-Past   Apache-2.0     no restriction at all
#   BTF-3         BTF-2/BTF-3               CC-BY-NC-4.0   redistribution IS allowed with
#                                                          attribution; COMMERCIAL USE is not
# Provenance, licences and derivation: docs/DATASETS-phase2.md
#
# BOTH DOWNLOADS ARE PINNED TO A COMMIT. This is not caution for its own sake: the FutureX
# parquet CHANGED upstream after these runs (252,921 -> 257,915 bytes on 2026-08-11), so an
# unpinned fetch would silently give you a different pool and a different 110-item draw.
# Every file is sha256-verified and the script HALTS on any mismatch.
set -euo pipefail
cd "$(dirname "$0")"

FX_REPO="futurex-ai/Futurex-Past"
FX_REV="3c2e39690de35eb1fcc621251f56343c72bae8c4"
FX_SHA="55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50"

BTF_REPO="BTF-2/BTF-3"
BTF_REV="ad5a2165eea26a8a43592ba36ff15765199ddc71"
BTF_SHA="50f01603ae5284e48b462ae8855a4b5e8c82004fd07f4a3c818c0e88e9b91c2b"

mkdir -p data/futurex/past/data data/btf runs

fetch () {  # repo rev path dest sha
  local url="https://huggingface.co/datasets/$1/resolve/$2/$3"
  if [ -f "$4" ] && [ "$(sha256sum "$4" | cut -d' ' -f1)" = "$5" ]; then
    echo "  have    $4"; return
  fi
  echo "  fetch   $4"
  curl -fsSL -o "$4" "$url"
  local got; got=$(sha256sum "$4" | cut -d' ' -f1)
  if [ "$got" != "$5" ]; then
    echo "HALT: sha256 mismatch for $4" >&2
    echo "  expected $5" >&2; echo "  got      $got" >&2
    echo "  The pinned revision did not return the expected bytes. Do NOT proceed:" >&2
    echo "  the item draw would not match the published records." >&2
    exit 1
  fi
}

echo "1/3  downloading pinned corpora"
fetch "$FX_REPO"  "$FX_REV"  "data/train-00000-of-00001.parquet" \
      "data/futurex/past/data/train-00000-of-00001.parquet" "$FX_SHA"
fetch "$BTF_REPO" "$BTF_REV" "btf3_binary_questions_and_forecasts.parquet" \
      "data/btf/btf3_binary_questions_and_forecasts.parquet" "$BTF_SHA"

echo "2/3  rebuilding the item corpora (seeded draws, contamination filter applied)"
python3 build_futurex_corpus.py --out runs/fx_items_110.json
python3 build_btf3_corpus.py    --out runs/btf3_items_110.json
python3 - <<'PY'
# fx_smoke4.json is a 4-item wiring fixture drawn from the RAW pool (before the contamination
# filter), so it is not a slice of the 110. Rebuilt by explicit item_id -- deterministic.
import json, pandas as pd
IDS = ["69a6d48ee78a390068a18729|2026-04-02", "8b7d371b8e8e2c1967c91f3b|2026-07-11",
       "cbc2fddf28ccc5687af1bcd3|2026-06-17", "c893e45534964d90d095abcc|2026-06-23"]
fx = pd.read_parquet("data/futurex/past/data/train-00000-of-00001.parquet")
pool = {f"{r['id']}|{r['end_time']}": r for r in fx.to_dict("records")}
missing = [i for i in IDS if i not in pool]
if missing:
    raise SystemExit(f"HALT: {len(missing)} smoke item(s) absent from the pinned parquet: {missing}")
out = [{"item_id": i, "prompt": pool[i]["prompt"], "level": int(pool[i]["level"]),
        "end_time": str(pool[i]["end_time"]), "ground_truth": pool[i].get("ground_truth")} for i in IDS]
json.dump(out, open("runs/fx_smoke4.json", "w"), indent=1)   # indent=1 reproduces the fixture byte-for-byte
print("  wrote runs/fx_smoke4.json (4 items)")
PY

echo "3/4  restoring the run artifacts the tests read (results/openrouter/ IS committed)"
python3 - <<'RESTORE'
import gzip, os, shutil
R = "../../results/openrouter"
if not os.path.isdir(R):
    raise SystemExit("HALT: %s not found. Run this from code/openrouter/ in the repo checkout." % R)
# our own run output, published gzipped -- decompress into the layout the tests expect
# generic: restore every run directory that was published, whatever it is called
for tag in sorted(d for d in os.listdir(R) if os.path.isdir(os.path.join(R, d))):
    src = os.path.join(R, tag)
    os.makedirs("runs/" + tag, exist_ok=True)
    gz = os.path.join(src, "records.jsonl.gz")
    if os.path.exists(gz):
        with gzip.open(gz, "rb") as f, open("runs/%s/records.jsonl" % tag, "wb") as o:
            shutil.copyfileobj(f, o)
    for extra in ("manifest.json", "README", "schedule.json"):
        s = os.path.join(src, extra)
        if os.path.exists(s): shutil.copy(s, "runs/%s/%s" % (tag, extra))
    print("  restore runs/" + tag)
# the frozen fixture's items.json is byte-identical to the rebuilt 110-item corpus
shutil.copy("runs/fx_items_110.json", "runs/_frozen_fxgate_2026-08-08/items.json")
for tag in os.listdir("runs"):
    d = "runs/" + tag
    if not os.path.isdir(d) or os.path.exists(d + "/items.json"): continue
    corpus = "runs/btf3_items_110.json" if "btf3" in tag else "runs/fx_items_110.json"
    shutil.copy(corpus, d + "/items.json")
m = os.path.join(R, "manifest_4d3477ce313573a7.json")
if os.path.exists(m): shutil.copy(m, "runs/manifest_4d3477ce313573a7.json")
print("  run artifacts restored")
RESTORE
echo "4/4  verifying the rebuild matches what the published records were bought against"
python3 - <<'PY'
import hashlib, sys
EXPECT = {"runs/fx_items_110.json":  "14b03da5a8d2d892b756",
          "runs/btf3_items_110.json":"1bab93361f198e53ee5d",
          "runs/fx_smoke4.json":     "e0af581a415e90d95cc6"}
bad = []
for p, pref in EXPECT.items():
    got = hashlib.sha256(open(p, "rb").read()).hexdigest()
    ok = got.startswith(pref)
    print(f"  {'OK  ' if ok else 'FAIL'} {p}  {got[:20]}")
    if not ok: bad.append((p, pref, got[:20]))
if bad:
    print("\nHALT: a rebuilt corpus does not match the one the published records were bought")
    print("against. The draw is seeded, so this means the upstream data moved. Do not compare")
    print("new calls against results/openrouter/*.jsonl.gz -- they would be different items.")
    sys.exit(1)
print("\nAll corpora reproduce byte-for-byte. Tests that need data can now run:")
print("  python3 -m unittest discover -p 'test_*.py'")
PY
