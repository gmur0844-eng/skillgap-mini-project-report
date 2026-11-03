"""Human-validation package: 48-case stratified subset of the frozen 88, blind export, reviewer independence, agreement,
gold freeze and a discipline-agnostic layout. Works on temporary copies; the real package is only read."""
import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
spec = importlib.util.spec_from_file_location("semantic_validation", ROOT / "scripts/evaluation/semantic_validation.py")
sv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sv)
ATTEST = "test: reviewers confirmed in writing that they answered alone, without AI tools"

BENCH = ROOT / "data/evaluation/semantic_benchmark_v1/benchmark.json"
PKG = ROOT / "data/evaluation/semantic_gold/computer-science-and-engineering/v1"


class Selection(unittest.TestCase):
    def setUp(self):
        self.bench = json.loads(BENCH.read_text())

    def test_48_of_88_deterministic_and_representative(self):
        a, _ = sv.select_subset(self.bench, 48, "seed")
        b, _ = sv.select_subset(self.bench, 48, "seed")
        self.assertEqual([c["benchmark_id"] for c in a], [c["benchmark_id"] for c in b])
        self.assertEqual(len(a), 48)
        self.assertEqual(len({c["benchmark_id"] for c in a}), 48)
        ids = {c["benchmark_id"] for c in self.bench}
        self.assertTrue(all(c["benchmark_id"] in ids for c in a))            # no invented case
        # every class that exists in the benchmark is present; proportions follow the benchmark, not equal counts
        self.assertEqual({c["label"] for c in a}, {c["label"] for c in self.bench})
        kinds = Counter(c["kind"] for c in a)
        full = Counter(c["kind"] for c in self.bench)
        for k, n in full.items():
            self.assertLessEqual(abs(kinds[k] - 48 * n / 88), 1.5, k)
        for tag in ("lexical_collision", "acronym", "hierarchy", "abbreviation", "alias", "paraphrase"):
            self.assertTrue(any(tag in (c.get("tags") or []) for c in a), tag)

    def test_committed_package_matches_the_selection(self):
        man = json.loads((PKG / "MANIFEST.json").read_text())
        subset = json.loads((PKG / "subset.json").read_text())
        chosen, _ = sv.select_subset(self.bench, 48, subset["seed"])
        self.assertEqual(subset["case_ids"], [c["benchmark_id"] for c in chosen])
        self.assertEqual(man["benchmark"]["sha256"], "94b4e79c49bc2c7a0c5bce0234298f9ebada568c1e767ee8651aac19ac3722b7")
        self.assertEqual(man["case_count"], 48)

    def test_blind_export_shows_no_system_output(self):
        rows = list(csv.DictReader((PKG / "blind_export.csv").open(encoding="utf-8")))
        self.assertEqual(len(rows), 48)
        header = " ".join(rows[0].keys()).lower()
        for leak in ("label", "prediction", "qwen", "model", "gold", "expected", "decision", "assistant", "score"):
            self.assertNotIn(leak, header)
        by_id = {c["benchmark_id"]: c for c in self.bench}
        for r in rows:
            self.assertEqual((r["relationship"], r["confidence_1_to_5"], r["rationale"]), ("", "", ""))
            rationale = (by_id[r["case_id"]].get("rationale") or "").strip()
            if len(rationale) > 12:
                self.assertNotIn(rationale, " ".join(r.values()))
        form = (ROOT / "scripts/evaluation/create_semantic_validation_form.gs").read_text()
        for leak in ("DEVELOPMENT_GOLD", "development gold", "V3_VALIDATED", "V3_RAW", "\"rationale\":", "\"label\":"):
            self.assertNotIn(leak, form)

    def test_assistant_adjudication_is_never_human_validation(self):
        adj = json.loads((PKG / "assistant_adjudication.json").read_text())
        self.assertEqual(adj["label_source"], "ASSISTANT_ADJUDICATION")
        self.assertFalse(adj["is_human_validated"])
        self.assertEqual(len(adj["cases"]), 88)
        self.assertFalse(any(p.name.startswith("labels_") for p in (PKG / "labels").glob("*")))


