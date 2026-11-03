import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.core_knowledge_loaders import (
    load_records_from_csv,
    load_records_from_json,
    validate_records,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "external" / "demo_fixture"


def test_load_csv_fixture_real_file():
    records = load_records_from_csv(FIXTURE_DIR / "core_knowledge_fixture.csv")
    assert len(records) == 5
    assert records[0]["domain"] == "FIXTURE DOMAIN 1"
    assert records[0]["topic"] == "Fixture Topic 1.1"
    assert records[0]["subtopic"] == "Fixture Subtopic 1.1.a"


def test_load_csv_empty_optional_fields_become_none():
    records = load_records_from_csv(FIXTURE_DIR / "core_knowledge_fixture.csv")
    no_subtopic_row = next(r for r in records if r["topic"] == "Fixture Topic 1.2")
    assert no_subtopic_row["subtopic"] is None
    assert no_subtopic_row["description"] is None


def test_load_json_fixture_real_file():
    records = load_records_from_json(FIXTURE_DIR / "core_knowledge_fixture.json")
    assert len(records) == 3
    assert records[0]["domain"] == "FIXTURE DOMAIN 1"


def test_load_json_rejects_non_array():
    import tempfile
    import json as json_module

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json_module.dump({"not": "a list"}, f)
        path = f.name
    try:
        raised = False
        try:
            load_records_from_json(path)
        except ValueError:
            raised = True
        assert raised
    finally:
        Path(path).unlink()


def test_validate_records_rejects_missing_domain_or_topic():
    records = [
        {"domain": "D1", "topic": "T1"},
        {"domain": "", "topic": "T2"},
        {"domain": "D3", "topic": ""},
        {"domain": None, "topic": None},
    ]
    valid, invalid = validate_records(records)
    assert len(valid) == 1
    assert len(invalid) == 3


def test_validate_records_csv_and_json_fixtures_agree_on_invalid_count():
    csv_records = load_records_from_csv(FIXTURE_DIR / "core_knowledge_fixture.csv")
    json_records = load_records_from_json(FIXTURE_DIR / "core_knowledge_fixture.json")

    _, csv_invalid = validate_records(csv_records)
    _, json_invalid = validate_records(json_records)

    assert len(csv_invalid) == 1
    assert len(json_invalid) == 1


def test_validate_records_empty_input():
    valid, invalid = validate_records([])
    assert valid == []
    assert invalid == []


def test_validate_records_deterministic():
    records = [{"domain": "D", "topic": "T"}, {"domain": "", "topic": "T2"}]
    r1 = validate_records(records)
    r2 = validate_records(records)
    assert r1 == r2


from app.pipelines.preprocessing.core_knowledge_loaders import records_fingerprint


def test_fingerprint_same_file_loaded_twice_is_identical():
    """Idempotency key: re-loading the same source produces the same key, so
    the orchestration's get_or_create_data_source reuses the same DataSource."""
    a = records_fingerprint(load_records_from_csv(FIXTURE_DIR / "core_knowledge_fixture.csv"))
    b = records_fingerprint(load_records_from_csv(FIXTURE_DIR / "core_knowledge_fixture.csv"))
    assert a == b


def test_fingerprint_order_insensitive():
    r = [{"domain": "D", "topic": "T1"}, {"domain": "D", "topic": "T2"}]
    assert records_fingerprint(r) == records_fingerprint(list(reversed(r)))


def test_fingerprint_changes_when_content_changes():
    r1 = [{"domain": "D", "topic": "T1"}]
    r2 = [{"domain": "D", "topic": "T1 changed"}]
    assert records_fingerprint(r1) != records_fingerprint(r2)


def test_fixtures_are_clearly_synthetic():
    """Guard: every fixture domain name must be visibly labelled FIXTURE so
    it can never be mistaken for real academic knowledge."""
    for path, loader in [
        (FIXTURE_DIR / "core_knowledge_fixture.csv", load_records_from_csv),
        (FIXTURE_DIR / "core_knowledge_fixture.json", load_records_from_json),
    ]:
        for r in loader(path):
            if r["domain"]:
                assert r["domain"].startswith("FIXTURE"), f"{path.name}: unlabelled domain {r['domain']!r}"
