import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.preprocessing.validation import validate_job_posting_row, validate_curriculum_document


def test_valid_row_passes():
    row = {"job_title": "Data Scientist", "raw_description": "A" * 50}
    result = validate_job_posting_row(row)
    assert result.is_valid


def test_missing_title_and_description_rejected():
    row = {"job_title": None, "raw_description": None}
    result = validate_job_posting_row(row)
    assert not result.is_valid
    assert result.reason == "missing_title_and_description"


def test_empty_description_rejected():
    row = {"job_title": "Data Scientist", "raw_description": ""}
    result = validate_job_posting_row(row)
    assert not result.is_valid
    assert result.reason == "empty_description"


def test_too_short_description_rejected():
    row = {"job_title": "Data Scientist", "raw_description": "short"}
    result = validate_job_posting_row(row)
    assert not result.is_valid
    assert result.reason == "description_too_short"


def test_no_real_content_rejected():
    row = {"job_title": "Data Scientist", "raw_description": "!!!!!!!!!!!!!!!!!!!!!!!!"}
    result = validate_job_posting_row(row)
    assert not result.is_valid
    assert result.reason == "description_no_real_content"


def test_curriculum_document_no_pages():
    result = validate_curriculum_document("fake.pdf", extracted_page_count=0, extracted_text_total_len=0)
    assert not result.is_valid
    assert result.reason == "no_pages_extracted"


def test_curriculum_document_valid():
    result = validate_curriculum_document("fake.pdf", extracted_page_count=3, extracted_text_total_len=500)
    assert result.is_valid