class Workflow(unittest.TestCase):
    """build -> two reviewers -> agreement -> adjudication -> freeze, on a temporary package of another discipline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self._saved = (sv.PACKAGES, sv.GS_FILE)
        sv.PACKAGES, sv.GS_FILE = t / "semantic_gold", t / "form.gs"
        sv.build(SimpleNamespace(discipline="Landscape Architecture", benchmark=str(BENCH), subset=48, seed="s1",
                                 version="v1", reviewers=2, reviewer_role="faculty", force=False))
        self.pkg = sv.PACKAGES / "landscape-architecture" / "v1"
        self.ids = json.loads((self.pkg / "subset.json").read_text())["case_ids"]

    def tearDown(self):
        sv.PACKAGES, sv.GS_FILE = self._saved
        self.tmp.cleanup()

    def _sheet(self, name, labels):
        path = Path(self.tmp.name) / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["case_id", "relationship", "confidence_1_to_5", "rationale"])
            for cid, lab in zip(self.ids, labels):
                w.writerow([cid, lab, 4, ""])
        return path

    def test_any_discipline_gets_the_same_layout(self):
        for f in ("MANIFEST.json", "subset.json", "blind_export.csv", "form_cases.json", "assistant_adjudication.json"):
            self.assertTrue((self.pkg / f).exists(), f)
        self.assertEqual(json.loads((self.pkg / "MANIFEST.json").read_text())["discipline"], "Landscape Architecture")
        src = (ROOT / "scripts/evaluation/semantic_validation.py").read_text()
        for branch in ("Computer Science", "CSE", "Mechanical", "Civil"):
            self.assertFalse(branch in src, f"discipline name {branch!r} in the validation code")

    def test_reviewers_agreement_and_freeze(self):
        a = ["Equivalent concept"] * 24 + ["Unrelated"] * 24
        b = ["Equivalent concept"] * 20 + ["Related concept"] * 4 + ["Unrelated"] * 24
        sv.import_sheet(SimpleNamespace(package=str(self.pkg), file=str(self._sheet("a", a)), reviewer="Reviewer A", attestation=ATTEST))
        sv.import_sheet(SimpleNamespace(package=str(self.pkg), file=str(self._sheet("b", b)), reviewer="Reviewer B", attestation=ATTEST))
        with self.assertRaises(SystemExit):   # label files are immutable
            sv.import_sheet(SimpleNamespace(package=str(self.pkg), file=str(self._sheet("a", a)), reviewer="Reviewer A", attestation=ATTEST))
        with self.assertRaises(SystemExit):   # the assistant or a model is never an independent reviewer
            sv.import_sheet(SimpleNamespace(package=str(self.pkg), file=str(self._sheet("c", a)), reviewer="Claude assistant", attestation=ATTEST))
        sv.agreement_cmd(SimpleNamespace(package=str(self.pkg)))
        ag = json.loads((self.pkg / "agreement.json").read_text())
        self.assertEqual(ag["measure"], "COHEN_KAPPA")
        self.assertEqual(ag["cases_labelled_by_all"], 48)
        self.assertEqual(len(ag["disagreements"]), 4)
        self.assertIn("SAME_CONCEPT", ag["per_class_agreement"])
        self.assertEqual(ag["disagreement_matrix"]["matrix"]["SAME_CONCEPT"]["RELATED"], 4)
        sv.freeze(SimpleNamespace(package=str(self.pkg)))
        gold = json.loads((self.pkg / "semantic_gold_v1.json").read_text())
        self.assertEqual(gold["status_counts"], {"UNANIMOUS": 44, "UNRESOLVED": 4})
        with self.assertRaises(SystemExit):   # frozen
            sv.freeze(SimpleNamespace(package=str(self.pkg)))

    def test_form_import_maps_user_labels_to_codes(self):
        path = Path(self.tmp.name) / "form.csv"
        head = ["Timestamp", "Reviewer ID (name or pseudonym)", "Discipline", "Role", "Relevant experience (years)"]
        for cid in self.ids:
            head += [f"{cid} -- relationship of A to B", f"{cid} -- confidence", f"{cid} -- rationale (optional)"]
        row = ["2026-10-01", "Dr R", "Landscape Architecture", "Faculty", "12"]
        for _ in self.ids:
            row += ["A is more specific", "5", ""]
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([head, row])
        sv.import_form(SimpleNamespace(package=str(self.pkg), csv=str(path), attestation=ATTEST))
        doc = json.loads(next((self.pkg / "labels").glob("labels_*.json")).read_text())
        self.assertEqual({r["label"] for r in doc["labels"]}, {"CHILD"})
        self.assertEqual(doc["label_source"], "INDEPENDENT_HUMAN_REVIEWER")
        self.assertEqual(doc["reviewer_background"]["role"], "Faculty")


class ReviewerForm(unittest.TestCase):
    """The Google Form: the frozen subset exactly, verbatim evidence, reviewer-blind, only a Reviewer ID collected."""

    def setUp(self):
        self.bench = json.loads(BENCH.read_text())
        self.man = json.loads((PKG / "MANIFEST.json").read_text())
        self.subset = json.loads((PKG / "subset.json").read_text())["case_ids"]
        self.cases = sv.form_cases_from_benchmark(self.bench, self.subset)
        self.script = (ROOT / "scripts/evaluation/create_semantic_validation_form.gs").read_text()

    def test_committed_script_is_the_frozen_subset_exactly(self):
        rep = sv.form_integrity(self.bench, self.subset, self.cases, self.man, self.script)
        self.assertEqual(rep["case_count"], 48)
        self.assertEqual((rep["duplicate_ids"], rep["missing_ids"], rep["modified_cases"]), ([], [], []))
        self.assertEqual(rep["case_ids"], self.subset)
        self.assertTrue(rep["order_matches_subset"])
        self.assertEqual(rep["blindness"]["leaks_found"], [])
        self.assertTrue(rep["passed"])
        self.assertIn(sv.cases_sha(self.cases), self.script)
        stored = json.loads((PKG / "form/form_integrity_report.json").read_text())
        self.assertTrue(stored["passed"])
        self.assertEqual(stored["cases_sha256"], sv.cases_sha(self.cases))

    def test_script_is_regenerated_identically(self):
        with tempfile.TemporaryDirectory() as t:
            saved = sv.GS_FILE
            sv.GS_FILE = Path(t) / "form.gs"
            try:
                self.assertEqual(sv.write_gs(self.man, self.cases), self.script)
            finally:
                sv.GS_FILE = saved

    def test_no_label_or_selection_field_reaches_the_form(self):
        for c in self.cases:
            self.assertEqual(set(c), {"n", "case_id", "concept_a", "context_a", "concept_b", "context_b"})
        start = self.script.index("var CASES = ")
        payload = self.script[start:]
        for leak in ("DEVELOPMENT_GOLD", "label_source", "\"label\":", "\"rationale\":", "\"kind\":", "\"tags\":",
                     "hard_case", "Qwen", "qwen", "V3_VALIDATED", "V3_RAW", "gate_v3"):
            self.assertNotIn(leak, payload, leak)

    def test_tampering_is_detected(self):
        bad = json.loads(json.dumps(self.cases))
        bad[3]["context_a"][0]["text"] += " (edited)"
        rep = sv.form_integrity(self.bench, self.subset, bad, self.man)
        self.assertEqual(rep["modified_cases"][0]["case_id"], self.subset[3])
        self.assertFalse(rep["passed"])
        dup = self.cases + [self.cases[0]]
        rep = sv.form_integrity(self.bench, self.subset, dup, self.man)
        self.assertEqual(rep["duplicate_ids"], [self.subset[0]])
        self.assertFalse(rep["passed"])
        rep = sv.form_integrity(self.bench, self.subset + ["bm1-999"], self.cases, self.man)
        self.assertEqual(rep["missing_ids"], ["bm1-999"])
        rep = sv.form_integrity(self.bench, list(reversed(self.subset)), self.cases, self.man)
        self.assertFalse(rep["order_matches_subset"])

    def test_definitions_are_the_project_label_schema(self):
        codes = [code for _, _, code in sv.FORM_CHOICES]
        self.assertEqual(codes, [x["code"] for x in sv.LABEL_SCHEMA["labels"]])
        self.assertEqual([sv.choice_text(l, w) for l, w, _ in sv.FORM_CHOICES],
                         ["A — Same concept", "B — Parent / broader concept", "C — Child / more specific concept",
                          "D — Related", "E — Partial overlap", "F — Unrelated", "G — Ambiguous",
                          "H — Insufficient evidence"])
        self.assertEqual(sv.choice_definition("PARENT"), "Concept A is a broader concept that includes Concept B")

    def test_rendered_form(self):
        rec = sv.simulate_form(self.script)
        if rec is None:
            self.skipTest("node not installed")
        chk = sv.rendered_check(self.script, self.cases)
        self.assertEqual(chk["status"], "PASSED", chk["problems"])
        self.assertEqual(rec["settings"]["title"], "Semantic Relationship Validation — Curriculum Intelligence")
        inputs = [i for i in rec["items"] if i["type"] != "PAGE_BREAK"]
        self.assertEqual([i["title"] for i in inputs if i["type"] == "TEXT"], ["Reviewer ID"])
        self.assertEqual(len(inputs), 1 + 3 * 48)
        visible = " ".join([rec["settings"]["description"]] + [i["title"] + " " + i["help"] for i in rec["items"]
                                                                 if i["type"] != "PAGE_BREAK" or i["title"].startswith("How")])
        for word in ("email address", "college", "branch", "year of study", "experience", "faculty", "student"):
            self.assertNotIn(word, visible.lower().replace("do not enter your name, email", ""))
        self.assertTrue(any("RESPONDER URL" in x for x in rec["logs"]))
        self.assertTrue(any("EDIT URL" in x for x in rec["logs"]))


class ReviewerFormImport(Workflow):
    def _form_csv(self, label="C — Child / more specific concept", conf="High", extra_case=None):
        path = Path(self.tmp.name) / "responses.csv"
        head, row = ["Timestamp", "Reviewer ID"], ["2026/10/02 10:00:00 AM GMT+5:30", "R-07"]
        ids = self.ids + ([extra_case] if extra_case else [])
        for n, cid in enumerate(ids, 1):
            head += [sv.question_title(n, cid, p) for p in ("Relationship", "Confidence", "Optional reasoning")]
            row += [label, conf, "context decides it" if n == 1 else ""]
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([head, row])
        return path

    def test_current_form_layout_imports_with_long_export(self):
        long_out = Path(self.tmp.name) / "long.csv"
        sv.import_form(SimpleNamespace(package=str(self.pkg), csv=str(self._form_csv()), long_out=str(long_out), attestation=ATTEST))
        doc = json.loads(next((self.pkg / "labels").glob("labels_*.json")).read_text())
        self.assertEqual({r["label"] for r in doc["labels"]}, {"CHILD"})
        self.assertEqual({r["confidence"] for r in doc["labels"]}, {"HIGH"})
        self.assertEqual(doc["reviewer"], "R-07")
        self.assertNotIn("role", doc["reviewer_background"])
        with long_out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0]), ["case_id", "reviewer_id", "relationship_label", "confidence", "reasoning",
                                         "timestamp"])
        self.assertEqual([r["case_id"] for r in rows], self.ids)
        self.assertEqual(rows[0]["reasoning"], "context decides it")

    def test_independent_labels_need_an_attestation(self):
        for missing in (None, "  "):
            with self.assertRaises(SystemExit) as ctx:
                sv.import_form(SimpleNamespace(package=str(self.pkg), csv=str(self._form_csv()), long_out=None,
                                               attestation=missing))
            self.assertIn("--attestation", str(ctx.exception))
        self.assertEqual(list((self.pkg / "labels").glob("labels_*.json")), [])
        sv.import_form(SimpleNamespace(package=str(self.pkg), csv=str(self._form_csv()), long_out=None, attestation=ATTEST))
        doc = json.loads(next((self.pkg / "labels").glob("labels_*.json")).read_text())
        self.assertEqual(doc["attestation"]["statement"], ATTEST)

    def test_answers_outside_the_form_are_rejected(self):
        with self.assertRaises(SystemExit):
            sv.import_form(SimpleNamespace(package=str(self.pkg), csv=str(self._form_csv(extra_case="bm1-999")), long_out=None, attestation=ATTEST))
        with self.assertRaises(SystemExit):
            sv.import_form(SimpleNamespace(package=str(self.pkg), csv=str(self._form_csv(conf="Very high")), long_out=None, attestation=ATTEST))
        with self.assertRaises(SystemExit):
            sv.import_form(SimpleNamespace(package=str(self.pkg), csv=str(self._form_csv(label="I — Something")), long_out=None, attestation=ATTEST))
