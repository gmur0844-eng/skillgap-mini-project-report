# Architecture — curriculum intelligence engine 2.0

Engine `knowledge-engine-2.0.0`, configuration `2.0.0` (`backend/app/knowledge_engine/engine_config.json`).
Engine 1.x stages are unchanged; 2.0 adds a full-ESCO taxonomy stage, an intelligence stage, a semantic-provider
layer, new GOLD files, API routes, DB tables and Flutter screens. Earlier GOLD runs are kept.

```
SOURCES (data/raw, hash-verified via data/metadata/curriculum_sources.json)
  curriculum PDFs (TARGET / PREVIOUS_VERSION / REFERENCE)   job-posting xlsx (4)   ESCO full ZIP   ESCO delta ZIP
      │                                                          │                      │               │
BRONZE  page text (layout-aware), cached by doc sha + parser fp  │                      │               │
      │                                                          │                      │               │
SILVER  courses · units · topics · outcomes · prerequisites     postings (dedupe,      esco_full.build_store
        (pydantic contracts, quarantine, noise labels)           provenance)            + delta annotations
      │                                                          │                      │
HEALTH GATE (per document; industry health) → analytics gates (BLOCKED outputs produce no numbers)
      │
GOLD  structural understanding   course families → concepts (TF-IDF clustering) → reference mappings
      topic extraction           topic_hierarchy (explicit "Head: items")
      skill / taxonomy layer     mentions in postings + topics → ESCO mapping (prefLabel precedence,
                                 alias-sense and acronym-sense rules, label evidence rule, containment rule)
      industry                   demand (posting + company prevalence, support states), segments, temporal scope
      intelligence (2.0)         occupations (ESCO labels → ISCO), skill taxonomy context, coverage relation +
                                 depth, gaps v2, trends, lag, prerequisite recommendations, semantic drift
                                 categories, peer benchmark, knowledge graph + consistency checks,
                                 semantic adjudication (SemanticModelProvider → decision records, cache)
      evidence                   evidence traces, why-not, review queues, lineage (run report)
      │
PUBLISH  PostgreSQL schema `knowledge` (psql \copy + INSERT … ON CONFLICT DO NOTHING; SQL integrity checks)
      │
API   /api/v1/curriculum/*  /api/v1/industry/*  /api/v1/semantic/*  /api/v1/intelligence/*   (FastAPI, read-only)
      │
FLUTTER  data-driven screens over those endpoints (not compiled here: no Flutter SDK)
```

## The five analysis agents (release candidate `0534d6e1d06a617f`)

An agent is a pipeline component with a defined responsibility, inputs and outputs. The agents are not five independent
language models. They run in this order, each reading the previous agents' stored outputs:

1. Curriculum Understanding
2. Discipline-to-Industry Relevance
3. Skill Intelligence
4. Skill-Gap Reasoning
5. Curriculum Recommendation

**Authoritative layers.** Every agent's authoritative layer runs inside `run_knowledge_pipeline.py`:

| Agent | Authoritative layer |
|---|---|
| 1 | structure, topic hierarchy and concepts (`silver.py`, `concepts.py`) |
| 2 and 3 | skill extraction, ESCO mapping, demand and its support rules (`industry.py`, `industry_stage.py`) |
| 4 | gap classification v2 (`intelligence_stage.py`) |
| 5 | existing-course-first recommendations and their reasoning |

**Experimental layers.** They run afterwards with `scripts/pipeline/run_agents.py --run <id>`:

| Agent | Experimental layer |
|---|---|
| 2 | `relevance.py` |
| 3 | `skill_intelligence.py`, skill-evidence qualification |
| 1 and 4 | `curriculum_understanding.py`, `gap_reasoning.py` |

They write only to `data/experiments/<layer>/<run>/`, plus a manifest with the sha256 of each output. A failed layer stops
the chain.

**Exposed through:**
- API: `/api/v1/agents` and `/api/v1/agents/gap-review` (labelled EXPERIMENTAL);
- Flutter screens: "Analysis agents" and "Gap review (experimental)".

The language model (Qwen via Ollama, or its verified recording) is advisory under Safe Mode in every agent. Details:
`docs/intelligence/README.md`.

## Determinism and reproducibility

**Run id.** It is a hash of:
- pipeline version;
- parser fingerprint;
- code fingerprint (every `*.py` in `knowledge_engine` and `analytics`);
- configuration hash;
- semantic identity (mode, model key, replayed recording sha256);
- source document hashes;
- review decisions.

**Deterministic order.**
- Ordered outputs never rely on an unspecified sort order.
- Ties in descriptive TF-IDF labels break by term.
- Peer top-k candidates use a stable sort.
- CSV exports are written in key order.

**Cross-machine reproducibility.**
- `run_report.json` records the numeric environment (Python, NumPy, SciPy, scikit-learn, BLAS).
- `scripts/audit/reproducibility_gate.py` compares two builds of the same run id. Only the fields listed in
  `scripts/audit/reproducibility_policy.json` may differ, and every allowed difference is reported.

## Evidence classes (used everywhere)

| Class | Meaning |
|---|---|
| `EXTRACTED` | read from a source document / posting, with provenance |
| `REFERENCE_MAPPED`, `NORMALIZED`, `REFERENCE_TAXONOMY_FACT` | a deterministic match to ESCO / a fact stated by ESCO |
| `MODEL_SUGGESTED` | a lexical model (TF-IDF) or a language model proposed it; uncalibrated |
| `INFERRED`, `INFERRED_FROM_TEXT` | computed from the above by a stated rule (gaps, coverage levels, recommendations) |
| `REVIEW_REQUIRED` | the rules could not decide; queued for optional human review |
| `INSUFFICIENT_EVIDENCE` | the data does not support a conclusion |
| `HUMAN_VALIDATED` | only from ingested human labels — **none exist** |

A recommendation or a model decision is never source evidence (`is_source_evidence = false`, DB CHECK).

## Modules (backend/app/knowledge_engine)

| Module | Role |
|---|---|
| `pipeline.py` | orchestration, run id, GOLD writing, bundle for publish |
| `silver.py`, `contracts.py`, `noise.py`, `health.py`, `quarantine.py` | structure, contracts, noise labels, health gates |
| `concepts.py`, `mapping.py`, `drift.py`, `prerequisites.py`, `review.py` | concepts, reference mappings, drift, prerequisites, review queue |
| `esco_delta.py` | delta change log (Added/Updated/Removed labels) |
| `esco_full.py` (2.0) | full ESCO store, integrity audit, matching vocabulary, occupations, hierarchies |
| `industry.py`, `industry_stage.py`, `jobs.py`, `evidence_guard.py` | mentions, mapping, sense rules, demand, gaps, recommendations |
| `intelligence.py`, `intelligence_stage.py` (2.0) | hierarchy, occupations, coverage, trends, lag, graph, adjudication |
| `semantic_backend.py` | similarity backends (TF-IDF used; embedding backends probe as unavailable) |
| `semantic_provider.py` (2.0) | SemanticModelProvider: Ollama / OpenAI-compatible / local transformers / embedding / deterministic fallback |
| `db_publish.py`, `app/db/knowledge_schema.sql` | PostgreSQL load and integrity |

## Generalization

No production code names an institution, programme, discipline or skill. Sources, roles and disciplines come
from the manifest. `scripts/evaluation/static_generalization_audit.py` → **0 forbidden conditionals** (8 literals, all
in seed/CLI data). The semantic hard cases are test data (`data/evaluation/semantic_hard_cases_v2.json`); a test
fails if any engine-2.0 module contains a conditional on one of them.
