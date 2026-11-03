"""
Industry / ESCO layer tests. Fixtures reproduce the SHAPE of the real
supplied files (ESCO v1.2.1 delta rows, job-board export rows); no test
depends on a real company, institution or subject.
"""
import csv
import io
import random
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge_engine import industry as ind
from app.knowledge_engine.config import load_config
from app.knowledge_engine.esco_delta import EXPECTED_COLUMNS, build_skill_vocabulary, read_delta_rows
from app.knowledge_engine.evidence_guard import CircularEvidenceError, require_source_path, require_source_records
from app.knowledge_engine.health import FAIL, analytics_gates, industry_health
from app.knowledge_engine.industry_stage import verify_sources
from app.knowledge_engine.jobs import ingest_postings, posting_identity, population_scope
from app.knowledge_engine.quarantine import Quarantine
from app.knowledge_engine.semantic_backend import TfidfBackend
from app.pipelines.preprocessing.skill_extraction import (
    IndexedVocabulary, build_vocabulary_index, extract_mentions_from_text, extract_mentions_indexed,
)

CFG = load_config()
SETTINGS = {"high_demand_threshold": 0.15, "partial_coverage_threshold": 0.4, "min_periods_for_trend": 2,
            "min_eligible_postings_per_period": 30, "min_skill_postings_for_trend": 5}
U = "http://data.europa.eu/esco/skill/"
SQL, SQL2, JS, PY, PM, COMM = (U + f"{i:08d}-0000-0000-0000-000000000000" for i in range(6))


def _delta_zip(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPECTED_COLUMNS)
    w.writerows(rows)
    path = Path(tempfile.mkdtemp()) / "delta.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("/delta.csv", buf.getvalue())
    return path


def _vocab():
    rows = [
        [SQL, "SQL", "altLabel", "None", "structured query language", "Added", "en"],
        [SQL, "SQL", "altLabel", "sequel old", "None", "Removed", "en"],
        [SQL2, "SQL Server", "description", "old", "new", "Updated", "en"],
        [JS, "JavaScript", "altLabel", "JS old", "JS", "Updated", "en"],
        [PY, "Python (computer programming)", "prefLabel", "Python (computer programming) ", "Python (computer programming)", "Updated", "en"],
        [PM, "project management", "altLabel", "None", "shared label", "Added", "en"],
        [SQL2, "SQL Server", "altLabel", "None", "shared label", "Added", "en"],
        [COMM, "communication", "altLabel", "None", "Kommunikation", "Added", "de"],
        [U + "A1.9.0", "skill group", "prefLabel", "x", "y", "Updated", "en"],
        ["http://data.europa.eu/ux2/nace2.1/532", "53.2 postal", "inScheme", "None", "scheme", "Added", "None"],
    ]
    return build_skill_vocabulary(read_delta_rows(_delta_zip(rows)))


# ---------------- ESCO delta semantics ----------------

def test_delta_semantics_added_updated_removed():
    vocab, audit = _vocab()
    labels = {(l["uri"], l["label"], l["label_kind"]) for l in vocab["labels"]}
    assert (SQL, "structured query language", "altLabel") in labels          # Added -> active
    assert (JS, "JS", "altLabel") in labels                                   # Updated new value -> active
    retired = {(r["uri"], r["label"]) for r in vocab["retired_labels"]}
    assert (SQL, "sequel old") in retired and (JS, "JS old") in retired        # Removed / Updated old -> retired
    assert not any(l["label"] in ("sequel old", "JS old") for l in vocab["labels"])
    assert (PY, "Python", "qualifier_stripped") in labels
    assert audit["prefLabel_updates_whitespace_only"] == 1
    assert audit["rows_by_concept_type"]["skill-group"] == 1
    assert U + "A1.9.0" not in vocab["concepts"]                               # grouping node, never a mapping target
    assert audit["concept_level"]["unchanged_baseline"] is None                 # unknown, not zero
    assert audit["reconstruction_scope"] == "PARTIAL_DELTA_SUBSET"


