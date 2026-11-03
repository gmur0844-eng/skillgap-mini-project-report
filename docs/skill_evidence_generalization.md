# Skill evidence v0.2: general qualification, evaluation and scorecard (experimental)

**Status:** experimental. The published release `c066b227857f9eaf` is authoritative and byte-identical; this layer
changes nothing in it, in the API or in the screens. v0.2 supersedes v0.1 (`skill_qualification.py`, kept for
comparison).

| Code | Path |
|---|---|
| Implementation | `backend/app/knowledge_engine/skill_evidence.py` |
| Audit and scorecard | `scripts/analysis/skill_evidence_audit.py` → `data/experiments/skill_evidence/<run>/scorecard.json` |
| Tests | `backend/tests/test_skill_evidence.py` |

## The question this phase answers

Phase 3B fixed the examples we had noticed. v0.2 replaces example-driven rules with general mechanisms. If a new
failure appears, the question is which error class it belongs to and whether the architecture handles that class,
never "which phrase to add to a list".

## Stages (kept separate)

```
EXTRACTION     what phrases appear to be skills?          release extractor + expand_occurrences()
CONTEXT        where does the phrase sit?                 parse_posting(), sentence_role(), list_head()
QUALIFICATION  is this occurrence usable skill evidence?  decide()  -> decision + evidence_strength
NORMALIZATION  which canonical concept is it?             resolve_concept()  -> CONFIRMED / UNCONFIRMED / NONE
RELEVANCE      is the concept relevant to the programme?  programme_relevance(), curriculum_profile()
DEMAND         how often in eligible postings?            audit: confirmed concepts and unnormalized wordings apart
```

## General mechanisms added in v0.2

1. **Occurrence-level extraction.** The release extractor keeps only the first occurrence of a phrase in a posting.
   `expand_occurrences()` adds every later whole-word occurrence as a derived mention, keeping the originals and
   their provenance. A skill whose first occurrence is in the company description and whose second is in the
   requirements is no longer lost.
2. **A bounded, deterministic context window:**
   - the clause and the sentence;
   - the list the phrase belongs to (items after a head such as "Required:" or "Languages:");
   - the section: the nearest heading, classified by role;
   - the posting's own job text (for written-out forms of abbreviations);
   - posting metadata (job title, employer name);
   - the employer-boilerplate state.

   Nothing outside the posting is read.
3. **Sentence roles.**
   - Job roles: `REQUIRED`, `PREFERRED`, `SKILLS_LIST`, `EDUCATION`, `RESPONSIBILITY`.
   - Employer roles: `COMPANY_DESCRIPTION`, `LEGAL_EEO`, `BENEFITS`, `SOCIAL_LINKS`.
   - `OTHER`.

   The role comes from genre cues of job-posting writing, section headings, list heads, imperative verbs and the
   subject of the sentence (the candidate, or the employer). The imperative verbs are the verbs that begin ESCO
   skill labels, so they come from the taxonomy, not from a hand-written list.
4. **Evidence strength.**
   - STRONG: a requirement, skills list or education requirement.
   - MEDIUM: experience asked for, or a task the job holder performs.
   - WEAK: optional or preferred, or job text with no cue.
   - NONE: employer text, or the employer's name.
5. **Qualification kept separate from normalization.** An occurrence in a job-role sentence is skill evidence even
   when its canonical concept is not confirmed (an ordinary word, an alias, or several candidate concepts). It is
   counted under its own wording and can **never** make a gap. A gap needs a confirmed concept (`skill_gap_eligible`).
6. **Normalization from context.** A concept is confirmed by any of:
   - a related skill in the same sentence (a shared ESCO parent);
   - a requirement bound to the word ("proficiency in X", "X skills");
   - the word being a skills-list item;
   - an abbreviation's written-out form appearing in the posting;
   - for an alias, a requirement plus a shared whole word with the concept's name;
   - among several candidates, exactly one fitting the context, or exactly one whose preferred name is the phrase.
7. **Syntactic guards.** These are linguistic classes, not word lists:
   - a closed-class (function) word is never a skill name;
   - part of a hyphenated compound ("open-source");
   - the first word of a capitalised multi-word name (a product).
8. **Employer as subject.** A sentence whose subject is the employer ("we", "our", or its name), with no reference
   to the candidate, is company description. A span inside the employer's name is `EXCLUDED_ENTITY_NAME`.
9. **What the skill is versus programme relevance.**
   - The decision says what the skill is: `QUALIFIED_TECHNICAL` (technology/tool/digital skill), `QUALIFIED_DOMAIN`,
     `QUALIFIED_PROFESSIONAL`, or `TRANSVERSAL`.
   - `programme_relevance` is a separate field: `IN_PROGRAMME_PROFILE`, `NEAR_PROGRAMME_PROFILE`,
     `OUTSIDE_PROGRAMME_PROFILE`, or `DISCIPLINE_ADJACENT` at skill level.
   - A legitimate finance skill stays a valid domain skill for every programme. It is gap-eligible only for a
     programme whose curricula name it.
