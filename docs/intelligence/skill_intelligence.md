# Skill intelligence stages (Phase 5, experimental)

*Code:* `backend/app/knowledge_engine/skill_intelligence.py`. It is built on the **Phase 3C skill evidence baseline**
(`skill_evidence.py` v0.2) and never replaces it.

The audit first checks that the Phase 3C scorecard is the validated one (sha256 `6ea0f53b…0823`, reproduced on the
owner's Mac on 2026-10-08). If it is not, the audit stops.

## The stages

Each stage reads a field that v0.2 already decided. A skill keeps the furthest stage it reaches and the reason it
stopped. Nothing is discarded.

| Stage | Passes when |
|---|---|
| MENTIONED | At least one occurrence in a posting. |
| QUALIFIED | The skill-level decision is demand evidence (technical, professional, domain or transversal). |
| NORMALIZED | At least one occurrence resolves to a confirmed taxonomy concept. |
| DISCIPLINE_RELEVANT | A qualified, **non-transversal** skill that is either in the programme profile or discipline-adjacent by posting evidence. Transversal skills matter to every programme. They are reported, never judged as discipline gaps. |
| DEMAND_SUPPORTED | Support is SUPPORTED or HIGH_SUPPORT, counted on qualified occurrences in job-relevant postings. |
| ANALYTICALLY_ELIGIBLE | All of the above, plus `skill_evidence.skill_gap_eligible`: at least one occurrence that is both confirmed and demand-eligible. |

## Results on the release (874 skill keys from Phase 3C)

| Stopped at | Skills |
|---|---|
| MENTIONED | 1 |
| QUALIFIED | 75 |
| NORMALIZED | 472: counted under their own wording only |
| DISCIPLINE_RELEVANT | 166: transversal, or outside the profile |
| DEMAND_SUPPORTED | 102: support below SUPPORTED |
| **ANALYTICALLY_ELIGIBLE** | **58** |

The gap reasoning (`gap_reasoning.md`) assigns states only to the 58 eligible skills. Every other skill is
INSUFFICIENT_EVIDENCE, with the reason for the stage at which it stopped.

### Examples

- **"make decisions" and "lead others".** They stop at DISCIPLINE_RELEVANT because they are transversal. Both were
  release gaps (MISSING), and "lead others" carried an "add elective" recommendation.
- **"python", "git", "linux", "aws".** These job-side wordings stay unconfirmed in v0.2, so they stop at NORMALIZED.
  For the job-side wording "python", the curriculum's own wording resolves to *Python (computer programming)*, so its
  coverage is read under that concept and the link is stated. The confirmed concept *Python (computer programming)*
  is itself eligible.

## Limitations

- The stages inherit the Phase 3C error profile. The largest class is wrong-sense (E5) on unseen postings. Only model
  and author labels exist so far, no human ones.
- Support thresholds are the release's (supported: at least 5 postings and at least 3 companies). They have not been
  re-derived here.
