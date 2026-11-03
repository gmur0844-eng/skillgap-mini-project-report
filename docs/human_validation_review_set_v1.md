# Human validation — how to review (dataset v1)

Files in `data/human_validation/v1/`:

| File | Purpose |
|---|---|
| `review_file.xlsx` (sheet `review`, sheet `options`) / `review_file.csv` | **the file to fill in** — 54 rows |
| `review_items.json` | the same items with the full original evidence (uids of topics, mappings, postings, concepts) |
| `freeze_manifest.json` | run `6472ec43cba27593`, content digest, code fingerprint `889d95730b7af071`, config hash, a hash of every item |

Schema of a stored decision: `docs/human_validation_schema.json`.

## What is in the set (54 items, deterministic selection)

| Group | Items | Why |
|---|---|---|
| Topics that make SQL "covered" (drive the only recommendation) | 4 | recommendation-affecting |
| PARENT / CHILD topic mappings with the least shared unit context | 8 | parent/child confusion |
| AMBIGUOUS topic mappings | 4 | two reference candidates too close |
| Largest REMOVED / ADDED drift concepts vs the closest topic in the same course family | 6 | drift conclusions |
| SAME_CONCEPT and RELATED/PARTIAL mappings with the least shared context | 8 | high-impact reference mappings, likely word-sense errors |
| Unmapped topics whose best candidate was just below threshold | 4 | possible missed matches |
| HIGH-priority discovered concepts: one member vs the concept | 6 | concept coherence |
| Job mention → ESCO: alias sense (MS Excel, .NET, …) 4, acronym sense (AWS, GCP) 2, ambiguous ESCO 1, programme relevance 2, context-dependent words 2, unmapped high-demand 2, the SQL recommendation link 1 | 14 | ESCO / demand-affecting |

Priority: HIGH 28, MEDIUM 26. Splits (hash of review_id): DEVELOPMENT 17 · VALIDATION 17 · FINAL_TEST 20.

## How to fill it in

For each row read LEFT (+ LEFT CONTEXT), RIGHT (+ RIGHT CONTEXT), the QUESTION, and the MODEL columns. Write in
`human_label` one of:

| Letter | Label | Meaning (LEFT relative to RIGHT) |
|---|---|---|
| A | SAME_CONCEPT | same thing |
| B | PARENT | LEFT is broader |
| C | CHILD | LEFT is narrower / a part |
| D | RELATED | clearly related, neither contains the other |
| E | PARTIAL_OVERLAP | overlapping in part |
| F | UNRELATED | not related (e.g. a different word sense) |
| G | AMBIGUOUS | cannot decide between readings |
| H | INSUFFICIENT_EVIDENCE | the text does not allow a judgement |

Also fill `reviewer` (required for every labelled row), optionally `review_timestamp`, `human_note` and
`human_error_category`. Leave rows you do not review empty — they stay unlabelled. Do not edit any other column.

## After review

```bash
python3 scripts/review/ingest_human_review.py data/human_validation/v1/review_file.xlsx
```

The script refuses the file (nothing stored) on a missing, unknown or duplicated review_id, a label outside A–H, a
labelled row without reviewer, an edited model column, or a change of the engine (code fingerprint or configuration)
since freezing. On success it writes `decisions.jsonl`, `gold_semantic_validation.json` (only human-labelled items,
by split) and `evaluation_v1.json` (precision / recall / F1 / confusion per split, verdicts CORRECT / INCORRECT /
ALTERNATIVE / AMBIGUOUS / INSUFFICIENT_EVIDENCE, error categories).

Rules that follow: the model is frozen while you review; any later change is Version 2 and is evaluated only on
VALIDATION / FINAL_TEST items; only human-confirmed relationships may be promoted to HUMAN_VALIDATED; a human decision
is evidence about a mapping, never about what a curriculum or posting contains.

**Status now: 0 of 54 items labelled. No human validation has taken place.**
