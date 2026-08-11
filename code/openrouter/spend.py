"""M6-T9 (L-$) — the spend state machine: price snapshot, ledger, reconciliation, hard stop.

PLAIN ENGLISH: keep an honest running total of what the run has actually cost, keyed to the same
identity as the records, and stop dead when it hits the ceiling.

THE FACT THAT SHAPES THIS WHOLE MODULE: `max_tokens` is NOT a cost bound. Five providers exceed it,
worst observed 98,349 billed tokens against a 4,000 cap -- 24.6x. So a pre-call ESTIMATE from
max_tokens cannot be trusted as a limit; it is a planning number only. The ceiling is enforced on
ACTUAL REPORTED spend, and the gap between estimate and actual is measured rather than assumed.

KEYED TO THE SAME IDENTITY AS THE RECORDS (audit-3 D6). The ledger keys on attempt_id
(unit_id : attempt_no : kind), not on a separate counter. A spend ledger with its own identity space
can double-charge on resume, or reconcile against the wrong attempt, and nothing would disagree.

Offline. No network. No spend.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manifest as MF  # noqa: E402


class SpendError(RuntimeError):
    """Raised when the ceiling is reached or the ledger cannot be trusted. Never a return value."""


def price_snapshot(roster):
    """Freeze prices BEFORE the run. Prices can change under a long run; a total computed from
    today's prices and yesterday's calls is neither."""
    missing = [m["id"] for m in roster if m.get("in") is None or m.get("out") is None]
    if missing:
        raise SpendError(f"no price on file for {missing}. Refusing to start a paid run with an "
                         f"unpriceable model -- the ceiling could not be enforced for it.")
    return {m["id"]: {"in": float(m["in"]), "out": float(m["out"])} for m in roster}


def estimate_max(prices, model, max_tokens, prompt_tokens_guess=400):
    """A PLANNING number, never a limit.

    Deliberately named `estimate_max` rather than `max_cost`: with providers that ignore max_tokens
    this is not an upper bound on anything. It exists to project a run's cost, not to gate it.
    """
    p = prices[model]
    return prompt_tokens_guess / 1e6 * p["in"] + max_tokens / 1e6 * p["out"]


class Ledger:
    """Actual spend, per attempt, with a hard ceiling.

    The ceiling is checked and the charge recorded UNDER ONE LOCK by the caller; this class is the
    accounting, not the concurrency. `charge` is idempotent per attempt_id so a resumed run cannot
    pay twice for the same attempt.
    """

    def __init__(self, ceiling, prices=None, journal=None):
        if ceiling is None or ceiling <= 0:
            raise SpendError("a paid run requires a positive spend ceiling")
        self.ceiling = float(ceiling)
        self.prices = prices or {}
        self.entries = {}          # attempt_id -> {model, unit_id, actual, estimated}
        self.halted = False
        # CRASH DURABILITY (Codex C1). A ledger written only at the end of the run is absent or
        # stale if the process dies after paid calls: records exist, resume skips them, and the
        # spend already made is invisible to the ceiling. The journal is appended ON EACH CHARGE, so
        # the worst loss is the in-flight attempt -- the same granularity as the records file.
        # Append-only rather than rewriting the whole ledger: at 3,700 attempts a full rewrite per
        # charge is quadratic, and a partial rewrite loses everything.
        self.journal = journal
        self._jfh = None
        if journal:
            self._jfh = open(journal, "a", buffering=1)

    @property
    def total(self):
        return round(sum(e["actual"] for e in self.entries.values()), 8)

    def remaining(self):
        return round(self.ceiling - self.total, 8)

    def would_exceed(self, estimated):
        return (self.total + max(0.0, estimated)) > self.ceiling

    def check_before(self, estimated=0.0):
        """Called BEFORE a call. Raises rather than returning False: a spend check that can be
        ignored is not a ceiling."""
        if self.halted:
            raise SpendError(f"ledger already halted at ${self.total:.4f}")
        if self.total >= self.ceiling:
            self.halted = True
            raise SpendError(f"spend ceiling reached: ${self.total:.4f} of ${self.ceiling:.2f}")
        return True

    def charge(self, attempt_id, model, actual, estimated=None, unit_id=None):
        """Record ACTUAL reported spend. Idempotent per attempt_id (audit D6: resume must not
        double-charge). Returns the entry."""
        if attempt_id in self.entries:
            return self.entries[attempt_id]                 # already paid for; not paid twice
        if actual is None or actual < 0:
            raise SpendError(f"attempt {attempt_id}: actual spend must be a non-negative number, "
                             f"got {actual!r} -- an unknown cost cannot be reconciled")
        e = {"attempt_id": attempt_id, "unit_id": unit_id, "model": model,
             "actual": float(actual), "estimated": estimated}
        self.entries[attempt_id] = e
        if self._jfh is not None:
            self._jfh.write(json.dumps(e) + "\n")      # durable BEFORE the caller continues
            os.fsync(self._jfh.fileno())
        if self.total >= self.ceiling:
            self.halted = True
        return e

    def close(self):
        if self._jfh is not None:
            self._jfh.close()
            self._jfh = None

    def reconcile(self):
        """How far the planning estimates were from reality -- MEASURED, per model.

        This is where the max_tokens lie becomes visible: a provider that ignores the cap shows a
        ratio far above 1.
        """
        by = collections.defaultdict(lambda: {"n": 0, "actual": 0.0, "estimated": 0.0})
        for e in self.entries.values():
            b = by[e["model"]]
            b["n"] += 1
            b["actual"] += e["actual"]
            if e["estimated"]:
                b["estimated"] += e["estimated"]
        out = {}
        for m, b in by.items():
            out[m] = {**b, "ratio": round(b["actual"] / b["estimated"], 3) if b["estimated"] else None}
        return {"total": self.total, "ceiling": self.ceiling, "remaining": self.remaining(),
                "by_model": out, "n_attempts": len(self.entries), "halted": self.halted}

    def save(self, path):
        json.dump({"ceiling": self.ceiling, "total": self.total, "halted": self.halted,
                   "entries": list(self.entries.values())}, open(path, "w"), indent=1)
        return path

    @classmethod
    def load(cls, path, ceiling=None, journal=None):
        """Resume the LEDGER, not just the records. A run that resumes its work but not its spend
        starts counting from zero and can spend the ceiling twice.

        The JOURNAL WINS over the summary file (Codex C1). If the run died before writing
        ledger.json, the journal is the only record of what was actually paid for; taking the
        summary would understate the spend by exactly the amount at risk.
        """
        d = json.load(open(path)) if path and os.path.exists(path) else {"ceiling": ceiling,
                                                                         "entries": []}
        led = cls(ceiling if ceiling is not None else d["ceiling"], journal=journal)
        for e in d["entries"]:
            led.entries[e["attempt_id"]] = e
        n_summary = len(led.entries)
        if journal and os.path.exists(journal):
            for line in open(journal):
                if line.strip():
                    e = json.loads(line)
                    led.entries.setdefault(e["attempt_id"], e)
        led.recovered_from_journal = len(led.entries) - n_summary
        if led.total >= led.ceiling:
            led.halted = True
        return led

    @classmethod
    def rebuild_from_journal(cls, journal, ceiling):
        """The recovery path when no summary exists at all -- a run killed mid-flight."""
        if not os.path.exists(journal):
            raise SpendError(f"no ledger journal at {journal}: the spend of a crashed run cannot be "
                             f"reconstructed, and resuming would spend the ceiling twice")
        led = cls(ceiling)
        for line in open(journal):
            if line.strip():
                e = json.loads(line)
                led.entries.setdefault(e["attempt_id"], e)
        if led.total >= led.ceiling:
            led.halted = True
        return led


def attempt_for(record, attempt_no=1, kind="first"):
    """The ledger's key IS the record's identity (audit D6) -- one identity space, not two."""
    uid = MF.unit_id(record.get("model"), record.get("item_id"), record.get("arm"))
    return MF.attempt_id(uid, attempt_no, kind), uid
