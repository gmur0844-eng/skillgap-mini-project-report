"""
Skill intelligence stages (Phase 5, experimental). Built on the Phase 3C skill evidence baseline (skill_evidence.py),
never replacing it: every stage reads a field that v0.2 already decided and records where a skill stops and why.

  1 MENTIONED              at least one occurrence in a job posting
  2 QUALIFIED              the skill-level decision is demand evidence (technical, professional, domain, transversal)
  3 NORMALIZED             at least one occurrence resolved to a confirmed taxonomy concept
  4 DISCIPLINE_RELEVANT    a qualified, non-transversal skill in the programme profile or discipline-adjacent by
                           posting evidence (transversal skills matter to every programme; they are reported, not
                           judged as discipline gaps)
  5 DEMAND_SUPPORTED       support state SUPPORTED or HIGH_SUPPORT counted on qualified occurrences in job-relevant
                           postings
  6 ANALYTICALLY_ELIGIBLE  all of the above and skill_evidence.skill_gap_eligible: a confirmed occurrence that is
                           itself demand-eligible

A skill that stops early is not discarded: it keeps its stage, its reason and its counts, and the gap reasoning says
INSUFFICIENT_EVIDENCE for it with that reason.
"""
from app.knowledge_engine import skill_evidence as se

METHOD = "skill intelligence stages v0.1 (experimental, over skill evidence v0.2)"
STAGES = ("MENTIONED", "QUALIFIED", "NORMALIZED", "DISCIPLINE_RELEVANT", "DEMAND_SUPPORTED", "ANALYTICALLY_ELIGIBLE")
SUPPORTED = ("SUPPORTED", "HIGH_SUPPORT")
RELEVANT = ("IN_PROGRAMME_PROFILE", "DISCIPLINE_ADJACENT")


def stage(row, occurrences=()):
    """row: one skill_evidence.jsonl record (Phase 3C); occurrences: its mention_evidence records."""
    checks = [
        ("MENTIONED", bool(row.get("decisions")), "no occurrence in any posting"),
        ("QUALIFIED", row.get("decision") in se.DEMAND_ELIGIBLE,
         f"skill-level decision {row.get('decision')}: not demand evidence"),
        ("NORMALIZED", bool(row.get("normalized_concept")),
         "no occurrence resolves to a confirmed taxonomy concept; counted under its own wording only"),
        ("DISCIPLINE_RELEVANT", row.get("decision") in se.QUALIFIED and row.get("programme_relevance") in RELEVANT,
         ("transversal skill: relevant to every programme, reported separately, never a discipline gap"
          if row.get("decision") == "TRANSVERSAL" else
          f"programme relevance {row.get('programme_relevance')}: outside the programme profile and not "
          "discipline-adjacent by posting evidence")),
        ("DEMAND_SUPPORTED", (row.get("new") or {}).get("support_state") in SUPPORTED,
         f"industry support {(row.get('new') or {}).get('support_state')} "
         f"({(row.get('new') or {}).get('postings', 0)} postings, {(row.get('new') or {}).get('companies', 0)} "
         "companies) is below SUPPORTED"),
        ("ANALYTICALLY_ELIGIBLE", bool(row.get("gap_eligible")) if not occurrences else
         se.skill_gap_eligible(row.get("decision"), row.get("programme_relevance"), occurrences),
         "no occurrence is both confirmed and demand-eligible"),
    ]
    passed, stop = [], None
    for name, ok, why in checks:
        if not ok:
            stop = {"stage": name, "reason": why}
            break
        passed.append(name)
    return {"skill_key": row["skill_key"], "skill_label": row.get("skill_label"),
            "stage_reached": passed[-1] if passed else None, "stages_passed": passed,
            "stopped_at": stop, "eligible": stop is None,
            "decision": row.get("decision"), "programme_relevance": row.get("programme_relevance"),
            "support_state": (row.get("new") or {}).get("support_state"),
            "postings": (row.get("new") or {}).get("postings", 0), "companies": (row.get("new") or {}).get("companies", 0),
            "strong_or_medium_postings": row.get("strong_or_medium_postings", 0),
            "normalized_concept": bool(row.get("normalized_concept")), "method": METHOD}
