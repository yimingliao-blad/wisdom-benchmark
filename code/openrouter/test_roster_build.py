"""Roster construction from a model list."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RB_PATH = os.path.join(HERE, "survey", "roster_build.py")
_spec = importlib.util.spec_from_file_location("roster_build", RB_PATH)
RB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RB)

# A catalog fixture written here, so the tests never depend on the live service or on today's prices.
CATALOG = {"data": [
    {"id": "vendor-a/model-1", "name": "VendorA: Model 1", "created": 1745875945,
     "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
     "top_provider": {"max_completion_tokens": 8192}, "context_length": 131072,
     "hugging_face_id": "VendorA/Model-1", "knowledge_cutoff": "2025-03-31"},
    {"id": "vendor-a/model-2", "name": "VendorA: Model 2", "created": 1745875945,
     "pricing": {"prompt": "0.000002", "completion": "0.000008"},
     "top_provider": {"max_completion_tokens": None}, "context_length": 200000,
     "hugging_face_id": "", "knowledge_cutoff": None},           # closed, no published cutoff
    {"id": "vendor-b/model-3", "name": "Model 3", "created": None,
     "pricing": {"prompt": "0.0000005", "completion": "0.0000005"},
     "top_provider": {}, "context_length": None,                  # no ceiling derivable at all
     "hugging_face_id": None, "knowledge_cutoff": None},
    {"id": "vendor-b/model-4", "name": "VendorB: Model 4", "created": 1745875945,
     "pricing": {}, "top_provider": {"max_completion_tokens": 4096},
     "context_length": 4096, "hugging_face_id": None},            # no price
]}


def write(tmp, name, text):
    p = os.path.join(tmp, name)
    open(p, "w", encoding="utf-8").write(text)
    return p


class NamesInARosterOut(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cat = write(self.tmp, "catalog.json", json.dumps(CATALOG))

    def run_build(self, models_text, overrides=None, anchor=None):
        argv = ["roster_build", "--models", write(self.tmp, "m.txt", models_text),
                "--catalog-cache", self.cat, "--out", os.path.join(self.tmp, "r.json")]
        if overrides:
            argv += ["--overrides", write(self.tmp, "o.json", json.dumps(overrides))]
        if anchor:
            argv += ["--anchor", anchor]
        old = sys.argv
        sys.argv = argv
        try:
            RB.main()
        finally:
            sys.argv = old
        return json.load(open(os.path.join(self.tmp, "r.json")))

    def test_a_bare_list_of_names_produces_a_usable_roster(self):
        r = self.run_build("vendor-a/model-1\nvendor-a/model-2\n")
        self.assertEqual([x["id"] for x in r], ["vendor-a/model-1", "vendor-a/model-2"])
        one = r[0]
        self.assertEqual((one["in"], one["out"]), (0.1, 0.4))     # per MILLION, from the catalog
        self.assertEqual(one["cap"], 8192)                        # max_completion_tokens
        self.assertEqual(one["weights"], "open")                  # hugging_face_id present
        self.assertEqual(one["cutoff"], "2025-03-31")
        self.assertEqual(one["basis"], "PUB-CATALOG")

    def test_the_ceiling_falls_back_to_context_length(self):
        self.assertEqual(self.run_build("vendor-a/model-2\n")[0]["cap"], 200000)

    def test_every_field_names_its_own_source(self):
        row = self.run_build("vendor-a/model-1\n")[0]
        for f in ("in", "out", "cap", "release", "weights", "cutoff", "series"):
            self.assertIn(f, row["field_sources"], f)
        self.assertTrue(row["field_sources"]["in"].startswith("catalog:"))

    def test_an_unknown_name_HALTS_and_suggests(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-a/model-11\n")
        self.assertIn("not served by OpenRouter", str(cm.exception))
        self.assertIn("vendor-a/model-1", str(cm.exception))      # the near-match hint

    def test_a_model_with_no_derivable_ceiling_HALTS(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-b/model-3\n")
        self.assertIn("no ceiling to escalate", str(cm.exception))

    def test_a_model_with_no_price_HALTS(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-b/model-4\n")
        self.assertIn("no usable price", str(cm.exception))

    def test_a_repeated_name_HALTS(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-a/model-1\nvendor-a/model-1\n")
        self.assertIn("repeats", str(cm.exception))

    def test_an_unpublished_cutoff_stays_NULL_and_is_never_guessed(self):
        row = self.run_build("vendor-a/model-2\n")[0]
        self.assertIsNone(row["cutoff"])
        self.assertEqual(row["basis"], "UNKNOWN")
        self.assertIsNotNone(row["release"])

    def test_the_anchor_REFUSES_an_unknown_cutoff(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-a/model-2\n", anchor="2026-02-16")
        self.assertIn("cutoff UNKNOWN", str(cm.exception))

    def test_the_anchor_REFUSES_a_cutoff_after_it(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-a/model-1\n", anchor="2024-01-01")
        self.assertIn("AFTER the anchor", str(cm.exception))

    def test_a_declared_cutoff_satisfies_the_anchor_and_is_labelled_declared(self):
        row = self.run_build("vendor-a/model-2\n", anchor="2026-02-16", overrides={
            "vendor-a/model-2": {"cutoff": "2025-06", "why": "vendor blog, not in the catalog"}})[0]
        self.assertEqual(row["cutoff"], "2025-06")
        self.assertEqual(row["basis"], "DECLARED")
        self.assertIn("vendor blog", row["field_sources"]["cutoff"])

    def test_an_override_with_no_WHY_is_refused(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-a/model-1\n",
                           overrides={"vendor-a/model-1": {"cutoff": "2020-01"}})
        self.assertIn("no 'why'", str(cm.exception))

    def test_an_override_for_a_model_not_in_the_list_is_refused(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-a/model-1\n",
                           overrides={"vendor-a/model-2": {"cutoff": "2020-01", "why": "x"}})
        self.assertIn("not in the list", str(cm.exception))

    def test_an_unknown_override_FIELD_is_refused(self):
        with self.assertRaises(RB.RosterError) as cm:
            self.run_build("vendor-a/model-1\n",
                           overrides={"vendor-a/model-1": {"colour": "blue", "why": "x"}})
        self.assertIn("not an overridable field", str(cm.exception))

    def test_the_family_column_groups_variants(self):
        r = self.run_build("vendor-a/model-1 | Fam X\nvendor-a/model-2 | Fam X\n")
        self.assertEqual({x["series"] for x in r}, {"Fam X"})
        self.assertEqual(r[0]["field_sources"]["series"], "declared in the model list")

    def test_comments_and_blank_lines_are_ignored(self):
        r = self.run_build("# a comment\n\nvendor-a/model-1   # trailing\n\n")
        self.assertEqual([x["id"] for x in r], ["vendor-a/model-1"])


class NoModelNameIsBakedIntoThePipeline(unittest.TestCase):

    # A real OpenRouter id: vendor/slug where the vendor is a known publisher.
    PATTERN = re.compile(
        r'["\'](?:anthropic|openai|google|meta-llama|qwen|deepseek|mistralai|z-ai|nvidia|'
        r'moonshotai|minimax|x-ai|microsoft|cohere|ai21|perplexity)/[a-z0-9][a-z0-9._-]*["\']')
    # Files whose PURPOSE is a specific model list or a recorded historical investigation.
    # roster_build.py's docstring shows two example lines of a model list; nothing else in the
    # tree -- including survey/ -- may name a model. The old survey/build_roster_25.py carried 25
    # ids as a source literal and was deleted, which is what made scanning survey/ possible.
    ALLOWED = {"survey/roster_build.py"}

    def test_no_pipeline_module_contains_a_model_id(self):
        offenders = {}
        for root, dirs, files in os.walk(HERE):
            dirs[:] = [d for d in dirs if d not in
                       {"repos", "runs", "__pycache__", ".git"}]
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                rel = os.path.relpath(p, HERE)
                if rel in self.ALLOWED:
                    continue
                hits = self.PATTERN.findall(open(p, encoding="utf-8").read())
                if hits:
                    offenders[rel] = sorted(set(hits))
        self.assertEqual(offenders, {},
                         "a model id in the pipeline couples the code to one roster; put the name "
                         "in a model-list file and let survey/roster_build.py derive the rest")

    def test_the_scanner_would_CATCH_a_planted_id(self):
        bait = 'M = "' + "anthropic" + "/" + 'claude-haiku-4.5"\n'
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.py")
            with open(p, "w") as fh:
                fh.write(bait)
            with open(p) as fh:
                self.assertTrue(self.PATTERN.findall(fh.read()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
