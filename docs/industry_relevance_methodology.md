# Discipline-to-industry relevance: methodology (experimental)

**Status:** experimental. The method is not part of the authoritative pipeline: the published release
(`c066b227857f9eaf`), its demand, gaps and recommendations are unchanged. Results of this method are written only to
`data/experiments/relevance/<run_id>/`.

**Code:** `backend/app/knowledge_engine/relevance.py`. **Audit:** `scripts/analysis/relevance_audit.py`.
**Tests:** `backend/tests/test_relevance.py`. **Results:** `docs/industry_relevance_evaluation.md`.

## The problem

Every supplied job posting counts towards industry demand today. Three examples show the effect:

- An equal-opportunity sentence in one employer's postings ("... pregnancy, childbirth, reproductive health
  decisions ...") makes **reproductive health** a skill observed in 12 postings.
- Finance postings make **financial statements** a high-support skill (10 postings, 6 companies).
- Solutions-architect postings make **help customers** observed in 11 postings.

The release already refuses to call these curriculum gaps: their evidence state is `DISCIPLINE_RELEVANCE_UNESTABLISHED`.
But they still enter demand and support states, and through them every percentage built on the eligible population.

## Principles

- **No blacklist.** No word, phrase, skill, discipline, institution or course is named in the code. A test enforces
  this.
- **Eligibility, never deletion.** Every posting and every mention is kept with its provenance. The method only
  decides what counts towards demand.
- **Job relevance is not skill relevance.** A relevant job can contain irrelevant phrases, and an irrelevant job can
  contain a relevant skill. The two are judged separately.
- **Absence of evidence is not evidence of absence.** An unresolved occupation, or a title that names nothing, never
  counts against a posting.
- **No tuned thresholds.** The rules are majority, existence and "every posting" definitions. The one numeric
  parameter, `OCCUPATION_MIN_SHARED = 2`, is provisional, and results are reported for 1, 2 and 3.

## Pipeline position

```
job postings -> text segments (job-specific / shared role text / employer boilerplate)
            -> job-discipline relevance  -> eligible demand population
            -> skill mentions in job text -> demand (new) -> skill-discipline relevance -> gap
```

## 1. Text segments (employer boilerplate)

Each description is split into sentences. A sentence of three or more words is classified by where else it occurs
verbatim (after lower-casing and removing punctuation):

| State | Definition | Counts as job evidence |
|---|---|---|
| `JOB_SPECIFIC` | occurs once | yes |
| `SHARED_ROLE_TEXT` | recurs in some, not all, of one employer's postings with different titles; a requirement block shared by related roles, e.g. "BS in computer science or a related field" | yes |
| `UNKNOWN` | recurs only under the same title (a re-post) | yes |
| `EMPLOYER_BOILERPLATE` | in **every** posting of its employer (two or more postings, different titles), or recurs verbatim across employers; e.g. equal-opportunity statements, "follow us on social media", company descriptions | no (kept, with provenance) |

## 2. Programme profile

The profile is the set of standardised (ESCO) skills that the programme's own curricula mention with an established
sense. The curricula are the current version, the earlier version and the reference curriculum; peers are excluded.
Skills that the coverage-depth stage found taught are added.

The **neighbourhood** is the set of ESCO skills that share an immediate parent (a skill or a skill group) with a
profile skill. These skills belong to the discipline's region of the taxonomy even when the curriculum does not
teach them yet, which is exactly what a gap is.

## 3. Job-discipline relevance

There are three independent signals, each `SUPPORTS`, `CONTRADICTS`, `MIXED` or `NO_EVIDENCE`:

| Signal | Supports | Contradicts |
|---|---|---|
| **skills**: the posting's job-specific, established, non-transversal skills | more skills inside the profile than outside both the profile and its neighbourhood | no skill in the profile or its neighbourhood (and at least one outside) |
| **occupation**: the resolved ESCO occupation (`EXACT`, `VARIANT` or `CANDIDATE`) and its essential and optional skills that are sector- or occupation-specific | at least `OCCUPATION_MIN_SHARED` of them are in the profile | none are. An unresolved occupation is `NO_EVIDENCE`. |
| **title** | the title names a profile skill, or shares a two-word phrase (stemmed) with a course title of the programme | never; a silent title is `NO_EVIDENCE` |

| Job relevance | Rule |
|---|---|
| `RELEVANT` | at least 2 signals support, none contradicts |
| `LIKELY_RELEVANT` | 1 supports, none contradicts |
| `NOT_RELEVANT` | at least 1 contradicts, none supports |
| `UNCERTAIN` | conflicting signals, or no evidence |

**Eligibility policy (proposed).** Only `NOT_RELEVANT` postings leave the demand population. `UNCERTAIN` postings
stay, because missing evidence is not evidence of irrelevance. The stricter policy, which keeps `RELEVANT` and
`LIKELY_RELEVANT` only, is reported alongside as a sensitivity.

Every posting record carries its evidence strength, its supporting and contradicting evidence, each signal with the
skills behind it, and whether it contributes to demand.

## 4. Demand (new)

A skill counts in a posting when two conditions hold:

- the skill is mentioned in the posting's **job text** (not only in employer boilerplate);
- the posting is **eligible**.

Mentions are the established mentions already behind the release's demand. Support states use the project's
existing thresholds (`industry.support_state`).

## 5. Skill-discipline relevance

| State | Rule |
|---|---|
| `IN_PROGRAMME_PROFILE` | the curricula mention or teach it |
| `TRANSVERSAL` | ESCO reuse level "transversal": a general skill, never a discipline gap |
| `DISCIPLINE_ADJACENT` | most of its job-specific postings are `RELEVANT` or `LIKELY_RELEVANT` (positive evidence, not mere eligibility) |
| `NOT_ESTABLISHED` | none of the above |

Only `IN_PROGRAMME_PROFILE` and `DISCIPLINE_ADJACENT` skills would be eligible to become curriculum gaps.

## Known limitations

- **The profile follows the curriculum documents, including open electives offered by other departments.** For
  example, "financial analysis" comes from an open elective of the current curriculum. As a result, finance skills
  sit in the profile's neighbourhood, and finance postings are often `UNCERTAIN` rather than `NOT_RELEVANT`.
- **The title signal is literal.** Titles such as "Security Engineer - Identity and Access" are missed when no
  course title shares the phrase.
- **Occupation resolution covers about a third of postings** (162 of 498 in the release). For the rest, the
  occupation signal is `NO_EVIDENCE`.
- **No human labels exist.** Precision and recall of the relevance states are unknown. The method must not be
  promoted before an evaluation against human labels (Phase 11). The advisory AI could review `UNCERTAIN` and
  conflicting cases, but its suggestions would not change results.

## Next stage: skill qualification (Phase 3B)

Job relevance decides which **postings** count. Skill qualification (`docs/skill_qualification_methodology.md`)
decides which **mentions** inside them are demand evidence:

- employer boilerplate is excluded;
- generic action phrases are excluded;
- ordinary words count only with context;
- aliases count only with a related skill in the sentence;
- domain knowledge is kept in demand but is gap-eligible only for a programme that names it.

Both layers are experimental; the release remains authoritative.
