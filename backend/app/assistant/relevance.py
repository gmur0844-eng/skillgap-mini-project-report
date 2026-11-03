"""
Syllabus relevance of a demanded skill, from ESCO's own classification recorded in the run
(intelligence/skill_taxonomy_context.jsonl: reuse level, collections, top-level skill groups) and the discipline's map
of core and supporting ESCO groups (data/metadata/syllabus_relevance.json).

  CORE_CONTENT           belongs in the discipline's syllabus as topics (ICT knowledge for CSE, a technology tool...)
  SUPPORTING_CONTENT     a neighbouring field the syllabus draws on (mathematics for CSE)
  PROFESSIONAL_PRACTICE  transversal or generic skills (leadership, decision making, communication): developed through
                         how courses are taught and assessed (projects, team work), not as syllabus topics
  OTHER_FIELD            knowledge of another field (financial analysis for CSE): an elective or minor at most
  UNCLASSIFIED           no taxonomy facts to decide on

The label guides the assistant and its drafts; it never changes a gap classification or an analysis result.
"""
import json
from functools import lru_cache
from pathlib import Path

from app.knowledge_engine import discipline_profiles

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "data/metadata/syllabus_relevance.json"

HOW = {
    "CORE_CONTENT": "teach as syllabus topics",
    "SUPPORTING_CONTENT": "cover where the syllabus draws on it (prerequisite or supporting course)",
    "PROFESSIONAL_PRACTICE": "develop through teaching methods and assessment (projects, team work, presentations), "
                             "not as syllabus topics",
    "OTHER_FIELD": "outside the discipline's core: an elective or minor at most",
    "UNCLASSIFIED": "no taxonomy facts: decide with faculty",
}


@lru_cache(maxsize=2)
def _config(path=str(CONFIG)):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def profile_of(run):
    target = next((d for d in run.report.get("documents") or [] if d.get("role") == "TARGET"), {})
    prof = discipline_profiles.resolve(target.get("discipline"))
    return (prof or {}).get("id") or _config()["default_profile"]


def taxonomy(run):
    from app.services import intelligence_service as svc
    try:
        rows = svc.IntelligenceRun(run).rows("skill_taxonomy_context.jsonl")
    except Exception:  # noqa: BLE001 -- older runs have no taxonomy context
        rows = []
    return {r["skill_key"]: r for r in rows}


def classify(tax, skill, profile_id, config=None):
    cfg = config or _config()
    prof = cfg["profiles"].get(profile_id) or cfg["profiles"][cfg["default_profile"]]
    practice = set(cfg["practice_groups"])
    tax = tax or {}
    groups = set(tax.get("top_skill_groups") or [])
    collections = set(tax.get("collections") or [])

    def out(label, reason):
        return {"relevance": label, "reason": reason, "how_to_address": HOW[label]}

    if tax.get("reuse_level") == "transversal" or "transversalSkillsCollection" in collections:
        return out("PROFESSIONAL_PRACTICE", "ESCO classifies it as a transversal skill")
    if not tax:
        if (skill or {}).get("skill_category") == "TECHNOLOGY_TOOL":
            return out("CORE_CONTENT" if prof.get("digital_is_core") else "SUPPORTING_CONTENT",
                       "a technology tool named in the postings")
        return out("UNCLASSIFIED", "no ESCO taxonomy facts for this skill")
    if groups & set(prof["core"]):
        return out("CORE_CONTENT", "ESCO group: " + ", ".join(sorted(groups & set(prof["core"]))))
    if "digitalSkillsCollection" in collections and prof.get("digital_is_core"):
        return out("CORE_CONTENT", "ESCO digital skills collection")
    if groups & set(prof.get("supporting") or []):
        return out("SUPPORTING_CONTENT", "ESCO group: " + ", ".join(sorted(groups & set(prof["supporting"]))))
    if groups and groups - {"knowledge", "skills"} <= practice:
        return out("PROFESSIONAL_PRACTICE", "ESCO group: " + ", ".join(sorted(groups - {"knowledge", "skills"})))
    fields = sorted(groups - {"knowledge", "skills"} - practice)
    if fields:
        return out("OTHER_FIELD", "ESCO group: " + ", ".join(fields))
    return out("UNCLASSIFIED", "the ESCO groups do not decide it")


class RunRelevance:
    """skill_key -> relevance for one run (computed once)."""

    def __init__(self, run):
        self.profile = profile_of(run)
        self._tax = taxonomy(run)
        self._skills = (run.industry or {}).get("skills") or {}
        self._cache = {}

    def of(self, skill_key):
        if skill_key not in self._cache:
            self._cache[skill_key] = classify(self._tax.get(skill_key), self._skills.get(skill_key), self.profile)
        return self._cache[skill_key]
