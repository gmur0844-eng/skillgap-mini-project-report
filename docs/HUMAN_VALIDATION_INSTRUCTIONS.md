# Human validation — instructions

## For the organiser

1. **Choose two independent reviewers.** Each should be a faculty member or practitioner of the discipline, and neither may have worked on this system.
   - Each labels the same 48 cases, alone.
   - More reviewers can be added later; agreement then switches from Cohen's kappa to Fleiss' kappa automatically.
2. **Create the form** (`docs/SEMANTIC_HUMAN_VALIDATION_FORM.md`) and send each reviewer the link separately.
   - Never show them any system output, the assistant's adjudication, or the other reviewer's answers.
3. **Import the responses:** `semantic_validation.py import-form`.
   - Label files are immutable.
   - A reviewer name that refers to the assistant or to a model is refused.
4. **Compute agreement:** `semantic_validation.py agreement`. This produces Cohen's kappa, raw agreement, per-class agreement and the disagreement matrix.
5. **Adjudicate disagreements.** A named human adjudicator fills in `adjudication_sheet.csv`, choosing one of the reviewers' labels or *Ambiguous*.
   - The adjudicator never sees model answers.
   - Then run `semantic_validation.py adjudicate`.
6. **Freeze the gold:** `semantic_validation.py freeze` writes `semantic_gold_v1.json`.
   - It is immutable; any correction becomes `semantic_gold_v2`.
7. **Evaluate:** `semantic_validation.py evaluate` compares the deterministic baseline, raw Qwen and validated Qwen with the gold, and applies gate v3.
   - Gate v3 was declared before any label existed.
   - Qwen leaves SAFE_MODE only if the gate passes, and then only for the classes that meet the per-class bar.

Never change a label after seeing model results.

## For each reviewer

The form shows the definitions below as choices A–H (Same concept, Parent / broader concept, Child / more specific
concept, Related, Partial overlap, Unrelated, Ambiguous, Insufficient evidence) **without the examples**: the example
pairs are cases of the validation subset, so do not show this page to reviewers.

For every case, you will see:

- **Concept A** — an expression from a job posting, a curriculum topic or a taxonomy label — together with the text around it;
- **Concept B** — a concept, usually from a skills taxonomy or a reference curriculum — with its description.

Choose how **A relates to B in this context**:

| Choice | Use when |
|---|---|
| Equivalent concept | A and B mean the same thing here ("SQL" and "SQL") |
| A is broader | A includes B |
| A is more specific | A is a kind or a part of B ("AWS" → "cloud technologies") |
| Related concept | clearly connected, but not equal and not one inside the other |
| Partial overlap | they share part of their meaning |
| Unrelated | different things, including a shared word used in a different sense ("Angular" framework vs angular momentum) |
| Ambiguous | the context allows more than one reading |
| Not enough evidence | the context does not decide it |

Guidance:

- Judge only from the text shown. Do not search for what a system might answer.
- A shared word, or one phrase appearing inside another, is not enough for *Equivalent concept* or for a hierarchy.
- Give your confidence: High (certain), Moderate (fairly sure) or Low (guess). Add a short reasoning whenever the case is difficult.
- The review takes about 30–45 minutes. You can stop and continue later.

## What is not human validation

`assistant_adjudication.json` holds the assistant's labels for all 88 cases, stored as **ASSISTANT_ADJUDICATION**.

- It is used only for error analysis and for preparing this review.
- It is never shown to reviewers, never used by the gate, never reported as accuracy and never called human-validated.
