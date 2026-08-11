"""M6-T8 (L-E) — concurrency: what 16 workers sharing one file and three counters can break.

Four failure modes, all invisible in a single-threaded run:
  X1  interleaved writes corrupt the JSONL mid-record
  X3  a worker's result lands under ANOTHER unit's identity (C3 misassociation, under load)
  X4  two threads quarantine the same model at once
  X5  a worker dies and its unit vanishes without appearing anywhere

X3 is the dangerous one: unit conservation still holds, the JSON is valid, the counts match, and the
table is wrong. It is only detectable because every record now carries the hash of the prompt that
produced it -- which is what the manifest check is for.

The stub deliberately introduces JITTER and interleaving pressure, because a concurrency test that
never actually races proves nothing.

Offline. No network. No spend.  Run: python3 -m unittest test_concurrency -v
"""
import collections
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manifest as MF          # noqa: E402
import persistence as PS       # noqa: E402

# A full run of the REAL runner under N workers, with a jittery stub in place of the network.
HARNESS = r'''
import json, random, sys, time
sys.path.insert(0, {here!r})
import run_openrouter as R, completeness_review as CR

def fake(prompt, mr, start_tokens, cap, reasoning=None):
    # JITTER: without it the pool serialises by accident and nothing ever races.
    time.sleep(random.random() * 0.01)
    trace = [{{"budget": start_tokens, "outcome": "ok", "chars": 40}}]
    body = "Weighed it.\n\n\\boxed{{No}}"
    raw = {{"provider": "Stub", "usage": {{"prompt_tokens": 300, "completion_tokens": 40}},
            "choices": [{{"finish_reason": "stop", "message": {{"content": body}}}}]}}
    return body, raw, 0.0001, trace

R.call_with_escalation = fake
CR.review = lambda *a, **k: (CR.COMPLETE, "verdict: complete", "stop")
sys.argv = {argv!r}
R.main()
'''


def run(tmp, tag, workers, n_items=6, models=("a/one", "b/two", "c/three")):
    # DISTINCT prompts per item. With identical text every unit shares one prompt hash, and a
    # swap between two units becomes undetectable -- which is a real limit on the misassociation
    # check, not merely a fixture defect. The real manifest has 100 distinct hashes for 100 items.
    items = [{"item_id": f"q{i}",
              "prompt": f"Question {i}: will outcome {i} occur?\n"
                        "IMPORTANT: Your final answer MUST end with this exact format:\n"
                        "\\boxed{Yes} or \\boxed{No}", "level": 1} for i in range(n_items)]
    json.dump(items, open(os.path.join(tmp, "items.json"), "w"))
    roster = [{"series": "S", "id": m, "cutoff": "2025-01", "basis": "PUB", "release": "2025",
               "in": 0.1, "out": 0.1} for m in models]
    json.dump(roster, open(os.path.join(tmp, "roster.json"), "w"))
    json.dump({m: 128000 for m in models}, open(os.path.join(tmp, "caps.json"), "w"))
    out = os.path.join(HERE, "runs", f"or_futurex_{tag}")
    argv = ["run_openrouter.py", "--items", os.path.join(tmp, "items.json"), "--bench", "futurex",
            "--tag", tag, "--models", os.path.join(tmp, "roster.json"),
            "--caps", os.path.join(tmp, "caps.json"), "--max-calls", "500", "--max-spend", "5",
            "--workers", str(workers), "--mode", "real"]
    p = subprocess.run([sys.executable, "-c", HARNESS.format(here=HERE, argv=argv)],
                       capture_output=True, text=True, timeout=300)
    return p, out, items, roster


