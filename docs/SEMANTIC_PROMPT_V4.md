# Prompt adjudicate-v4 (experiment, 2026-10-22)

## Why

The v3 model run (`data/semantic_runs/qwen-270-v3`) was compared with reviewer responses on the 45 subset cases where
R02 and R03 agree. These are **development data**: both reviewers read about the topics with an AI assistant first, so
their answers are not independent labels. Results:

| | Matches R02 and R03 |
|---|---|
| model answer (raw) | 15 / 45 |
| after the evidence validator (what the analysis would read) | 9 / 45 |
| when the validated model commits to a relationship | right 9 of 25 times |

Two causes were found:

1. **The prompt did not state the validator's rules.** v3 asked for source-side evidence only. The validator also
   requires:
   * a concept-side item for SAME_CONCEPT, PARENT, CHILD, RELATED and PARTIAL_OVERLAP;
   * a direction item for PARENT and CHILD (ESCO hierarchy or relation, course, unit or outcome);
   * source text for SAME_CONCEPT of a short form.

   `NO_CONCEPT_EVIDENCE` alone discarded 17 of the 45 answers, including 4 that were right.
2. **Confusions of breadth.**
   * A narrower concept called SAME_CONCEPT: 7 cases.
   * Partial overlap called SAME_CONCEPT: 5 cases.
   * A broader concept called RELATED: 4 cases.

## What changed

Only the prompt (`semantic_v3.build_prompt_v4`):

* it states the validator's evidence rules as they are;
* it gives an ordered decision procedure:
  1. sense;
  2. same only if interchangeable;
  3. a specific kind, product or provider is CHILD;
  4. a broader area is PARENT;
  5. shared meaning is PARTIAL_OVERLAP;
  6. association is RELATED.

**What did not change:**
* the inputs (the same frozen candidates, the same hashes);
* the output schema;
* the validator `validate_decision`, which is as strict as before;
* the model;
* the production prompt. `engine_config` still says `adjudicate-v3`, so analyses and their recorded model decisions
  are unchanged.

v4 is used only when asked for (`--protocol adjudicate-v4`). The prompt names no skill, concept, discipline or
benchmark pair. A test checks it against all 88 benchmark pairs.

## Run it (on the Mac, with Ollama running)

```
cd ~/Sites/skillgap-final
.venv/bin/python scripts/semantic/run_frozen_adjudication.py --frozen data/semantic_runs/qwen-270-v3 \
    --protocol adjudicate-v4 --benchmark-only --out data/semantic_runs/qwen-270-v4/out --run-name qwen-270-v4
.venv/bin/python scripts/semantic/score_against_reviewers.py \
    --run v3=data/semantic_runs/qwen-270-v3/out --run v4=data/semantic_runs/qwen-270-v4/out \
    --out data/semantic_runs/qwen-270-v4/score_against_reviewers.json
```

`--benchmark-only` runs the 88 benchmark candidates, about 15 minutes at v3's speed (median 10 s per decision with
qwen2.5:7b-instruct). The v3 run is not touched.

## How to read the result

* **DEVELOPMENT** compares against the R02/R03 agreed cases, which the prompt was designed with in view. A better score
  there shows the fix works on the cases it targets. It does **not** show that the model has become reliable: a prompt
  can fit its development cases.
* **INDEPENDENT** stays PENDING until independent labels exist (see `INDEPENDENT_REVIEWER_BRIEF.md`). Only that
  reference shows whether v4 generalises, and only `semantic_validation.py evaluate` against the pre-declared gate v3 can
  take the model out of SAFE_MODE.
* If v4 does better on independent labels, making it the production prompt is a separate decision. It changes the cache
  key, so its decisions have to be recorded again.

Tests: `backend/tests/test_semantic_prompt_v4.py`.

## Result (run 2026-10-22, qwen2.5:7b-instruct, 88 benchmark candidates, 850 s)

Against the development reference (the 45 cases on which R02 and R03 agree; AI-assisted, not independent):

| | Raw | After the validator | Right when committing |
|---|---|---|---|
| v3 | 15 / 45 | 9 / 45 | 9 of 25 |
| v4 as run | 12 / 45 | 2 / 45 | 2 of 3 |
| v4, with the brackets removed from the cited ids (diagnostic only; the validator is unchanged) | 12 / 45 | 9 / 45 | 9 of 26 |

**Why v4 as run collapsed.** The prompt displays items as `[L1]`. v4 said "cite items by their id" but dropped v3's
`"ref": "<id>"` example, so the model wrote the brackets. 73 citations named ids that do not exist, and the validator
correctly treats invented references as REVIEW_REQUIRED. This was a defect of the v4 prompt.

**Why v4 does not help even without that defect.**
* The ordered procedure removed the over-use of SAME_CONCEPT (21 raw answers → 6).
* The answers moved to other errors instead: CHILD → RELATED in 6 cases, CHILD → PARENT in 4 (the direction reversed,
  e.g. "cloud computing is broader than cloud technologies" for the narrower term), PARTIAL_OVERLAP → RELATED in 4.
* Concept-side citations improved (NO_CONCEPT_EVIDENCE 17 → 13). Direction evidence became the new blocker
  (NO_DIRECTIONAL_EVIDENCE 6).

**Decision.** v4 is not adopted; production stays on adjudicate-v3, which never changed. No further prompt variants are
tried against these 45 cases: each attempt would be tuned on the same development answers, and neither attempt has
moved the validated score. Breadth and direction judgments look like a limit of the 7-billion-parameter model, rather
than of the wording. The next informative steps are independent labels (`INDEPENDENT_REVIEWER_BRIEF.md`), and, if
wanted, the same frozen run with a larger local model.

Outputs: `data/semantic_runs/qwen-270-v4/out/` (kept as run).
