import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.skill_extraction import (
    build_vocabulary_index,
    extract_mentions_from_text,
    extract_mentions_from_tag_field,
    deduplicate_mentions,
    mention_hash_for,
    partition_new_mentions,
)

ESCO_SKILLS = [
    {"id": 1, "external_id": "esco:python", "preferred_label": "Python (computer programming)"},
    {"id": 2, "external_id": "esco:ml", "preferred_label": "machine learning"},
    {"id": 3, "external_id": "esco:cloud", "preferred_label": "cloud computing"},
    {"id": 4, "external_id": "esco:docker", "preferred_label": "Docker (software)"},
    {"id": 5, "external_id": "esco:sql", "preferred_label": "SQL"},
    {"id": 6, "external_id": "esco:llm", "preferred_label": "large language models"},
    {"id": 7, "external_id": "esco:k8s", "preferred_label": "Kubernetes"},
]
ESCO_ALIASES = [
    {"skill_id": 1, "external_id": "esco:python", "alias_label": "python programming"},
    {"skill_id": 2, "external_id": "esco:ml", "alias_label": "ML"},
    {"skill_id": 7, "external_id": "esco:k8s", "alias_label": "K8s"},
]


def _vocab():
    return build_vocabulary_index(ESCO_SKILLS, ESCO_ALIASES)


def test_build_vocabulary_index_includes_skills_aliases_and_technical_tokens():
    vocab = _vocab()
    labels = {t.term_text for t in vocab}
    assert "Python (computer programming)" in labels
    assert "ML" in labels
    assert "C++" in labels


def test_multiword_skill_not_split():
    text = "We use machine learning and cloud computing every day."
    mentions = extract_mentions_from_text(text, _vocab())
    texts = {m.normalized_text for m in mentions}
    assert "machine learning" in texts
    assert "cloud computing" in texts
    assert "machine" not in texts
    assert "learning" not in texts


def test_technical_token_boundaries_exact_case():
    text = "Looking for someone skilled in C++, C#, .NET, Node.js and ASP.NET."
    mentions = extract_mentions_from_text(text, _vocab())
    raw_texts = {m.original_text for m in mentions}
    assert "C++" in raw_texts
    assert "C#" in raw_texts
    assert ".NET" in raw_texts
    assert "Node.js" in raw_texts
    assert "ASP.NET" in raw_texts
    net_matches = [m for m in mentions if m.original_text == ".NET"]
    assert len(net_matches) == 1


def test_alias_matching():
    text = "Strong ML background required, with K8s experience."
    mentions = extract_mentions_from_text(text, _vocab())
    methods = {(m.normalized_text, m.method) for m in mentions}
    assert ("ml", "alias") in methods
    assert ("k8s", "alias") in methods
    for m in mentions:
        if m.normalized_text in ("ml", "k8s"):
            assert m.mapping_status == "mapped"


def test_normalized_label_case_insensitive_match():
    """"Kubernetes" (preferred_label, exact case) vs "kubernetes" (lowercase)
    -- tests the normalized_label fallback specifically, using a label with no
    parenthetical disambiguation so case is the only variable."""
    text = "Experience with kubernetes required."
    mentions = extract_mentions_from_text(text, _vocab())
    k8s_mentions = [m for m in mentions if m.original_text.lower() == "kubernetes"]
    assert len(k8s_mentions) == 1
    assert k8s_mentions[0].method == "normalized_label"
    assert k8s_mentions[0].mapping_status == "mapped"

    # Exact-case match of the same label should report "exact_label" instead.
    exact_text = "Experience with Kubernetes required."
    exact_mentions = extract_mentions_from_text(exact_text, _vocab())
    assert any(m.method == "exact_label" and m.original_text == "Kubernetes" for m in exact_mentions)


def test_unmapped_technical_token_stays_unmapped():
    text = "Experience with TensorFlow required."
    mentions = extract_mentions_from_text(text, _vocab())
    tf_mentions = [m for m in mentions if m.original_text == "TensorFlow"]
    assert len(tf_mentions) == 1
    assert tf_mentions[0].mapping_status == "unmapped"
    assert tf_mentions[0].skill_id is None
    assert tf_mentions[0].method == "technical_token"


