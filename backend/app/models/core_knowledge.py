"""
Core Discipline Knowledge Layer.

WHY THIS IS SEPARATE FROM INDUSTRY DEMAND AND ESCO: a discipline's
academically-recognized core knowledge (e.g. what ECE fundamentally covers)
is a DIFFERENT kind of fact from "what job postings currently ask for" or
"how ESCO happens to label a skill" -- conflating them would let a
temporary industry fad silently stand in for foundational academic
knowledge, or vice versa. See docs/core_knowledge_methodology.md.

PROVENANCE: reuses app.models.data_source.DataSource rather than a parallel
system -- DataSource.source_type is free-text, so this layer's new source
kinds (ACADEMIC_FRAMEWORK, UNIVERSITY_CURRICULUM, PROFESSIONAL_BODY,
INDUSTRY_JOB, ESCO, OTHER) are just string values in that existing column --
no schema change was needed there.

MAPPING HUB: CoreKnowledgeSkillMapping links to the canonical Skill table
(app.models.skills.Skill), which is already ESCO/O*NET-taxonomy-aware. This
means "CoreTopic -> ESCO Skill" (spec Phase 3) is achieved TRANSITIVELY
through this one mapping table -- a duplicate "core topic to ESCO" table
was deliberately not created. Similarly "JOB_SKILL -> CORE_TOPIC" is
achieved transitively via ExtractedSkill -> Skill -> CoreKnowledgeSkillMapping
-> CoreTopic; no direct job-to-core-topic table exists or is needed.

EMPTY BY DESIGN THIS PHASE: no real domains/topics/subtopics/mappings are
inserted anywhere in this codebase. This is framework only. The only
exception is a clearly-labeled DEMO/TEST fixture under
data/external/demo_fixture/, following the same convention already used for
every other fixture in this project -- never usable as production data.
"""
from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, UniqueConstraint
from app.db.session import Base


class CoreKnowledgeDomain(Base):
    """Top-level academic knowledge area within a Discipline. is_active lets
    a superseded/retracted domain be deactivated without deleting its
    provenance trail."""
    __tablename__ = "core_knowledge_domains"
    __table_args__ = (UniqueConstraint("discipline_id", "name", name="uq_core_domain_discipline_name"),)
    id = Column(Integer, primary_key=True)
    discipline_id = Column(Integer, ForeignKey("disciplines.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)
    confidence = Column(Float, nullable=True)
    is_active = Column(Integer, default=1)


class CoreTopic(Base):
    __tablename__ = "core_topics"
    __table_args__ = (UniqueConstraint("domain_id", "name", name="uq_core_topic_domain_name"),)
    id = Column(Integer, primary_key=True)
    domain_id = Column(Integer, ForeignKey("core_knowledge_domains.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)
    confidence = Column(Float, nullable=True)
    is_active = Column(Integer, default=1)


class CoreSubtopic(Base):
    __tablename__ = "core_subtopics"
    __table_args__ = (UniqueConstraint("topic_id", "name", name="uq_core_subtopic_topic_name"),)
    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("core_topics.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)
    confidence = Column(Float, nullable=True)
    is_active = Column(Integer, default=1)


class CoreKnowledgeSkillMapping(Base):
    """Evidence-backed link from a core topic OR subtopic (exactly one of
    core_topic_id/core_subtopic_id is set) to a canonical Skill -- see this
    file's module docstring for why this single table also covers the
    "CoreTopic -> ESCO Skill" case."""
    __tablename__ = "core_knowledge_skill_mappings"
    __table_args__ = (
        UniqueConstraint("core_topic_id", "core_subtopic_id", "skill_id", name="uq_core_skill_mapping"),
    )
    id = Column(Integer, primary_key=True)
    core_topic_id = Column(Integer, ForeignKey("core_topics.id"), nullable=True, index=True)
    core_subtopic_id = Column(Integer, ForeignKey("core_subtopics.id"), nullable=True, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    method = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)


class CurriculumTopicCoreTopicMapping(Base):
    """Links a REAL, verbatim CurriculumTopic (extracted from an actual
    ingested curriculum document -- NEVER overwritten or normalized in
    place) to a canonical CoreTopic. Both wordings remain independently
    queryable and traceable."""
    __tablename__ = "curriculum_topic_core_topic_mappings"
    __table_args__ = (
        UniqueConstraint("curriculum_topic_id", "core_topic_id", name="uq_curriculum_core_topic_mapping"),
    )
    id = Column(Integer, primary_key=True)
    curriculum_topic_id = Column(Integer, ForeignKey("curriculum_topics.id"), nullable=False, index=True)
    core_topic_id = Column(Integer, ForeignKey("core_topics.id"), nullable=False, index=True)
    method = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=True)
    analysis_run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=True)
