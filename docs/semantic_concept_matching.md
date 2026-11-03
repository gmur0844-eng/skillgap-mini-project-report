# Semantic Concept Matching — Honest Capability Statement

## What was requested vs. what is actually implemented

The project brief called for a transformer-based architecture: Sentence
Transformers/BGE/E5/MPNet/MiniLM embeddings, cross-encoders, Natural
Language Inference, zero-shot classification, and optionally LLMs — layered
on top of the existing deterministic matching.

**This build environment cannot run any of that.** Verified directly, not
assumed:
- No `torch`, no `transformers`, no `sentence-transformers` installed.
- No network access to install them (`pip install sentence-transformers`
  fails with "No matching distribution found" — there is no package index
  reachable).
- HuggingFace itself (`huggingface.co`) returns `403` from this sandbox's
  egress proxy, the same restriction that has blocked every other external
  service in this project (NCS, Jooble, AICTE/CBIT downloads).

This is a hard infrastructure constraint, not a design choice. Building
something and *calling* it "semantic embeddings" would be dishonest.

## What was actually built instead

A **two-stage fallback architecture**, using only `scikit-learn` (already a
project dependency):

- **Stage 1 (unchanged)**: the existing deterministic taxonomy
  (`core_knowledge_mapping.py`) — exact/normalized/abbreviation/synonym/
  conjunction/compound. Always tried first; when it matches, Stage 2 is
  never consulted, so `SAME_CONCEPT` is reserved exclusively for these
  verified deterministic methods.
- **Stage 2 (new)**: TF-IDF + cosine similarity retrieval
  (`concept_semantic_matching.py`), with a small custom tokenizer doing
  minimal suffix-stripping ("Searching"→"search", not a real Porter
  stemmer or nltk — neither available) and a generic English stopword
  filter.
- **Stage 3 (new)**: a deterministic, rule-based relationship classifier
  (token-containment heuristics), producing SAME_CONCEPT / RELATED /
  PARENT / CHILD / PARTIAL_OVERLAP / UNRELATED / AMBIGUOUS /
  INSUFFICIENT_EVIDENCE.

**This is classical statistical term-overlap, not meaning-based
understanding.** It genuinely helps with cases sharing distinctive
vocabulary and genuinely fails at pure paraphrase with no shared words —
both demonstrated below with real data, not cherry-picked.

## Model abstraction (Step 4, honored despite no real model existing)

`retrieve_candidate_concepts(..., vectorize_fn=None)` accepts an optional
`vectorize_fn(query_text, corpus_texts) -> similarity_scores` callable. The
default is the TF-IDF implementation; a genuine transformer embedder could
be substituted later with zero changes to any caller, `resolve_concept`, or
the result shape, the moment model access exists.

## Context windows (Step 3) — implemented for real, no ML required

`build_context_representation()` assembles course title, module heading,
adjacent topics, and outcomes around a bare topic string, and
`_contextualized_text()` folds the course title into the retrieval query —
genuinely improving disambiguation (e.g. "Scheduling" retrieves "Process
Scheduling" over "Project Scheduling" when "Operating Systems" context is
present), verified by a real test.

## Real results — run against actual CBIT/AICTE data, not synthetic-only

Against 113 real, genuine CBIT R-22A courses vs. the 29-topic AICTE
reference:

| | Count |
|---|---|
| Stage 1 (deterministic, historically valid) | 8 |
| Stage 2 RELATED | 15 |
| Stage 2 PARTIAL_OVERLAP | 28 |
| Stage 2 CHILD | 2 |
| Stage 2 AMBIGUOUS | 15 |
| Stage 2 INSUFFICIENT_EVIDENCE | 45 |

**These numbers are NOT a "curriculum alignment score."** RELATED/
PARTIAL_OVERLAP/CHILD are lexical-overlap-based hypotheses requiring human
review (`review_required: true` on every Stage-2 result except none — the
implementation never marks a Stage-2 result as not-needing-review), not
verified semantic equivalences.

