from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.db.session import Base


class DataSource(Base):
    """
    Provenance record. Every ingested document/dataset row links to exactly one
    of these via `source_id`. This is what makes "where did this data come from?"
    (spec Section 3) answerable for any record in the system.
    """
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True)
    source_name = Column(String(255), nullable=False)
    source_url = Column(String(1024), nullable=True)
    source_type = Column(String(64), nullable=False, index=True)  # taxonomy | labour_market | curriculum
    retrieval_date = Column(DateTime, nullable=False)
    license = Column(String(255), nullable=True)
    version = Column(String(64), nullable=True)
    institution = Column(String(255), nullable=True)
    programme = Column(String(255), nullable=True)
    country = Column(String(128), nullable=True)
    time_period = Column(String(64), nullable=True)
    file_hash = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    # Explicit, filterable flag for DEMO/TEST fixture data (previously only
    # indicated by free text in source_name). 1 = synthetic/test fixture:
    # must never be presented as real academic/industry evidence, and is
    # excluded by default from the core-knowledge API. Set EXPLICITLY by the
    # caller -- never inferred from a name string.
    is_test_data = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class DataQualityMetric(Base):
    """
    One row per (analysis_run, metric_name) — powers the Data Quality dashboard
    (Section 9 / 25). Never hardcoded; written by the validation stage of the
    pipeline for whichever dataset it just processed.
    """
    __tablename__ = "data_quality_metrics"

    id = Column(Integer, primary_key=True)
    analysis_run_id = Column(Integer, nullable=True, index=True)
    source_id = Column(Integer, nullable=True, index=True)
    metric_name = Column(String(128), nullable=False)
    metric_value = Column(String(64), nullable=False)  # stored as string; cast on read (mixed numeric/%/text)
    computed_at = Column(DateTime, default=datetime.utcnow)
