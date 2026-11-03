# Gap reasoning (Phase 6, experimental)

*Code:* `backend/app/knowledge_engine/gap_reasoning.py`.

This layer **extends** gap classification v2 (`intelligence_stage.gap_v2`) rather than adding a parallel classifier.
v2 stays authoritative, and the screens and recommendations are unchanged, until this layer has been reviewed by
people (Phase 11) and promoted.

## States

| State | Rule | v2 equivalent |
|---|---|---|
| NO_GAP | Taught at SUBSTANTIAL or ADVANCED depth in a course every student takes, or whose status the document does not print. | COVERED |
| LIMITED_COVERAGE | Either taught, but only in elective options; or not taught itself while a **directly narrower** concept is, so the skill is reached through a specific instance. | PARTIAL |
| DEPTH_GAP | Taught only at INTRODUCTORY depth in a compulsory (or unprinted-status) course. | PARTIAL |
| STRUCTURAL_GAP | Not taught (ABSENT, or only a MENTION) in a **complete** document. | MISSING |
| INSUFFICIENT_EVIDENCE | One of: the skill did not reach ANALYTICALLY_ELIGIBLE; the document is partial or prints no semesters; or the skill names the programme's own discipline. | INSUFFICIENT_EVIDENCE |
| REVIEW_REQUIRED | The curriculum evidence disagrees with itself. Either a title or outcome claims the skill but no topic teaches it (UNCERTAIN), or a whole course is named after a skill whose topics show only introductory depth (the release's COURSE_TITLE_NAMES_SKILL rule). | REVIEW_REQUIRED |
| OUTDATED_COVERAGE | SUBSTANTIAL or ADVANCED coverage while the industry trend is DECLINING or REPLACED. | OUTDATED |

**OUTDATED_COVERAGE is wired to one trend source**, `industry_v2/skill_trends.jsonl`, as COMPLETION_AUDIT §19.1
asked. With one posting period every trend is INSUFFICIENT_DATA, so the state cannot fire on the release. It does fire
in the synthetic suite.

**Partial documents.** A partial document can show what is taught, never what is missing. Any gap or review state
becomes INSUFFICIENT_EVIDENCE when the target's scope is not COMPLETE; NO_GAP stays.

**Corroboration never decides.** The reference curriculum, the institution's other curriculum and peer curricula are
reported beside every state ("PEER: 1 of 3 teach it"). They never decide it. A broader concept being taught is
reported as context only, because the taxonomy is not proof.

**Transformer slot (advisory).** `reason(..., semantic_coverage=f)` records `f`'s output under `advisory` with
`applied: false`. A test checks that the state never changes because of it. No model is wired in.

## Results on the release (target CBIT R22A, 58 analytically eligible skills)

| State | Skills |
|---|---|
| NO_GAP | 15 |
| LIMITED_COVERAGE | 10: e.g. kubernetes, docker, DevOps, Hadoop, cyber security, NoSQL, project management. All are taught only in electives. |
| DEPTH_GAP | 5: MySQL, Agile development, data models, node.js, accounting |
| STRUCTURAL_GAP | 21: e.g. TypeScript, PostgreSQL, Scala, C#, GDPR, data engineering |
| REVIEW_REQUIRED | 6: Python (computer programming), data analytics, SPARK, system design, JavaScript Framework, ICT encryption |
| INSUFFICIENT_EVIDENCE | 1: "computer science" names the programme's own discipline |

**The 11 confirmed v2 gaps**, in the new reasoning:

| Skill | v2 | New |
|---|---|---|
| MySQL, Agile development, data models, node.js | PARTIAL | DEPTH_GAP |
| NoSQL, financial analysis, docker | PARTIAL | LIMITED_COVERAGE (elective only) |
| SPARK, system design | MISSING | REVIEW_REQUIRED (only a course outcome names it) |
| make decisions, lead others | MISSING | INSUFFICIENT_EVIDENCE (transversal) |

**The 11 issued recommendations.** 7 still have a gap state:

- 4 are DEPTH_GAP;
- 3 are LIMITED_COVERAGE. Here the issue is access through electives, not absence.

2 now need review: SPARK and system design. 2 are no longer a basis: make decisions, and lead others ("add elective").

**Transitions from v2** (243 v2 skills):

| v2 | Phases 4–6 | Skills |
|---|---|---|
| COVERED | NO_GAP | 6 |
| COVERED | LIMITED_COVERAGE (taught only in electives) | 6 |
| COVERED | INSUFFICIENT_EVIDENCE (stage) | 5 |
| PARTIAL | DEPTH_GAP | 4 |
| PARTIAL | LIMITED_COVERAGE | 3 |
| PARTIAL | REVIEW_REQUIRED | 1 |
| PARTIAL | NO_GAP | 1 |
| PARTIAL | INSUFFICIENT_EVIDENCE (stage) | 11 |
| MISSING | REVIEW_REQUIRED | 2 |
| MISSING | INSUFFICIENT_EVIDENCE | 2 |
| INSUFFICIENT_EVIDENCE | STRUCTURAL_GAP | 14 |
| INSUFFICIENT_EVIDENCE | NO_GAP | 3 |
| INSUFFICIENT_EVIDENCE | REVIEW_REQUIRED | 2 |
| INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | 183 |

The 14 new structural gaps come from the larger Phase 3C demand evidence, for example TypeScript and Scala, which
reach SUPPORTED in v0.2. Every changed skill is listed with both reasons in `scorecard.json →
release_comparison.changed`.

## Evaluation

| Check | Result | Label source |
|---|---|---|
| Release extraction reproduced | 1,812 / 1,812 mentions identical; 0 mappings changed | — |
| Course status vs code conventions (3 institutions) | 290 agree, 2 disagree, 31 abstained (precision 0.993) | institution code convention |
| Synthetic cross-discipline suite (4 invented programmes) | course kind 13/15, status 15/15, level 10/10, scope 4/4, coverage 12/12, **gap 23/23** | AUTHOR_LABELLED |
| Determinism | All analysis outputs are byte-identical across `PYTHONHASHSEED` values, and across a working tree whose BRONZE cache had to be rebuilt | — |

**Synthetic suite.** The suite is `data/evaluation/gap_reasoning_suite_v1`, covering agricultural (UG), applied
chemistry (PG), commerce (partial document) and civil (UG). It was written **after** the implementation, so it is a
specification, not an accuracy estimate.

Its first run scored course status 14/15 and gap 20/23:

- **Status miss.** A "SEMESTER - VI" heading was missed because its hyphen counted as a numeric column. The rule was
  fixed generally and re-checked on the real documents, which were unchanged.
- **Gap misses.** All three came from an authoring error: the civil document had only two semesters, so the code
  correctly called it PARTIAL. The suite was corrected.
- **Course-kind failures.** The two are kept as known failures. Both runs are recorded in its MANIFEST.

**Blind review set.** `data/evaluation/gap_state_review_v1/` lists the 58 eligible skills with their evidence and
without the system's state. The system states are in a separate hashed file. **No human labels exist yet.** They are
Phase 11 work.

## Inputs and reproducibility

The audit declares every input in `INPUT_CONTRACT`, each with a class, and opens them only through that contract.
It checks all of them before any analysis.

| Class | What it is |
|---|---|
| RELEASE | The protected GOLD. Read only. |
| SOURCE | Raw documents, the source manifest and ESCO. |
| WORKING_TREE | SILVER for curricula and jobs, written by pipeline runs. Never packaged. |
| REGENERABLE_CACHE | BRONZE page text. Never packaged. |
| EXPERIMENT | The Phase 3C outputs, checked by hash. |
| EVALUATION, CONFIG | Evaluation data and the engine configuration. |

**How a missing BRONZE cache is rebuilt.** The cache is keyed by (source sha256, parser fingerprint). It exists only
where a pipeline run has processed that document. When a working tree lacks it, the audit rebuilds it with the
pipeline's own `bronze_pages`, but only if both of these hold:

- the raw source is present with the run's sha256;
- the installed parser fingerprint equals the run's recorded one.

Otherwise it stops with an `InputContractError` that says why.

**What every page text must reproduce.** Whether it came from the cache or was rebuilt, the page text must
reproduce:

- the SILVER records in content;
- the release GOLD courses;
- the run's 1,812 curriculum mentions.

**Run-assigned fields.** SILVER is rewritten by every run that processes a document, and a run stamps each topic with
the document's role in that run. A later run can therefore leave a different role in SILVER. The audit compares that
run-assigned field against the run being audited, not against the file. A test pins the list of such fields to the
pipeline's code.

**What the scorecard records.** It carries each document's page-text content hash, which has no timestamp. Which
caches were present and which were rebuilt goes to `provenance.json`, because that is machine-local.

## Tests

`backend/tests/test_gap_reasoning.py` has 32 tests:

- programme level;
- course kind;
- six invented scheme layouts;
- coverage levels, UNCERTAIN, access, practice and progression;
- taxonomy relations;
- consistency with the Phase 3C syllabus rule;
- every stage stop and every gap state;
- the partial-document guard;
- that the advisory scorer and corroboration change nothing;
- properties: more teaching never worsens a gap; ineligible skills are always INSUFFICIENT_EVIDENCE; no gap state
  comes from an incomplete document; evidence order and unrelated prose are irrelevant;
- a static audit of the three modules;
- the synthetic suite, with its two known failures asserted.

## Limitations

- **No human validation.** The states are rule outputs, checked against a synthetic specification and against code
  conventions (for status only).
- **Topic-based depth.** Depth is still measured from topic wording. A skill taught under a different name is found
  only through the taxonomy hierarchy (narrower concepts) or a confirmed syllabus resolution. Nothing semantic is
  applied.
- **Electives.** LIMITED_COVERAGE does not weigh how many students take an elective. The documents do not say.
- **Thin corroboration.** Peer evidence is thin. Two of three peers have no parsed semesters or status, and the
  reference prints no scheme.