### A genuine success (validation examples from the brief)
Run as unit tests against a small synthetic reference set (the brief's own
examples): "Searching techniques including sequential and binary search"
correctly retrieves "Searching"; "Deadlock prevention, avoidance, detection
and recovery" correctly retrieves "Deadlock Management"; "Normalization and
functional dependencies" correctly retrieves "Database Normalization". All
at LOW-to-MEDIUM confidence (0.19–0.48), correctly not claimed as certain.

### A genuine, real bug found and fixed via honest testing
Initial real-data testing surfaced "INDIAN CONSTITUTION AND FUNDAMENTAL
PRINCIPLES" spuriously matching "Signals and Systems" — both share only the
word "and". With a tiny 29-item reference corpus, IDF weighting alone did
not sufficiently downweight common connector words. Fixed with an explicit,
generic English stopword filter (not a CBIT/AICTE-specific list) and locked
in with a regression test.

### A genuine, disclosed remaining limitation: polysemy
Real CBIT course "DATABASE MANAGEMENT SYSTEMS" scores *higher* against
AICTE's "Management-I" (an Organizational Behaviour course, 0.6067) than
against the genuinely correct "Introduction to Database Systems" (0.604) —
both share the stemmed token "manag[e]", and TF-IDF has no way to know
"Management" means something entirely different in each context. In this
case the ambiguity-detection safety net caught it (the two scores were
within the configured gap, correctly flagged `AMBIGUOUS`, not silently
wrong). But "ENERGY MANAGEMENT SYSTEM" hit the same underlying collision
and was NOT caught — it was classified `CHILD` of "Management-I" at 0.58
confidence, which is wrong. **This is a real, disclosed failure case,
not hidden.** It is exactly the kind of context-sensitive word-sense
disambiguation a real transformer embedding would handle far better than
lexical overlap ever can — concrete evidence for why the original
architecture was requested, not a hypothetical justification.

### Concept discovery (Step 8)
Of the 45 courses with no candidate clearing the similarity floor, all 45
correctly produce a `NEW_DISCOVERED_UNMAPPED` record rather than being
forced into an unrelated existing concept (e.g. "LINEAR ALGEBRA AND
CALCULUS", "INDIAN CONSTITUTION AND FUNDAMENTAL PRINCIPLES", "COMMUNITY
ENGAGEMENT" — genuinely outside the current 29-topic CSE-core reference,
correctly left unmapped rather than guessed at).

## What was NOT implemented this phase, and why

- **NLI / cross-encoder verification (Step 7)**: no model available (same
  root cause as above).
- **Knowledge graph, 7 new DB models (Topic/Concept/ConceptRelationship/
  ConceptMapping/SemanticEvidence/ConceptEmbedding/ReviewItem), 9 new API
  routes (Step 18)**: designed conceptually above, but not implemented —
  there is no live database in this sandbox (confirmed unavailable across
  every phase of this project), and writing untestable schema/API code
  against a DB that cannot be exercised was judged premature. The result
  shapes already returned by `resolve_concept`/`discover_concept` map
  directly onto these models' intended fields, so implementing them once a
  DB exists is a mechanical persistence step, not a redesign.
- **Labeled evaluation dataset with precision/recall/F1 (Step 16)**: not
  built. A real precision/recall claim requires enough independently
  labeled examples to be statistically meaningful; fabricating a small
  hand-picked set and reporting "F1" on it would misrepresent rigor that
  doesn't exist yet.
- **Layout-aware, multi-column PDF extraction (Step 1) using PyMuPDF
  blocks/coordinates**: not implemented this phase. `pdftotext -layout`
  (already in use) approximates column order but does not give real
  coordinate/block data. This remains the single highest-value next step
  for improving raw extraction quality, independent of the semantic layer.

## Foundational work: layout-aware extraction + corpus-wide clustering (Steps 1-7)

