"""
Exact + near-duplicate detection for job postings (spec Section 8).

Exact duplicates: identical clean_description hash.
Near duplicates: same job_title + company_name + high text-overlap (Jaccard on
shingles) — many job boards repost the same listing with minor boilerplate
differences.
"""
import hashlib
from typing import Iterable


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def shingles(text: str, k: int = 5) -> set:
    tokens = text.lower().split()
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def find_near_duplicates(
    postings: Iterable[dict], similarity_threshold: float = 0.85
) -> dict:
    """
    postings: iterable of {"id": ..., "job_title": ..., "company_name": ...,
                            "clean_description": ...}
    Returns {posting_id: duplicate_of_id} for postings judged near-duplicates of
    an earlier posting with the same title+company. O(n^2) within each
    (title, company) bucket — fine for MVP scale, revisit with MinHash/LSH if
    the real dataset makes this a bottleneck.

    SCOPE / KNOWN LIMITATION (documented per Phase-1 hardening review): this
    function only ever sees the batch of postings passed to it in one
    ingestion call -- it has no knowledge of postings already sitting in the
    database from a previous run, and no knowledge of postings under a
    different title (e.g. "ML Engineer" vs "Machine Learning Engineer" at the
    same company won't be bucketed together). Cross-run duplicate protection
    is handled separately, and only for EXACT text matches, via
    `clean_description_hash` on JobPosting + the DB-level lookup in
    app.pipelines.ingestion.job_postings — see that module's docstring.
    Extending this to cross-run NEAR-duplicate detection (e.g. via MinHash/LSH
    against the whole table) is deliberately out of scope for Phase 1.
    """
    buckets: dict = {}
    for p in postings:
        key = ((p.get("job_title") or "").strip().lower(), (p.get("company_name") or "").strip().lower())
        buckets.setdefault(key, []).append(p)

    duplicate_of: dict = {}
    for group in buckets.values():
        kept = []
        for p in group:
            p_shingles = shingles(p.get("clean_description") or "")
            match = None
            for kept_p, kept_shingles in kept:
                if jaccard_similarity(p_shingles, kept_shingles) >= similarity_threshold:
                    match = kept_p["id"]
                    break
            if match is not None:
                duplicate_of[p["id"]] = match
            else:
                kept.append((p, p_shingles))
    return duplicate_of


def partition_already_ingested(rows: list[dict], existing_external_ids: set) -> tuple[list[dict], list[dict]]:
    """
    Splits rows into (new_rows, already_ingested_rows) based on
    `external_posting_id`, given the set of external ids already present in
    the database for this source. Pure/DB-free so the idempotency decision is
    independently unit-testable -- the DB-touching caller only has to build
    `existing_external_ids` with one query and then run this.

    Rows with no external_posting_id (some real datasets don't have one) are
    always treated as new -- idempotency by external id is only possible when
    the source dataset actually provides one; see the JobPosting model's
    UniqueConstraint docstring for the DB-level backstop.
    """
    new_rows, already_ingested = [], []
    for row in rows:
        eid = row.get("external_posting_id")
        if eid and eid in existing_external_ids:
            already_ingested.append(row)
        else:
            new_rows.append(row)
    return new_rows, already_ingested
