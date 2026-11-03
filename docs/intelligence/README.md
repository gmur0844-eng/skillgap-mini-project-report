# Intelligence layer documentation

## The five analysis agents

An agent here is a pipeline component with a defined responsibility, inputs and outputs, not an LLM wrapper. The
agents run in this order, and each reads the previous agents' stored outputs:

1. Curriculum Understanding
2. Discipline-to-Industry Relevance
3. Skill Intelligence
4. Skill-Gap Reasoning
5. Curriculum Recommendation

**Authoritative layers.** Every agent's authoritative layer runs inside the knowledge pipeline
(`scripts/pipeline/run_knowledge_pipeline.py`).

**Experimental layers.** The experimental layers of agents 1–4 run afterwards, in order:
`python3 scripts/pipeline/run_agents.py --run <run_id>`. They write only to `data/experiments/<layer>/<run_id>/` and
record a manifest in `data/experiments/agents/<run_id>/manifest.json`.

**API.**

- `GET /api/v1/agents`: the registry, with each agent's responsibility, code, inputs and outputs, and whether its
  outputs exist for the selected run.
- `GET /api/v1/agents/gap-review`: the experimental gap states beside the authoritative classification, labelled
  EXPERIMENTAL.

**App.** "Analysis agents" (System) and "Gap review (experimental)" (Evidence). The Skill gaps and Recommendations
screens keep showing the authoritative results.

**The semantic model (Qwen)** stays advisory under Safe Mode in every agent.

| Layer | Document | Status |
|---|---|---|
| Discipline-to-industry relevance | `../industry_relevance_methodology.md`, `../industry_relevance_evaluation.md` | EXPERIMENTAL (Phase 3) |
| Skill evidence (qualification, normalization) | `../skill_evidence_generalization.md` | EXPERIMENTAL; baseline validated on the Mac (Phase 3C) |
| Curriculum understanding | `curriculum_understanding.md` | EXPERIMENTAL (Phase 4) |
| Skill intelligence stages | `skill_intelligence.md` | EXPERIMENTAL (Phase 5) |
| Gap reasoning | `gap_reasoning.md` | EXPERIMENTAL (Phase 6); v2 stays authoritative |
| Recommendation reasoning | `../recommendation_methodology.md` | EXPERIMENTAL (Phase 7) |

**How to reproduce Phases 4–6 by hand** (`run_agents.py` runs steps 1 and 2, after the relevance audit):

1. `python3 scripts/analysis/skill_evidence_audit.py --final-holdout` (Phase 3C baseline).
2. `python3 scripts/analysis/gap_reasoning_audit.py`.
3. `python3 scripts/analysis/gap_review_sample.py` (blind review set).