def test_no_match_in_unrelated_text():
    text = "We are hiring a friendly office manager for our reception desk."
    mentions = extract_mentions_from_text(text, _vocab())
    assert mentions == []


def test_extract_mentions_from_tag_field_naukri_style():
    """
    Real example lifted from data/external/demo_fixture/naukri_job_postings_fixture.csv row 1.
    IMPORTANT, HONEST LIMITATION documented here: real ESCO preferred labels
    are often disambiguated ("Python (computer programming)"), so a bare tag
    like "Python" only maps if an ALIAS covers that exact short form. This
    fixture's alias list only has "python programming"/"python coding" for
    that skill (mirroring the real demo_fixture/esco_skills_fixture.csv
    content) -- so the bare "Python" tag legitimately stays UNMAPPED here.
    This is correct, spec-compliant behavior (no blind fuzzy matching to force
    a match), not a bug -- it will resolve once real, fuller ESCO alias data
    (or a curated_mapping entry) is loaded.
    """
    tag_string = "Python, PyTorch, AWS, Docker, LLMs"
    mentions = extract_mentions_from_tag_field(tag_string, _vocab())
    assert len(mentions) == 5
    assert all(m.method == "structured_tag" for m in mentions)

    python_mention = next(m for m in mentions if m.original_text == "Python")
    assert python_mention.mapping_status == "unmapped"  # honest: no alias covers bare "Python" in this fixture
    assert python_mention.skill_id is None

    llms_mention = next(m for m in mentions if m.original_text == "LLMs")
    assert llms_mention.mapping_status == "unmapped"
    assert llms_mention.skill_id is None

    pytorch_mention = next(m for m in mentions if m.original_text == "PyTorch")
    assert pytorch_mention.mapping_status == "unmapped"  # technical token, not (yet) an ESCO entry in this fixture


def test_extract_mentions_from_tag_field_matches_real_alias():
    """The positive counterpart to the test above: a tag that DOES match a
    real alias in the fixture ("python programming") maps correctly."""
    tag_string = "python programming, machine learning"
    mentions = extract_mentions_from_tag_field(tag_string, _vocab())
    python_mention = next(m for m in mentions if m.original_text == "python programming")
    assert python_mention.mapping_status == "mapped"
    assert python_mention.skill_id == 1
    ml_mention = next(m for m in mentions if m.original_text == "machine learning")
    assert ml_mention.mapping_status == "mapped"
    assert ml_mention.skill_id == 2


def test_tag_field_empty_string():
    assert extract_mentions_from_tag_field("", _vocab()) == []
    assert extract_mentions_from_tag_field(None, _vocab()) == []


def test_deduplicate_mentions_collapses_repeats():
    text = "Docker and more Docker and even more Docker."
    mentions = extract_mentions_from_text(text, _vocab())
    assert len(mentions) == 3
    deduped = deduplicate_mentions(mentions)
    assert len(deduped) == 1


def test_deterministic_repeated_extraction():
    text = "Python, machine learning, and Docker are required."
    first = extract_mentions_from_text(text, _vocab())
    second = extract_mentions_from_text(text, _vocab())
    assert [(m.normalized_text, m.method) for m in first] == [(m.normalized_text, m.method) for m in second]


def test_extraction_over_real_curriculum_fixture_topics():
    """
    Combines two already-tested pure modules end to end, DB-free: real
    generated fixture PDF -> curriculum_structuring -> topic text ->
    skill_extraction. Demonstrates the curriculum side of extraction works on
    genuinely extracted (not hand-typed) topic text.
    """
    import pdfplumber
    from app.pipelines.preprocessing.curriculum_structuring import structure_curriculum_pages

    fixture_pdf = Path(__file__).resolve().parents[2] / "data" / "external" / "demo_fixture" / "sample_curriculum.pdf"
    pages = []
    with pdfplumber.open(fixture_pdf) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")

    structure = structure_curriculum_pages(pages)
    all_mentions = []
    for topic in structure.topics:
        all_mentions.extend(extract_mentions_from_text(topic.topic_text, _vocab()))

    normalized_found = {m.normalized_text for m in all_mentions}
    # The fixture PDF's CS405 Cloud Computing unit lists "AWS, GCP" and "Docker, Kubernetes"
    assert "docker (software)" in normalized_found or "docker" in {m.original_text.lower() for m in all_mentions}
    assert any(m.original_text == "AWS" for m in all_mentions)  # technical token
    assert any(m.original_text == "Kubernetes" for m in all_mentions)


