from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, UniqueConstraint
from app.db.session import Base


class AnalysisRun(Base):
    """
    One row per pipeline execution (spec Section 35/42 — reproducibility).
    Every downstream result (alignment, gap, drift, recommendation) links back to
    the run that produced it, along with the exact dataset/model/config versions
    used, so results can be reproduced or audited later.
    """
    __tablename__ = "analysis_runs"
    id = Column(Integer, primary_key=True)
    run_type = Column(String(32), nullable=False, default="ingestion")  # ingestion | analysis
    dataset_name = Column(String(64), nullable=True, index=True)  # esco | onet | job_postings | curriculum
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)
    status = Column(String(32), nullable=False, default="pending")  # pending|running|succeeded|failed
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    records_processed = Column(Integer, nullable=True)
    records_failed = Column(Integer, nullable=True)
    dataset_version = Column(String(64), nullable=True)
    pipeline_version = Column(String(32), nullable=True)
    embedding_model_name = Column(String(255), nullable=True)
    embedding_model_version = Column(String(32), nullable=True)
    taxonomy_version = Column(String(64), nullable=True)
    record_counts_json = Column(Text, nullable=True)  # e.g. {"job_postings": 12400, "courses": 38}
    error_log = Column(Text, nullable=True)
    population_scope = Column(String(64), nullable=True)
    # "global" (spans all postings/courses, no programme concept -- e.g. industry
    # demand, "overall"-level curriculum coverage, historical trends) or
    # "programme:<programme_id>" (e.g. curriculum drift, which is inherently
    # tied to two CurriculumVersion rows of one programme). NULL means the
    # run predates this field or genuinely has no determinable scope -- never
    # treated as automatically compatible with anything. See
    # app.analytics.run_compatibility for how this is used.


class IngestionRejection(Base):
    """
    One row per record dropped or flagged during ingestion/preprocessing, with
    the reason it was dropped (spec: "Track records removed during preprocessing
    and WHY they were removed."). This is what the Data Quality dashboard's
    "inspect problematic records" view reads from — never just a discarded count.
    """
    __tablename__ = "ingestion_rejections"
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    dataset_name = Column(String(64), nullable=False)
    record_identifier = Column(String(255), nullable=True)  # e.g. source row index or external id
    reason = Column(String(64), nullable=False, index=True)  # e.g. empty_description | missing_title_and_description
    detail = Column(Text, nullable=True)
    raw_snippet = Column(Text, nullable=True)  # small excerpt for inspection, not the full record


class AlignmentResult(Base):
    """
    Course/programme-level TEXT alignment (TF-IDF) and SKILL-SET alignment
    (Jaccard) -- deliberately kept as separate columns, never combined into
    one composite score (spec: no arbitrary weighted score). combined_alignment
    stays NULL until a validated methodology for combining them exists.

    entity_id is NULL for an "overall" level row (e.g. the single dataset-wide
    skill-set Jaccard score) where there is no single course/programme this
    result belongs to -- NULL here means "not applicable", never a fabricated
    placeholder id.
    """
    __tablename__ = "alignment_results"
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    level = Column(String(16), nullable=False)  # programme | course | module | skill | overall
    entity_id = Column(Integer, nullable=True)  # id within that level's table; NULL for "overall"
    tfidf_alignment = Column(Float, nullable=True)  # text_alignment_score -- see app.analytics.tfidf_alignment
    skill_set_alignment = Column(Float, nullable=True)  # Jaccard score -- see app.analytics.skill_set_alignment
    semantic_alignment = Column(Float, nullable=True)  # reserved for future embedding-based alignment; unused this phase
    combined_alignment = Column(Float, nullable=True)  # NOT populated this phase -- see class docstring
    demand_weighted_coverage = Column(Float, nullable=True)  # NOT populated this phase (later GOLD skill-gap phase)
    vocabulary_size = Column(Integer, nullable=True)  # TF-IDF provenance
    reference_doc_length = Column(Integer, nullable=True)  # TF-IDF provenance
    # source_population_size: the ACTUAL number of source documents that
    # contributed non-empty text to this comparison (e.g. postings with a
    # non-empty clean_description that went into the TF-IDF reference corpus;
    # or, for the skill-set alignment row, the industry skill count). This is
    # deliberately NOT the same as the broader eligible population, which may
    # include records with no usable text/evidence -- see
    # eligible_source_population_size for that broader count.
    source_population_size = Column(Integer, nullable=True)
    target_population_size = Column(Integer, nullable=True)  # same "actual contributor" semantics, target side
    eligible_source_population_size = Column(Integer, nullable=True)  # broader population before text/evidence filtering (e.g. all eligible non-duplicate postings, regardless of whether they had usable text)
    method_config_json = Column(Text, nullable=True)  # e.g. {"ngram_range": [1,2], "min_df": 1, "stop_words": "english"}


