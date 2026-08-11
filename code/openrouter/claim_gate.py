"""M6-T1/S2 — the CLAIM ADMISSIBILITY GATE.

PLAIN ENGLISH: a gate that stops an analysis claim being computed over records that structurally
cannot support it.

THE FAILURE IT PREVENTS. Ask "how often does a natural truncation occur?" across the whole stored
corpus and you get "none found" -- but 417 records have no `finish_reason` at all, so they could
never have shown one. Absence of evidence read as evidence of absence, reported as a rate.

WHY A GATE OVER CLAIMS, NOT A LABEL ON RECORDS (Codex gate-4 finding 5). Labelling records once does
not stop the NEXT query forgetting. The enforcement has to sit where the claim is constructed, so a
claim cannot be evaluated without first declaring what it needs.

FAIL-LOUD DESIGN, four rules:
  1. a claim with NO declared requirement is an ERROR, never a permissive default -- silence is how
     a claim ends up computed over everything;
  2. a field PRESENT BUT NULL/EMPTY counts as MISSING -- `finish_reason: null` proves nothing;
  3. the gate RETURNS the rejected set; it never silently filters, so the caller must see the loss;
  4. an admissible set of ZERO halts -- a claim with no evidence is not a finding.

Offline. No network. No spend.
"""
import collections
import json
import os


class ClaimError(RuntimeError):
    """Raised when a claim is malformed or has no admissible evidence. Never returned as a value."""


def field_present(rec, field):
    """Present AND non-empty. Rule 2: a null or empty field is MISSING, not present."""
    v = rec.get(field, None)
    if v is None:
        return False
    if isinstance(v, (str, list, dict)) and len(v) == 0:
        return False
    return True


class Claim:
    """A question, plus the record fields answering it REQUIRES.

    >>> c = Claim("natural truncation rate", requires=["finish_reason", "text"])
    >>> r = c.admit(records)
    >>> r.admitted_n, r.rejected_n, r.missing_field_counts
    """

    def __init__(self, name, requires, note=None):
        if not name or not str(name).strip():
            raise ClaimError("a claim must be named -- an anonymous claim cannot be audited")
        # Rule 1: no requirement is an ERROR, not "admit everything"
        if not requires:
            raise ClaimError(
                f"claim {name!r} declares NO required fields. That is not a permissive default: a "
                f"claim must state what evidence it needs, or it will silently be computed over "
                f"records that cannot support it.")
        self.name = str(name)
        self.requires = list(requires)
        self.note = note

    def admit(self, records):
        admitted, rejected = [], []
        missing = collections.Counter()
        for r in records:
            gaps = [f for f in self.requires if not field_present(r, f)]
            if gaps:
                rejected.append((r, gaps))
                for g in gaps:
                    missing[g] += 1
            else:
                admitted.append(r)
        res = ClaimResult(self, admitted, rejected, dict(missing), len(records))
        # Rule 4: no evidence is not a finding
        if not admitted:
            raise ClaimError(
                f"claim {self.name!r} has ZERO admissible records out of {len(records)}: every one "
                f"lacks {sorted(set(self.requires))}. A claim with no evidence is not a finding.")
        return res


class ClaimResult:
    """Both sides of the partition. Rule 3: rejection is DATA returned, never a silent filter."""

    def __init__(self, claim, admitted, rejected, missing_field_counts, considered):
        self.claim = claim
        self.admitted = admitted
        self.rejected = rejected                     # [(record, [missing fields])]
        self.missing_field_counts = missing_field_counts
        self.considered = considered

    admitted_n = property(lambda self: len(self.admitted))
    rejected_n = property(lambda self: len(self.rejected))

    def summary(self):
        return {"claim": self.claim.name, "requires": self.claim.requires,
                "considered": self.considered, "admitted": self.admitted_n,
                "rejected": self.rejected_n,
                "admitted_frac": round(self.admitted_n / self.considered, 4) if self.considered else 0.0,
                "missing_field_counts": self.missing_field_counts,
                "note": self.claim.note}

    def report(self):
        s = self.summary()
        head = (f"  claim {s['claim']!r}: admitted {s['admitted']}/{s['considered']}, "
                f"rejected {s['rejected']}")
        if s["missing_field_counts"]:
            head += "  (missing: " + ", ".join(
                f"{k}x{v}" for k, v in sorted(s["missing_field_counts"].items())) + ")"
        return head

    def rejected_by_field(self, field):
        return [r for r, gaps in self.rejected if field in gaps]


# THE FROZEN CORPUS SNAPSHOT — one definition, used by every pinned COUNT.
#
# load_corpus() globs every run directory, so the corpus GROWS whenever a run happens. Any test that
# pins a COUNT over it breaks on the next run, and the tempting fix -- bump the literal -- destroys
# the pin: a number re-bumped on every failure asserts nothing.
#
# So counts are pinned over this frozen list, while INVARIANTS ("there are no natural truncations",
# "no verdict contradicts its record") are asserted over the WHOLE corpus including future runs,
# because that is where a first counter-example would appear.
#
# This lived in test_corpus_mining first and was NOT shared; test_persistence then broke the same
# way on the next run. Same class of bug as two copies of one regex drifting apart -- so there is
# one definition here and no second copy.
SNAPSHOT_RUNS = ("or_futurex_glm45", "or_futurex_M5", "or_futurex_M5_halted_oldsemantics",
                 "or_futurex_M5_run2_oldreader", "or_futurex_M5_run3_prefix_codexfindings",
                 "or_futurex_smoke35", "or_futurex_smoke35_r1", "or_futurex_smoke35_v2",
                 "or_futurex_smoke_budget2000")


def load_snapshot(ok_only=True, root=None):
    """The frozen corpus the pinned counts describe. Never widens as new runs land."""
    root = root or os.path.dirname(os.path.abspath(__file__))
    rows = []
    for d in SNAPSHOT_RUNS:
        rows += load_corpus(root=root, ok_only=ok_only,
                            pattern=os.path.join(root, "runs", d, "records.jsonl"))
    return rows


def load_corpus(root=None, pattern=None, ok_only=True):
    """Read every stored record. Malformed lines are COUNTED and raised, never skipped quietly."""
    import glob
    root = root or os.path.dirname(os.path.abspath(__file__))
    pattern = pattern or os.path.join(root, "runs", "or_futurex_*", "records.jsonl")
    rows, bad = [], 0
    for f in sorted(glob.glob(pattern)):
        for line in open(f):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                bad += 1
    if bad:
        raise ClaimError(f"{bad} malformed line(s) in the corpus -- refusing to build claims over a "
                         f"file I cannot fully read")
    return [r for r in rows if r.get("ok") is True] if ok_only else rows
