"""
Ingestion outcome: ONE canonical interpretation of an ingestion result, computed on the server and returned with it,
so the API and every screen say the same thing. Pure functions; no I/O.

Four separate dimensions are never collapsed into one "succeeded / failed" field:

  execution_status    did the processing run to the end?          SUCCEEDED | FAILED
  extraction_status   was curriculum content extracted?            EXTRACTED | PARTIAL_EXTRACTION | NO_USABLE_CONTENT |
                                                                   EXTRACTION_FAILED
  analysis_readiness  would the analysis's own course checks       PASS | FAIL | NOT_CHECKED (absent: not run)
                      accept it? (same SILVER build and health
                      thresholds as the pipeline; FAIL -> review)
  structuring_status  was the extracted text organised into        STRUCTURED | PARTIALLY_STRUCTURED | NOT_STRUCTURED
                      courses? (text can be extracted while no
                      course is recognised: topics then belong to
                      no course and cannot be analysed)
  quality_status      is the document's extraction trustworthy?    ACCEPTABLE | LOW_CONFIDENCE | INVALID_DOCUMENT
  review_status       may downstream intelligence use it?          NOT_REQUIRED | NEEDS_REVIEW

and one overall outcome for the headline (plus REGISTERED_AS_REFERENCE for a non-curriculum reference document):

  SUCCESSFUL_AND_USABLE                        executed, courses/topics/outcomes > 0, confidence > 0, not flagged
  NEEDS_REVIEW                                 executed and content extracted, but something is missing or flagged
  EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT    executed, but no course / no topic / zero confidence
  EXECUTION_FAILED                             processing did not complete

Only SUCCESSFUL_AND_USABLE results may flow into downstream intelligence without a human decision
(usable_for_analysis). Everything else carries review_status NEEDS_REVIEW and a next action.
"""

SUCCESSFUL_AND_USABLE = "SUCCESSFUL_AND_USABLE"
NEEDS_REVIEW = "NEEDS_REVIEW"
NO_USABLE_CONTENT = "EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT"
EXECUTION_FAILED = "EXECUTION_FAILED"
REGISTERED_AS_REFERENCE = "REGISTERED_AS_REFERENCE"
OUTCOMES = (SUCCESSFUL_AND_USABLE, NEEDS_REVIEW, NO_USABLE_CONTENT, EXECUTION_FAILED, REGISTERED_AS_REFERENCE)

HEADLINES = {
    SUCCESSFUL_AND_USABLE: "Successfully extracted — ready for analysis",
    NEEDS_REVIEW: "Processing completed, but the extraction is incomplete — review required",
    NO_USABLE_CONTENT: "Processing completed, but no usable curriculum content was extracted — review required",
    EXECUTION_FAILED: "Processing failed — review error details",
    REGISTERED_AS_REFERENCE: "Reference document registered — it is not a curriculum, so no curriculum extraction ran",
}


def reference_outcome():
    """A GENERAL_REFERENCE document (taxonomy, framework, reference text): registered with provenance, not extracted."""
    return {"outcome": REGISTERED_AS_REFERENCE, "execution_status": "SUCCEEDED", "extraction_status": "NOT_APPLICABLE",
            "quality_status": None, "review_status": "NOT_REQUIRED", "usable_for_analysis": False,
            "headline": HEADLINES[REGISTERED_AS_REFERENCE], "reasons": [],
            "next_action": "It is listed under Evidence → Sources with its provenance"}


