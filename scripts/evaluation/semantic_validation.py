#!/usr/bin/env python3
"""
Discipline-agnostic human validation of a frozen semantic benchmark.

A validation PACKAGE lives at data/evaluation/semantic_gold/<discipline-slug>/<version>/ and is created from any frozen
benchmark (no discipline appears in this code; the first package is just data):

  build          --discipline "<name>" --benchmark <file> [--subset 48] [--seed <text>] [--version v1]
                 MANIFEST.json            discipline, benchmark path + SHA-256, label schema, reviewer design, status
                 subset.json              the stratified human-validation subset and how it was selected
                 blind_export.csv         the subset as reviewers see it: texts and evidence only (no prediction, no
                                          development label, no system decision, no confidence)
                 form_cases.json          the same cases for the Google Form generator
                 assistant_adjudication.json  the assistant's labels for ALL cases, stored as ASSISTANT_ADJUDICATION
                                          (never human validation; never used by the gate)
                 scripts/evaluation/create_semantic_validation_form.gs is regenerated with these cases
  form           --package <dir>   regenerate the reviewer Google Form script from the frozen subset (complete
                 evidence, verbatim) + form/form_integrity_report.json and form/response_mapping.json; refuses on
                 any integrity or blindness failure (docs/SEMANTIC_HUMAN_VALIDATION_FORM.md)
  import-form    --package <dir> --csv <Google Forms responses CSV> [--long-out <csv>]   one immutable label file
                 per reviewer; --long-out: case_id,reviewer_id,relationship_label,confidence,reasoning,timestamp
  import-sheet   --package <dir> --file <filled blind_export.csv> --reviewer "<name>"
  agreement      --package <dir>   Cohen's kappa (2 reviewers) / Fleiss (3+), raw and per-class agreement, matrix
  adjudication-sheet / adjudicate --file --adjudicator     predefined procedure (choose a reviewer's label or AMBIGUOUS)
  freeze         --package <dir>   semantic_gold_v1.json (UNANIMOUS / ADJUDICATED only; the rest listed, excluded)
  evaluate       --package <dir> --predictions <jsonl>   metrics.json: every system vs gold, and the declared gate

Nothing here reads a model prediction before `evaluate`, and no label is ever changed after it.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.knowledge_engine import semantic_eval as se  # noqa: E402

PACKAGES = ROOT / "data/evaluation/semantic_gold"
GS_FILE = ROOT / "scripts/evaluation/create_semantic_validation_form.gs"
LABEL_SCHEMA = {
    "version": "relationship-labels-v1",
    "labels": [
        {"code": "SAME_CONCEPT", "user_label": "Equivalent concept", "meaning": "A and B denote the same thing in this context"},
        {"code": "PARENT", "user_label": "A is broader", "meaning": "A is a broader concept that includes B"},
        {"code": "CHILD", "user_label": "A is more specific", "meaning": "A is a narrower concept, a kind or part of B"},
        {"code": "RELATED", "user_label": "Related concept", "meaning": "clearly connected, but neither equal nor one inside the other"},
        {"code": "PARTIAL_OVERLAP", "user_label": "Partial overlap", "meaning": "they share part of their meaning"},
        {"code": "UNRELATED", "user_label": "Unrelated", "meaning": "different things (e.g. a shared word with a different sense)"},
        {"code": "AMBIGUOUS", "user_label": "Ambiguous", "meaning": "the context allows more than one reading"},
        {"code": "INSUFFICIENT_EVIDENCE", "user_label": "Not enough evidence", "meaning": "the context does not decide it"},
    ],
    "confidence": {"scale": [1, 5], "labels": {"1": "guess", "3": "fairly sure", "5": "certain"}},
}
CODE_BY_USER = {x["user_label"].lower(): x["code"] for x in LABEL_SCHEMA["labels"]}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_package(pkg):
    pkg = Path(pkg)
    man = json.loads((pkg / "MANIFEST.json").read_text())
    raw = (ROOT / man["benchmark"]["path"]).read_bytes()
    if sha(raw) != man["benchmark"]["sha256"]:
        raise SystemExit("benchmark hash mismatch: the frozen benchmark was modified")
    bench = json.loads(raw)
    subset = json.loads((pkg / "subset.json").read_text())["case_ids"]
    return pkg, man, bench, subset


def _ctx(items):
    return " | ".join(f"[{i.get('source_type')}] {i.get('text')}" for i in items or [])


# ------------------------------------------------------------------ selection

def select_subset(bench, size, seed):
    """
    Stratified, proportional, deterministic:
      1. strata = case kind (the benchmark's candidate families); quotas proportional to the benchmark
         (largest remainder), so the subset mirrors the benchmark instead of forcing equal classes;
      2. inside a kind, cases are spread over the assistant's development labels proportionally, and every label that
         occurs in the benchmark is represented at least once (rare classes such as PARENT stay testable);
      3. failure-mode tags (lexical collision, acronym, hierarchy, abbreviation, alias, paraphrase) that the proportional
         pass missed are added by swapping within the same kind+label cell when possible;
      4. inside a cell, order = SHA-256(seed + case id): reproducible and independent of any model output.
    Reviewers never see the development labels; they are used only to keep the class mix representative.
    """
    def order(c):
        return hashlib.sha256(f"{seed}|{c['benchmark_id']}".encode()).hexdigest()

    def largest_remainder(counts, total):
        n = sum(counts.values())
        raw = {k: total * v / n for k, v in counts.items()}
        q = {k: int(v) for k, v in raw.items()}
        for k in sorted(raw, key=lambda k: (-(raw[k] - q[k]), k))[: total - sum(q.values())]:
            q[k] += 1
        return q

    by_kind = defaultdict(list)
    for c in bench:
        by_kind[c["kind"]].append(c)
    kind_q = largest_remainder({k: len(v) for k, v in by_kind.items()}, size)
    chosen = []
    for kind, cases in sorted(by_kind.items()):
        cells = defaultdict(list)
        for c in cases:
            cells[c["label"]].append(c)
        cq = largest_remainder({k: len(v) for k, v in cells.items()}, kind_q[kind])
        for label, cs in sorted(cells.items()):
            chosen += sorted(cs, key=order)[: cq[label]]
    # every label of the benchmark at least once
    have = Counter(c["label"] for c in chosen)
    for label in sorted({c["label"] for c in bench} - set(have)):
        cand = sorted((c for c in bench if c["label"] == label), key=order)[0]
        donor_kind = cand["kind"]
        donors = sorted((c for c in chosen if c["kind"] == donor_kind and have[c["label"]] > 1), key=order, reverse=True)
        if donors:
            chosen.remove(donors[0])
            have[donors[0]["label"]] -= 1
        chosen.append(cand)
        have[label] += 1
    # failure-mode coverage
    tags = ("lexical_collision", "acronym", "hierarchy", "abbreviation", "alias", "paraphrase")
    for tag in tags:
        if not any(tag in (c.get("tags") or []) for c in chosen):
            cand = next((c for c in sorted(bench, key=order) if tag in (c.get("tags") or []) and c not in chosen), None)
            if cand:
                donors = sorted((c for c in chosen if c["kind"] == cand["kind"] and c["label"] == cand["label"]
                                 and not set(c.get("tags") or []) & set(tags)), key=order, reverse=True)
                if donors:
                    chosen.remove(donors[0])
                    chosen.append(cand)
    chosen = sorted(chosen, key=lambda c: c["benchmark_id"])
    return chosen, kind_q


def build(a):
    raw = Path(a.benchmark).read_bytes()
    bench = json.loads(raw)
    pkg = PACKAGES / slug(a.discipline) / a.version
    if (pkg / "MANIFEST.json").exists() and not a.force:
        raise SystemExit(f"{pkg} exists; packages are immutable once built (use --version v2)")
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "labels").mkdir(exist_ok=True)
    chosen, kind_q = select_subset(bench, a.subset, a.seed)
    ids = [c["benchmark_id"] for c in chosen]
    rel = str(Path(a.benchmark).resolve().relative_to(ROOT))
    manifest = {
        "package": f"semantic_gold/{slug(a.discipline)}/{a.version}", "discipline": a.discipline,
        "benchmark": {"path": rel, "sha256": sha(raw), "cases": len(bench), "version": Path(rel).parent.name},
        "benchmark_version": Path(rel).parent.name, "label_schema_version": LABEL_SCHEMA["version"],
        "label_schema": LABEL_SCHEMA, "case_count": len(ids),
        "reviewer_design": {"target_reviewers": a.reviewers, "reviewer_role": a.reviewer_role,
                            "each_reviewer_labels": "all subset cases, independently, without seeing any system output",
                            "blind_to": ["model predictions", "assistant adjudication", "deterministic prediction",
                                         "model confidence", "current system decision", "expected answer"]},
        "agreement": {"measure": "COHEN_KAPPA (2 reviewers) / FLEISS_KAPPA (3+)", "status": "PENDING"},
        "adjudication": {"procedure": "a named human adjudicator chooses one of the reviewers' labels or AMBIGUOUS; the "
                                      "model answer and the assistant adjudication are never shown or used",
                         "status": "PENDING"},
        "gold_status": "PENDING_INDEPENDENT_LABELS", "review_count": 0,
        "created_at": now(), "created_by": "scripts/evaluation/semantic_validation.py build",
    }
    (pkg / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    subset = {"case_ids": ids, "size": len(ids), "seed": a.seed,
              "method": select_subset.__doc__.strip(),
              "kind_quotas": kind_q,
              "distribution": {"kind": dict(Counter(c["kind"] for c in chosen)),
                               "development_label (never shown to reviewers)": dict(Counter(c["label"] for c in chosen)),
                               "tags": dict(Counter(t for c in chosen for t in c.get("tags") or []))},
              "benchmark_distribution": {"kind": dict(Counter(c["kind"] for c in bench)),
                                         "development_label": dict(Counter(c["label"] for c in bench))}}
    (pkg / "subset.json").write_text(json.dumps(subset, indent=1, ensure_ascii=False))
    form_cases = []
    with (pkg / "blind_export.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "concept_a", "concept_a_context", "concept_b", "concept_b_description", "relationship",
                    "confidence_1_to_5", "rationale"])
        for i, c in enumerate(chosen, 1):
            b_desc = c.get("right_description") or _ctx(c.get("right_context"))
            w.writerow([c["benchmark_id"], c["left_text"], _ctx(c["left_context"]), c["right_concept"], b_desc, "", "", ""])
            form_cases.append({"n": i, "case_id": c["benchmark_id"], "concept_a": c["left_text"],
                               "context_a": [x.get("text") for x in c["left_context"] or []][:4],
                               "concept_b": c["right_concept"], "description_b": b_desc})
    (pkg / "form_cases.json").write_text(json.dumps(form_cases, indent=1, ensure_ascii=False))
    adjudication = {"label_source": "ASSISTANT_ADJUDICATION", "is_human_validated": False,
                    "use": "error analysis and preparation of the human review only; never shown to reviewers, never "
                           "used by the promotion gate, never reported as accuracy",
                    "provenance": "the frozen benchmark's development labels (labelled by the assistant before the "
                                  "benchmark was frozen; see its FREEZE_MANIFEST known_bias)",
                    "cases": [{"case_id": c["benchmark_id"], "label": c["label"], "rationale": c.get("rationale"),
                               "in_human_subset": c["benchmark_id"] in ids} for c in bench]}
    (pkg / "assistant_adjudication.json").write_text(json.dumps(adjudication, indent=1, ensure_ascii=False))
    write_gs(manifest, form_cases_from_benchmark(bench, ids))
    shown = pkg.relative_to(ROOT) if pkg.is_relative_to(ROOT) else pkg
    print(json.dumps({"package": str(shown), "cases": len(ids), "distribution": subset["distribution"]}, indent=1))


# ------------------------------------------------------------------ reviewer form

FORM_TITLE = "Semantic Relationship Validation — Curriculum Intelligence"
FORM_DESCRIPTION = (
    "This form is part of an independent evaluation of semantic relationships used in a curriculum-intelligence "
    "system.\n\n"
    "You will review {n} cases involving concepts, skills, curriculum topics, and reference concepts.\n\n"
    "For each case, review the information provided and select the relationship that best describes the two "
    "concepts.\n\n"
    "Please make your judgment independently based only on the information provided.\n\n"
    "The system's AI prediction is not shown to you.\n\n"
    "There are no expected answers shown in this form.")
# Reviewer-facing choice letter and wording -> the project's label code (relationship-labels-v1). The meaning shown
# to the reviewer is LABEL_SCHEMA[code]["meaning"], with "A"/"B" written out as "Concept A"/"Concept B".
FORM_CHOICES = [("A", "Same concept", "SAME_CONCEPT"), ("B", "Parent / broader concept", "PARENT"),
                ("C", "Child / more specific concept", "CHILD"), ("D", "Related", "RELATED"),
                ("E", "Partial overlap", "PARTIAL_OVERLAP"), ("F", "Unrelated", "UNRELATED"),
                ("G", "Ambiguous", "AMBIGUOUS"), ("H", "Insufficient evidence", "INSUFFICIENT_EVIDENCE")]
FORM_CONFIDENCE = [("High", "HIGH", "certain"), ("Moderate", "MODERATE", "fairly sure"), ("Low", "LOW", "guess")]
REVIEWER_ID_TITLE = "Reviewer ID"
SOURCE_WORDS = {"SOURCE_TEXT": "Source text", "JOB_TITLE": "Job title", "COURSE_TITLE": "Course title",
                "UNIT_TITLE": "Unit title", "LEARNING_OUTCOME": "Learning outcome",
                "ESCO_DESCRIPTION": "Reference concept description", "ESCO_HIERARCHY": "Reference concept hierarchy"}
# Only these benchmark fields reach the form: the inputs a reviewer needs. Never the label, rationale, reviewer,
# label source, kind, tags, candidate/evidence-span ids or anything a system produced.
FORM_CASE_FIELDS = {"concept_a": "left_text", "context_a": "left_context", "concept_b": "right_concept",
                    "context_b": "right_context"}
QUESTION_RE = re.compile(r"^Case (\d+) \(Ref\. ([^)]+)\) — (Relationship|Confidence|Optional reasoning)$")


REVIEWER_ID_HELP = ("Enter the reviewer ID you were given. Do not enter your name, email or any other personal "
                    "information.")
JUDGE_INTRO = ("Each case shows Concept A and Concept B with the context / evidence they come from. Choose the "
               "relationship of Concept A to Concept B in this context.")
GUIDANCE = ("Judge only from the text shown. A shared word, or one phrase appearing inside another, is not enough "
            "for Same concept or for a parent / child relationship. Texts are shown exactly as they appear in "
            "the source documents.")
CONFIRMATION = "Thank you. Your judgments have been recorded."


def reviewer_visible_frame(cases):
    """The non-evidence text a reviewer reads (mirrors the Apps Script); used for the blindness scan."""
    out = [FORM_TITLE, FORM_DESCRIPTION.format(n=len(cases)), REVIEWER_ID_TITLE, REVIEWER_ID_HELP, "How to judge each case",
           JUDGE_INTRO, GUIDANCE, CONFIRMATION]
    out += [choice_text(l, w) + ": " + choice_definition(code) for l, w, code in FORM_CHOICES]
    out += [f"{words}: {meaning}" for words, _, meaning in FORM_CONFIDENCE]
    for c in cases:
        out += [question_title(c["n"], c["case_id"], p) for p in ("Relationship", "Confidence", "Optional reasoning")]
    return out


def choice_text(letter, words):
    return f"{letter} — {words}"


def choice_definition(code):
    meaning = next(x["meaning"] for x in LABEL_SCHEMA["labels"] if x["code"] == code)
    return re.sub(r"\b(A|B)\b", r"Concept \1", meaning)


def question_title(n, case_id, part):
    return f"Case {n} (Ref. {case_id}) — {part}"


def form_cases_from_benchmark(bench, subset_ids):
    """The subset cases, in subset order, with the complete benchmark evidence verbatim and nothing else."""
    by_id = {c["benchmark_id"]: c for c in bench}
    cases = []
    for n, cid in enumerate(subset_ids, 1):
        c = by_id[cid]
        cases.append({"n": n, "case_id": cid, "concept_a": c["left_text"],
                      "context_a": [{"source": SOURCE_WORDS.get(x.get("source_type"), "Evidence"), "text": x.get("text")}
                                    for x in c.get("left_context") or []],
                      "concept_b": c["right_concept"],
                      "context_b": [{"source": SOURCE_WORDS.get(x.get("source_type"), "Evidence"), "text": x.get("text")}
                                    for x in c.get("right_context") or []]})
    return cases


def form_integrity(bench, subset_ids, cases, manifest, script_text=None):
    """case_count, case_ids, duplicate_ids, missing_ids, modified_cases + order and blindness checks."""
    by_id = {c["benchmark_id"]: c for c in bench}
    ids = [c["case_id"] for c in cases]
    dup = sorted(k for k, v in Counter(ids).items() if v > 1)
    missing = [cid for cid in subset_ids if cid not in by_id]
    invented = [cid for cid in ids if cid not in by_id or cid not in subset_ids]
    not_in_form = [cid for cid in subset_ids if cid not in ids]
    modified = []
    for c in cases:
        b = by_id.get(c["case_id"])
        if b is None:
            continue
        diffs = []
        if c["concept_a"] != b["left_text"]:
            diffs.append("concept_a")
        if c["concept_b"] != b["right_concept"]:
            diffs.append("concept_b")
        for side, key in (("context_a", "left_context"), ("context_b", "right_context")):
            if [x["text"] for x in c[side]] != [x.get("text") for x in b.get(key) or []]:
                diffs.append(side)
            if [x["source"] for x in c[side]] != [SOURCE_WORDS.get(x.get("source_type"), "Evidence")
                                                  for x in b.get(key) or []]:
                diffs.append(side + ".source")
        extra = set(c) - {"n", "case_id", *FORM_CASE_FIELDS}
        if extra:
            diffs.append("extra fields: " + ", ".join(sorted(extra)))
        if diffs:
            modified.append({"case_id": c["case_id"], "fields": diffs})
    leaks = []
    visible = reviewer_visible_frame(cases)          # everything a reviewer reads except the verbatim evidence
    forbidden_ci = ["qwen", "claude", "gpt", "llm", "assistant", "gold", "gate", "score", "benchmark", "correct",
                    "development", "adjudicat", "rationale", "hard case", "known error", "selected because"]
    forbidden_cs = [x["code"] for x in LABEL_SCHEMA["labels"]] + ["ALIAS_SENSE", "DIAGNOSTIC",
                    "AMBIGUOUS_TAXONOMY_LABEL", "AMBIGUOUS_TOPIC_MAPPING", "hard_case", "lexical_collision"]
    for text in visible:
        low = text.lower()
        leaks += [f"{w!r} in {text[:60]!r}" for w in forbidden_ci if w in low]
        leaks += [f"{w!r} in {text[:60]!r}" for w in forbidden_cs if w in text]
    if script_text is not None:
        start = script_text.index("var CASES = ") + len("var CASES = ")
        end = script_text.index("\n];\n", start) + 2
        payload = json.loads(script_text[start:end])
        keys = {k for c in payload for k in c}
        if keys - {"n", "case_id", *FORM_CASE_FIELDS}:
            leaks.append("case keys: " + ", ".join(sorted(keys - {"n", "case_id", *FORM_CASE_FIELDS})))
        for c in payload:                    # no development label / rationale of a case anywhere in its payload
            b = by_id.get(c["case_id"], {})
            r = (b.get("rationale") or "").strip()
            if len(r) > 12 and r in json.dumps(c, ensure_ascii=False):
                leaks.append(f"rationale of {c['case_id']}")
        if payload != cases:
            modified.append({"case_id": "*", "fields": ["script payload differs from the generated cases"]})
    report = {
        "case_count": len(cases), "case_ids": ids, "duplicate_ids": dup, "missing_ids": missing,
        "modified_cases": modified,
        "invented_ids": invented, "subset_ids_not_in_form": not_in_form,
        "order_matches_subset": ids == list(subset_ids),
        "expected_case_count": manifest.get("case_count"),
        "benchmark": {"path": manifest["benchmark"]["path"], "sha256": manifest["benchmark"]["sha256"],
                      "sha256_verified": True, "cases": len(bench)},
        "blindness": {"form_fields_per_case": ["case number", "case reference id", "Concept A", "context / evidence of A",
                                               "Concept B", "context / evidence of B"],
                      "excluded_benchmark_fields": sorted(set(next(iter(bench)).keys()) - {"benchmark_id", "left_text",
                                                          "left_context", "right_concept", "right_context"}),
                      "leaks_found": leaks},
        "label_definitions": {"schema_version": LABEL_SCHEMA["version"],
                              "choices": [{"choice": choice_text(l, w), "code": code,
                                           "definition_shown": choice_definition(code)} for l, w, code in FORM_CHOICES]},
    }
    report["passed"] = (report["case_count"] == manifest.get("case_count") and not dup and not missing and not modified
                        and not invented and not not_in_form and report["order_matches_subset"] and not leaks)
    return report


def response_mapping(manifest, cases):
    return {
        "version": "semantic-form-responses-v1",
        "form_title": FORM_TITLE,
        "package": manifest["package"],
        "benchmark": {"path": manifest["benchmark"]["path"], "sha256": manifest["benchmark"]["sha256"]},
        "output_columns": [
            {"name": "case_id", "from": "the reference in the question title 'Case <n> (Ref. <case_id>) — …'",
             "join": "benchmark_id of the frozen benchmark; model outputs are joined on it later, outside the form"},
            {"name": "reviewer_id", "from": f"the '{REVIEWER_ID_TITLE}' answer (pseudonymous; no name or email is collected)"},
            {"name": "relationship_label", "from": "'Case <n> (Ref. <case_id>) — Relationship'",
             "mapping": {choice_text(l, w): code for l, w, code in FORM_CHOICES}},
            {"name": "confidence", "from": "'Case <n> (Ref. <case_id>) — Confidence'",
             "mapping": {words: code for words, code, _ in FORM_CONFIDENCE}},
            {"name": "reasoning", "from": "'Case <n> (Ref. <case_id>) — Optional reasoning' (empty when not given)"},
            {"name": "timestamp", "from": "the 'Timestamp' column Google Forms adds to every response"},
        ],
        "one_row_per": "reviewer × case",
        "expected_rows_per_reviewer": len(cases),
        "case_ids": [c["case_id"] for c in cases],
        "never_in_form_or_export": ["Qwen prediction", "Claude prediction", "system prediction", "expected label",
                                    "gold label", "model confidence", "model score", "benchmark result",
                                    "promotion gate", "whether the model was correct",
                                    "why a case was selected"],
        "importer": "python3 scripts/evaluation/semantic_validation.py import-form --package <package dir> "
                    "--csv <Google Forms responses CSV> [--long-out <responses_long.csv>]",
        "apps_script_export": "exportResponsesLongCsv() in create_semantic_validation_form.gs writes the same columns "
                              "to a CSV in the form owner's Google Drive",
    }


GS_TEMPLATE = r'''/**
 * Semantic Relationship Validation — Curriculum Intelligence
 * Creates the reviewer-blind Google Form for validation package __PACKAGE__
 * (__COUNT__ cases of the frozen benchmark __BENCH_PATH__, sha256 __BENCH_SHA__).
 *
 * GENERATED by: python3 scripts/evaluation/semantic_validation.py form --package data/evaluation/__PACKAGE__
 * Do not edit by hand: the case texts below are verbatim from the frozen benchmark and are checked by
 * data/evaluation/__PACKAGE__/form/form_integrity_report.json.
 *
 * RUN
 *   1. https://script.google.com -> New project -> replace Code.gs with this file -> Save.
 *   2. Select function createSemanticValidationForm -> Run -> authorise (Google Forms; Drive only for the export).
 *   3. View -> Execution log: the Form EDIT URL and the RESPONDER URL are printed there.
 *   After responses: run exportResponsesLongCsv (writes case_id, reviewer_id, relationship_label, confidence,
 *   reasoning, timestamp to a CSV in your Drive), or download the responses CSV and run import-form.
 *
 * The form collects only a Reviewer ID. It shows no prediction of any system, no expected or gold answer, no score,
 * no confidence of any model and no reason why a case was chosen.
 */

var FORM_TITLE = __TITLE__;
var FORM_DESCRIPTION = __DESCRIPTION__;
var EXPECTED_CASE_COUNT = __COUNT__;
var CASES_SHA256 = '__CASES_SHA__';
var REVIEWER_ID_TITLE = __REVIEWER_ID_TITLE__;
var CHOICES = __CHOICES__;
var CONFIDENCE = __CONFIDENCE__;
var GUIDANCE = __GUIDANCE__;
var REVIEWER_ID_HELP = __REVIEWER_ID_HELP__;
var JUDGE_INTRO = __JUDGE_INTRO__;
var CONFIRMATION = __CONFIRMATION__;

var CASES = __CASES__;

function verifyCases_() {
  if (CASES.length !== EXPECTED_CASE_COUNT) {
    throw new Error('Expected ' + EXPECTED_CASE_COUNT + ' cases, found ' + CASES.length);
  }
  var seen = {};
  for (var i = 0; i < CASES.length; i++) {
    if (seen[CASES[i].case_id]) throw new Error('Duplicate case ' + CASES[i].case_id);
    seen[CASES[i].case_id] = true;
    if (CASES[i].n !== i + 1) throw new Error('Case order changed at position ' + (i + 1));
  }
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(CASES),
      Utilities.Charset.UTF_8);
  var hex = digest.map(function (b) { return ('0' + (b & 0xff).toString(16)).slice(-2); }).join('');
  if (hex !== CASES_SHA256) {
    throw new Error('Case texts differ from the frozen subset (sha256 ' + hex + '); regenerate this script.');
  }
}

function caseHelp_(c) {
  var lines = [];
  lines.push('CONCEPT A:  ' + c.concept_a);
  lines.push('');
  lines.push('Context / evidence for Concept A:');
  c.context_a.forEach(function (x) { lines.push('• ' + x.source + ': ' + x.text); });
  lines.push('');
  lines.push('CONCEPT B:  ' + c.concept_b);
  lines.push('');
  lines.push('Context / evidence for Concept B:');
  if (c.context_b.length === 0) lines.push('• (none)');
  c.context_b.forEach(function (x) { lines.push('• ' + x.source + ': ' + x.text); });
  return lines.join('\n');
}

function title_(c, part) {
  return 'Case ' + c.n + ' (Ref. ' + c.case_id + ') — ' + part;
}

function createSemanticValidationForm() {
  verifyCases_();
  var form = FormApp.create(FORM_TITLE);
  form.setDescription(FORM_DESCRIPTION);
  try { form.setEmailCollectionType(FormApp.EmailCollectionType.DO_NOT_COLLECT); }
  catch (e) { form.setCollectEmail(false); }
  try { form.setRequireLogin(false); } catch (e) { /* only available to Workspace accounts */ }
  form.setLimitOneResponsePerUser(false);   // would require sign-in, i.e. identity
  form.setAllowResponseEdits(false);
  form.setPublishingSummary(false);         // reviewers never see other reviewers' answers
  form.setShowLinkToRespondAgain(false);
  form.setShuffleQuestions(false);
  form.setProgressBar(true);
  form.setConfirmationMessage(CONFIRMATION);
  form.setAcceptingResponses(true);

  form.addTextItem().setTitle(REVIEWER_ID_TITLE).setRequired(true)
      .setHelpText(REVIEWER_ID_HELP);

  var defs = CHOICES.map(function (c) { return c.choice + ': ' + c.definition; }).join('\n');
  var conf = CONFIDENCE.map(function (c) { return c.choice + ': ' + c.meaning; }).join('\n');
  form.addPageBreakItem().setTitle('How to judge each case')
      .setHelpText(JUDGE_INTRO + '\n\n' + defs + '\n\n' + GUIDANCE
          + '\n\nConfidence:\n' + conf);

  for (var i = 0; i < CASES.length; i++) {
    var c = CASES[i];
    form.addPageBreakItem().setTitle('Case ' + c.n + ' of ' + CASES.length).setHelpText(caseHelp_(c));
    form.addMultipleChoiceItem().setTitle(title_(c, 'Relationship'))
        .setHelpText('Relationship of Concept A (' + c.concept_a + ') to Concept B (' + c.concept_b + ').')
        .setChoiceValues(CHOICES.map(function (x) { return x.choice; })).setRequired(true);
    form.addMultipleChoiceItem().setTitle(title_(c, 'Confidence'))
        .setChoiceValues(CONFIDENCE.map(function (x) { return x.choice; })).setRequired(true);
    form.addParagraphTextItem().setTitle(title_(c, 'Optional reasoning')).setRequired(false);
  }

  var counts = verifyCreatedForm_(form);
  var publishedState = 'unknown';
  try { form.setPublished(true); publishedState = String(form.isPublished()); }
  catch (e) { publishedState = 'not reported by this Apps Script version (open the form and check "Published")'; }
  var published = form.getPublishedUrl();
  var shortUrl = '';
  try { shortUrl = form.shortenFormUrl(published); } catch (e) { shortUrl = '(not available)'; }
  Logger.log('Form created: ' + FORM_TITLE);
  Logger.log('Form ID:       ' + form.getId());
  Logger.log('EDIT URL:      ' + form.getEditUrl());
  Logger.log('RESPONDER URL: ' + published);
  Logger.log('Short URL:     ' + shortUrl);
  Logger.log('Published:     ' + publishedState);
  Logger.log('Check:         ' + JSON.stringify(counts));
  return {editUrl: form.getEditUrl(), responderUrl: published, shortUrl: shortUrl, check: counts};
}

function verifyCreatedForm_(form) {
  var items = form.getItems();
  var counts = {pages: 0, multipleChoice: 0, paragraph: 0, text: 0, other: 0};
  items.forEach(function (it) {
    var t = it.getType();
    if (t === FormApp.ItemType.PAGE_BREAK) counts.pages++;
    else if (t === FormApp.ItemType.MULTIPLE_CHOICE) counts.multipleChoice++;
    else if (t === FormApp.ItemType.PARAGRAPH_TEXT) counts.paragraph++;
    else if (t === FormApp.ItemType.TEXT) counts.text++;
    else counts.other++;
  });
  var ok = counts.pages === CASES.length + 1 && counts.multipleChoice === 2 * CASES.length
      && counts.paragraph === CASES.length && counts.text === 1 && counts.other === 0;
  if (!ok) throw new Error('Created form does not have the expected structure: ' + JSON.stringify(counts));
  counts.cases = CASES.length;
  counts.ok = ok;
  return counts;
}

/** Long-format export: one row per reviewer x case. Set FORM_ID (from the log) before running. */
var FORM_ID = '';

function exportResponsesLongCsv() {
  if (!FORM_ID) throw new Error('Set FORM_ID to the Form ID printed by createSemanticValidationForm.');
  var form = FormApp.openById(FORM_ID);
  var re = /^Case (\d+) \(Ref\. ([^)]+)\) — (Relationship|Confidence|Optional reasoning)$/;
  var rows = [['case_id', 'reviewer_id', 'relationship_label', 'confidence', 'reasoning', 'timestamp']];
  var codeByChoice = {};
  CHOICES.forEach(function (c) { codeByChoice[c.choice] = c.code; });
  var confByChoice = {};
  CONFIDENCE.forEach(function (c) { confByChoice[c.choice] = c.code; });
  form.getResponses().forEach(function (r) {
    var reviewer = '';
    var byCase = {};
    r.getItemResponses().forEach(function (ir) {
      var t = ir.getItem().getTitle();
      if (t === REVIEWER_ID_TITLE) { reviewer = String(ir.getResponse()).trim(); return; }
      var m = re.exec(t);
      if (!m) return;
      var cid = m[2];
      byCase[cid] = byCase[cid] || {};
      byCase[cid][m[3]] = String(ir.getResponse() || '');
    });
    var ts = Utilities.formatDate(r.getTimestamp(), 'UTC', "yyyy-MM-dd'T'HH:mm:ss'Z'");
    CASES.forEach(function (c) {
      var a = byCase[c.case_id] || {};
      rows.push([c.case_id, reviewer, codeByChoice[a['Relationship']] || '', confByChoice[a['Confidence']] || '',
          a['Optional reasoning'] || '', ts]);
    });
  });
  var csv = rows.map(function (row) {
    return row.map(function (v) { return '"' + String(v).replace(/"/g, '""') + '"'; }).join(',');
  }).join('\n');
  var file = DriveApp.createFile('semantic_validation_responses_long.csv', csv, MimeType.CSV);
  Logger.log('Exported ' + (rows.length - 1) + ' rows: ' + file.getUrl());
}
'''


def cases_sha(cases):
    return sha(json.dumps(cases, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def write_gs(manifest, cases):
    choices = [{"choice": choice_text(l, w), "code": code, "definition": choice_definition(code)}
               for l, w, code in FORM_CHOICES]
    conf = [{"choice": words, "code": code, "meaning": meaning} for words, code, meaning in FORM_CONFIDENCE]
    js = lambda v: json.dumps(v, ensure_ascii=False)   # noqa: E731
    text = (GS_TEMPLATE
            .replace("__PACKAGE__", manifest["package"])
            .replace("__BENCH_PATH__", manifest["benchmark"]["path"])
            .replace("__BENCH_SHA__", manifest["benchmark"]["sha256"])
            .replace("__COUNT__", str(len(cases)))
            .replace("__CASES_SHA__", cases_sha(cases))
            .replace("__TITLE__", js(FORM_TITLE))
            .replace("__DESCRIPTION__", js(FORM_DESCRIPTION.format(n=len(cases))))
            .replace("__REVIEWER_ID_TITLE__", js(REVIEWER_ID_TITLE))
            .replace("__CHOICES__", json.dumps(choices, ensure_ascii=False, indent=1))
            .replace("__CONFIDENCE__", json.dumps(conf, ensure_ascii=False, indent=1))
            .replace("__GUIDANCE__", js(GUIDANCE))
            .replace("__REVIEWER_ID_HELP__", js(REVIEWER_ID_HELP))
            .replace("__JUDGE_INTRO__", js(JUDGE_INTRO))
            .replace("__CONFIRMATION__", js(CONFIRMATION))
            .replace("__CASES__", json.dumps(cases, ensure_ascii=False, indent=1)))
    GS_FILE.write_text(text, encoding="utf-8")
    return text


def simulate_form(script_text):
    """Run the Apps Script against a recording FormApp mock (node); None when node is not installed."""
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".gs", delete=False, encoding="utf-8") as f:
        f.write(script_text)
    try:
        out = subprocess.run([node, str(ROOT / "scripts/evaluation/simulate_form.js"), f.name], capture_output=True,
                             text=True, timeout=120)
    finally:
        Path(f.name).unlink(missing_ok=True)
    if out.returncode:
        raise SystemExit("the Apps Script failed in simulation:\n" + out.stderr[-2000:])
    return json.loads(out.stdout)


def rendered_check(script_text, cases):
    """What a reviewer would actually see, item by item, checked against the cases and the blindness rules."""
    rec = simulate_form(script_text)
    if rec is None:
        return {"status": "SKIPPED", "reason": "node is not installed"}
    items, problems = rec["items"], []
    st = rec["settings"]
    if st.get("title") != FORM_TITLE or st.get("description") != FORM_DESCRIPTION.format(n=len(cases)):
        problems.append("title or description differs from the specification")
    if st.get("emailCollection") != "DO_NOT_COLLECT" or st.get("publishingSummary") is not False:
        problems.append("email collection or response summary not disabled")
    inputs = [i for i in items if i["type"] != "PAGE_BREAK"]
    if inputs[0]["title"] != REVIEWER_ID_TITLE or not inputs[0]["required"]:
        problems.append("first question is not the required Reviewer ID")
    if [i for i in inputs if i["type"] == "TEXT"] != inputs[:1]:
        problems.append("personal-information question present")
    pages = [i for i in items if i["type"] == "PAGE_BREAK"][1:]
    letters = [choice_text(l, w) for l, w, _ in FORM_CHOICES]
    for c, page in zip(cases, pages):
        if page["title"] != f"Case {c['n']} of {len(cases)}":
            problems.append(f"page title of {c['case_id']}")
        for x in [c["concept_a"], c["concept_b"]] + [y["text"] for y in c["context_a"] + c["context_b"]]:
            if x not in page["help"]:
                problems.append(f"{c['case_id']}: evidence not shown verbatim: {x[:40]!r}")
        qs = [i for i in inputs if i["title"].startswith(f"Case {c['n']} (Ref. {c['case_id']}) — ")]
        kinds = [(q["type"], q["title"].split(" — ")[-1], q["required"], q["choices"]) for q in qs]
        want = [("MULTIPLE_CHOICE", "Relationship", True, letters),
                ("MULTIPLE_CHOICE", "Confidence", True, [w for w, _, _ in FORM_CONFIDENCE]),
                ("PARAGRAPH_TEXT", "Optional reasoning", False, None)]
        if kinds != want:
            problems.append(f"{c['case_id']}: questions {kinds}")
    if len(pages) != len(cases):
        problems.append(f"{len(pages)} case pages for {len(cases)} cases")
    # blindness on the rendered frame: all visible text minus the verbatim evidence of each case
    frame = [st.get("title", ""), st.get("description", ""), st.get("confirmation", "")]
    for i in items:
        frame += [i["title"], i["help"] if not i["title"].startswith("Case ") or i["type"] != "PAGE_BREAK" else ""]
        frame += i["choices"] or []
    frame = [t for t in frame if t]
    bad = []
    for text in frame:
        low = text.lower()
        bad += [w for w in ("qwen", "claude", "gpt", "assistant", "gold", "gate", "score", "benchmark", "correct",
                            "development", "adjudicat", "rationale") if w in low and "Relationship of Concept A" not in text]
        bad += [x["code"] for x in LABEL_SCHEMA["labels"] if x["code"] in text]
    if bad:
        problems.append("visible frame mentions: " + ", ".join(sorted(set(bad))))
    return {"status": "FAILED" if problems else "PASSED", "problems": problems[:50],
            "items": dict(Counter(i["type"] for i in items)), "case_pages": len(pages),
            "questions_per_case": 3, "settings": st}


def form_cmd(a):
    """Regenerate the reviewer form from an existing package (no case is selected, changed or added)."""
    pkg, man, bench, subset = load_package(a.package)
    cases = form_cases_from_benchmark(bench, subset)
    text = write_gs(man, cases)
    report = form_integrity(bench, subset, cases, man, text)
    report["rendered_check"] = rendered_check(text, cases)
    if report["rendered_check"].get("status") == "FAILED":
        report["passed"] = False
    report.update(generated_at=now(), script=str(GS_FILE.relative_to(ROOT)) if GS_FILE.is_relative_to(ROOT) else str(GS_FILE),
                  script_sha256=sha(text.encode("utf-8")), cases_sha256=cases_sha(cases))
    out = pkg / "form"
    out.mkdir(exist_ok=True)
    (out / "form_integrity_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    (out / "response_mapping.json").write_text(json.dumps(response_mapping(man, cases), indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ("case_count", "duplicate_ids", "missing_ids", "modified_cases",
                                             "order_matches_subset", "passed")} | {"leaks": report["blindness"]["leaks_found"]},
                     indent=1))
    if not report["passed"]:
        raise SystemExit("form integrity check failed")
    return report


# ------------------------------------------------------------------ labels

def _store_labels(pkg, man, reviewer, rows, source_file, meta=None, attestation=None):
    """An INDEPENDENT_HUMAN_REVIEWER label set: it counts for agreement, gold and the gate, so it is stored only with
    a statement that the reviewer answered alone, from the case text, without AI tools and without seeing system
    output or another reviewer's answers (attestation: who confirmed it, and how). Responses that do not meet this go
    through import-responses instead."""
    try:
        name = se.check_reviewer(reviewer)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not (attestation or "").strip():
        raise SystemExit("an independent label set needs --attestation: who confirmed that the reviewer answered alone, "
                         "without AI tools, and how; otherwise import the responses with import-responses")
    out = pkg / "labels" / f"labels_{slug(name)}_v1.json"
    if out.exists():
        raise SystemExit(f"{out.name} exists; label sets are immutable")
    doc = {"benchmark": man["benchmark_version"], "benchmark_sha256": man["benchmark"]["sha256"], "package": man["package"],
           "reviewer": name, "reviewer_background": meta or {}, "label_version": "v1", "label_schema_version": man["label_schema_version"],
           "independent": True, "model_blind": True, "label_source": "INDEPENDENT_HUMAN_REVIEWER",
           "attestation": {"statement": attestation.strip(), "recorded_at": now()},
           "ingested_at": now(), "source_file_sha256": sha(Path(source_file).read_bytes()),
           "labels": rows, "labelled": sum(1 for r in rows if r["label"])}
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    return out, doc


def _label_code(value):
    v = (value or "").strip()
    if not v:
        return None
    return CODE_BY_USER.get(v.lower()) or (v.upper() if v.upper() in se.LABELS else "INVALID:" + v)


def _form_columns(header):
    """Column -> (case_id, part) for both form layouts (current 'Case n (Ref. id) — Part' and the earlier one)."""
    cols = {}
    for h in header:
        m = QUESTION_RE.match((h or "").strip())
        if m:
            cols[h] = (m.group(2), {"Relationship": "label", "Confidence": "confidence",
                                    "Optional reasoning": "reasoning"}[m.group(3)])
            continue
        m = re.match(r"^(\S+) -- (relationship of A to B|confidence|rationale \(optional\))$", (h or "").strip())
        if m:
            cols[h] = (m.group(1), {"relationship of A to B": "label", "confidence": "confidence"}.get(m.group(2), "reasoning"))
    return cols


def _form_label(value):
    v = (value or "").strip()
    if not v:
        return None
    for letter, words, code in FORM_CHOICES:
        if v == choice_text(letter, words) or v.lower() == words.lower():
            return code
    return _label_code(v)


def _form_confidence(value):
    v = (value or "").strip()
    if not v:
        return None
    if v.isdigit():
        return int(v)                                  # earlier 1-5 layout
    for words, code, _ in FORM_CONFIDENCE:
        if v.lower() == words.lower():
            return code
    return "INVALID:" + v


def import_form(a):
    """Google Forms responses CSV -> one immutable label file per reviewer (+ optional long-format CSV)."""
    pkg, man, bench, subset = load_package(a.package)
    with open(a.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)
    cols = _form_columns(header)
    unknown = sorted({cid for cid, _ in cols.values()} - set(subset))
    if unknown:
        raise SystemExit(f"responses contain cases outside the frozen subset: {unknown[:10]}")
    rid_col = next((h for h in header if h.strip() in (REVIEWER_ID_TITLE, "Reviewer ID (name or pseudonym)")), None)
    if not rid_col:
        raise SystemExit("no Reviewer ID column in the responses")
    stored, long_rows = [], []
    for r in rows:
        reviewer = (r.get(rid_col) or "").strip()
        per = defaultdict(dict)
        for h, (cid, part) in cols.items():
            per[cid][part] = r.get(h)
        labels, errors = [], []
        for cid in subset:
            got = per.get(cid, {})
            lab = _form_label(got.get("label"))
            conf = _form_confidence(got.get("confidence"))
            if lab and lab.startswith("INVALID:"):
                errors.append(f"{cid}: {lab[8:]!r}")
                continue
            if isinstance(conf, str) and conf.startswith("INVALID:"):
                errors.append(f"{cid}: confidence {conf[8:]!r}")
                continue
            reasoning = (got.get("reasoning") or "").strip() or None
            labels.append({"benchmark_id": cid, "label": lab, "confidence": conf, "rationale": reasoning})
            long_rows.append({"case_id": cid, "reviewer_id": reviewer, "relationship_label": lab or "",
                              "confidence": conf if conf is not None else "", "reasoning": reasoning or "",
                              "timestamp": (r.get("Timestamp") or "").strip()})
        if errors:
            raise SystemExit(f"{reviewer}: rejected answers: {errors[:10]}")
        meta = {k: v for k, v in {"discipline": r.get("Discipline"), "role": r.get("Role"),
                                  "experience_years": r.get("Relevant experience (years)"),
                                  "submitted": r.get("Timestamp")}.items() if v}
        out, doc = _store_labels(pkg, man, reviewer, labels, a.csv, meta, getattr(a, "attestation", None))
        stored.append((out.name, doc["labelled"]))
    if getattr(a, "long_out", None):
        with open(a.long_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["case_id", "reviewer_id", "relationship_label", "confidence", "reasoning",
                                              "timestamp"])
            w.writeheader()
            w.writerows(long_rows)
    _refresh_manifest(pkg, man)
    print(json.dumps({"stored": stored}, indent=1))


def import_sheet(a):
    pkg, man, bench, subset = load_package(a.package)
    ids = set(subset)
    rows, errors = [], []
    with open(a.file, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = (r.get("case_id") or "").strip()
            if cid not in ids:
                errors.append(f"unknown case {cid!r}")
                continue
            lab = _label_code(r.get("relationship"))
            if lab and lab.startswith("INVALID:"):
                errors.append(f"{cid}: {lab[8:]!r}")
                continue
            conf = (r.get("confidence_1_to_5") or "").strip()
            rows.append({"benchmark_id": cid, "label": lab, "confidence": int(conf) if conf.isdigit() else None,
                         "rationale": (r.get("rationale") or "").strip() or None})
    if errors:
        raise SystemExit("rejected:\n  " + "\n  ".join(errors[:50]))
    out, doc = _store_labels(pkg, man, a.reviewer, rows, a.file, attestation=getattr(a, "attestation", None))
    _refresh_manifest(pkg, man)
    print(f"stored {out} ({doc['labelled']} labelled of {len(ids)})")


def _sets(pkg, man, subset):
    ids = set(subset)
    sets = se.load_label_sets(pkg / "labels", man["benchmark"]["sha256"])
    for s in sets:
        s["labels"] = {k: v for k, v in s["labels"].items() if k in ids}
    return sets


def _refresh_manifest(pkg, man):
    sets = se.load_label_sets(pkg / "labels", man["benchmark"]["sha256"])
    man["review_count"] = len(sets)
    man["reviewers"] = [s["reviewer"] for s in sets]
    (pkg / "MANIFEST.json").write_text(json.dumps(man, indent=1, ensure_ascii=False))


def agreement_cmd(a):
    pkg, man, bench, subset = load_package(a.package)
    sets = _sets(pkg, man, subset)
    res = se.agreement(sets)
    res["per_class_agreement"] = se.per_class_agreement(sets)
    res["disagreement_matrix"] = se.disagreement_matrix(sets)
    (pkg / "agreement.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    man["agreement"] = {"measure": res["measure"], "kappa": res["kappa"], "status": "COMPUTED" if len(sets) >= 2 else "PENDING",
                        "reviewers": res["reviewers"], "cases_labelled_by_all": res["cases_labelled_by_all"]}
    (pkg / "MANIFEST.json").write_text(json.dumps(man, indent=1, ensure_ascii=False))
    print(json.dumps({k: res[k] for k in ("reviewers", "cases_labelled_by_all", "measure", "kappa")}, indent=1))


def adjudication_sheet(a):
    pkg, man, bench, subset = load_package(a.package)
    res = se.agreement(_sets(pkg, man, subset))
    by_id = {c["benchmark_id"]: c for c in bench}
    path = pkg / "adjudication_sheet.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "concept_a", "concept_a_context", "concept_b", "reviewer_labels", "decision", "note"])
        for d in res["disagreements"]:
            c = by_id[d["case"]]
            w.writerow([d["case"], c["left_text"], _ctx(c["left_context"]), c["right_concept"],
                        "; ".join(f"{k}={v}" for k, v in sorted(d["labels"].items())), "", ""])
    print(f"{len(res['disagreements'])} disagreement(s) -> {path}")


def adjudicate(a):
    pkg, man, bench, subset = load_package(a.package)
    try:
        name = se.check_reviewer(a.adjudicator)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    decisions = {}
    with open(a.file, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = _label_code(r.get("decision"))
            if d and not d.startswith("INVALID:"):
                decisions[r["case_id"].strip()] = d
    out = pkg / "adjudication.json"
    if out.exists():
        raise SystemExit("adjudication.json exists; adjudications are immutable")
    out.write_text(json.dumps({"benchmark_sha256": man["benchmark"]["sha256"], "adjudicator": name, "adjudicated_at": now(),
                               "process": man["adjudication"]["procedure"], "decisions": decisions}, indent=1))
    print(f"stored {out} ({len(decisions)} decisions)")


def freeze(a):
    pkg, man, bench, subset = load_package(a.package)
    gold_path = pkg / "semantic_gold_v1.json"
    if gold_path.exists():
        raise SystemExit("semantic_gold_v1 is frozen; a revision is released as semantic_gold_v2")
    sets = _sets(pkg, man, subset)
    if not sets:
        raise SystemExit("no independent label set; gold stays PENDING_INDEPENDENT_LABELS")
    adj = json.loads((pkg / "adjudication.json").read_text()) if (pkg / "adjudication.json").exists() else None
    rows = se.build_gold([c for c in bench if c["benchmark_id"] in set(subset)], sets, adj)
    doc = {"gold": "semantic_gold_v1", "package": man["package"], "discipline": man["discipline"], "frozen_at": now(),
           "benchmark_sha256": man["benchmark"]["sha256"], "reviewers": [s["reviewer"] for s in sets],
           "adjudicator": (adj or {}).get("adjudicator"),
           "agreement": {k: v for k, v in se.agreement(sets).items() if k != "disagreements"},
           "status_counts": dict(Counter(r["adjudication_status"] for r in rows)), "cases": rows}
    gold_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    man["gold_status"] = "FROZEN"
    (pkg / "MANIFEST.json").write_text(json.dumps(man, indent=1, ensure_ascii=False))
    print(f"frozen {gold_path}: {doc['status_counts']}")


def import_responses(a):
    """Form responses (.xlsx, every worksheet, or .csv) -> verbatim records under <package>/responses/ with their
    source location. They are research records, not label sets: they never count towards agreement, gold or the gate
    (that is import-form, for independent human reviewers). --source states how the answers were produced."""
    from app.knowledge_engine import semantic_responses as sr
    pkg, man, bench, subset = load_package(a.package)
    reviewers = [r.strip() for r in a.reviewers.split(",")] if a.reviewers else None
    try:
        records, report = sr.parse_source(a.file, list(subset), man["package"], a.source, reviewers, a.note)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if report["unknown_questions"]:
        raise SystemExit(f"the source has questions outside the frozen subset: {report['unknown_questions'][:10]}")
    if not records:
        raise SystemExit("no responses found" + (f" for {reviewers}" if reviewers else "") + f": {report['sheets']}")
    stored = sr.store(pkg, records, report, a.file, man["benchmark"]["sha256"])
    print(json.dumps({"stored": stored, "records": len(records),
                      "status_counts": dict(Counter(r["status"] for r in records)),
                      "report": report}, indent=1, ensure_ascii=False, default=str))
    if "CONFLICT" in stored.values():
        raise SystemExit("some reviewers already have different stored responses; nothing was overwritten")


def compare_responses(a):
    from app.knowledge_engine import semantic_responses as sr
    pkg, man, bench, subset = load_package(a.package)
    records, _ = sr.load(pkg)
    m = sr.metrics(records, list(subset), a.a, a.b)
    print(json.dumps({k: v for k, v in m.items() if k != "definitions"}, indent=1, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(sr.export_csv(records, {a.a, a.b}), encoding="utf-8")
        print(f"wrote {a.out}")


def evaluate(a):
    pkg, man, bench, subset = load_package(a.package)
    gate_path = ROOT / a.gate
    gate = json.loads(gate_path.read_text())
    preds = [json.loads(x) for x in Path(a.predictions).read_text().splitlines() if x.strip()]
    preds = [p for p in preds if p["benchmark_id"] in set(subset)]
    sets = _sets(pkg, man, subset)
    out = {"package": man["package"], "discipline": man["discipline"], "benchmark_sha256": man["benchmark"]["sha256"],
           "gate": gate["version"], "gate_sha256": sha(gate_path.read_bytes()), "evaluated_at": now(),
           "cases": len(subset), "reviewers": [s["reviewer"] for s in sets]}
    gold_path = pkg / "semantic_gold_v1.json"
    if not gold_path.exists():
        out.update(se.pending_status(man["benchmark"]["sha256"], gate, sets))
    else:
        gdoc = json.loads(gold_path.read_text())
        gold = {r["case_id"]: r["gold"] for r in gdoc["cases"] if r["gold"]}
        by_id = {p["benchmark_id"]: p for p in preds}
        cases = [{**c, "left": by_id[c["benchmark_id"]]["left"], "right": by_id[c["benchmark_id"]]["right"],
                  "tags": by_id[c["benchmark_id"]]["tags"], "kind": by_id[c["benchmark_id"]]["kind"]}
                 for c in bench if c["benchmark_id"] in by_id]
        findings = se.group_findings(preds)
        systems = {name: se.evaluate_system(cases, gold, {p["benchmark_id"]: p.get(col) for p in preds},
                                            findings if name != "DETERMINISTIC_BASELINE" else None)
                   for name, col in se.SYSTEMS.items()}
        comp = {m: se.contingency(systems["DETERMINISTIC_BASELINE"]["per_case"], systems[m]["per_case"])
                for m in ("QWEN_RAW", "QWEN_VALIDATED")}
        out.update(status="INDEPENDENTLY_EVALUATED", gold_cases=len(gold), systems=systems, baseline_vs_model=comp,
                   gate_result=se.apply_gate(gate, gdoc["cases"], gdoc["agreement"], systems[gate["evaluated_system"]], sets))
    (pkg / "metrics.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({k: out.get(k) for k in ("status", "reviewers", "gold_cases", "mode")}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--discipline", required=True)
    b.add_argument("--benchmark", required=True)
    b.add_argument("--subset", type=int, default=48)
    b.add_argument("--seed", default="semantic-validation-v1")
    b.add_argument("--version", default="v1")
    b.add_argument("--reviewers", type=int, default=2)
    b.add_argument("--reviewer-role", default="independent domain reviewer (faculty or practitioner of the discipline)")
    b.add_argument("--force", action="store_true")
    sub.add_parser("form").add_argument("--package", required=True)
    r = sub.add_parser("import-responses")
    r.add_argument("--package", required=True)
    r.add_argument("--file", required=True, help="the form's responses: .xlsx (every worksheet is read) or .csv")
    r.add_argument("--source", required=True, choices=("HUMAN_UNASSISTED", "HUMAN_AI_ASSISTED", "NOT_STATED"),
                   help="how the answers were produced, as stated by the reviewers or whoever collected them")
    r.add_argument("--reviewers", help="comma-separated reviewer ids to import (default: every reviewer in the file)")
    r.add_argument("--note", help="the statement behind --source, kept with every record")
    c = sub.add_parser("compare-responses")
    c.add_argument("--package", required=True)
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)
    c.add_argument("--out", help="also write both reviewers' records as CSV")
    for name in ("import-form", "import-sheet", "agreement", "adjudication-sheet", "adjudicate", "freeze", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--package", required=True)
        if name in ("import-form", "import-sheet"):
            p.add_argument("--attestation", required=True,
                           help="who confirmed that each reviewer answered alone, without AI tools or system output, "
                                "and how (kept in the label file)")
        if name == "import-form":
            p.add_argument("--csv", required=True)
            p.add_argument("--long-out", help="also write case_id,reviewer_id,relationship_label,confidence,reasoning,timestamp")
        if name == "import-sheet":
            p.add_argument("--file", required=True)
            p.add_argument("--reviewer", required=True)
        if name == "adjudicate":
            p.add_argument("--file", required=True)
            p.add_argument("--adjudicator", required=True)
        if name == "evaluate":
            p.add_argument("--predictions", default=str(ROOT / "data/semantic_runs/qwen-270-v3/analysis/benchmark_predictions.jsonl"))
            p.add_argument("--gate", default="data/evaluation/semantic_gate_v3.json")
    a = ap.parse_args()
    {"build": build, "form": form_cmd, "import-form": import_form, "import-sheet": import_sheet, "agreement": agreement_cmd,
     "adjudication-sheet": adjudication_sheet, "adjudicate": adjudicate, "freeze": freeze, "evaluate": evaluate,
     "import-responses": import_responses, "compare-responses": compare_responses}[a.cmd](a)