class CurriculumSkillCoverage(Base):
    """
    GOLD: per-skill curriculum coverage at a given aggregation level
    (spec Section 4/5). courses_with_skill / eligible_courses is the
    coverage_percentage denominator -- both are always stored together so the
    population is never ambiguous.
    """
    __tablename__ = "curriculum_skill_coverage"
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    level = Column(String(16), nullable=False)  # "programme" | "institution" | "overall"
    entity_id = Column(Integer, nullable=True)  # programme_id or institution_id; NULL for "overall"
    courses_with_skill = Column(Integer, nullable=False)
    eligible_courses = Column(Integer, nullable=False)  # the denominator -- always stored explicitly
    coverage_percentage = Column(Float, nullable=True)
    topics_with_skill = Column(Integer, nullable=False, default=0)
    outcomes_with_skill = Column(Integer, nullable=False, default=0)


class SkillAlignment(Base):
    """
    GOLD: the per-skill industry-demand-vs-curriculum-coverage comparison
    (spec Section 6). classification is a transparent, threshold-based label
    -- NOT a recommendation (see app.analytics.skill_set_alignment.classify_demand_coverage).
    thresholds_used_json records exactly which threshold values produced this
    classification, so a later config change doesn't retroactively make old
    results ambiguous.
    """
    __tablename__ = "skill_alignments"
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    industry_posting_count = Column(Integer, nullable=True)
    industry_demand_percentage = Column(Float, nullable=True)
    curriculum_course_count = Column(Integer, nullable=True)
    curriculum_coverage_percentage = Column(Float, nullable=True)
    demand_rank = Column(Integer, nullable=True)  # 1 = highest demand among skills in this run
    coverage_rank = Column(Integer, nullable=True)
    classification = Column(String(32), nullable=True)  # HIGH_DEMAND_LOW_COVERAGE | ... | NULL if either side has no evidence
    thresholds_used_json = Column(Text, nullable=True)  # e.g. {"high_demand_threshold": 0.15, "high_coverage_threshold": 0.15}


class SkillGap(Base):
    """
    GOLD: evidence-based curriculum gap classification for a canonical skill
    (spec: MISSING | PARTIAL | COVERED | INSUFFICIENT_EVIDENCE -- never
    "outdated", never a numeric score). This model existed as an unused
    placeholder before this phase; extended here rather than duplicated.

    industry_demand / curriculum_coverage are nullable: NULL means no
    population/evidence was available for that side (see
    app.analytics.skill_set_alignment.resolve_evidence_value) -- NEVER
    silently treated as 0. gap_score is left NULL/unpopulated by design: the
    spec explicitly forbids inventing an arbitrary numeric score to rank
    these states; the column is kept only for backward compatibility /
    potential future use once a validated scoring methodology exists.
    trend_label and drift_status are separate EVIDENCE DIMENSIONS, never
    folded into classification -- a skill can be MISSING + TRENDING_UP just
    as easily as MISSING + INSUFFICIENT_DATA.
    """
    __tablename__ = "skill_gaps"
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    industry_demand = Column(Float, nullable=True)  # NULL = no industry evidence, NOT 0%
    curriculum_coverage = Column(Float, nullable=True)  # NULL = no curriculum evidence, NOT 0%
    semantic_similarity = Column(Float, nullable=True)  # reserved; not populated this phase
    high_demand = Column(Integer, nullable=True)  # 0/1 boolean; NULL if industry_demand is NULL (see model docstring)
    trend_label = Column(String(24), nullable=True)  # TRENDING_UP | TRENDING_DOWN | STABLE | INSUFFICIENT_DATA -- passthrough from SkillDemand, evidence only
    drift_status = Column(String(24), nullable=True)  # SKILL_ADDED | ... -- passthrough from CurriculumSkillDrift, evidence only, optional
    trend_compatibility = Column(String(24), nullable=True)  # COMPATIBLE | INCOMPATIBLE_SCOPE | UNKNOWN_SCOPE | NO_RUN -- see app.analytics.run_compatibility
    drift_compatibility = Column(String(24), nullable=True)  # same vocabulary; drift is inherently programme-scoped while demand/coverage are "global", so this is very often INCOMPATIBLE_SCOPE by construction -- see docs/gap_classification_methodology.md
    gap_score = Column(Float, nullable=True)  # NOT populated this phase -- see class docstring
    classification = Column(String(24), nullable=False)  # MISSING | PARTIAL | COVERED | INSUFFICIENT_EVIDENCE
    evidence_state = Column(String(24), nullable=False)  # BOTH_MEASURED | NO_INDUSTRY_EVIDENCE | NO_CURRICULUM_EVIDENCE | NO_EVIDENCE
    reasons_json = Column(Text, nullable=True)  # human-readable explanation list -- explainability (spec Section 9)
    thresholds_used_json = Column(Text, nullable=True)  # e.g. {"high_demand_threshold": 0.15, "partial_coverage_threshold": 0.4}
    source_demand_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True)
    source_coverage_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True)
    source_trend_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True)
    source_drift_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True)


