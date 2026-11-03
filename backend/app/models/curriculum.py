from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.db.session import Base


class Institution(Base):
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    country = Column(String(128), nullable=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)

    programmes = relationship("Programme", back_populates="institution")


class Discipline(Base):
    """
    Data/configuration-driven engineering discipline grouping (e.g.
    "Computing & Data", "Electronics & Electrical", "Mechanical &
    Manufacturing") -- a REFERENCE TABLE, not a hardcoded enum. New
    disciplines can be added via a row insert at any time; nothing in the
    analytics layer hardcodes which disciplines exist. Seed data for the
    illustrative examples above lives in scripts/seed/, not in this file or
    in any analytics module.
    """
    __tablename__ = "disciplines"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)


class Department(Base):
    """A department within an institution, e.g. 'Dept. of Mechanical Engineering'."""
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    discipline_id = Column(Integer, ForeignKey("disciplines.id"), nullable=True, index=True)


class Programme(Base):
    __tablename__ = "programmes"
    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)  # nullable for backward compatibility with programmes ingested before this field existed
    name = Column(String(255), nullable=False)
    programme_code = Column(String(64), nullable=True)
    degree_level = Column(String(64), nullable=True)  # e.g. BTech, MSc
    specialization = Column(String(255), nullable=True)
    aliases_json = Column(Text, nullable=True)  # e.g. ["AI&DS", "AIDS", "Artificial Intelligence and Data Science"] -- how the SAME programme is referred to across different source documents; never used by analytics logic itself, purely for human/UI disambiguation
    is_active = Column(Integer, default=1)  # 0/1 boolean (sqlite-friendly)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)

    institution = relationship("Institution", back_populates="programmes")
    courses = relationship("Course", back_populates="programme")
    curriculum_versions = relationship("CurriculumVersion", back_populates="programme")


class CurriculumVersion(Base):
    """
    Explicit versioning so real curriculum-drift analysis (Case A, Section 19) is
    possible when multiple versions exist, and honestly labeled as
    'industry-relative drift' when only one exists (Case B).
    """
    __tablename__ = "curriculum_versions"
    id = Column(Integer, primary_key=True)
    programme_id = Column(Integer, ForeignKey("programmes.id"), nullable=False, index=True)
    version_label = Column(String(64), nullable=False)  # e.g. "2021", "v2"
    effective_period = Column(String(64), nullable=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)

    programme = relationship("Programme", back_populates="curriculum_versions")


class Document(Base):
    """Raw ingested curriculum document (PDF/TXT/CSV/DOCX) + extraction metadata."""
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    file_name = Column(String(512), nullable=False)
    file_type = Column(String(16), nullable=False)
    raw_path = Column(String(1024), nullable=False)  # bronze layer path
    extracted_text_path = Column(String(1024), nullable=True)  # silver layer path
    page_count = Column(Integer, nullable=True)
    extraction_method = Column(String(64), nullable=True)  # e.g. pdfplumber, ocr_fallback
    extraction_confidence = Column(Float, nullable=True)  # 0-1; low confidence => flagged, not silently trusted
    flagged_for_review = Column(Integer, default=0)  # 0/1 boolean (sqlite-friendly)
    # what the document is for (data/metadata/document_roles.json: TARGET, PREVIOUS_VERSION, PEER, REFERENCE,
    # GENERAL_REFERENCE); nullable for documents ingested before the role existed
    document_role = Column(String(32), nullable=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    programme_id = Column(Integer, ForeignKey("programmes.id"), nullable=False, index=True)
    curriculum_version_id = Column(Integer, ForeignKey("curriculum_versions.id"), nullable=True, index=True)
    course_code = Column(String(64), nullable=True)
    name = Column(String(255), nullable=False)

    programme = relationship("Programme", back_populates="courses")
    modules = relationship("Module", back_populates="course")


class Module(Base):
    __tablename__ = "modules"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)

    course = relationship("Course", back_populates="modules")
    topics = relationship("CurriculumTopic", back_populates="module")


class CurriculumTopic(Base):
    """Leaf-level structured unit extracted from a curriculum document (Section 7)."""
    __tablename__ = "curriculum_topics"
    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=False, index=True)
    topic_text = Column(Text, nullable=False)
    learning_outcome = Column(Text, nullable=True)
    source_page = Column(Integer, nullable=True)
    extraction_confidence = Column(Float, nullable=True)

    module = relationship("Module", back_populates="topics")


class CourseLearningOutcome(Base):
    """
    Course-level learning outcome (e.g. "Course Outcomes" / "Learning Outcomes"
    sections in a syllabus). Kept separate from CurriculumTopic.learning_outcome
    (a topic-scoped free-text field) because these are extracted and attributed
    at the course level, not tied to one specific topic.
    """
    __tablename__ = "course_learning_outcomes"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    outcome_label = Column(String(32), nullable=True)  # e.g. "CO1", "CLO1", "Course Outcome 1" -- the ORIGINAL identifier as written, never renumbered/normalized away
    outcome_text = Column(Text, nullable=False)
    source_page = Column(Integer, nullable=True)
    extraction_confidence = Column(Float, nullable=True)
