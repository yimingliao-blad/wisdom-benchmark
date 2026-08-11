# Testing the phase-2 harness

```bash
cd code/openrouter
./fetch_data.sh                              # downloads the corpora, rebuilds the item files
python3 -m unittest discover -p 'test_*.py'  # 454 tests, offline, no spend
```

**Measured on a simulated fresh clone, 2026-08-11: `Ran 454 tests … FAILED (failures=2)` — 452 pass.**

The 2 that fail are `test_the_plans_scope_block_matches_the_current_roster` and
`test_it_covers_EVERY_arm_not_just_the_one_last_rebuilt`. Both drive `survey/plan_scope.py` against
`../../../plans/openrouter-output-integrity/plan.md`, a planning document in a private repo that is
not part of this project. **They cannot pass here and are not expected to** — `plan_scope.py` is a
dev-tree tool that regenerates a scope block in that plan; it is published for completeness because
`roster_build.py` and the roster data are the interesting half.

Without `fetch_data.sh` the numbers are much worse — `312 ran, 206 passed, 100 errored` — because
most tests read a benchmark corpus or a run directory. Every one of those errors is an absent file,
not a code defect; the harness fails loud on missing data by design.

## What `fetch_data.sh` does

1. **Downloads two corpora, pinned to a commit and sha256-verified.**

   | dataset | source | revision | licence |
   |---|---|---|---|
   | FutureX-Past | `futurex-ai/Futurex-Past` | `3c2e396…` | Apache-2.0 |
   | BTF-3 (binary) | `BTF-2/BTF-3` | `ad5a216…` | **CC-BY-NC-4.0** |

   **The pin is not ceremony.** The FutureX parquet changed upstream after these runs — 252,921 bytes
   when we drew the sample, 257,915 as of 2026-08-11. An unpinned fetch gives a different pool and
   therefore a different 110-item draw, which would not correspond to the published records. The
   script halts on any sha256 mismatch rather than continuing with the wrong data.

2. **Rebuilds the item corpora** with the seeded draws (`DRAW_SEED = 20260808`) and the contamination
   filter, via `build_futurex_corpus.py` and `build_btf3_corpus.py`. BTF-3's draw prints its
   stratum-balance gate; FutureX filters to post-anchor items *before* drawing.

3. **Restores the run directories** by decompressing `results/openrouter/*/records.jsonl.gz` — those
   are our own outputs and *are* committed, so no download is needed for them.

4. **Verifies the rebuild is byte-identical** to the corpora the published records were bought
   against, by sha256:

   ```
   OK   runs/fx_items_110.json    14b03da5a8d2d892b756
   OK   runs/btf3_items_110.json  1bab93361f198e53ee5d
   OK   runs/fx_smoke4.json       e0af581a415e90d95cc6
   ```

   If any differs the script **halts** and says not to compare new calls against the published data.
   This check earned its place during development: it caught a rebuilt fixture that parsed equal but
   serialised differently, which would have produced a subtly different file.

## Why the corpora are not committed

Third-party and variously licensed — **BTF-3 is CC-BY-NC-4.0** — and the item files contain the
benchmark prompts with their ground truth. Same policy as phase 1's `code/download_data.sh`.
Our own run output *is* committed, gzipped, under `results/openrouter/`.

## Requirements

`curl`, `python3`, `pandas`, `pyarrow`. No Hugging Face account or token: both datasets are public
and are fetched over plain HTTPS from the pinned revision.