10. **Programme profile with curriculum-side qualification.** In a syllabus topic the genre establishes the teaching
    sense. A one-word subject name ("Statistics", "Surveying") with one candidate concept therefore resolves, which
    the release's conservative mapping could not do.
11. **Extension point for a transformer.**
    - `features()` builds the deterministic evidence record.
    - An optional `semantic_scorer` adds `features["semantic"]`, which is recorded.
    - `decide()` reads only deterministic fields today, and a test proves the hook does not change decisions.
    - A pretrained model can later be added as a classifier or reranker without changing the data model.

**Ablation (validation set).** Two further guards were implemented and evaluated, and are switched off:

- requiring an unconfirmed competence word to be framed as a skill;
- rejecting an unconfirmed non-technical word that modifies the next word.

On validation (independent labels), F1 was 0.822 with both off, 0.782 with only the modifier rule, 0.723 with only
the competence rule, and 0.696 with both. The guards stay in the code, switched off, so the ablation can be
reproduced.

## Evaluation design

| Set | Items | Labels | Role |
|---|---|---|---|
| Development (`skill_qualification_benchmark_v1`) | 239 real mentions | **AUTHOR_LABELLED** (the method's developer) | used to design v0.1 and v0.2 |
| Validation (`skill_qualification_validation_v1`) | 150 random real mentions | **INDEPENDENT_MODEL_LABELLED**: a separate model annotator that saw only the labelling guide and the items, never the code. **Not human.** | used to choose between rule variants |
| Final holdout (`skill_qualification_holdout_v1`) | 200 random real mentions | **INDEPENDENT_MODEL_LABELLED**, not human | sealed; run **once** after the implementation was frozen (`FROZEN_IMPLEMENTATION.json` records file hashes) |
| Synthetic (`skill_generalization_suite_v1`) | 59 occurrence cases, 17 programme-relevance cases, 13 postings, 5 programmes | **AUTHOR_LABELLED**, written and frozen **before** v0.2 | unseen phrases, unseen disciplines, writing styles, adversarial cases |

**About the sets:**

- The validation and holdout samples were frozen, and their labels written, before any v0.2 code existed. Both
  exclude development items.
- **Human labels: none yet.** `labels_human.csv` in each folder is the empty template for independent reviewers.
  Their results will be reported separately.
- **One post-holdout change:** the skill-level gap rule. It does not affect the mention-level outputs the holdout
  measures, which re-ran identically. It is recorded in `FROZEN_IMPLEMENTATION.json`.

## Scorecard (positive class: demand evidence)

| Set (label source) | Precision | Recall | F1 | Accuracy | Abstention | v0.1 F1 |
|---|---|---|---|---|---|---|
| Development (author) | 0.770 | 0.912 | 0.835 | 0.812 | 5.4% | 0.722 |
| Validation (independent model) | 0.750 | 0.892 | 0.815 | 0.800 | 11.3% | 0.475 |
| **Final holdout (independent model)** | **0.795** | **0.908** | **0.848** | 0.840 | 5.5% | 0.559 |
| Synthetic (author, written before v0.2) | 1.000 | 1.000 | 1.000 | 1.000 | – | – |

**On the holdout, v0.2 versus v0.1:** recall rose from 0.408 to 0.908 and F1 from 0.559 to 0.848. Precision fell
from 0.889 to 0.795. v0.1 was too conservative.

**Synthetic suite detail** (author-labelled, so the 1.0 results are weak evidence; they say only that the
mechanisms behave as designed on cases written before the code):

| Measure | Result |
|---|---|
| Extraction recall of skill-sense phrases | 1.0 |
| Unseen phrases (39 cases) | F1 1.0 |
| Unseen disciplines (45 cases: mechanical, electrical, civil, finance, biotechnology, retail) | F1 1.0 |
| Writing styles (31 cases, 17 styles) | F1 1.0 |
| Boilerplate rejection | 12/12 |
| Generic-action rejection | 2/2 |
| List extraction | 17/17 |
| Verb-form competencies | 5/5 |
| Ambiguous abbreviations | 4/4 |
| Adversarial cases | 7/7 |
| Programme relevance (17 cases) | 1.0 |
| Evidence-strength agreement | 0.98 |

**Strength agreement on the real sets** (exact match of STRONG/MEDIUM/WEAK/NONE with the independent annotator):
0.71 on validation and 0.67 on the holdout. The main confusion is MEDIUM vs STRONG for "experience with X".

## Error taxonomy

The error classes are reusable, and every disagreement is classed automatically:

| Class | Name |
|---|---|
| E1 | BOILERPLATE |
| E2 | GENERIC_ACTION |
| E3 | INSUFFICIENT_CONTEXT |
| E4 | WRONG_ENTITY |
| E5 | WRONG_SENSE |
| E6 | LIST_EXTRACTION |
| E7 | VERB_FORM_EXTRACTION |
| E8 | SECTION_MISCLASSIFICATION |
| E9 | DOMAIN_RELEVANCE_ERROR |
| E10 | PROGRAMME_RELEVANCE_ERROR |
| E11 | TAXONOMY_MAPPING_ERROR |
| E12 | OVER_ABSTENTION |

**Counts by set:**

| Set | E1 | E2 | E5 | E6 | E7 | E8 | E12 |
|---|---|---|---|---|---|---|---|
| Development | 1 | 19 | – | – | 3 | 20 | 2 |
| Validation | – | – | 21 | 1 | – | 3 | 5 |
| Holdout | – | – | 21 | – | – | 6 | 5 |
| Synthetic | – | – | – | – | – | – | – |

**The dominant remaining class is E5, wrong sense.** These are ordinary or abstract words in job sentences counted
as unnormalized skill evidence ("patterns", "mechanisms", "feedback", "lead" as in "a sales lead"). They never reach
gaps, but they do inflate unnormalized demand.

## Results on the 498 release postings

**Mentions.** 15,439 occurrences: 10,032 extracted, plus 5,407 later occurrences that the release extractor had
collapsed.

| Decision | Occurrences |
|---|---|
| Qualified technical | 2,606 |
| Qualified domain | 2,271 |
| Qualified professional | 453 |
| Transversal | 3,284 |
| Excluded: employer boilerplate | 2,155 |
| Excluded: company, legal, benefits or social text | 2,053 |
| Excluded: employer name | 1,096 |
| Excluded: generic capability | 28 |
| Excluded: insufficient context | 933 |
| Ambiguous | 560 |

The abstention rate is 9.7%. Every abstention records its reason and what context would resolve it.

**The release's 243 demand skills:**

| Support state | Release | v0.2 |
|---|---|---|
| High support | 41 | 41 |
| Supported | 27 | 31 |
| Observed | 53 | 36 |
| Insufficient evidence | 122 | 135 |

**Leave supported status:** application process, build trust, fraud detection, labour law, make decisions, meet
deadlines, mongodb (mostly the employer's own name), personal development, social media management, team building.

**New supported concepts** (confirmed normalization), including:

| Skill | Postings |
|---|---|
| Python | 108 |
| Java | 68 |
| Scala | 36 |
| communication | 158 |
| troubleshoot | 24 |
| ICT project management methodologies | 16 |
| accounting | 16 |

Another 125 unnormalized wordings reach supported level. They are reported, never gap-eligible.

**Release gaps that are no longer gap candidates:**

- make decisions (partial; transversal);
- lead others (missing; transversal);
- Internet of Things (partial; its job-posting occurrences are company text).

**Recommendations.** 9 of the 11 issued recommendations keep their basis. *make decisions* and *lead others* lose
theirs because they are transversal.

**The terms named earlier.** None of them is special-cased; the outcomes follow from the general mechanisms:

| Term | Result | Mechanism |
|---|---|---|
| make decisions | 89 → 7 postings; transversal; not a gap | boilerplate (76) and generic capability; 10 stated requirements remain |
| reproductive health | 12 → 0 | boilerplate |
| social media management | 151 → 1 | social-link and company text; the hidden label "linkedin" is unconfirmed |
| help customers | 7 postings | counted under its own wording only: several concepts and no confirmation, so it can never be a gap |
| financial statements | 10 postings, high support; valid domain skill | near, not in, this programme's profile, so not a gap; it would be one for a programme that names it |
| machine learning | 72 → 29, still high support | 61 occurrences in employer text removed |

## Static audit

`StaticAudit` in the test file checks the production modules (`skill_evidence.py`, `skill_qualification.py`,
`relevance.py`). They contain no skill name, subject, college, discipline or employer, outside docstrings and
comments.

The only word lists are:

- English function words (closed class);
- genre cues of job-posting writing (headings, requirement, preference, legal, social and benefits wording).

A test checks that neither overlaps the skill vocabulary used in evaluation. The imperative-verb lexicon is derived
from the taxonomy at run time.

## Remaining limitations

- **No independent human labels.** The holdout and validation labels come from a separate model annotator. They are
  more independent than author labels, but not human validation.
- **Wrong sense (E5) is the main error.** It needs either a sense model or a transformer reranker; the hook exists.
- **The synthetic suite is small and author-written.** Its perfect scores show the mechanisms work as designed, not
  that they generalize statistically.
- **Strength agreement is moderate** (0.67–0.71).
- **Sentence-role cues are English-only** genre cues.
- **The "every posting of an employer" boilerplate rule** still lets repeated company text that appears in only
  some postings through, unless the sentence's subject is the employer.
- **Unnormalized wordings** ("design", "planning", "lead") are counted as evidence but never become gaps. Normalizing
  them better is future work.
- **Some cross-sector soft-skill concepts** (e.g. "communication") are typed as domain knowledge, because the ESCO
  reuse level does not mark them transversal.
