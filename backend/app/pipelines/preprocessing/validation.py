"""
Record-level validation for job postings (spec: validate before preprocessing,
and always record WHY a record was rejected).

Deliberately pure / DB-free so it's directly unit-testable and reusable from
both the CLI ingestion script and the API ingestion endpoint.
"""
from dataclasses import dataclass
from typing import Optional

MIN_DESCRIPTION_LENGTH = 20  # below this, a "description" is almost certainly truncated/garbage, not real content


@dataclass
class ValidationResult:
    is_valid: bool
    reason: Optional[str] = None  # None if valid
    detail: Optional[str] = None


def _alnum_count(text: str, enough: int) -> int:
    """Letters and digits in text, counted until `enough` is reached (the exact count below it)."""
    n = 0
    for c in text:
        if c.isalnum():
            n += 1
            if n >= enough:
                return n
    return n


def validate_job_posting_row(row: dict) -> ValidationResult:
    """
    row is expected to already be mapped to the generic schema keys:
    job_title, company_name, raw_description (see COLUMN_MAP in the ingestion
    adapter). Returns a ValidationResult; never raises for a merely-bad row —
    only genuinely unexpected structural issues should raise upstream.
    """
    title = (row.get("job_title") or "").strip()
    description = (row.get("raw_description") or "").strip()

    if not description and not title:
        return ValidationResult(False, "missing_title_and_description")

    if not description:
        return ValidationResult(False, "empty_description")

    if len(description) < MIN_DESCRIPTION_LENGTH:
        return ValidationResult(
            False, "description_too_short", f"length={len(description)} chars"
        )

    # A description that is literally just whitespace/punctuation after stripping
    # HTML tags is common in scraped datasets (e.g. "<div></div>").
    alnum_chars = _alnum_count(description, MIN_DESCRIPTION_LENGTH)
    if alnum_chars < MIN_DESCRIPTION_LENGTH:
        return ValidationResult(
            False, "description_no_real_content", f"alnum_chars={alnum_chars}"
        )

    return ValidationResult(True)


def validate_curriculum_document(file_path: str, extracted_page_count: int, extracted_text_total_len: int) -> ValidationResult:
    """Minimal structural validation for an ingested curriculum document."""
    if extracted_page_count == 0:
        return ValidationResult(False, "no_pages_extracted")
    if extracted_text_total_len < 50:
        return ValidationResult(False, "extracted_text_too_short", f"len={extracted_text_total_len}")
    return ValidationResult(True)
