# Discipline-to-industry relevance: audit of the 498 release postings (experimental)

This audit ran the experimental relevance method (`docs/industry_relevance_methodology.md`) over the published
release `c066b227857f9eaf`, with the current curriculum (B.E. CSE R22A) as the programme. The outputs are in
`data/experiments/relevance/c066b227857f9eaf/`:

- `job_relevance.jsonl`: every posting, with its signals and evidence;
- `skill_relevance.jsonl`: every demanded skill, with current, new and strict demand;
- `traces.json`;
- `summary.json`.

The release itself is unchanged. To reproduce, run `python3 scripts/analysis/relevance_audit.py --run c066b227857f9eaf`
(about 10 seconds).

**Programme profile.** The profile has 111 standardised skills, taken from the current, earlier and reference
curricula. Its neighbourhood in the skills reference has 1,802 skills.

## Current method compared with the new method

| | Current (release) | New, proposed policy | New, strict policy |
|---|---|---|---|
| Postings | 498 | 498 (all kept) | 498 (all kept) |
| Relevant | – | 79 | 79 |
| Likely relevant | – | 163 | 163 |
| Uncertain | – | 207 (eligible) | 207 (not eligible) |
| Not relevant | – | 49 | 49 |
| **Eligible postings** | **498** | **449** | **242** |
| Demanded skills with ≥1 eligible posting (job text) | 243 | 224 | 148 |
| Demanded skills excluded (no eligible job-text posting) | 0 | 19 | 95 |
| High support | 41 | 38 | 23 |
| Supported | 27 | 27 | 23 |
| Observed | 53 | 43 | 33 |
| Insufficient evidence | 122 | 135 | 164 |

**Signals.** In the counts below, "for" means the signal supports relevance, "against" means it contradicts it,
and "none" means no evidence.

- **Skills:** 216 for, 39 against, 170 mixed, 73 none.
- **Occupation:** 29 for, 22 against, 10 mixed, 437 none. An unresolved occupation never counts against a posting.
- **Title:** 101 for, 397 none.

**Text.**

| Text kind | Sentences | Skill mentions of demanded skills |
|---|---|---|
| Job-specific | 14,703 | 1,356 |
| Shared role text | 6,111 | 520 |
| Employer boilerplate | 4,714 | 376 |
| Unknown | 86 | 15 |

**Sensitivity to the one provisional number** (`OCCUPATION_MIN_SHARED`):

| Value | Eligible (proposed) | Eligible (strict) | Skills with supported or high support |
|---|---|---|---|
| 1 | 450 | 249 | 65 |
| 2 | 449 | 242 | 65 |
| 3 | 448 | 240 | 65 |

The results barely depend on this number.

## What changes, and why

### Employer boilerplate inflated demand more than irrelevant jobs did

| Skill | Current postings | Postings where it appears only in boilerplate | New postings (proposed) | Skill relevance |
|---|---|---|---|---|
| social media management | 151 (high support) | 116 ("follow us on social media"-type text) | 33 | discipline-adjacent |
| make decisions | 89 | 66 | 20 | in profile |
| machine learning | 72 | 41 (company descriptions) | 31, still high support | in profile |
| data protection | 42 | 30 | 12 | discipline-adjacent |
| sign language | 32 | 32 | 0 | not established |
| reproductive health | 12 | 12 (an equal-opportunity statement) | 0 | not established |

Under the proposed policy, three skills lose supported status: *application process*, *meet deadlines* and
*think creatively*. All are generic language that appears mainly in employer text.

### Irrelevant jobs

Under the strict policy, 22 skills lose supported or high support. Examples: financial statements, customer service,
labour law, market research, lead a team, strategic planning, management consulting.

Under the proposed policy they keep their support, because those postings are `UNCERTAIN` rather than contradicted.

### Issued recommendations

All 11 issued recommendations keep their skills `IN_PROGRAMME_PROFILE`, and none drops below "supported" under
either policy. Under the strict policy, MySQL and NoSQL move from high support to supported. Make decisions moves
from high support to supported under both policies.

The method therefore does not undermine a published recommendation. It does show that "make decisions" (89 → 20
postings) rests largely on employer text.

