# Independent reviewers: brief and procedure

The semantic model stays advisory (SAFE_MODE) until its answers are compared with **independent human labels** and pass
the gate declared before any label existed (`data/evaluation/semantic_gate_v3.json`). That needs at least two
reviewers who answer the 48-case form independently. The responses collected so far (R01–R05) do not qualify: they were
prepared with AI assistance or their source was not stated, so they are kept as research records only
(`SEMANTIC_HUMAN_VALIDATION_FORM.md`, last section).

## Who

Two or more people who know the subject, for example faculty, final-year students or practitioners of computer
science. They must not be among R01–R05, and must not have seen those answers, this project's model outputs or its
development labels. Give each a new ID such as `I01` or `I02`; the form collects no name or email.

## What to send each reviewer

The responder link of the existing form (`SEMANTIC_HUMAN_VALIDATION_FORM.md`, "Create the form"), their reviewer ID, and
this text:

> You will judge 48 pairs of terms. For each pair, the form shows where Concept A was found (a job posting or a
> syllabus) and what Concept B means. Choose how A relates to B, how sure you are, and optionally why.
>
> Please:
> * answer **on your own**, from the text shown in the form and your own knowledge;
> * **do not use ChatGPT, Claude, Gemini, Copilot or any other AI tool**, and do not search the web for the pairs;
> * do not discuss the cases with anyone or look at anyone else's answers until you have submitted;
> * if the text shown does not let you decide, choose "Ambiguous" or "Insufficient evidence"; that is a valid answer,
>   not a failure.
>
> It takes about 60–90 minutes, and can be done in one sitting. After submitting, please reply to confirm in one
> sentence that you answered alone and without AI tools.

## Collecting the answers

1. Keep each reviewer's confirmation (an email or message) as it arrives.
2. Download the responses (Form → Responses → Link to Sheets → File → Download → CSV).
3. Import them as independent labels. The import refuses without an attestation, and the statement is stored with the
   labels:

   ```
   P=data/evaluation/semantic_gold/computer-science-and-engineering/v1
   .venv/bin/python scripts/evaluation/semantic_validation.py import-form --package $P --csv responses.csv \
       --attestation "I01 and I02 each confirmed by email on <date> that they answered alone without AI tools"
   ```

   Only reviewers who confirmed should be in the CSV. Delete any other row before importing.
4. Run the predefined procedure: `agreement`, then `adjudication-sheet` / `adjudicate` (a named human adjudicator
   decides the disagreements), then `freeze`, then `evaluate`.
5. Score the v3 and v4 prompts on the independent labels: `scripts/semantic/score_against_reviewers.py` (its
   INDEPENDENT column fills in once `semantic_gold_v1.json` is frozen).

Nothing in this procedure can be done by the assistant. It cannot be a reviewer, an adjudicator or the source of an
attestation.
