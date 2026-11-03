import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.text_cleaning import clean_job_description, TECHNICAL_TOKEN_SAMPLES


def test_technical_tokens_survive_cleaning():
    raw = (
        "Looking for an engineer with experience in "
        + ", ".join(TECHNICAL_TOKEN_SAMPLES)
        + ". Apply now! Job ID: 12345"
    )
    cleaned = clean_job_description(raw)
    for token in TECHNICAL_TOKEN_SAMPLES:
        assert token in cleaned, f"Technical token '{token}' was damaged by cleaning"


def test_html_and_urls_stripped():
    raw = "<p>Great role</p> visit https://example.com/apply or email us@example.com"
    cleaned = clean_job_description(raw)
    assert "<p>" not in cleaned
    assert "https://" not in cleaned
    assert "@" not in cleaned


def test_boilerplate_lines_removed():
    raw = "Real job content here.\nEqual Opportunity Employer statement text.\nJob ID: ABC123"
    cleaned = clean_job_description(raw)
    assert "Real job content here." in cleaned
    assert "Equal Opportunity" not in cleaned


def test_deterministic_output():
    raw = "Python, AWS, and Docker required."
    assert clean_job_description(raw) == clean_job_description(raw)


def test_empty_input():
    assert clean_job_description("") == ""
    assert clean_job_description(None) == ""
