from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.session import Base


class Skill(Base):
    """
    A normalized skill concept. `taxonomy` distinguishes ESCO vs O*NET rows —
    they are NOT merged into one ID space (spec Section 10: "Do not assume ESCO
    and O*NET IDs are interchangeable"). Cross-taxonomy links live in
    SkillCrosswalk below, with an explicit method + confidence.
    """
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True)
    taxonomy = Column(String(16), nullable=False, index=True)  # "ESCO" | "ONET"
    external_id = Column(String(128), nullable=False, index=True)  # ESCO URI or O*NET code
    preferred_label = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    skill_group = Column(String(255), nullable=True)

    __table_args__ = (UniqueConstraint("taxonomy", "external_id", name="uq_skill_taxonomy_external_id"),)

    aliases = relationship("SkillAlias", back_populates="skill")


class SkillAlias(Base):
    __tablename__ = "skill_aliases"
    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    alias_label = Column(String(512), nullable=False, index=True)

    skill = relationship("Skill", back_populates="aliases")


class SkillRelationship(Base):
    """Hierarchy / broader-narrower / related relationships within one taxonomy."""
    __tablename__ = "skill_relationships"
    id = Column(Integer, primary_key=True)
    source_skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    target_skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    relationship_type = Column(String(32), nullable=False)  # broader | narrower | related


class SkillCrosswalk(Base):
    """
    Explicit ESCO <-> O*NET mapping layer (spec Section 10: "Create an explicit
    crosswalk/mapping layer"). No official crosswalk exists — this is generated
    by this project's own alias + embedding matching (Phase 6+), and every row
    carries its own method/confidence rather than being treated as ground truth.
    """
    __tablename__ = "skill_crosswalk"
    id = Column(Integer, primary_key=True)
    esco_skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    onet_skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    method = Column(String(64), nullable=False)  # exact_alias | embedding_similarity | manual
    confidence = Column(Float, nullable=False)


class SkillEmbedding(Base):
    """
    Cached embedding (Section 38): keyed by (entity type/id, text_hash, model_name,
    model_version) so re-running the pipeline never regenerates an embedding for
    text that hasn't changed.
    """
    __tablename__ = "skill_embeddings"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String(32), nullable=False)  # skill | curriculum_topic | job_skill_span
    entity_id = Column(Integer, nullable=False, index=True)
    text_hash = Column(String(64), nullable=False, index=True)
    model_name = Column(String(255), nullable=False)
    model_version = Column(String(32), nullable=False)
    vector_json = Column(Text, nullable=False)  # serialized vector; swap for pgvector column in Postgres migration

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "text_hash", "model_name", "model_version", name="uq_embedding_cache_key"),
    )