def test_delta_header_is_verified():
    path = Path(tempfile.mkdtemp()) / "bad.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("delta.csv", "a,b\n1,2\n")
    try:
        list(read_delta_rows(path))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# ---------------- extraction ----------------

def test_indexed_extraction_is_identical_to_reference_extractor():
    vocab = build_vocabulary_index(
        [{"id": i, "external_id": str(i), "preferred_label": lab} for i, lab in
         enumerate(["SQL", "project management", "Java", "JavaScript", "C++", "manage budgets", "R", "machine learning"])],
        [{"skill_id": 1, "external_id": "1", "alias_label": "PM"}, {"skill_id": 3, "external_id": "3", "alias_label": "JS"}])
    index = IndexedVocabulary(vocab)
    rng = random.Random(7)
    words = ["SQL", "sql", "Java", "JavaScript", "javascript", "C++", "C", "R&D", "R", "project", "management",
             "Project Management", "manage  budgets", ".NET", "ASP.NET", "Node.js", "AWS", "Docker", "machine", "learning", ",", ".", "and"]
    for _ in range(300):
        text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 25)))
        a = [(m.original_text, m.method, m.start, m.end, m.skill_id) for m in extract_mentions_from_text(text, vocab)]
        b = [(m.original_text, m.method, m.start, m.end, m.skill_id) for m in extract_mentions_indexed(text, index)]
        assert sorted(a, key=lambda x: x[2]) == sorted(b, key=lambda x: x[2]), text


def test_context_dependent_labels_and_qualification_role():
    assert ind.label_is_context_dependent("communication")[0]
    assert ind.label_is_context_dependent("R")[0]
    assert ind.label_is_context_dependent("Python", ["qualifier_stripped"])[0]
    assert ind.label_is_context_dependent("Angular")[0]            # "Angular momentum" in a physics syllabus
    assert not ind.label_is_context_dependent("JavaScript")[0]
    assert not ind.label_is_context_dependent("C#")[0]
    assert not ind.label_is_context_dependent("SQL")[0]
    assert not ind.label_is_context_dependent("manage budgets")[0]
    text = "Strong SQL skills. Bachelor's degree in Computer Science or related field."
    assert ind.mention_role(text, text.index("SQL")) == "SKILL"
    assert ind.mention_role(text, text.index("Computer")) == "QUALIFICATION_REQUIREMENT"


def _mapped(texts):
    vocab, _ = _vocab()
    terms, label_index = ind.build_vocabulary(vocab)
    index = IndexedVocabulary(terms)
    records = [{"uid": f"p{i}", "text": t} for i, t in enumerate(texts)]
    mentions = ind.extract(records, "text", "uid", index, "job_posting")
    mappings = ind.map_skills(mentions, vocab, label_index, TfidfBackend, CFG["industry"])
    return mentions, mappings


def test_esco_mapping_states():
    _, m = _mapped(["We use SQL daily", "sql and structured query language", "Python scripting",
                    "shared label here", "Docker and Kubernetes"])
    assert m["sql"]["status"] in ("EXACT", "NORMALIZED")
    assert m["structured query language"]["status"] == "NORMALIZED"
    assert m["structured query language"]["mapping_method"] == "altLabel_active_after_delta"
    assert m["python"]["status"] == "INSUFFICIENT_EVIDENCE"                # bare word of a qualified prefLabel
    assert m["shared label"]["status"] == "AMBIGUOUS" and len(m["shared label"]["candidates"]) == 2
    assert m["docker"]["status"] == "UNMAPPED" and m["docker"]["esco_uri"] is None
    assert all(x["score_is_calibrated"] is False for x in m.values())
    assert m["docker"]["skill_category"] == "TECHNOLOGY_TOOL"


def test_retired_label_is_not_matched():
    mentions, _ = _mapped(["knowledge of sequel old systems"])
    assert not any(x["normalized_text"] == "sequel old" for x in mentions)


# ---------------- ingestion ----------------

