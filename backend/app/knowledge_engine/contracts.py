"""
Strict data contracts between pipeline stages (pydantic v2).

Every stage hands the next stage a list of plain dicts. Before a stage
consumes them, `enforce()` validates each record against the stage's
contract: valid records pass through unchanged (as validated dicts), invalid
ones are QUARANTINED with the exact validation errors instead of failing the
whole run.

Contracts encode invariants the rest of the pipeline relies on, e.g. a topic
must carry its document, course and page (provenance), a similarity score
must be in [0, 1] and is never called "confidence", an evidence status must
come from the controlled vocabulary.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"
UID_PATTERN = r"^[a-z]+:[0-9a-f]{16}$"

EVIDENCE_STATUSES = (
    "EXTRACTED",            # the document literally contains this (text, heading, statement)
    "NORMALIZED",           # extracted text after deterministic cleaning
    "DISCOVERED",           # emerged from corpus clustering; not yet validated
    "MODEL_SUGGESTED",      # inferred by the similarity model; not validated
    "REFERENCE_MAPPED",     # deterministic (exact/normalized/abbreviation/synonym) match to reference data
    "HUMAN_VALIDATED",      # a stored human review decision accepted it
    "INSUFFICIENT_EVIDENCE",
    "REVIEW_REQUIRED",
)
EvidenceStatus = Literal[EVIDENCE_STATUSES]

RELATIONSHIPS = (
    "SAME_CONCEPT", "RELATED", "PARENT", "CHILD", "PARTIAL_OVERLAP", "UNRELATED",
    "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "NEW_DISCOVERED_UNMAPPED",
    "BELONGS_TO_FAMILY", "CO_OCCURS_IN_UNIT", "PREREQUISITE_OF",
)
Relationship = Literal[RELATIONSHIPS]

DOCUMENT_ROLES = ("TARGET", "PREVIOUS_VERSION", "REFERENCE", "PEER")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class DocumentRecord(_Strict):
    doc_id: str = Field(min_length=1)
    role: Literal[DOCUMENT_ROLES]
    institution: str = Field(min_length=1)
    programme: str = Field(min_length=1)
    discipline: str = Field(min_length=1)
    curriculum_version: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    page_count: int = Field(gt=0)


class PageRecord(_Strict):
    doc_id: str
    page_number: int = Field(gt=0)
    text: str
    extraction_method: Literal["pdfplumber_table_topics_column", "pdftotext_layout"]


class CourseRecord(_Strict):
    course_uid: str = Field(pattern=UID_PATTERN)
    doc_id: str
    course_code: str = Field(min_length=2, max_length=20)
    title: str = Field(min_length=2)
    title_raw: str = Field(min_length=1)
    semester: Optional[str] = None
    category: Optional[str] = None
    first_page: int = Field(gt=0)
    title_page: int = Field(gt=0)
    occurrences: int = Field(ge=1)
    evidence_status: EvidenceStatus


class UnitRecord(_Strict):
    unit_uid: str = Field(pattern=UID_PATTERN)
    course_uid: str = Field(pattern=UID_PATTERN)
    label: str = Field(min_length=1)
    title: Optional[str] = None
    page_number: int = Field(gt=0)


class TopicRecord(_Strict):
    topic_uid: str = Field(pattern=UID_PATTERN)
    doc_id: str
    course_uid: str = Field(pattern=UID_PATTERN)
    course_code: str
    unit_label: Optional[str] = None
    raw_text: str = Field(min_length=1)
    clean_text: str
    page_number: int = Field(gt=0)
    extraction_method: str
    noise_label: str
    evidence_status: EvidenceStatus


class ConceptRecord(_Strict):
    concept_uid: str = Field(pattern=UID_PATTERN)
    discipline: str
    family_uid: str = Field(pattern=UID_PATTERN)
    name: str = Field(min_length=1)
    support: int = Field(ge=1)
    member_topic_uids: list[str] = Field(min_length=1)
    source_documents: list[str] = Field(min_length=1)
    evidence_status: EvidenceStatus
    review_priority: Literal["HIGH", "MEDIUM", "LOW"]

    @field_validator("member_topic_uids")
    @classmethod
    def _unique_members(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("duplicate member topic uid")
        return value


class MappingRecord(_Strict):
    mapping_uid: str = Field(pattern=UID_PATTERN)
    source_uid: str = Field(pattern=UID_PATTERN)
    target_uid: Optional[str] = None
    relationship: Relationship
    similarity_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    score_is_calibrated: Literal[False] = False
    method: str = Field(min_length=1)
    evidence_status: EvidenceStatus


class EdgeRecord(_Strict):
    edge_uid: str = Field(pattern=UID_PATTERN)
    source_uid: str = Field(pattern=UID_PATTERN)
    target_uid: str = Field(pattern=UID_PATTERN)
    relationship: Relationship
    method: str
    evidence_status: EvidenceStatus


CONTRACTS = {
    "document": DocumentRecord,
    "page": PageRecord,
    "course": CourseRecord,
    "unit": UnitRecord,
    "topic": TopicRecord,
    "concept": ConceptRecord,
    "mapping": MappingRecord,
    "edge": EdgeRecord,
}


def enforce(records, contract_name, quarantine=None, stage=None):
    """
    Validate every record against CONTRACTS[contract_name]. Returns the list
    of valid records (as dicts, extra fields preserved). Invalid records are
    handed to `quarantine.add(stage, record, reason)` -- never silently
    dropped and never allowed to fail the run.
    """
    model = CONTRACTS[contract_name]
    valid = []
    for record in records:
        try:
            valid.append(model.model_validate(record).model_dump())
        except ValidationError as exc:
            reason = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            if quarantine is not None:
                quarantine.add(stage or contract_name, record, f"CONTRACT_VIOLATION({contract_name}): {reason}")
    return valid
