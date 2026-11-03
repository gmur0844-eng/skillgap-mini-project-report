"""Generic Unicode-aware boundaries: contraction/possessive tails are never free-standing matches."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.skill_extraction import (  # noqa: E402
    IndexedVocabulary, VocabTerm, _term_pattern, extract_mentions_from_text, extract_mentions_indexed)


def hits(term, text):
    return [m.group(0) for m in _term_pattern(term).finditer(text)]


def test_ascii_and_curly_contractions_do_not_yield_tails():
    for text in ("We're hiring", "We’re hiring", "We‘re hiring", "Weʼre hiring"):
        assert hits("re", text) == []
    for tail, text in (("t", "don't stop"), ("t", "don’t stop"), ("s", "it's here"), ("s", "it’s here"),
                       ("ll", "we’ll see"), ("ve", "we've done"), ("d", "I’d say")):
        assert hits(tail, text) == [], (tail, text)


def test_possessive_stem_still_matches():
    assert hits("company", "the company's growth") == ["company"]
    assert hits("company", "the company’s growth") == ["company"]


def test_standalone_words_and_punctuation_unchanged():
    assert hits("re", "RE: subject line") == ["RE"]
    assert hits("re", "(re) submit") == ["re"]
    assert hits("SQL", "SQL, NoSQL") == ["SQL"]
    assert hits(".NET", "ASP.NET and .NET") == [".NET"]
    vocab = [VocabTerm(t, t, t, "exact_label") for t in ("C", "C++", "C#")]
    found = sorted(m.original_text for m in extract_mentions_from_text("C++ and C, not C#", vocab))
    assert found == ["C", "C#", "C++"]  # longest-first consumption; unchanged behaviour
    assert hits("C++", "Strong C++ skills") == ["C++"]
    assert hits("node.js", "node.js/react") == ["node.js"]


def test_unicode_letters_are_word_characters():
    assert hits("net", "ñnet") == []
    assert hits("café", "un café noir") == ["café"]
    assert hits("data", "données data") == ["data"]


def test_indexed_extraction_equals_plain_extraction_on_contractions():
    vocab = [VocabTerm(t, t, t, "exact_label") for t in ("re", "reverse engineering", "it", "s", "company", "hiring")]
    idx = IndexedVocabulary(vocab)
    for text in ("We’re hiring, it’s the company’s best role", "We're Hiring: RE required"):
        a = [(m.start, m.end, m.normalized_text) for m in extract_mentions_from_text(text, vocab)]
        b = [(m.start, m.end, m.normalized_text) for m in extract_mentions_indexed(text, idx)]
        assert sorted(a) == sorted(b)
        assert all(m[2] != "s" for m in a)