def test_posting_identity_rules():
    assert posting_identity("https://www.linkedin.com/jobs/view/4468510458/") == ("linkedin", "4468510458", "url_external_id")
    assert posting_identity("https://indeed.com/viewjob?jk=bcbb9ea7ee83ecdc")[:2] == ("indeed", "bcbb9ea7ee83ecdc")
    assert posting_identity("http://in.indeed.com/job/officer-bcbb9ea7ee83ecdc")[:2] == ("indeed", "bcbb9ea7ee83ecdc")
    assert posting_identity("https://www.naukri.com/job-listings-manager-bengaluru-9-to-14-years-070826025488")[:2] == ("naukri", "070826025488")
    assert posting_identity("https://www.naukri.com/job-listings-220926901644")[:2] == ("naukri", "220926901644")
    platform, ext, method = posting_identity("https://jobs.example.com/Apply/123-role/?utm=x#top")
    assert (platform, method) == ("jobs.example.com", "canonical_url") and ext == "https://jobs.example.com/Apply/123-role"
    assert posting_identity("")[2] == "NO_URL"


def _xlsx(rows):
    import pandas as pd
    cols = ["job_title", "url", "source_url", "posted_date", "job_country_code", "is_remote", "employment_status",
            "seniority", "job_location", "job_description", "salary", "hiring_manager_full_name", "hiring_manager_first_name",
            "hiring_manager_role", "hiring_manager_linkedin_url", "company_name", "company_url", "company_linkedin_url",
            "company_industry", "company_employee_count", "company_revenue_usd", "company_seo_description",
            "company_description", "company_city"]
    path = Path(tempfile.mkdtemp()) / "jobs.xlsx"
    pd.DataFrame([{c: r.get(c) for c in cols} for r in rows]).to_excel(path, index=False, sheet_name="Jobs")
    return path


def test_ingestion_statuses_and_personal_data_dropped():
    desc = "Build data pipelines with SQL and Python for reporting teams across regions."
    rows = [
        {"job_title": "Data Engineer", "url": "https://www.linkedin.com/jobs/view/111/", "posted_date": "2026-09-22",
         "job_description": desc, "company_name": "Acme", "hiring_manager_full_name": "A Person"},
        {"job_title": "Data Engineer", "url": "https://linkedin.com/jobs/view/111", "posted_date": "2026-09-22",
         "job_description": desc + " Duplicate row.", "company_name": "Acme"},
        {"job_title": "Clerk", "url": "https://www.linkedin.com/jobs/view/222/", "posted_date": "2026-09-22",
         "job_description": "short", "company_name": "Beta"},
        {"job_title": "Analyst", "url": None, "posted_date": "2026-09-22", "job_description": desc, "company_name": "Gamma"},
    ]
    path = _xlsx(rows)
    tmp = Path(tempfile.mkdtemp())
    result = ingest_postings([{"source_id": "f1", "path": str(path), "abs_path": str(path), "sha256": "a" * 64}],
                             tmp / "bronze", tmp / "silver", 0.75)
    statuses = [r["status"] for r in sorted(result["records"], key=lambda r: r["row_number"])]
    assert statuses == ["ACCEPTED", "DUPLICATE", "REJECTED", "QUARANTINED"]
    assert all(r["reason"] for r in result["records"])
    assert len(result["postings"]) == 1
    bronze = (tmp / "bronze" / ("a" * 16) / "records.jsonl").read_text()
    assert "A Person" not in bronze and "hiring_manager" not in bronze
    scope = population_scope(result["postings"], [{"path": str(path)}])
    assert scope["eligible_postings"] == 1 and "not necessarily representative" in scope["representativeness_warning"]


# ---------------- demand / temporal ----------------

def _postings(n, companies):
    return [{"posting_uid": f"posting:{i:016x}", "company_key": companies[i % len(companies)], "posted_date": "2026-09-22"}
            for i in range(n)]