### Step 1: Layout-aware AICTE re-extraction (real fix, real regression avoided)

Root cause confirmed directly (not assumed): AICTE's syllabus pages use a
genuine 4-column table (Module | Topics | Pedagogy suggestions | Lab
practice); `pdftotext -layout`'s single text stream interleaves all four
columns, which is exactly why previous topic extraction contained pedagogy
notes and lab text mixed into "topics." `pdfplumber.find_tables()` +
`extract_tables()` isolates the Topics column cleanly -- verified: CS-301's
topics went from garbled ("Introduction and basic structures and
algorithms. (i) Explain 𝑛𝑛 between algorithms...") to clean ("Abstract
Data-types", "Arrays", "Linked Lists", "Stacks", "Queues", "Dictionary
ADT"). Extraction confidence: 0.77 -> 0.79.

**A real regression found and reverted via honest testing**: applying the
same word-position "prose" reconstruction to CBIT (which has no Topics
table at all -- confirmed via `find_tables()`) *destroyed* quality (349->31
modules). Fixed with a hybrid approach: table-column isolation only for
pages that actually contain a detected Topics column (31/214 AICTE pages;
0/246 CBIT pages), falling back to the already-proven `pdftotext`
extraction everywhere else. CBIT's real numbers are fully preserved: 316
course entries, 349 modules, 600 outcomes, confidence 0.83.

**A second, more severe bug found and fixed**: initial boilerplate
(header/footer) detection wrongly stripped "UNIT-I", "Course Outcomes",
and other structural markers that legitimately recur once per course --
not because they're running headers, but because the document has that
many courses. This destroyed CBIT's module/outcome detection (349->31
modules) even on pages using the safe fallback path. Fixed by excluding
any line matching a known structural-marker regex from ever being
classified as boilerplate, regardless of page-repetition count. Locked in
with two regression tests.

### Steps 3-4: Clean corpus + corpus-wide clustering (real results)

Combined real corpus: 4,506 AICTE + 3,117 CBIT topic fragments (7,623
total, after excluding fragments under 12 characters as noise). Clustered
into 150 groups via TF-IDF + KMeans (`n_clusters=150` is a configurable
exploration parameter, not empirically tuned -- no labeled ground truth
exists yet). 128 of 150 clusters contain fragments from BOTH documents --
the strongest available evidence of a genuinely shared concept using only
lexical statistics.

**Genuine successes**: clusters correctly grouped algorithm/design-related
content, Design-Thinking-related content, and Engineering-Physics-related
content coherently across both documents.

**Genuine, disclosed failures, not hidden**: the single largest cluster
(2,610 fragments) is dominated by textbook-citation vocabulary
("veerarajan", "reprint", "chapter") -- bibliography noise that leaked
through extraction, exactly the failure mode the original brief warned
against, now visible and flagged rather than silently degrading results.
A second cluster wrongly grouped "Tests for convergence" (mathematics)
with "Testing Creative"/"Test Group Marketing" (a Design Thinking course)
purely because they share the stemmed word "test" -- the same
context-blind lexical-collision limitation already documented for
Stage 2/3 matching.

### Steps 6-7: Human review artifact (created, NOT auto-promoted)

`data/silver/core_knowledge/aicte_derived_cse_reference/cluster_review_queue.json`
-- all 150 clusters, each with representative terms, up to 6 example
fragments (full provenance: source document, course code, module heading,
page number), a heuristic (non-authoritative) bibliography-noise flag (5
clusters flagged), and an empty `review_decision`/`reviewer_notes` field
for a human to fill in. **Nothing in this file has been treated as ground
truth or fed into any matching/mapping step.**

### Step 8: NOT performed

Per explicit instruction, no cluster has been promoted to the canonical
concept ontology, and no new CBIT<->AICTE alignment percentage is reported
this phase -- that requires human review of the artifact above first.