def test_mention_hash_deterministic_and_distinguishing():
    """PHASE HARDENING: idempotency key must be stable across repeated calls
    with the same inputs, and different for genuinely different mentions."""
    h1 = mention_hash_for("job_posting", 42, "python", "exact_label")
    h2 = mention_hash_for("job_posting", 42, "python", "exact_label")
    assert h1 == h2  # deterministic

    h3 = mention_hash_for("job_posting", 43, "python", "exact_label")  # different source id
    h4 = mention_hash_for("job_posting", 42, "docker", "exact_label")  # different text
    h5 = mention_hash_for("job_posting", 42, "python", "alias")  # different method
    h6 = mention_hash_for("curriculum_topic", 42, "python", "exact_label")  # different source type

    assert len({h1, h3, h4, h5, h6}) == 5  # all distinct


def test_partition_new_mentions_first_run_all_new():
    text = "Python, machine learning, and Docker are required."
    mentions = extract_mentions_from_text(text, _vocab())
    existing_hashes = set()  # simulates an empty DB -- first ever run
    new_with_hash, skipped = partition_new_mentions(mentions, "job_posting", 1, existing_hashes)
    assert len(new_with_hash) == len(mentions)
    assert skipped == []


def test_orchestration_idempotency_simulated_two_runs():
    """
    PHASE HARDENING: simulates exactly what app.pipelines.ingestion.skill_extraction
    does across two runs -- run once, persist the hashes (as the DB would),
    run again on the identical source with the same extracted mentions, and
    verify the second run finds everything already there and inserts nothing
    new. This is the orchestration's actual idempotency behavior, not just a
    test of the hash function in isolation.
    """
    text = "Python, machine learning, and Docker are required."
    source_type, source_id = "job_posting", 99

    # --- Run 1: empty DB ---
    mentions_run1 = extract_mentions_from_text(text, _vocab())
    existing_hashes = set()  # represents ExtractedSkill.mention_hash values already in the DB
    new_with_hash_1, skipped_1 = partition_new_mentions(mentions_run1, source_type, source_id, existing_hashes)
    assert len(new_with_hash_1) == len(mentions_run1)
    assert skipped_1 == []
    # Simulate persisting: the DB now "contains" these hashes.
    for _, h in new_with_hash_1:
        existing_hashes.add(h)

    # --- Run 2: identical source re-processed (e.g. pipeline re-run) ---
    mentions_run2 = extract_mentions_from_text(text, _vocab())  # deterministic -- same mentions
    new_with_hash_2, skipped_2 = partition_new_mentions(mentions_run2, source_type, source_id, existing_hashes)
    assert new_with_hash_2 == []  # nothing new to insert
    assert len(skipped_2) == len(mentions_run2)  # everything correctly recognized as already-ingested


def test_orchestration_idempotency_different_source_id_not_skipped():
    """A different source (different job posting) with the SAME text content
    must NOT be treated as already-ingested -- the hash is source-scoped."""
    text = "Python required."
    mentions = extract_mentions_from_text(text, _vocab())
    existing_hashes = set()
    new_with_hash_a, _ = partition_new_mentions(mentions, "job_posting", 1, existing_hashes)
    for _, h in new_with_hash_a:
        existing_hashes.add(h)

    new_with_hash_b, skipped_b = partition_new_mentions(mentions, "job_posting", 2, existing_hashes)
    assert len(new_with_hash_b) == len(mentions)  # posting #2 is genuinely new evidence
    assert skipped_b == []