def test_posting_and_company_prevalence_are_separate():
    postings = _postings(10, ["one"] * 9 + ["two"])  # one employer with many postings
    pairs = [("skill:a", p["posting_uid"]) for p in postings[:6]]
    row = ind.demand(pairs, postings, {}, CFG["industry"])[0]
    assert row["posting_count"] == 6 and row["posting_prevalence_pct"] == 60.0
    assert row["company_count"] == 1 and row["eligible_companies"] == 2 and row["company_prevalence_pct"] == 50.0
    assert row["support_state"] == "OBSERVED"  # 6 postings but 1 company: below SUPPORTED's company minimum
    assert "not importance" in row["statement"]


def test_single_period_gives_no_trend():
    t = ind.temporal_demand([("s", "p")], _postings(100, ["a"]), SETTINGS)
    assert t["trend_status"] == "INSUFFICIENT_EVIDENCE" and t["trend_label_for_all_skills"] == "INSUFFICIENT_DATA"


# ---------------- gaps + recommendations ----------------

def _skill(key, status="EXACT"):
    return {"skill_key": key, "label": key, "esco_status": status, "esco_uri": key if status == "EXACT" else None}


def _gaps(target_cov, reference_cov, demand_rows, statuses=None):
    skills = {d["skill_key"]: _skill(d["skill_key"], (statuses or {}).get(d["skill_key"], "EXACT")) for d in demand_rows}
    return ind.classify_gaps(skills, demand_rows, target_cov, 100, reference_cov, {}, 100, SETTINGS, "scope:x", "run")


def _d(key, n, companies):
    return {"skill_key": key, "posting_count": n, "posting_prevalence_pct": float(n), "company_count": companies,
            "company_prevalence_pct": float(companies), "support_state": ind.support_state(n, companies, CFG["industry"])}


def test_gap_discipline_guard_and_none_vs_zero():
    demand_rows = [_d("inref", 6, 6), _d("nowhere", 20, 20), _d("taught", 6, 6)]
    target_cov = {"taught": {"courses_with_skill": 2, "coverage_percentage": 2.0, "course_codes": ["X1", "X2"]}}
    reference_cov = {"inref": {"courses_with_skill": 1}}
    gaps = {g["skill_key"]: g for g in _gaps(target_cov, reference_cov, demand_rows)}
    assert gaps["inref"]["classification"] == "MISSING" and gaps["inref"]["curriculum_coverage_pct"] == 0.0
    assert gaps["nowhere"]["classification"] == "INSUFFICIENT_EVIDENCE"
    assert gaps["nowhere"]["evidence_state"] == "DISCIPLINE_RELEVANCE_UNESTABLISHED"
    assert gaps["taught"]["classification"] == "PARTIAL"
    for g in gaps.values():
        for key in ("industry_population", "industry_count", "industry_prevalence_pct", "curriculum_population",
                    "curriculum_count", "curriculum_coverage_pct", "evidence_state", "reasons", "run_id", "population_scope_ref"):
            assert key in g


def test_every_gap_gets_a_recommendation_or_a_structured_suppression():
    demand_rows = [_d("inref", 6, 6), _d("weak", 2, 2), _d("amb", 8, 8), _d("taught", 6, 6)]
    target_cov = {"taught": {"courses_with_skill": 2, "coverage_percentage": 2.0, "course_codes": ["X1", "X2"]}}
    gaps = _gaps(target_cov, {"inref": {"courses_with_skill": 1}, "weak": {"courses_with_skill": 1},
                              "amb": {"courses_with_skill": 1}}, demand_rows, {"amb": "AMBIGUOUS"})
    recs, suppressed = ind.recommend(gaps, target_cov, CFG["industry"])
    assert len(recs) + len(suppressed) == len(gaps)
    by = {r["skill_key"]: r for r in recs}
    why = {s["skill_key"]: {w["code"] for w in s["reasons"]} for s in suppressed}
    assert "INDUSTRY_SUPPORT_BELOW_THRESHOLD" in why["weak"]
    assert "ESCO_MAPPING_AMBIGUOUS" in why["amb"]
    assert by["taught"]["action_type"] == "EXPAND_EXISTING_TOPIC" and by["taught"]["target_course_codes"] == ["X1", "X2"]
    assert by["inref"]["action_type"] in ("ADD_ELECTIVE", "ADD_NEW_SUBJECT", "ADD_MODULE")
    assert all(r["is_source_evidence"] is False and r["evidence_status"] == "MODEL_SUGGESTED" for r in recs)