## The three traced terms

Each trace below follows the chain posting → title → company → industry → extracted skill → normalisation →
standardised-skill mapping → relevance → demand → gap. Employer industry is recorded for only 1 of the 33 postings.

### reproductive health

- **Mapping:** exact preferred label in the skills reference (sector-specific).
- **Where it appears:** 12 Twilio postings, of every kind (software architect, marketing manager, support
  engineer). In each one the phrase sits in the same equal-opportunity sentence, which appears in all 12 Twilio
  postings, so it is `EMPLOYER_BOILERPLATE`.
- **Demand:** current 12 postings, 1 company (observed); new 0, under both policies.
- **Skill relevance:** not established.
- **Gap:** insufficient evidence today, with discipline relevance not established; it is no longer in demand at
  all.
- **Conclusion:** the phrase is legitimate text but not evidence about any job. It leaves demand without a word list.

### help customers

- **Mapping:** ambiguous (no single standardised skill).
- **Where it appears:** 11 postings at Databricks and MongoDB: solutions architects, forward-deployed engineers, a
  sales specialist and one software engineer. The phrase sits in job text, either job-specific or shared role text.
- **Job relevance:** 1 relevant, 3 likely relevant, 7 uncertain. The uncertain ones are technical customer-facing
  roles with mixed skill evidence.
- **Demand:** current 11 postings, 2 companies (observed); new 11 (observed); strict 4 (observed).
- **Skill relevance:** not established. It is not in the curricula, not in their taxonomy neighbourhood, and the
  majority of its postings lack positive relevance evidence.
- **Gap:** stays insufficient evidence.
- **Conclusion:** relevant jobs can contain non-discipline phrases. The posting stays in demand, but the phrase
  cannot become a discipline gap.

### financial statements

- **Mapping:** exact preferred label in the skills reference (cross-sector).
- **Where it appears:** 10 postings at CRED, MongoDB, Stripe, Databricks, EY and Meesho: accounts payable,
  controllers, credit risk, consolidation, finance systems. All mentions are job-specific.
- **Job relevance:** all 10 are uncertain. They have no skill in the programme profile, but the profile's
  neighbourhood contains finance skills, because the current curriculum offers a "financial analysis" open elective.
  That is enough to stop the skills signal contradicting relevance.
- **Demand:** current 10 postings, 6 companies (high support); new 10 (high support); strict 0.
- **Skill relevance:** not established.
- **Gap:** stays insufficient evidence.
- **Conclusion:** irrelevant jobs are not always identified, because the curriculum documents themselves span
  disciplines through open electives. The skill is still never a discipline gap. Its demand drops only under the
  strict policy.

## Assessment

- **Boilerplate separation is the clearest gain.** It removes non-job text from demand by definition, with no
  tuning.
- **Job relevance is useful but uncalibrated.** About 10% of postings are contradicted, 49% have positive evidence
  and 42% stay uncertain.
- **Known false negatives** among the `NOT_RELEVANT` postings include some engineering-manager roles whose
  job-specific text names only management skills.
- **Before promotion:** a stratified human-labelled sample of the 498 postings is needed (relevant / not relevant
  to the programme) to estimate precision and recall of each state. That belongs to Phase 11.
- **Until then,** nothing here changes the published release or any screen.

## Skill qualification on the same postings (Phase 3B)

The qualified, per-mention view of the same 498 postings is in `docs/skill_qualification_methodology.md`. In
summary (v0.1):

- **make decisions:** demand falls from 89 to 1 posting. The skill is transversal and is no longer a gap candidate.
- **social media management:** 151 → 0 postings (boilerplate and an unconfirmed hidden label).
- **reproductive health:** 12 → 0 (boilerplate).
- **help customers:** 11 → 0 (ambiguous).
- **financial statements:** stays in demand as qualified domain knowledge, and is not a gap candidate for this
  programme.
- **New demand:** Python, Java and communication enter demand through sentence context.
- **Evaluation:** against 239 assistant-labelled benchmark mentions (no human labels), v0 scored F1 0.80 (held-out)
  and v0.1 scored F1 0.72 (precision 0.93, recall 0.59; not held-out).
