# Skill qualification: methodology and evaluation (experimental)

**Status:** experimental (v0.1), superseded by v0.2: see `docs/skill_evidence_generalization.md`. The published release `c066b227857f9eaf` is authoritative and unchanged; so are its
demand, gaps, recommendations, the API and the screens. Qualification results are written only to
`data/experiments/skill_qualification/<run_id>/`.

| | Authoritative | Experimental |
|---|---|---|
| Postings, extraction, ESCO mapping, demand, gaps, recommendations | release `c066…` GOLD | – |
| Boilerplate and job relevance | – | `relevance.py` (Phase 3) |
| Skill qualification | – | `skill_qualification.py` (Phase 3B) |
| Benchmark labels | – | assistant labels only; no human labels exist |

**Files.**

- Code: `backend/app/knowledge_engine/skill_qualification.py`
- Audit: `scripts/analysis/skill_qualification_audit.py`
- Tests: `backend/tests/test_skill_qualification.py`
- Benchmark: `data/evaluation/skill_qualification_benchmark_v1/`

## Where qualification sits

```
RAW JOB -> BOILERPLATE DETECTION -> JOB/DISCIPLINE RELEVANCE -> SKILL EXTRACTION -> SKILL QUALIFICATION
        -> NORMALIZATION / ESCO -> INDUSTRY DEMAND -> CURRICULUM COVERAGE -> GAP -> RECOMMENDATION
```

