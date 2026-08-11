"""M6-T13 (L-R) — the provenance bundle: what a published number is BOUND to.

PLAIN ENGLISH: tie the result to everything that produced it, so the table can be reproduced or
audited later, after the roster, the prompts or the code have moved on.

WHAT IT IS AND IS NOT (audit E2, which corrected my first version). The bundle is the immutable
PUBLICATION UNIT -- a binding index that proves which artifacts and code produced a table. It is NOT
a semantic authority: on conflict the MANIFEST wins on planned units and the RECORDS win on observed
evidence. Getting that backwards would create a second source of truth, which is the defect the
authority hierarchy exists to prevent.

E8: the bundle includes the ANALYSIS TABLE ITSELF, hashed. Binding only the inputs makes a result
reproducible in principle but not actually bound to the artifact that was published.

Offline. No network. No spend.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class ProvenanceError(RuntimeError):
    """Raised when a bundle would be incomplete. A partial bundle is worse than none: it looks
    authoritative and is not."""


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _sha_obj(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]


# every module whose behaviour can change a NUMBER in the table
CODE_FILES = ["run_openrouter.py", "completeness_review.py", "bench_formats.py", "manifest.py",
              "schedule.py", "claim_gate.py", "item_validate.py", "response_schema.py",
              "persistence.py", "spend.py", "analyze.py", "finalize.py"]

# Codex C9: provenance.py cannot change a number, but it decides WHICH MISMATCHES ARE DETECTED --
# a weakened verify() would silently stop catching the edits this bundle exists to catch. It is
# recorded separately rather than folded into CODE_FILES, because "the code that computed the
# result" and "the code that checks the result" are different claims and should not be conflated.
VERIFIER_FILES = ["provenance.py"]


def git_state(root=None):
    """Recorded, never trusted to be clean. A dirty tree is a fact about the run, not an error."""
    root = root or os.path.join(HERE, "..", "..", "..")
    try:
        rev = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15)
        st = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                            capture_output=True, text=True, timeout=15)
        dirty = [l for l in st.stdout.splitlines() if l.strip()]
        return {"head": rev.stdout.strip() or None, "dirty_files": len(dirty),
                "clean": len(dirty) == 0}
    except Exception as e:
        return {"head": None, "error": f"{type(e).__name__}: {e}", "clean": None}


def build(manifest, schedule, table, records_path, raw_path=None, ledger=None,
          censored=(), notes=None):
    """Bind a published table to everything that produced it.

    Missing REQUIRED pieces raise: a bundle that silently omits the records it summarises would
    assert reproducibility it cannot support.
    """
    for name, obj in (("manifest", manifest), ("schedule", schedule), ("table", table)):
        if not obj:
            raise ProvenanceError(f"a bundle requires the {name}; refusing to publish a partial one")
    if not os.path.exists(records_path):
        raise ProvenanceError(f"records not found at {records_path}")
    if manifest["manifest_id"] != schedule["manifest_id"]:
        raise ProvenanceError(
            f"schedule {schedule['schedule_id']} was built for manifest "
            f"{schedule['manifest_id']}, not {manifest['manifest_id']} -- these did not run together")
    if table.get("manifest_id") != manifest["manifest_id"]:
        raise ProvenanceError(
            f"the table was computed against manifest {table.get('manifest_id')}, not "
            f"{manifest['manifest_id']} -- binding them would assert a link that does not exist")

    code, verifier = {}, {}
    for group, target in ((CODE_FILES, code), (VERIFIER_FILES, verifier)):
        for f in group:
            p = os.path.join(HERE, f)
            if not os.path.exists(p):
                raise ProvenanceError(f"code file {f} is missing; the bundle cannot describe the run")
            target[f] = _sha_file(p)

    b = {"bundle_version": "prov-v1",
         "authority_note": ("BINDING INDEX, not a semantic authority: on conflict the MANIFEST wins "
                            "on planned units and the RECORDS win on observed evidence."),
         "manifest_id": manifest["manifest_id"], "schedule_id": schedule["schedule_id"],
         "n_planned": manifest["n_units"],
         "roster_hash": manifest["roster_hash"], "items_hash": manifest["items_hash"],
         "records_path": os.path.basename(records_path), "records_sha": _sha_file(records_path),
         "raw_responses_sha": _sha_file(raw_path) if raw_path and os.path.exists(raw_path) else None,
         "table_sha": _sha_obj(table),                       # E8: the OUTPUT is bound too
         "table_totals": table.get("totals"),
         "ledger": (ledger.reconcile() if hasattr(ledger, "reconcile") else ledger),
         "n_censored": len(censored),
         "code_sha": code, "code_bundle_sha": _sha_obj(code),
         "verifier_sha": verifier,
         "git": git_state(), "notes": notes}
    b["bundle_id"] = _sha_obj({k: b[k] for k in
                               ("manifest_id", "schedule_id", "records_sha", "table_sha",
                                "code_bundle_sha")})
    return b


def verify(bundle, table=None, records_path=None):
    """Re-derive the hashes and report every mismatch. Silence here would defeat the whole point."""
    bad = []
    if table is not None and _sha_obj(table) != bundle["table_sha"]:
        bad.append("table_sha: the published table is not the one this bundle binds")
    if records_path and os.path.exists(records_path):
        if _sha_file(records_path) != bundle["records_sha"]:
            bad.append("records_sha: the records file changed after the bundle was written")
    for label, group in (("code_sha", bundle.get("code_sha") or {}),
                         ("verifier_sha", bundle.get("verifier_sha") or {})):
        for f, sha in group.items():
            p = os.path.join(HERE, f)
            if not os.path.exists(p):
                bad.append(f"{label}: {f} no longer exists")
            elif _sha_file(p) != sha:
                bad.append(f"{label}: {f} changed since the run")
    return {"ok": not bad, "mismatches": bad}


def save(bundle, path):
    if os.path.exists(path):
        raise ProvenanceError(f"{path} exists -- a bundle is WRITE-ONCE")
    json.dump(bundle, open(path, "w"), indent=1)
    return path
