# Independent labelling guide

Fill the `label` column with one of: SAME_CONCEPT, PARENT, CHILD, RELATED, PARTIAL_OVERLAP, UNRELATED, AMBIGUOUS, INSUFFICIENT_EVIDENCE.

- Judge the meaning in the given context only. A shared word or one string inside another is not a hierarchy.
- PARENT: LEFT is broader than RIGHT. CHILD: LEFT is narrower than RIGHT.
- Use AMBIGUOUS when the context allows more than one reading, INSUFFICIENT_EVIDENCE when it decides nothing.
- Do not look at any model output or at the development gold while labelling.
