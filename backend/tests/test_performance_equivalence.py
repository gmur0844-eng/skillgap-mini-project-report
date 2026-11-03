"""Speed-ups that must not change any result: each faster path is compared with the original computation."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics import concept_semantic_matching as csm
from app.pipelines.preprocessing.skill_extraction import (
    IndexedVocabulary, VocabTerm, extract_mentions_from_text, extract_mentions_indexed)
from app.pipelines.preprocessing.validation import MIN_DESCRIPTION_LENGTH, validate_job_posting_row

TERMS = ["SQL", "Java", "JavaScript", "C++", "C#", ".NET", "ASP.NET", "Node.js", "R", "Go", "a a", "data  base",
         "machine learning", "learning", "(R)", "- dash term", "it", "IT", "k8s", "kubernetes", "e-mail", "o'reilly",
         "réseau", "café latte", "σ test", "s3", "_under", "x_y", "AI/ML", "ML", "power bi", "bi"]
PIECES = ["SQL", "sql", "Java", "javascript", "C++", "C#", ".NET", "ASP.NET", "Node.js", "R", "R&D", "go", "a", "a",
          "data", "base", "data  base", "machine", "learning", "(R)", "- dash term", "dash", "term", "it", "IT's",
          "we're", "don’t", "k8s", "kubernetes", "e-mail", "o'reilly", "réseau", "café", "latte", "Σ", "σ", "ς",
          "test", "s3", "_under", "x_y", "AI/ML", "ML", "power", "bi", "K8s", "ſql", "ıt", "İT",
          "é", "1", "2.0", ",", ".", "/", "-", "'", "\n", "\t", "  ", "and"]


def _vocab():
    return [VocabTerm(t, i, str(i), "exact_label") for i, t in enumerate(TERMS)]


def _key(ms):
    return sorted((m.original_text, m.normalized_text, m.method, m.start, m.end, m.skill_id) for m in ms)


def test_indexed_matcher_equals_the_original_on_awkward_texts():
    vocab = _vocab()
    index = IndexedVocabulary(vocab)
    rng = random.Random(11)
    for _ in range(3000):
        sep = rng.choice([" ", "", "  ", "\n"])
        text = sep.join(rng.choice(PIECES) for _ in range(rng.randint(1, 30)))
        assert _key(extract_mentions_from_text(text, vocab)) == _key(extract_mentions_indexed(text, index)), repr(text)


def test_repeated_overlapping_terms_follow_finditer():
    vocab = _vocab()
    index = IndexedVocabulary(vocab)
    for text in ("a a a a", "a a a", "Java Java Java", "SQL,SQL;SQL", "learning machine learning learning"):
        assert _key(extract_mentions_from_text(text, vocab)) == _key(extract_mentions_indexed(text, index)), text


def test_cached_stemming_gives_the_same_tokens_and_a_new_list_each_time():
    text = "Scheduling and Searching of Operating Systems processes"
    expected = [csm._simple_stem.__wrapped__(w) for w in ["Scheduling", "Searching", "Operating", "Systems", "processes"]]
    first, second = csm._stemming_tokenizer(text), csm._stemming_tokenizer(text)
    assert first == second == expected
    first.append("x")
    assert csm._stemming_tokenizer(text) == expected


def test_validation_counts_letters_only_as_far_as_needed():
    for n in range(0, MIN_DESCRIPTION_LENGTH + 5):
        text = ("a" * n + " ." * 30)[: max(n + 60, MIN_DESCRIPTION_LENGTH)]
        r = validate_job_posting_row({"job_title": "t", "raw_description": text})
        if n < MIN_DESCRIPTION_LENGTH:
            assert (r.is_valid, r.reason, r.detail) == (False, "description_no_real_content", f"alnum_chars={n}")
        else:
            assert r.is_valid


def test_run_output_comparison_masks_run_derived_ids_and_their_order(tmp_path):
    import importlib.util
    from app.knowledge_engine.silver import uid
    spec = importlib.util.spec_from_file_location(
        "compare_run_outputs", Path(__file__).resolve().parents[2] / "scripts/evaluation/compare_run_outputs.py")
    cro = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cro)
    a, b = "a" * 16, "b" * 16
    for run, gaps in ((a, ["gap:1111111111111111", "gap:2222222222222222"]),
                      (b, ["gap:3333333333333333", "gap:4444444444444444"])):
        d = tmp_path / run / "industry"
        d.mkdir(parents=True)
        rows = [{"gap_uid": g, "skill": s, "run_id": run, "scope": uid("scope", run, "ALL_POSTINGS")}
                for g, s in zip(gaps, ("docker", "sql") if run == a else ("sql", "docker"))]
        (d / "skill_gaps.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        (tmp_path / run / "observability.json").write_text(json.dumps({"t": run}))
    assert cro.compare(tmp_path, a, b)["different"] == []
    (tmp_path / b / "industry/skill_gaps.jsonl").write_text('{"skill": "java"}')
    assert cro.compare(tmp_path, a, b)["different"] == ["industry/skill_gaps.jsonl"]
