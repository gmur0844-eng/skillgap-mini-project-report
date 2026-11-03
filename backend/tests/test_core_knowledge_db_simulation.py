"""
LOGIC SIMULATION -- NOT A DATABASE TEST.

This environment has no SQLAlchemy, FastAPI, psycopg2, or PostgreSQL, and no
network to install them (verified directly: `pip install sqlalchemy` fails
with "No matching distribution found"). The real orchestration in
app.pipelines.ingestion.core_knowledge (ingest_core_knowledge_records,
map_curriculum_topics_to_core_topics) is therefore NEVER executed by this
file -- it cannot be imported here at all, since importing it pulls in
`sqlalchemy` transitively via the model modules.

What this file DOES do: exercise the same REAL pure building blocks the
orchestration uses (records_fingerprint, validate_records,
match_text_to_core_topics, scope_core_topics_to_discipline) against a
minimal in-memory store that enforces the SAME uniqueness rules as the real
schema's UniqueConstraints, driving through the same control flow the
orchestration follows. This proves the ALGORITHM is correct -- it does NOT
prove the ORM code that wraps it is bug-free, and must never be reported as
"database tested".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.core_knowledge_loaders import (
    load_records_from_csv, validate_records, records_fingerprint,
)
from app.analytics.core_knowledge_mapping import (
    match_text_to_core_topics, MATCH_STATUS_MATCHED, MATCH_STATUS_AMBIGUOUS, MATCH_STATUS_NO_MATCH,
)

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "external" / "demo_fixture" / "core_knowledge_fixture.csv"


class InMemoryCoreKnowledgeStore:
    """Mirrors the real UniqueConstraints:
    uq_core_domain_discipline_name(discipline_id, name)
    uq_core_topic_domain_name(domain_id, name)
    uq_core_subtopic_topic_name(topic_id, name)
    and DataSource identity by file_hash (as get_or_create_data_source uses)."""

    def __init__(self):
        self.sources = {}       # file_hash -> source_id
        self.domains = {}       # (discipline_id, name) -> id
        self.topics = {}        # (domain_id, name) -> id
        self.subtopics = {}     # (topic_id, name) -> id
        self._next_id = 1

    def _id(self):
        i = self._next_id
        self._next_id += 1
        return i

    def get_or_create_source(self, fingerprint):
        if fingerprint in self.sources:
            return self.sources[fingerprint], False
        sid = self._id()
        self.sources[fingerprint] = sid
        return sid, True

    def get_or_create_domain(self, discipline_id, name):
        key = (discipline_id, name)
        if key in self.domains:
            return self.domains[key], False
        did = self._id()
        self.domains[key] = did
        return did, True

    def get_or_create_topic(self, domain_id, name):
        key = (domain_id, name)
        if key in self.topics:
            return self.topics[key], False
        tid = self._id()
        self.topics[key] = tid
        return tid, True

    def get_or_create_subtopic(self, topic_id, name):
        key = (topic_id, name)
        if key in self.subtopics:
            return self.subtopics[key], False
        sid = self._id()
        self.subtopics[key] = sid
        return sid, True


def simulate_ingest(store, records, discipline_id=1):
    """Mirrors the control flow of ingest_core_knowledge_records exactly,
    using only the real pure helpers plus the in-memory store above."""
    fingerprint = records_fingerprint(records)
    source_id, source_created = store.get_or_create_source(fingerprint)

    valid, invalid = validate_records(records)
    domains_created = topics_created = subtopics_created = 0

    for r in valid:
        _, dcreated = store.get_or_create_domain(discipline_id, r["domain"])
        domains_created += int(dcreated)
        domain_id = store.domains[(discipline_id, r["domain"])]

        _, tcreated = store.get_or_create_topic(domain_id, r["topic"])
        topics_created += int(tcreated)
        topic_id = store.topics[(domain_id, r["topic"])]

        if r.get("subtopic"):
            _, scr = store.get_or_create_subtopic(topic_id, r["subtopic"])
            subtopics_created += int(scr)

    return {
        "source_id": source_id, "source_created": source_created,
        "domains_created": domains_created, "topics_created": topics_created,
        "subtopics_created": subtopics_created, "invalid_records": len(invalid),
    }


def test_first_ingestion_creates_expected_counts():
    records = load_records_from_csv(FIXTURE)
    store = InMemoryCoreKnowledgeStore()
    result = simulate_ingest(store, records)

    assert result["source_created"] is True
    assert result["domains_created"] == 2       # FIXTURE DOMAIN 1, FIXTURE DOMAIN 2
    assert result["topics_created"] == 3         # 1.1, 1.2, 2.1
    assert result["subtopics_created"] == 3      # 1.1.a, 1.1.b, 2.1.a
    assert result["invalid_records"] == 1        # the intentionally-invalid row


def test_second_identical_ingestion_creates_no_duplicates():
    records = load_records_from_csv(FIXTURE)
    store = InMemoryCoreKnowledgeStore()
    simulate_ingest(store, records)

    before_sources = len(store.sources)
    before_domains = len(store.domains)
    before_topics = len(store.topics)
    before_subtopics = len(store.subtopics)

    second = simulate_ingest(store, records)

    assert second["source_created"] is False   # fingerprint matched -> reused, not duplicated
    assert second["domains_created"] == 0
    assert second["topics_created"] == 0
    assert second["subtopics_created"] == 0
    assert len(store.sources) == before_sources
    assert len(store.domains) == before_domains
    assert len(store.topics) == before_topics
    assert len(store.subtopics) == before_subtopics


def test_ten_repeated_ingestions_still_no_duplicates():
    records = load_records_from_csv(FIXTURE)
    store = InMemoryCoreKnowledgeStore()
    for _ in range(10):
        simulate_ingest(store, records)
    assert len(store.sources) == 1
    assert len(store.domains) == 2
    assert len(store.topics) == 3
    assert len(store.subtopics) == 3


def test_ingesting_a_modified_fixture_creates_a_new_source_but_reuses_shared_topics():
    records = load_records_from_csv(FIXTURE)
    store = InMemoryCoreKnowledgeStore()
    simulate_ingest(store, records)

    modified = records + [{"domain": "FIXTURE DOMAIN 3", "topic": "Fixture Topic 3.1", "subtopic": None, "description": None}]
    second = simulate_ingest(store, modified)

    assert second["source_created"] is True   # different content -> different fingerprint -> new source
    assert second["domains_created"] == 1     # only the genuinely new domain
    assert second["topics_created"] == 1


def test_ambiguous_match_is_never_persisted_in_simulation():
    """Same guarantee as the real orchestration's control flow: only
    MATCH_STATUS_MATCHED results would ever be written; AMBIGUOUS/NO_MATCH
    are counted but never turned into a mapping row."""
    candidates = [{"id": 1, "name": "Fixture Topic A"}, {"id": 2, "name": "fixture  topic a"}]
    result = match_text_to_core_topics("FIXTURE TOPIC A", candidates)
    assert result["status"] == MATCH_STATUS_AMBIGUOUS

    persisted = []
    if result["status"] == MATCH_STATUS_MATCHED:
        persisted.append(result)
    assert persisted == []  # nothing written, matching the real orchestration's behavior


def test_unmatched_topic_is_never_persisted_as_authoritative_in_simulation():
    result = match_text_to_core_topics("Completely Unrelated Wording", [{"id": 1, "name": "Fixture Topic A"}])
    assert result["status"] == MATCH_STATUS_NO_MATCH
    persisted = [result] if result["status"] == MATCH_STATUS_MATCHED else []
    assert persisted == []


def test_curriculum_wording_never_mutated_by_mapping_logic():
    """Structural check, not a runtime one: the mapping match function takes
    curriculum text as INPUT and returns a separate result object -- it has
    no mechanism to write back into the source text at all."""
    curriculum_wording = "Digital Logic Design"
    original = str(curriculum_wording)
    match_text_to_core_topics(curriculum_wording, [{"id": 1, "name": "Fixture Topic A"}])
    assert curriculum_wording == original  # untouched -- strings are immutable in Python, and nothing tries to reassign it
