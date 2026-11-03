from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, UniqueConstraint, Index
from app.db.session import Base


class Occupation(Base):
    __tablename__ = "occupations"
    id = Column(Integer, primary_key=True)
    taxonomy = Column(String(16), nullable=False, index=True)  # ESCO | ONET
    external_id = Column(String(128), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)


class IndustryDomain(Base):
    """
    Data/configuration-driven industry-domain reference table (e.g.
    "Software & IT Services", "Electronics Manufacturing", "Automotive"),
    mirroring app.models.curriculum.Discipline's design: a reference table,
    not a hardcoded enum, extensible by inserting rows. NOT populated with
    fabricated classifications by this project -- see JobPosting.industry_domain_id.
    """
    __tablename__ = "industry_domains"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)


class JobDiscipline(Base):
    """
    Many-to-many: a single job posting can be relevant to more than one
    engineering discipline (spec Section 4 -- "do not force every job into
    exactly one discipline"). Deliberately NOT populated with invented
    classifications by any code in this project; `method`/`confidence`
    exist so that a FUTURE real classifier (e.g. skill-evidence-based
    inference, or a taxonomy mapping) can populate this table with its
    provenance intact, rather than this schema silently assuming a
    classification exists where none has actually been computed.
    """
    __tablename__ = "job_disciplines"
    __table_args__ = (
        UniqueConstraint("job_posting_id", "discipline_id", name="uq_job_discipline"),
    )
    id = Column(Integer, primary_key=True)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False, index=True)
    discipline_id = Column(Integer, ForeignKey("disciplines.id"), nullable=False, index=True)
    method = Column(String(64), nullable=True)  # e.g. "skill_evidence_inference" -- NULL until a real method populates this
    confidence = Column(Float, nullable=True)


class JobPosting(Base):
    """
    Silver-layer job posting. RAW_DESCRIPTION and CLEAN_DESCRIPTION are both kept
    (spec Section 8 + 46) so the dashboard's per-record inspection view (Section 45)
    can show raw -> clean side by side.

    PHASE-1 HARDENING: (source_id, external_posting_id) is unique whenever
    external_posting_id is present, so the DB itself rejects a true duplicate
    insert even if the application-level idempotency check in
    app.pipelines.ingestion.job_postings were ever bypassed or buggy -- this is
    the "do not rely only on Python-side checks" requirement. Both Postgres and
    SQLite treat multiple NULLs as distinct under a UNIQUE constraint, so
    postings without an external id (some real datasets don't have one) are
    unaffected. clean_description_hash is indexed separately to support a
    cheap, exact cross-run duplicate check without a full-table text scan.
    """
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_posting_id", name="uq_job_posting_source_external_id"),
        Index("ix_job_posting_clean_description_hash", "clean_description_hash"),
    )
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)
    external_posting_id = Column(String(128), nullable=True, index=True)
    job_title = Column(String(512), nullable=True)
    company_name = Column(String(255), nullable=True)
    location = Column(String(255), nullable=True)
    posted_date = Column(DateTime, nullable=True, index=True)
    salary_raw = Column(String(128), nullable=True)
    occupation_id = Column(Integer, ForeignKey("occupations.id"), nullable=True)
    industry_domain_id = Column(Integer, ForeignKey("industry_domains.id"), nullable=True)  # NULL until a real classifier populates it -- never fabricated

    raw_description = Column(Text, nullable=False)
    clean_description = Column(Text, nullable=True)
    clean_description_hash = Column(String(64), nullable=True)  # sha256 of clean_description; see Index above
    skills_raw = Column(Text, nullable=True)  # e.g. Naukri's comma-separated "skills" tag column, kept verbatim

    is_duplicate = Column(Integer, default=0)  # 0/1
    duplicate_of_id = Column(Integer, ForeignKey("job_postings.id"), nullable=True)
    duplicate_scope = Column(String(24), nullable=True)  # "within_batch" | "cross_run" -- see deduplication docstring

    ingested_at = Column(DateTime, default=datetime.utcnow)


class ExtractedSkill(Base):
    """
    A SKILL MENTION: evidence that a source actually referred to a skill --
    deliberately NOT the same concept as Skill (the canonical taxonomy entity,
    in app.models.skills). A mention may or may not resolve to a canonical
    skill (mapping_status); an unmapped mention is preserved, never discarded,
    per the project's "no false positives" rule.

    Exactly one of job_posting_id / course_id / curriculum_topic_id /
    course_learning_outcome_id should be set, identifying where the mention
    was found: course_id for a course-title-level mention, curriculum_topic_id
    for a syllabus topic, course_learning_outcome_id for a learning outcome,
    job_posting_id for a job description or its structured skills tag field.
    """
    __tablename__ = "extracted_skills"
    __table_args__ = (
        Index("ix_extracted_skill_mention_hash", "mention_hash"),
    )
    id = Column(Integer, primary_key=True)

    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True, index=True)
    curriculum_topic_id = Column(Integer, ForeignKey("curriculum_topics.id"), nullable=True, index=True)
    course_learning_outcome_id = Column(Integer, ForeignKey("course_learning_outcomes.id"), nullable=True, index=True)

    original_text_span = Column(String(512), nullable=False)  # raw mention exactly as found in the source text
    normalized_text_span = Column(String(512), nullable=True)  # case/whitespace-normalized form used for matching
    normalized_skill_id = Column(Integer, ForeignKey("skills.id"), nullable=True, index=True)
    mapping_status = Column(String(16), nullable=False, default="unmapped")  # "mapped" | "unmapped"
    extraction_method = Column(String(32), nullable=False)
    # structured_tag | exact_label | alias | normalized_label | technical_token
    confidence = Column(Float, nullable=False)
    context_snippet = Column(Text, nullable=True)
    page_or_section = Column(String(64), nullable=True)

    mention_hash = Column(String(64), nullable=True)  # idempotency key -- see app.pipelines.ingestion.skill_extraction
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True, index=True)


class JobSkillRelation(Base):
    __tablename__ = "job_skill_relations"
    id = Column(Integer, primary_key=True)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)


class CurriculumSkillRelation(Base):
    __tablename__ = "curriculum_skill_relations"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    coverage_strength = Column(Float, nullable=True)  # e.g. 1.0 explicit, 0.5 partial/implied


class SkillDemand(Base):
    """
    Per (skill, time_bucket) real demand statistics computed from job_postings.
    Never hardcoded — written only by the analytics stage (Section 14/15).

    time_bucket="overall" (written by run_industry_demand_analysis) represents
    a non-temporal, all-time snapshot. A real period bucket (e.g. "2026-01",
    "2026-Q1", "2026", written by run_historical_industry_demand) additionally
    populates period_start/period_end so the exact date range is unambiguous
    -- time_bucket alone is a label, period_start/end are the actual boundary
    dates used to select postings into that bucket.
    """
    __tablename__ = "skill_demand"
    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    time_bucket = Column(String(16), nullable=False)  # e.g. "2024-Q3", or "overall"
    period_start = Column(DateTime, nullable=True)  # NULL for "overall" (non-temporal) rows
    period_end = Column(DateTime, nullable=True)
    posting_count = Column(Integer, nullable=False)
    total_relevant_postings = Column(Integer, nullable=False)
    demand_percentage = Column(Float, nullable=False)
    growth_rate = Column(Float, nullable=True)  # relative change vs. the immediately preceding period, if computed
    trend_label = Column(String(24), nullable=True)  # TRENDING_UP | TRENDING_DOWN | STABLE | INSUFFICIENT_DATA
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True)