class DriftResult(Base):
    __tablename__ = "drift_results"
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    programme_id = Column(Integer, ForeignKey("programmes.id"), nullable=False, index=True)
    time_bucket = Column(String(16), nullable=False)
    alignment_score = Column(Float, nullable=False)
    drift_score = Column(Float, nullable=False)
    drift_type = Column(String(32), nullable=False)  # versioned_drift | industry_relative_drift
    notes = Column(Text, nullable=True)


class Recommendation(Base):
    """
    GOLD: deterministic, evidence-based curriculum action derived from a
    SkillGap classification (spec: ADD_NEW_SUBJECT | ADD_ELECTIVE |
    ADD_MODULE | UPDATE_EXISTING_TOPIC | EXPAND_EXISTING_TOPIC |
    REVIEW_EXISTING_COURSE, or no action at all). This model existed as an
    unused placeholder before this phase; extended here rather than
    duplicated.

    No priority/score column is populated: the spec explicitly forbids an
    arbitrary "Recommendation Score". `priority` is kept only for backward
    compatibility and stays NULL until a validated prioritization
    methodology is designed separately (same precedent as
    SkillGap.gap_score).

    current_coverage / industry_demand are nullable for the same
    None-vs-zero reasons as SkillGap. A UniqueConstraint on
    (analysis_run_id, skill_id) prevents one classification run from ever
    accidentally producing two recommendation rows for the same skill.
    """
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "skill_id", name="uq_recommendation_run_skill"),
    )
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True, index=True)  # primary target course, if any (see target_course_codes_json for the full list)
    current_coverage = Column(Float, nullable=True)  # NULL = no curriculum evidence, NOT 0%
    industry_demand = Column(Float, nullable=True)  # NULL = no industry evidence, NOT 0%
    trend_label = Column(String(24), nullable=True)
    drift_status = Column(String(24), nullable=True)
    recommendation_state = Column(String(32), nullable=False)
    # RECOMMENDATION_SUPPORTED | INSUFFICIENT_EVIDENCE | NO_ACTION_INDICATED
    action_type = Column(String(32), nullable=True)  # NULL when recommendation_state != RECOMMENDATION_SUPPORTED
    # ADD_NEW_SUBJECT | ADD_ELECTIVE | ADD_MODULE | UPDATE_EXISTING_TOPIC | EXPAND_EXISTING_TOPIC | REVIEW_EXISTING_COURSE
    target_level = Column(String(16), nullable=True)  # PROGRAMME | COURSE | NULL
    target_course_codes_json = Column(Text, nullable=True)  # e.g. ["CS301", "CS405"] -- course codes actually found to carry evidence, never invented
    grouped_skill_ids_json = Column(Text, nullable=True)  # other skill_ids grouped into this same recommendation, only when real SkillRelationship data supports it
    evidence_json = Column(Text, nullable=False)  # the structured gap-classification evidence this recommendation was built from
    reasons_json = Column(Text, nullable=False)  # human-readable, field-derived explanation list -- never hardcoded text
    priority = Column(String(16), nullable=True)  # NOT populated this phase -- see class docstring
    source_gap_classification_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True)


class CurriculumSkillDrift(Base):
    """
    GOLD: per-skill comparison between two CurriculumVersion snapshots of the
    SAME programme (spec Section 8). status is a purely DESCRIPTIVE
    classification -- never interpreted as good/bad, never labeled
    "outdated" automatically. Course-level drift (which specific courses/
    skills changed) is computed by the same pure functions but is written
    only to the GOLD artifact, not a separate DB table -- see
    docs/temporal_methodology.md for why a dedicated course-drift table was
    judged unnecessary (avoiding over-modeling per spec Section 10).
    """
    __tablename__ = "curriculum_skill_drifts"
    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False, index=True)
    previous_curriculum_version_id = Column(Integer, ForeignKey("curriculum_versions.id"), nullable=False, index=True)
    current_curriculum_version_id = Column(Integer, ForeignKey("curriculum_versions.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    previous_coverage_percentage = Column(Float, nullable=True)  # NULL = no evidence in the previous version (not 0%)
    current_coverage_percentage = Column(Float, nullable=True)  # NULL = no evidence in the current version (not 0%)
    absolute_change = Column(Float, nullable=True)  # current - previous, in percentage points; NULL if either side is NULL
    status = Column(String(24), nullable=False)
    # SKILL_ADDED | SKILL_REMOVED | COVERAGE_INCREASED | COVERAGE_DECREASED | UNCHANGED | INSUFFICIENT_DATA