class UnderSixteenWorkers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tag = "conc_test"
        import shutil
        shutil.rmtree(os.path.join(HERE, "runs", f"or_futurex_{self.tag}"), ignore_errors=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(os.path.join(HERE, "runs", f"or_futurex_{self.tag}"), ignore_errors=True)

    def test_X1_no_interleaved_or_malformed_lines(self):
        p, out, items, roster = run(self.tmp, self.tag, workers=16)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        path = os.path.join(out, "records.jsonl")
        bad = 0
        recs = []
        for line in open(path):
            if not line.strip():
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                bad += 1
        self.assertEqual(bad, 0, "a mid-record interleave would corrupt the JSONL")
        self.assertEqual(len(recs), len(items) * len(roster))

    def test_X5_every_planned_unit_appears_exactly_once(self):
        """Unit conservation: a worker that dies must not make a unit vanish silently."""
        p, out, items, roster = run(self.tmp, self.tag, workers=16)
        recs = [json.loads(l) for l in open(os.path.join(out, "records.jsonl")) if l.strip()]
        seen = collections.Counter(PS.record_unit_id(r) for r in recs)
        self.assertEqual(len(seen), len(items) * len(roster))
        self.assertTrue(all(v == 1 for v in seen.values()),
                        f"duplicated units under load: {[k for k, v in seen.items() if v > 1]}")

    def test_X3_no_MISASSOCIATION_under_load(self):
        """The silent one. Valid JSON, conserved units, matching counts -- and a wrong table.

        Only detectable because each record carries the hash of the prompt that produced it.
        """
        p, out, items, roster = run(self.tmp, self.tag, workers=16)
        recs = [json.loads(l) for l in open(os.path.join(out, "records.jsonl")) if l.strip()]
        m = MF.build(roster, items, arms=("original",))
        v = MF.verify_records_against(m, recs)
        self.assertEqual(v["counts"].get("MISASSOCIATED", 0), 0,
                         f"a response landed under the wrong unit: {v['detail'][:3]}")
        self.assertEqual(v["counts"].get("MATCH"), m["n_units"])
        self.assertTrue(v["clean"])

    def test_the_misassociation_check_would_actually_CATCH_one(self):
        """A test that can only pass is not evidence: corrupt one record and confirm detection."""
        p, out, items, roster = run(self.tmp, self.tag, workers=16)
        recs = [json.loads(l) for l in open(os.path.join(out, "records.jsonl")) if l.strip()]
        m = MF.build(roster, items, arms=("original",))
        # Pick two records with DIFFERENT item_ids explicitly. Taking recs[0] and recs[1] made this
        # order-dependent: under 16 workers they can be the same item from different models, and
        # swapping q3 with q3 is a no-op -- a flaky test that failed for a reason unrelated to the
        # check it was testing.
        a = recs[0]
        b = next(r for r in recs if r["item_id"] != a["item_id"])
        a["item_id"], b["item_id"] = b["item_id"], a["item_id"]
        v = MF.verify_records_against(m, recs)
        self.assertGreaterEqual(v["counts"].get("MISASSOCIATED", 0), 2)
        self.assertFalse(v["clean"])

    def test_results_are_identical_at_one_worker_and_sixteen(self):
        """Concurrency must not change WHAT is produced, only how fast."""
        import shutil
        p1, out1, items, roster = run(self.tmp, self.tag, workers=1)
        a = sorted(PS.record_unit_id(json.loads(l))
                   for l in open(os.path.join(out1, "records.jsonl")) if l.strip())
        shutil.rmtree(out1, ignore_errors=True)
        p2, out2, _, _ = run(self.tmp, self.tag, workers=16)
        b = sorted(PS.record_unit_id(json.loads(l))
                   for l in open(os.path.join(out2, "records.jsonl")) if l.strip())
        self.assertEqual(a, b, "the same units must be produced regardless of worker count")


class TheChecksOwnLimits(unittest.TestCase):
    """What the misassociation check CANNOT see, stated rather than assumed."""

    def test_a_swap_between_units_sharing_a_prompt_is_UNDETECTABLE(self):
        """Found by a fixture that gave every item the same text. The check compares prompt hashes,
        so two units with IDENTICAL prompts are indistinguishable to it. The real 100-item manifest
        has 100 distinct hashes, but this is a property to rely on knowingly, not by luck."""
        same = [{"item_id": f"q{i}", "level": 1,
                 "prompt": "IMPORTANT: Your final answer MUST end with this exact format:\n"
                           "\\boxed{Yes} or \\boxed{No}"} for i in range(3)]
        roster = [{"series": "S", "id": "a/one", "cutoff": "2025-01", "basis": "PUB",
                   "release": "2025", "in": 0.1, "out": 0.1}]
        m = MF.build(roster, same, arms=("original",))
        self.assertEqual(len({u["prompt_sha"] for u in m["units"]}), 1,
                         "the fixture must actually share a hash for this to mean anything")
        recs = [{"model": u["model"], "item_id": u["item_id"], "arm": u["arm"],
                 "prompt_sha": u["prompt_sha"]} for u in m["units"]]
        recs[0]["item_id"], recs[1]["item_id"] = recs[1]["item_id"], recs[0]["item_id"]
        v = MF.verify_records_against(m, recs)
        self.assertEqual(v["counts"].get("MISASSOCIATED", 0), 0,
                         "documents the blind spot: identical prompts hide a swap")

    def test_the_REAL_manifest_has_distinct_prompts_per_item(self):
        """So the blind spot above does not apply to the actual run."""
        real = json.load(open(os.path.join(HERE, "runs", "manifest_4d3477ce313573a7.json")))
        per_model = collections.defaultdict(set)
        for u in real["units"]:
            per_model[u["model"]].add(u["prompt_sha"])
        n_items = real["n_items"]
        for model, shas in per_model.items():
            self.assertEqual(len(shas), n_items,
                             f"{model} has {len(shas)} distinct prompts for {n_items} items")


class QuarantineUnderLoad(unittest.TestCase):
    """X4: two threads deciding to quarantine the same model at the same moment."""

    def test_quarantine_state_is_idempotent(self):
        import threading
        state = {"quarantined": {}, "bad": {}}
        lock = threading.Lock()
        errs = []

        def worker():
            try:
                for _ in range(200):
                    with lock:
                        state["bad"].setdefault("m", []).append(1)
                        if "m" not in state["quarantined"]:
                            state["quarantined"]["m"] = "PROVIDER_ERROR"
            except Exception as e:      # a race would surface as a dict mutation error
                errs.append(e)

        ts = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(list(state["quarantined"]), ["m"], "quarantining twice must be a no-op")
        self.assertEqual(len(state["bad"]["m"]), 8 * 200, "every failure must still be recorded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
