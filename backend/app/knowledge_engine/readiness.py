"""
Analysis readiness of an uploaded curriculum, judged by the SAME rules the analysis applies.

An upload used to be called "ready for analysis" by the ingestion outcome while the knowledge pipeline's document
health gate then failed the same file (a real upload: 4 "courses" that were table total rows; ingestion said ready,
the pipeline found 0 valid courses and blocked every analysis). This module runs the pipeline's own SILVER build
(silver.build_silver) on the upload's structure and applies the pipeline's own course-level health checks
(health.document_health thresholds from engine_config.json), so the two can no longer disagree.

Checks that only exist in the pipeline run (manifest hash, OCR page ratio on the layout text, the baseline for a known
document hash) are not repeated here; they cannot be judged at upload time and are reported by the analysis itself.
"""
from app.knowledge_engine.config import load_config
from app.knowledge_engine.health import FAIL, PASS, _check
from app.knowledge_engine.quarantine import Quarantine
from app.knowledge_engine.silver import build_silver

COURSE_CHECKS = ("valid_courses", "titled_course_ratio", "topic_noise_ratio", "provenance_completeness")

_PLAIN = {
    "valid_courses": "only {value} course(s) could be validated; the analysis needs at least {threshold}",
    "titled_course_ratio": "only {pct} of recognised courses have a readable title; the analysis needs {tpct}",
    "topic_noise_ratio": "{pct} of extracted topic lines look like noise; the analysis accepts at most {tpct}",
    "provenance_completeness": "{pct} of topics can be traced to a course and page; the analysis needs {tpct}",
}


def _plain(check):
    v, t = check["value"], check["threshold"]
    return _PLAIN[check["check"]].format(value=v, threshold=t, pct=f"{float(v or 0):.0%}", tpct=f"{float(t or 0):.0%}")


def curriculum_readiness(structure, doc_id, sha256, cfg=None):
    """{"status": PASS|FAIL, "checks": [...], "reasons": [plain sentences], counts...} for a parsed upload."""
    cfg = cfg or load_config()
    quarantine = Quarantine()
    records = build_silver({"doc_id": doc_id, "sha256": sha256}, structure, quarantine, cfg["topics"])
    topics = records["topics"]
    unresolved = sum(1 for q in quarantine.items if q["stage"] == "silver.course" and q["reason"].startswith("UNRESOLVED_TITLE"))
    valid = len(records["courses"])
    h = cfg["health"]
    titled_den = valid + unresolved
    titled = valid / titled_den if titled_den else 0.0
    noise = sum(1 for t in topics if t["noise_label"] != "TOPIC") / max(1, len(topics))
    prov = sum(1 for t in topics if t["doc_id"] and t["course_uid"] and t["page_number"]) / max(1, len(topics))
    checks = [
        _check("valid_courses", valid, h["min_valid_courses"], valid >= h["min_valid_courses"]),
        _check("titled_course_ratio", round(titled, 4), h["min_titled_course_ratio"], titled >= h["min_titled_course_ratio"]),
        _check("topic_noise_ratio", round(noise, 4), h["max_topic_noise_ratio"], noise <= h["max_topic_noise_ratio"]),
        _check("provenance_completeness", round(prov, 4), h["min_provenance_completeness"],
               prov >= h["min_provenance_completeness"]),
    ]
    failed = [c for c in checks if c["status"] == FAIL]
    quarantined = {}
    for q in quarantine.items:
        if q["stage"] == "silver.course":
            reason = q["reason"].split(":")[0]
            quarantined[reason] = quarantined.get(reason, 0) + 1
    return {
        "status": FAIL if failed else PASS,
        "checks": checks,
        "reasons": [_plain(c) for c in failed],
        "valid_courses": valid,
        "courses_with_semester": sum(1 for c in records["courses"] if c.get("semester")),
        "courses_set_aside": quarantined,
        "learned_code_shapes": list(getattr(structure, "learned_code_shapes", []) or []),
        "basis": "the analysis's own course checks (SILVER build and document health thresholds)",
    }