Extraction (the release's) finds phrases and proposes standardised concepts. Qualification decides what each
extracted phrase is in its sentence, and whether it may count as demand evidence. No stage is merged into another.
Every extracted mention is kept, and qualification adds fields without changing the mention.

## Evidence used

There is no list of skills, disciplines or institutions anywhere; a test enforces this.

| Evidence | Used for |
|---|---|
| **Provenance** of the span: employer boilerplate, shared role text, or job-specific text (Phase 3) | boilerplate is never job evidence |
| **ESCO concept**: type (knowledge or skill-competence), reuse level, immediate parents, and how the surface matched (a preferred or alternative label, or a hidden search label) | type of skill; transversal competencies; alias handling |
| **Requirement framing** in the mention's clause ("experience with", "skills", "ability to", "knowledge of", "proficiency in", "required", …) | whether a competence is stated as required or only described as an activity |
| **Framing bound to the word** ("proficiency in X", "X skills") | resolving ordinary words such as "python", "communication" or "accounting" |
| **Taxonomy siblings** in the same sentence (another resolved skill sharing an immediate ESCO parent) | resolving ordinary words, aliases and multi-candidate surfaces ("Python, Java and SQL") |
| **Surface form**: a skill-competence named by its own verb phrase ("make decisions") or in nominal form ("decision-making skills") | generic action phrases versus competencies |
| **Programme profile and neighbourhood** (Phase 3) | technical or domain skill, relative to the programme |
| **Job relevance** (Phase 3) | eligibility of the posting, and discipline adjacency at skill level |

The framing cues are a grammatical lexicon of how English job text states requirements. They name no skill. The
relevance layer's job-level policy decides which postings are eligible; qualification decides which mentions are
evidence.

## Decisions

The first rule that applies wins.

| Decision | Rule | Demand | Gap |
|---|---|---|---|
| `EXCLUDED_BOILERPLATE` | the span is employer boilerplate | no | no |
| `AMBIGUOUS` | several candidate concepts and no single one supported by the sentence; or an alias or hidden-label match with no related skill in the sentence (framing alone does not establish *which* concept an alias names) | no | no |
| `EXCLUDED_INSUFFICIENT_CONTEXT` | an ordinary word whose sense the sentence does not establish (no bound framing, no related skill), or no concept at all | no | no |
| `EXCLUDED_GENERIC_CAPABILITY` | a skill-competence named by its bare verb phrase with no requirement framing ("help customers modernise", "how we make decisions"), or a transversal or cross-sector competence mentioned without framing | no | no |
| `TRANSVERSAL` | a transversal competency (ESCO reuse level) stated as a requirement ("ability to make decisions", "leadership skills") | yes | no |
| `QUALIFIED_TECHNICAL` | a technology or tool, or a concept the programme's curricula name | yes | yes |
| `QUALIFIED_PROFESSIONAL` | a non-transversal competence stated as a requirement ("proven ability to lead a team") | yes | no |
| `QUALIFIED_DOMAIN` | knowledge the programme's curricula do not name (e.g. a finance concept for a computing programme): legitimate, counted in demand | yes | no |
| `DISCIPLINE_ADJACENT` (skill level) | `QUALIFIED_DOMAIN` whose job-specific postings are mostly `RELEVANT` or `LIKELY_RELEVANT` | yes | yes |

**Confidence** is categorical, never a model score:

- **HIGH:** a label match with an established sense.
- **MEDIUM:** resolved by sentence context.
- **LOW:** ambiguous or unresolved.

**Each mention record contains:**

- the raw phrase and the normalised phrase;
- the span and the sentence;
- the posting, its title, its company and its job-relevance state;
- the text kind, and whether the span is boilerplate;
- the release's concept, mapping status and sense;
- whether requirement framing is present;
- the resolved concept, the type, the decision, the confidence, the reason and what resolved it;
- whether it is eligible for demand and for gaps.

## Version history (honest record)

- **v0.** The rules above, with framing anywhere in the clause, accepted for ordinary words and aliases alike.
  Measured once on the frozen benchmark (below) before any change.
- **v0.1.** Three changes, made after reading v0's **demand output** (not the benchmark):
  1. Words such as "scratch" ("from scratch"), "source" ("open-source") and "dies" were resolved to programming and
     game concepts because "experience" appeared elsewhere in their clause. Ordinary words now need framing bound to
     the word itself.
  2. "SaaS" resolved to *service-oriented modelling* through a hidden label. Aliases now need a related skill in the
     sentence; framing is not enough.
  3. A concept merely next to the profile in the taxonomy was `QUALIFIED_TECHNICAL`. It is now
     `QUALIFIED_DOMAIN` unless posting evidence makes it `DISCIPLINE_ADJACENT`.

  Because v0.1 was produced after the benchmark had been read, **the benchmark is no longer a clean held-out test
  for v0.1**.

Also fixed in v0.1:

- **A defect:** technology tokens with spurious taxonomy candidates (Docker, Kubernetes) had been marked ambiguous;
  they are now evaluated as technology tokens.
- **A reproducibility defect:** the reported sibling depended on hash order.

## Benchmark and evaluation

The benchmark is `data/evaluation/skill_qualification_benchmark_v1/`. It holds 239 real extracted mentions from the
498 postings, frozen with seed 20261008 (`benchmark.jsonl` sha256 `c2c58fbe…`). It has two strata:

- **131 hard cases:** up to six postings each for make decisions, decision making, reproductive health, help
  customers, financial statements, LinkedIn, Instagram, machine learning, SQL, Docker, Kubernetes, AWS, leadership,
  communication, Python, Java, lead a team, customer service, meet deadlines and project management.
- **108 random mentions.**

**Label question:** *does this phrase, in this sentence, state a skill or knowledge the job requires (demand
evidence)?*

**Label sources:**

| Source | File | Status |
|---|---|---|
| Human (independent reviewers) | `labels_human.csv` | **empty; no human validation has happened** |
| Assistant (model-generated) | `labels_assistant.jsonl` | 239 labels written by the assistant that designed the method, from phrase, sentence and title only (system decisions not shown). **Not independent and not human.** |
| Automated (the method) | – | the system output under test |

**Results against assistant labels.** Positive class: demand evidence. 125 positive, 114 negative.

| Version | Precision | Recall | F1 | Accuracy | TP / FP / FN / TN |
|---|---|---|---|---|---|
| v0 (held-out) | 0.869 | 0.744 | 0.802 | 0.808 | 93 / 14 / 32 / 100 |
| v0.1 (not held-out) | 0.925 | 0.592 | 0.722 | 0.762 | 74 / 6 / 51 / 108 |

v0.1 is deliberately conservative: it trades recall for precision.

**v0.1 errors:**

- 24 demand mentions were left `AMBIGUOUS`: aliases such as "decision-making", "people management" and "SaaS"
  without a related skill in the sentence.
- 20 were `EXCLUDED_INSUFFICIENT_CONTEXT`: ordinary words in a list after a colon ("languages: Python, Golang"),
  "logging", "accounting memos".
- 6 were excluded as generic capability: "lead a team" stated as a responsibility, "solve problems".
- 5 false positives were company or product descriptions repeated in only some of an employer's postings, so they
  count as shared role text ("available across AWS … Microsoft Azure"), or a software category ("Project
  Management" as a platform).

## Results on the 498 postings (v0.1)

There are 10,032 extracted mentions in total.

**Mention decisions:**

| Decision | Mentions |
|---|---|
| Qualified technical | 984 |
| Qualified domain | 1,055 |
| Qualified professional | 57 |
| Transversal | 148 |
| Excluded as employer boilerplate | 1,816 |
| Excluded as generic capability | 130 |
| Excluded for insufficient context | 3,760 |
| Ambiguous | 2,082 |

**Release demand skills (243):**

| Skill decision | Skills |
|---|---|
| Qualified technical | 46 |
| Discipline-adjacent | 51 |
| Qualified domain | 65 |
| Qualified professional | 21 |
| Transversal | 14 |
| Generic capability | 16 |
| Ambiguous | 24 |
| Boilerplate | 5 |
| Insufficient context | 1 |

**Support states of release skills:**

| Support state | Release | v0.1 |
|---|---|---|
| High support | 41 | 37 |
| Supported | 27 | 30 |
| Observed | 53 | 31 |
| Insufficient evidence | 122 | 145 |

**Leave supported status:** application process, attend to detail, build trust, data processing, data
visualisation software, google sheets, lead a team, make decisions, manage a team, meet deadlines, ml, social media
management.

**Enter demand as supported or high support:** skills the release withheld as context-dependent words, now
resolved by bound framing or related skills:

| Skill | Postings |
|---|---|
| Python | 99 |
| Java | 65 |
| Scala | 33 |
| Communication | 139 |
| Troubleshoot | 16 |
| ICT project management methodologies | 14 |
| English | 10 |
| Ruby | 9 |
| Accounting | 8 |
| R | 7 |
| Assertiveness | 6 |
| Domain name service | 5 |

These need curriculum coverage measured before a gap can be classified. The curriculum side still uses the
release's conservative mapping; see the limitations.

**Release gaps.** Six of the release's confirmed or partial gaps would no longer be gap candidates:

| Skill | Release gap | v0.1 decision |
|---|---|---|
| make decisions | partial | transversal |
| lead others | missing | transversal |
| ml | partial | ambiguous between *machine learning* and the ML programming language |
| cascading style sheets | partial | insufficient context |
| google docs | missing | ambiguous |
| ocr | partial | ambiguous |

**Recommendations:**

- 9 of the 11 issued recommendations keep their basis: a gap-eligible skill with supported demand. They are
  system design, data models, SPARK, Agile development, MySQL, Docker, Node.js, financial analysis and NoSQL.
- *make decisions* (expand an existing topic) loses its basis: it is transversal, and its demand falls from 89
  postings to 1.
- *lead others* (add an elective) loses its basis: it is transversal and never a discipline gap.

**The five named terms:**

| Term | Release | v0.1 | Why |
|---|---|---|---|
| make decisions | 89 postings, high support, partial gap | 1 posting; transversal; not a gap candidate | 76 mentions are employer boilerplate ("how we make decisions"), 60 are aliases without taxonomy context, 9 are bare verb phrases; 2 are stated requirements |
| reproductive health | 12, observed | 0; boilerplate | equal-opportunity sentence in every Twilio posting |
| social media management | 151, high support | 0; boilerplate | "follow us on LinkedIn/Instagram" (116 boilerplate) and the hidden label "linkedin" (40 ambiguous) |
| help customers | 11, observed | 0; ambiguous | no single concept; the phrase describes the job's purpose, not a requirement |
| financial statements | 10, high support | 10, high support; qualified domain; not a gap candidate | legitimate finance knowledge in finance postings, kept in demand but not named by this programme's curricula. A programme that teaches it would see it as `QUALIFIED_TECHNICAL` (tested). |

## Remaining limitations

- **No human labels.** Precision and recall above are against model-generated labels from the method's author.
  They are an internal development estimate, not validation.
- **v0.1 is conservative.** Recall is 0.59 against the assistant labels. Aliases, lists after a colon and
  responsibilities phrased as verbs are the main losses.
- **The profile side is not qualified.** The programme profile comes from curriculum mentions under the release's
  conservative mapping, so Python and Java, which the curricula teach, are not in the profile. Here they become
  discipline-adjacent rather than technical.
- **ESCO reuse level is the only soft-skill marker.** Cross-sector knowledge such as "communication" is classed as
  domain or discipline-adjacent rather than professional.
- **Boilerplate needs every one of an employer's postings.** Company descriptions repeated in only some postings
  count as shared role text.
- **Some multi-candidate surfaces stay ambiguous** whenever more than one candidate fits the sentence
  ("ML": *machine learning* or the ML language).
- **No transformer is used.** As requested, deterministic qualification comes first. A pretrained model could later
  be evaluated against this benchmark once human labels exist.
