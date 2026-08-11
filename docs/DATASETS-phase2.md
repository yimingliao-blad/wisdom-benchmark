# Phase 2 datasets — where the data comes from

Phase 1's `docs/DATASETS.md` covers the six capability benchmarks. This file covers the two
forecasting benchmarks used by the OpenRouter harness in `code/openrouter/`.

**Nothing here needs to be done by hand.** `code/openrouter/fetch_data.sh` performs every step below
and verifies it. This document exists so the provenance is readable without running anything, and so
the runs can be reconstructed if a source ever disappears.

---

## 1. FutureX-Past

| | |
|---|---|
| **Hugging Face** | [`futurex-ai/Futurex-Past`](https://huggingface.co/datasets/futurex-ai/Futurex-Past) |
| **File** | `data/train-00000-of-00001.parquet` |
| **Pinned revision** | `3c2e39690de35eb1fcc621251f56343c72bae8c4` |
| **sha256 of that file** | `55ecf4f11909d412d515eeeab5b5891012adde4ff4353d35204179728704ad50` |
| **Size at that revision** | 252,921 bytes |
| **Licence** | **Apache-2.0** — no restriction on redistribution or commercial use |
| **Rows** | 1,118 |
| **Columns** | `id`, `prompt`, `end_time`, `level`, `title`, `ground_truth` |

Direct download of the exact bytes used:

```
https://huggingface.co/datasets/futurex-ai/Futurex-Past/resolve/3c2e39690de35eb1fcc621251f56343c72bae8c4/data/train-00000-of-00001.parquet
```

### ⚠ This dataset changed upstream after our runs

As of 2026-08-11 the current revision's parquet is **257,915 bytes** — ours was **252,921**. The pool
is not the one we sampled. **Always fetch the pinned revision above**, or the 110-item draw will not
reproduce and new calls will not be comparable to the records in `results/openrouter/`.

### How the 110-item corpus is derived

`code/openrouter/build_futurex_corpus.py`, seed **`20260808`**:

1. Build the pool as `item_id = f"{id}|{end_time}"`, carrying `prompt` **byte-for-byte** from the
   dataset's own column — the prompt is never rebuilt or reworded.
2. **Filter to post-anchor items first**, then draw. The contamination anchor is
   **`2026-02-16`** (`item_validate.ANCHOR`): an item must resolve *after* it, or a model may already
   know the answer from pre-training.
3. Draw **110** items — 100 target plus 10 spares for the expected 3–6% unit loss.

The order matters. An earlier ad-hoc draw filtered *after* drawing and shipped 11 pre-anchor items;
the validator caught it and halted the paid run before a single call was bought. That is why the draw
lives in a script with the filter built in.

Result: `runs/fx_items_110.json`, sha256 begins `14b03da5a8d2d892b756`.

---

## 2. BTF-3 — *Bench to the Future 3*

| | |
|---|---|
| **Hugging Face** | [`BTF-2/BTF-3`](https://huggingface.co/datasets/BTF-2/BTF-3) |
| **File** | `btf3_binary_questions_and_forecasts.parquet` (the `binary` config) |
| **Pinned revision** | `ad5a2165eea26a8a43592ba36ff15765199ddc71` |
| **sha256 of that file** | `50f01603ae5284e48b462ae8855a4b5e8c82004fd07f4a3c818c0e88e9b91c2b` |
| **Licence** | **CC-BY-NC-4.0** — attribution required, **non-commercial use only** |
| **Rows** | 1,515 resolved binary questions |

Direct download of the exact bytes used:

```
https://huggingface.co/datasets/BTF-2/BTF-3/resolve/ad5a2165eea26a8a43592ba36ff15765199ddc71/btf3_binary_questions_and_forecasts.parquet
```

Unchanged upstream as of 2026-08-11 — the repository HEAD is still `ad5a216`.

The dataset also ships `btf3_numeric_questions_and_forecasts.parquet` and a **703 MB**
`scraped_pages` corpus. **Neither is used here** and `fetch_data.sh` does not download them.

### Licence obligation, stated plainly

CC-BY-NC-4.0 lets you copy and redistribute the material with attribution, **for non-commercial
purposes**. If you use BTF-3 through this repository, that restriction travels with it — it applies
to the dataset, not to this repository's own code, which carries no such term.

### How the 110-item corpus is derived

`code/openrouter/build_btf3_corpus.py`, seed **`20260808`**:

1. Render only `question`, `background` and `resolution_criteria`. The resolution itself is never
   rendered — `item_validate` has an `outcome_leaked` rule that halts if it appears.
2. Stratify on what the analysis actually needs: **outcome × field-length tertile**, giving six
   strata `o{0,1}-L{0,1,2}`. Tertile cuts fall at 3,408 and 4,101 field-chars.
3. Draw 110 with a **balance gate at tolerance 0.1** — the draw's stratum proportions must track the
   pool's, or the build halts rather than handing the study a skewed slice.
4. The 3,000-char field cap used by the earlier `build_btf3_sample.py` is **deliberately dropped**;
   prompt lengths here run 4,888–13,040 chars.

Result: `runs/btf3_items_110.json`, sha256 begins `1bab93361f198e53ee5d`.

---

## 3. `fx_smoke4.json` — the 4-item wiring fixture

Four FutureX items used by the offline wiring tests. Drawn from the **raw** pool *before* the
contamination filter existed, so it is not a subset of the 110. It is rebuilt deterministically by
explicit `item_id`:

```
69a6d48ee78a390068a18729|2026-04-02      cbc2fddf28ccc5687af1bcd3|2026-06-17
8b7d371b8e8e2c1967c91f3b|2026-07-11      c893e45534964d90d095abcc|2026-06-23
```

Serialised with `json.dump(..., indent=1)` — that is what reproduces the fixture byte-for-byte.
Result sha256 begins `e0af581a415e90d95cc6`.

---

## 4. Why these are fetched rather than committed

Not a licensing bar. To be accurate about it:

- **FutureX-Past is Apache-2.0** — it could be committed with no restriction whatsoever.
- **BTF-3 is CC-BY-NC-4.0**, which *permits* redistribution with attribution; it restricts
  **commercial use**, not copying. The binary parquet is 6.2 MB and could be committed with an
  attribution and non-commercial notice.

They are fetched because:

1. **The phase-1 policy already works this way** (`code/download_data.sh`), and consistency is worth
   more than saving one command.
2. **A pinned fetch is stronger than a copy.** It records *which* upstream revision the results came
   from and verifies it, which is how the FutureX upstream change was noticed at all. A committed
   copy would have silently diverged from its source with nothing to compare against.
3. **Repo weight** — the datasets plus their aux corpora are far larger than the results.

If you would rather have them committed, both may be: FutureX freely, BTF-3 with attribution and a
non-commercial notice. That is a choice, not a constraint.

**Our own run output is committed** — every scored row, gzipped, under `results/openrouter/`. Those
are our observations, not third-party data.

---

## 5. Attribution

- **FutureX-Past** — `futurex-ai/Futurex-Past`, Apache-2.0.
- **BTF-3 (Bench to the Future 3)** — `BTF-2/BTF-3`, CC-BY-NC-4.0. Non-commercial use only.
