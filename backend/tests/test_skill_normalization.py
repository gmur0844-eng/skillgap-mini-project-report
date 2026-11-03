import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.skill_normalization import normalize_skill_text, TECHNICAL_TOKENS


def test_case_normalization():
    assert normalize_skill_text("Python") == "python"
    assert normalize_skill_text("PYTHON") == "python"
    assert normalize_skill_text("python") == "python"


def test_whitespace_normalization():
    assert normalize_skill_text("  Python  ") == "python"
    assert normalize_skill_text("machine   learning") == "machine learning"
    assert normalize_skill_text("Python\nProgramming") == "python programming"


def test_technical_tokens_survive_normalization_exactly_except_case():
    """PHASE HARDENING: normalization must never strip punctuation from
    technical tokens -- C++ -> C would be a critical bug."""
    cases = {
        "C++": "c++",
        "C#": "c#",
        ".NET": ".net",
        "Node.js": "node.js",
        "ASP.NET": "asp.net",
        "React.js": "react.js",
        "PyTorch": "pytorch",
        "scikit-learn": "scikit-learn",
    }
    for raw, expected in cases.items():
        result = normalize_skill_text(raw)
        assert result == expected, f"{raw} normalized to {result}, expected {expected}"
        # critical negative assertions: punctuation must not have been stripped
        assert "+" not in raw or "+" in result
        assert "#" not in raw or "#" in result
        assert "." not in raw or "." in result


def test_deterministic_repeated_calls():
    for _ in range(5):
        assert normalize_skill_text("Machine Learning") == "machine learning"


def test_empty_and_none_input():
    assert normalize_skill_text("") == ""
    assert normalize_skill_text(None) == ""


def test_all_spec_mandated_technical_tokens_present():
    required = [
        "C++", "C#", ".NET", "Node.js", "React.js", "Next.js", "Vue.js",
        "PyTorch", "TensorFlow", "scikit-learn", "SQL", "MySQL", "PostgreSQL",
        "MongoDB", "AWS", "Azure", "GCP", "Docker", "Kubernetes",
    ]
    for token in required:
        assert token in TECHNICAL_TOKENS, f"{token} missing from TECHNICAL_TOKENS"
