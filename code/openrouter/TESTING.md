# Testing

```bash
cd code/openrouter
./fetch_data.sh                              # fetch corpora, rebuild the item files
python3 -m unittest discover -p 'test_*.py'
```

452 of 454 pass from a fresh checkout. The two that fail drive `survey/plan_scope.py` against a
document that is not part of this repository, so they cannot pass here.

Without `fetch_data.sh` most tests error on a missing input file: the harness halts on absent data
rather than guessing.

Requirements: `curl`, `python3`, `pandas`, `pyarrow`. No account or token needed — both datasets are
public and fetched over HTTPS from a pinned revision.

Sources and licences: [`docs/DATASETS-phase2.md`](../../docs/DATASETS-phase2.md).
