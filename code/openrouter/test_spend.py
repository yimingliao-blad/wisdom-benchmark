"""Spend accounting."""
import json
import os
import tempfile
import unittest

import manifest as MF
import spend as SP

ROSTER = [{"id": "a/one", "in": 1.0, "out": 2.0}, {"id": "b/two", "in": 0.5, "out": 1.0}]


class PricesAreFrozenFirst(unittest.TestCase):
    def test_a_snapshot_is_taken_before_the_run(self):
        p = SP.price_snapshot(ROSTER)
        self.assertEqual(p["a/one"]["out"], 2.0)

    def test_an_unpriceable_model_refuses_to_start(self):
        with self.assertRaises(SP.SpendError) as cm:
            SP.price_snapshot(ROSTER + [{"id": "c/three", "in": None, "out": None}])
        self.assertIn("c/three", str(cm.exception))


class TheCeilingIsEnforcedOnACTUALSpend(unittest.TestCase):

    def test_the_estimate_is_named_a_planning_number_not_a_limit(self):
        p = SP.price_snapshot(ROSTER)
        est = SP.estimate_max(p, "a/one", 16000)
        self.assertGreater(est, 0)
        # and the real world can exceed it by 24.6x -- so it must never be used as the gate
        led = SP.Ledger(ceiling=1.0)
        led.charge("u:1:first", "a/one", actual=est * 24.6, estimated=est)
        self.assertGreater(led.total, est, "actual spend can far exceed the estimate")

    def test_the_ceiling_halts_the_ledger(self):
        led = SP.Ledger(ceiling=0.10)
        led.charge("u1:1:first", "a/one", actual=0.10)
        self.assertTrue(led.halted)
        with self.assertRaises(SP.SpendError) as cm:
            led.check_before()
        self.assertIn("halted", str(cm.exception))

    def test_check_before_RAISES_rather_than_returning_false(self):
        led = SP.Ledger(ceiling=0.05)
        led.charge("u1:1:first", "a/one", actual=0.06)
        with self.assertRaises(SP.SpendError):
            led.check_before()

    def test_a_zero_or_missing_ceiling_is_refused(self):
        for bad in (0, -1, None):
            with self.assertRaises(SP.SpendError):
                SP.Ledger(ceiling=bad)

    def test_an_unknown_cost_cannot_be_charged(self):
        led = SP.Ledger(ceiling=1.0)
        with self.assertRaises(SP.SpendError) as cm:
            led.charge("u1:1:first", "a/one", actual=None)
        self.assertIn("cannot be reconciled", str(cm.exception))


class ResumeDoesNotDoubleCharge(unittest.TestCase):

    def test_charging_the_same_attempt_twice_is_idempotent(self):
        led = SP.Ledger(ceiling=1.0)
        led.charge("u1:1:first", "a/one", actual=0.10)
        led.charge("u1:1:first", "a/one", actual=0.10)
        self.assertEqual(led.total, 0.10, "the same attempt must not be paid for twice")
        self.assertEqual(len(led.entries), 1)

    def test_a_RETRY_is_a_different_attempt_and_is_charged(self):
        led = SP.Ledger(ceiling=1.0)
        led.charge("u1:1:first", "a/one", actual=0.10)
        led.charge("u1:2:retry", "a/one", actual=0.10)
        self.assertEqual(led.total, 0.20)

    def test_the_ledger_key_IS_the_record_identity(self):
        rec = {"model": "a/one", "item_id": "q1", "arm": "original"}
        aid, uid = SP.attempt_for(rec)
        self.assertEqual(uid, MF.unit_id("a/one", "q1", "original"))
        self.assertTrue(aid.startswith(uid), "one identity space, not two")

    def test_a_resumed_run_reloads_the_ledger_not_just_the_records(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ledger.json")
            led = SP.Ledger(ceiling=1.0)
            led.charge("u1:1:first", "a/one", actual=0.60)
            led.save(p)
            back = SP.Ledger.load(p)
            self.assertEqual(back.total, 0.60)
            self.assertEqual(back.remaining(), 0.40)
            back.charge("u1:1:first", "a/one", actual=0.60)     # the same attempt, after resume
            self.assertEqual(back.total, 0.60, "resume must not re-charge completed attempts")


class ReconciliationMakesTheGapVISIBLE(unittest.TestCase):
    def test_a_provider_that_ignores_max_tokens_shows_a_ratio_far_above_one(self):
        led = SP.Ledger(ceiling=100.0)
        led.charge("u1:1:first", "greedy/model", actual=2.46, estimated=0.10)   # the 24.6x case
        led.charge("u2:1:first", "honest/model", actual=0.10, estimated=0.10)
        r = led.reconcile()
        self.assertAlmostEqual(r["by_model"]["greedy/model"]["ratio"], 24.6, places=1)
        self.assertAlmostEqual(r["by_model"]["honest/model"]["ratio"], 1.0, places=1)

    def test_reconcile_reports_the_running_state(self):
        led = SP.Ledger(ceiling=1.0)
        led.charge("u1:1:first", "a/one", actual=0.25)
        r = led.reconcile()
        self.assertEqual(r["total"], 0.25)
        self.assertEqual(r["remaining"], 0.75)
        self.assertEqual(r["n_attempts"], 1)
        self.assertFalse(r["halted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