def _n(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# More than this share of extracted topic lines attributed to no course means the course structure was only partly
# recognised (existing institutional syllabi: 0-27%), so the document needs review before analysis.
MAX_UNATTRIBUTED_TOPIC_SHARE = 0.5


def _structuring(courses, topics, unattributed):
    """STRUCTURED / PARTIALLY_STRUCTURED / NOT_STRUCTURED, with the reason when not STRUCTURED. Text extraction and
    course structuring are separate: a page's text can be read in full while none of it is recognised as a course."""
    if courses == 0:
        if topics:
            return "NOT_STRUCTURED", (f"text was extracted ({topics} topic lines) but no course code or course header was "
                                      "recognised, so none of it can be attributed to a course; the document's course "
                                      "format may not be supported")
        return "NOT_STRUCTURED", None
    if unattributed is not None and topics and unattributed / topics > MAX_UNATTRIBUTED_TOPIC_SHARE:
        return "PARTIALLY_STRUCTURED", (f"{unattributed} of {topics} topic lines are attributed to no course; some courses "
                                        "were probably not recognised")
    return "STRUCTURED", None


def curriculum_outcome(result, low_confidence_threshold=0.3):
    """Interpret a curriculum ingestion result dict (the pipeline's return value)."""
    status = str(result.get("status") or "").lower()
    if status != "succeeded":
        reason = result.get("reason") or result.get("error") or "the document could not be processed"
        invalid = bool(result.get("reason"))
        return {
            "outcome": EXECUTION_FAILED, "execution_status": "FAILED", "extraction_status": "EXTRACTION_FAILED",
            "quality_status": "INVALID_DOCUMENT" if invalid else None, "review_status": "NEEDS_REVIEW",
            "usable_for_analysis": False, "headline": HEADLINES[EXECUTION_FAILED],
            "reasons": [str(reason)], "next_action": "Check the file (a text-based PDF or TXT curriculum), then retry",
        }
    courses, modules = _n(result.get("courses_found")), _n(result.get("modules_found"))
    topics, outcomes = _n(result.get("topics_found")), _n(result.get("outcomes_found"))
    confidence = float(result.get("extraction_confidence") or 0.0)
    flagged = bool(result.get("flagged_for_review"))
    unattributed = result.get("topics_unattributed")
    structuring, structuring_reason = _structuring(courses, topics, None if unattributed is None else _n(unattributed))
    reasons = []
    if courses == 0:
        reasons.append(structuring_reason or "no course was recognised")
    if topics == 0:
        reasons.append("no topic was extracted")
    if confidence == 0:
        reasons.append("extraction confidence is 0 (no page contributed structure)")
    if reasons:
        outcome, extraction = NO_USABLE_CONTENT, "NO_USABLE_CONTENT"
        if outcomes == 0:
            reasons.append("no learning outcome was extracted")
        if flagged:
            reasons.append("the document is flagged for review")
    else:
        if outcomes == 0:
            reasons.append("no learning outcome was extracted")
        if modules == 0:
            reasons.append("no module/unit structure was recognised")
        if structuring_reason:
            reasons.append(structuring_reason)
        readiness = result.get("analysis_readiness") or {}
        if readiness.get("status") == "FAIL":
            # the analysis applies these same checks and would block every result for this document
            reasons.extend(f"analysis check: {r}" for r in readiness.get("reasons") or [])
        elif readiness.get("status") == "NOT_CHECKED":
            reasons.extend(readiness.get("reasons") or [])
        if flagged:
            reasons.append(f"extraction confidence {confidence:.0%} is below the review threshold "
                           f"{low_confidence_threshold:.0%}" if confidence < low_confidence_threshold
                           else "the document is flagged for review")
        outcome = NEEDS_REVIEW if reasons else SUCCESSFUL_AND_USABLE
        extraction = "PARTIAL_EXTRACTION" if reasons else "EXTRACTED"
    quality = ("LOW_CONFIDENCE" if (confidence < low_confidence_threshold or flagged) else "ACCEPTABLE")
    usable = outcome == SUCCESSFUL_AND_USABLE
    return {
        "outcome": outcome, "execution_status": "SUCCEEDED", "extraction_status": extraction,
        "structuring_status": structuring, "quality_status": quality,
        "analysis_readiness": (result.get("analysis_readiness") or {}).get("status"), "review_status": "NOT_REQUIRED" if usable else "NEEDS_REVIEW",
        "usable_for_analysis": usable, "headline": HEADLINES[outcome], "reasons": reasons,
        "counts": {"courses": courses, "modules": modules, "topics": topics, "outcomes": outcomes,
                   **({} if unattributed is None else {"topics_unattributed": _n(unattributed)})},
        "extraction_confidence": confidence,
        "next_action": ("Open curriculum intelligence" if usable else
                        "Review the extraction (Preprocessing Preview) before this document is used by any analysis"),
    }


def job_postings_outcome(result):
    """Interpret a job-postings ingestion result dict."""
    status = str(result.get("status") or "succeeded").lower()
    if status == "failed":
        return {"outcome": EXECUTION_FAILED, "execution_status": "FAILED", "extraction_status": "EXTRACTION_FAILED",
                "quality_status": None, "review_status": "NEEDS_REVIEW", "usable_for_analysis": False,
                "headline": "Processing failed — review error details", "reasons": [str(result.get("reason") or "")],
                "next_action": "Check the file and the column preset, then retry"}
    accepted = _n(result.get("records_accepted"))
    rejected = _n(result.get("records_rejected"))
    duplicates = _n(result.get("duplicates_flagged"))
    reasons = []
    if accepted == 0:
        reasons.append("no posting was accepted")
    elif rejected:
        reasons.append(f"{rejected} row(s) rejected")
    if accepted and duplicates >= accepted:
        reasons.append("every accepted posting is a duplicate")
    if accepted == 0 or (accepted and duplicates >= accepted):
        outcome, extraction = NO_USABLE_CONTENT, "NO_USABLE_CONTENT"
        headline = "Processing completed, but no usable job postings were accepted — review required"
    elif rejected:
        outcome, extraction, headline = NEEDS_REVIEW, "PARTIAL_EXTRACTION", "Postings imported with rejected rows — review required"
    else:
        outcome, extraction, headline = SUCCESSFUL_AND_USABLE, "EXTRACTED", "Job postings imported — ready for analysis"
    usable = outcome == SUCCESSFUL_AND_USABLE
    return {"outcome": outcome, "execution_status": "SUCCEEDED", "extraction_status": extraction,
            "quality_status": "ACCEPTABLE" if usable else "LOW_CONFIDENCE", "review_status": "NOT_REQUIRED" if usable else "NEEDS_REVIEW",
            "usable_for_analysis": usable, "headline": headline, "reasons": reasons,
            "counts": {"accepted": accepted, "rejected": rejected, "duplicates": duplicates},
            "next_action": "Open industry intelligence" if usable else "Review the rejected rows (Data Quality) before analysis"}