# ---------------- circular evidence ----------------

def test_generated_outputs_cannot_become_source_evidence():
    repo = Path(tempfile.mkdtemp())
    for bad in ("data/gold/knowledge/run1/industry/recommendations.jsonl", "data/silver/jobs/x/postings.jsonl",
                "data/evaluation/semantic_benchmark.json", "exports/recommendations.csv"):
        try:
            require_source_path(bad, repo)
            raise AssertionError(f"{bad} accepted as source evidence")
        except CircularEvidenceError:
            pass
    assert require_source_path("data/raw/jobs/jobs.xlsx", repo) == "data/raw/jobs/jobs.xlsx"
    assert require_source_path("data/metadata/review_decisions.json", repo)
    rec = {"recommendation_uid": "rec:1", "action_type": "ADD_MODULE", "evidence_status": "MODEL_SUGGESTED", "is_source_evidence": False}
    for record in (rec, {"topic_uid": "t", "evidence_status": "MODEL_SUGGESTED"}):
        try:
            require_source_records([record], "curriculum topic")
            raise AssertionError("derived record accepted")
        except CircularEvidenceError:
            pass
    assert require_source_records([{"topic_uid": "t", "evidence_status": "EXTRACTED"}], "curriculum topic")


def test_manifest_pointing_at_recommendations_is_refused():
    manifest = {"industry_sources": [{"source_id": "loop", "path": "data/gold/knowledge/r/industry/recommendations.jsonl"}]}
    try:
        verify_sources(manifest, Path(tempfile.mkdtemp()), Quarantine())
        raise AssertionError("expected CircularEvidenceError")
    except CircularEvidenceError:
        pass


# ---------------- health gate ----------------

def _ind_summary(**over):
    base = {"files_expected": 4, "files_verified": 4, "records_read": 100, "duplicates": 0, "missing_description": 0,
            "eligible_postings": 100, "postings_with_skill": 70, "unique_normalized_skills": 130, "unique_skills_eligible": 100,
            "esco_mapped_skills": 90, "ambiguous_skills": 1, "postings_with_provenance": 100, "esco_skill_concepts": 9000,
            "mentions": 180}
    base.update(over)
    return base


BASE = {"eligible_postings": 100, "mentions": 180, "unique_skills_eligible": 100, "esco_mapped_skills": 90, "recorded_at": "t"}


def test_industry_health_passes_and_catastrophic_drop_fails():
    assert industry_health(_ind_summary(), CFG, BASE)["status"] == "PASS"
    dropped = industry_health(_ind_summary(mentions=12, postings_with_skill=10), CFG, BASE)
    assert dropped["status"] == FAIL
    failing = {c["check"] for c in dropped["checks"] if c["status"] == FAIL}
    assert {"baseline_regression", "skill_extraction_yield"} <= failing
    assert industry_health(_ind_summary(files_verified=3), CFG, BASE)["status"] == FAIL
    assert industry_health(_ind_summary(esco_mapped_skills=5), CFG, BASE)["status"] == FAIL


def test_failed_industry_health_blocks_demand_gaps_and_recommendations():
    gates = analytics_gates({"t": {"status": "PASS"}}, {"t": "TARGET"}, [], True, 100, CFG,
                            industry_health_status=FAIL, taxonomy_scope="PARTIAL_DELTA_SUBSET")
    assert gates["industry_demand"]["status"] == "BLOCKED"
    assert gates["industry_gap"]["status"] == "BLOCKED" and gates["recommendations"]["status"] == "BLOCKED"
    assert gates["skill_taxonomy"]["status"] == "ALLOWED" and gates["skill_taxonomy"]["scope"] == "PARTIAL_DELTA_SUBSET"
    ok = analytics_gates({"t": {"status": "PASS"}}, {"t": "TARGET"}, [], True, 100, CFG, industry_health_status="PASS")
    assert ok["industry_gap"]["status"] == "ALLOWED"
