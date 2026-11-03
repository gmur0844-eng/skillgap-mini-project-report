# Qwen semantic run — 270 frozen adjudication candidates

Run `qwen-270-v1` · 2026-09-27 13:04–13:32 IST (first invocation) and 13:37 (cached rerun) · data in
`data/semantic_runs/qwen-270-v1/` (candidates, freeze manifest, `out/`, `analysis/`).

**There are no human labels for these 270 candidates. Nothing below is an accuracy figure.** Agreement numbers are
agreement with the deterministic baseline or with expectations the assistant transcribed from the specification.

**Headline: the model ran cleanly (270/270 schema-valid, 0 retries, reproducible), but the run exposed a serious
systemic failure in the alias-sense candidates: the model accepts the ESCO alias statement it is shown as proof of
meaning. Following the stop rule, the prompt was not changed and nothing was rerun. Nothing is passed downstream.**

## 1. Environment

MacBook Air 13-inch, Apple M5, 16 GB unified memory, macOS Tahoe 26.6.2; Homebrew Python 3.14.7; model on the M5 GPU
(Metal). The run executed on the Mac (the cloud environment cannot reach the Mac's localhost); results were read back
through the shared folder `~/Sites/qwen-run`.

## 2. Model

`qwen2.5:7b-instruct` · family qwen2 · 7.6B parameters · GGUF **Q4_K_M** · Ollama digest `845dbda0ea48…b697e` ·
4.68 GB on disk · context 4,096 tokens · temperature 0.

## 3. Runtime

Ollama 0.34.4 (Homebrew service), endpoint `http://127.0.0.1:11434`, `/api/chat` with the decision JSON Schema as
`format` (constrained output). Concurrency 1 (sequential). Provider selected through the production
`discover_providers()` from `engine_config.json` — no command-line model override.

## 4. Prompt / schema / engine versions

| Item | Value |
|---|---|
| prompt_version | `adjudicate-v2` |
| schema_version | `decision-schema-v1` (new constant; part of the cache key) |
| engine config | `2.0.0`; `semantic_ai.providers[ollama]` = qwen2.5:7b-instruct @ 127.0.0.1:11434, Q4_K_M |
| config sha256 (as run) | recorded in `out/archive/run-01/run_meta.json` |
| semantic_provider.py / runner sha256 | recorded in the same file |
| source run of the candidates | `438ec2c0d5182dd4` (content digest `70c46d9b…5807`, code fp `9da5e152b40604b3`) |

Code changed for this run (no architecture change): `SCHEMA_VERSION`; per-decision latency, token counts,
`candidate_id`, full rejected raw outputs; a `MODEL_FAILURE` state (no model text at all) distinct from
`REVIEW_REQUIRED` (invalid text); DB CHECK widened accordingly. 519 tests pass.

## 5. Candidate population (frozen)

The 270 candidates were regenerated with the unchanged production function
(`intelligence.adjudication_candidates`) from run `438ec2c0` and **every** (input_hash, context_hash) was verified
against the 270 decisions recorded in that run before freezing (0 mismatches, 270 distinct ids;
`candidates_sha256 e871862e…6d03f`). The runner re-verified the file hash and every candidate hash before calling
the model (0 mismatches).

| Kind | n | What LEFT / RIGHT are |
|---|---|---|
| ALIAS_SENSE | 212 | a posting mention whose alias sense the rules could not establish / the ESCO concept; RIGHT CONTEXT = the sentence "'X' is an English ESCO altLabel of 'Y'" |
| AMBIGUOUS_TAXONOMY_LABEL | 36 | a surface whose ESCO label belongs to several concepts / one candidate concept |
| AMBIGUOUS_TOPIC_MAPPING | 22 | a target curriculum topic / one of two too-close reference topics |

Baseline (deterministic) for all 270: `AMBIGUOUS`, state `RULE_VERDICT_NO_MODEL`.

## 6. Runtime statistics (first invocation, 270 uncached calls)

| Measure | Value |
|---|---|
| total runtime | 1,709.5 s (28.5 min) |
| latency mean / median / p95 | 6.33 s / 6.40 s / 8.52 s |
| min / max | 3.08 s / 11.85 s |
| mean latency by fifth of the run (execution order) | 4.44 · 6.14 · 6.92 · 7.42 · 6.74 s |
| tokens | 104,434 prompt (≈387/call) · 24,723 output (≈92/call) |
| model calls / retries / failures | 270 / 0 / 0 |

Latency rose by about 60 % after the first fifth. The cause was not measured (memory pressure and heat are both
possible; see §8).

## 7. Cache statistics

| Invocation | cache hits | cache misses | model calls | sorted output-hash digest |
|---|---|---|---|---|
| 1 (13:04) | 0 | 270 | 270 | `e6a11d35…cefbf` |
| 2 (13:37) | 270 | 0 | 0 | `e6a11d35…cefbf` (identical) |

Cache file: 270 records, 270 distinct keys (key = hash of provider/model/base URL/temperature, prompt version, schema
version, config, input hash, context hash).

## 8. Validation statistics

| Check | Result |
|---|---|
| schema (stored decisions) | 270/270 valid; first-attempt success 100 %; rejected model outputs 0 |
| decision states | MODEL_SUGGESTED 270; REVIEW_REQUIRED 0; MODEL_FAILURE 0; HUMAN_VALIDATED 0 |
| relationship values | all within the 8 allowed |
| provenance | every record has decision_id, candidate_id, provider, model, prompt/schema version, input/context/output hashes, latency, tokens |
| evidence grounding (declared before the run: quoted evidence must occur in the given inputs) | 267 all grounded; 1 ungrounded ("ict"→*computer technology*, the model quoted its own explanation); 1 partly grounded; 1 definite relationship without evidence |
| **evidence source (added after seeing outputs — see §12)** | for all 169 alias SAME_CONCEPT decisions the only evidence is the ESCO alias statement, never the posting text |
| promotion above MODEL_SUGGESTED | 0 (by rule: each candidate exists because the deterministic rule was not satisfied) |
| model consistency (20 candidates re-asked without cache, both invocations) | relationship identical 20/20 each time; output byte-identical 17/20 and 16/20 (wording differs) |
| rerun consistency | identical output hashes across invocations |
| source mutation | sha256 of every file under `data/raw`, `data/silver` and GOLD run `438ec2c0` identical before and after |
| tests / static audit | 519/519 pass; 0 forbidden subject conditionals |
| memory | first-invocation samples were **lost** (see §17). Sample at the start of the second invocation, model loaded: system free memory 24 %, swap used 1.40 GB of 2.0 GB |

## 9. Baseline → Qwen transition matrix

Before = `AMBIGUOUS` for every candidate.

| Kind | SAME_CONCEPT | PARENT | RELATED | UNRELATED | AMBIGUOUS | INSUFFICIENT_EVIDENCE | total |
|---|---|---|---|---|---|---|---|
| ALIAS_SENSE | 169 | 7 | 3 | 16 | 17 | 0 | 212 |
| AMBIGUOUS_TAXONOMY_LABEL | 15 | 4 | 11 | 5 | 0 | 1 | 36 |
| AMBIGUOUS_TOPIC_MAPPING | 3 | 4 | 11 | 3 | 0 | 1 | 22 |
| **all** | **187** | **15** | **25** | **24** | **17** | **2** | **270** |

Unchanged (still AMBIGUOUS) 17 · changed 253 · newly resolved to a definite relationship 251 · newly rejected
(UNRELATED) 24 · newly ambiguous 0 · insufficient evidence 2 · newly review-required 0 · CHILD and PARTIAL_OVERLAP
never used. Full per-candidate table: `analysis/changed_decisions.jsonl`; matrix: `analysis/transitions.csv`.

## 10. Important changed cases (read by the assistant; judgements are the assistant's, not labels)

**Where the model helped: it rejected collisions the extractor produced.**
* "call" (weekly call reviews, call logs, "call 'Time out for Safety'") → *Computer Assisted Language Learning*:
  UNRELATED ×4.
* "did" ("What did we learn?") → *direct inward dialing*: UNRELATED.
* "it" ("it's your career") → *computer technology*: UNRELATED.
* "JSON" → *open source model*: UNRELATED.
* "re" in "We're / We’re" → *reverse engineering*: UNRELATED ×6.
* "Technical Skills" → *apply knowledge of science, technology and engineering*: UNRELATED.
* ESCO label choice, all plausible: "ict" → *computer technology* SAME vs *in-circuit test* UNRELATED; "ml" →
  *machine learning* SAME vs *ML (computer programming)* UNRELATED; "ppc" → *pay-per-click* SAME;
  "conflict resolution" → *resolve conflicts* SAME.
* Paraphrases of soft skills: "attention to detail" → *attend to detail*, "be responsible" → *assume responsibility*,
  "problem-solving skills" → *solve problems*, "CRM" → *customer relationship management*, "PLC" →
  *programmable logic controller*.

**Where it was wrong or inconsistent.**
* "re" in "We’re Hiring – AVEVA PI Developer" → *reverse engineering*: **SAME_CONCEPT** (4 such). The same collision
  was rejected in 6 other postings.
* "CMM" in a list of gauges (micrometer, bore gauge, height gauge…, so coordinate measuring machine) → *ICT process
  quality models*: SAME_CONCEPT.
* "SEM" in "SAP BPC, SEM-BCS, EC-CS" → *search engine optimisation*: SAME_CONCEPT. In digital marketing SEM (search
  engine marketing) is still not SEO.
* "repair processes" (two-wheeler servicing) → *types of metal manufacturing processes*: SAME_CONCEPT.
* "electrical equipment" → *maintain electronic equipment*: SAME_CONCEPT.
* "data collection" / "data analysis" → *statistics*: SAME_CONCEPT (4). This is the error the alias rule was built
  to stop.
* "operational excellence" → *lean manufacturing*, "clinical trials" → *pharmaceutical drug development*,
  "identify opportunities" → *show entrepreneurial spirit*: SAME_CONCEPT, where RELATED or CHILD would fit.
* Direction of PARENT: "AWS" PARENT of *cloud technologies*; "Loops" PARENT of "Iteration and loops".
* Topic mappings: "Loops" → "Feedback loop" RELATED (different sense); "Irrotational fields and Solenoidal fields" →
  "field" SAME_CONCEPT; "vector" → "vector surface integrals" UNRELATED.
* "gimp" → *graphics editor software* UNRELATED (GIMP is one).

## 11. Hard-case results

In the 270 (diagnostic only):

| Term | n | Model |
|---|---|---|
| .NET → *Visual Basic* | 5 | AMBIGUOUS ×5 — did not accept the alias |
| MS Excel → *use spreadsheets software* | 6 | SAME_CONCEPT 5, PARENT 1 |
| data collection / data analysis → *statistics* | 4 | SAME_CONCEPT 4 (the case the rules exist to block) |
| AWS → *cloud technologies* | 5 | SAME 2, PARENT 2, RELATED 1; the EY service-line list ("Markets, BMC, AWS, Finance…") → PARENT |
| quality systems → *quality control systems* | 2 | SAME_CONCEPT |
| ML → *machine learning* / *ML (computer programming)* | 2 | SAME / UNRELATED |
| Angular, network, version control systems, communication, accounting, Java, Python, SQL, GCP | 0 | not among the 270 (the rules held them back earlier, so no model decision exists) |

Separate diagnostic set: 16 fixed pairs **without any context** (`semantic_hard_cases_v2.json`). They agree with the
specification's expectation on 8/16, identically in both invocations:
* Agree: Java/JavaScript UNRELATED, Python/python snake UNRELATED, cloud/cloud computing PARENT, AI and ML SAME,
  .NET/Visual Basic RELATED, model and testing PARENT.
* Differ: Angular/angular momentum → PARENT; network/neural network → PARENT; SQL/SQL injection → PARENT;
  database/DBMS → PARENT; Git/GitHub → PARENT; C/C++ → SAME_CONCEPT; CNN/convolutional neural network → UNRELATED;
  React/chemical reaction → RELATED.

Pattern: without context, when LEFT is a word inside RIGHT the model answers PARENT.

## 12. ESCO safety results

* Nothing in ESCO, the skills, the demand, the gaps or the recommendations changed; GOLD was read-only.
* **Systemic failure.** The candidate generator (unchanged production code) gives the model the alias fact as RIGHT
  CONTEXT: "'X' is an English ESCO altLabel of 'Y'". For all 169 alias SAME_CONCEPT decisions the quoted evidence is
  that sentence, and 159 of their reasons cite it ("'SEM' is an English ESCO altLabel of search engine
  optimisation"). The model has turned the taxonomy fact back into a claim about meaning, which is the exact error
  the alias-sense rule prevents.
* The declared grounding check does not catch this, because the quote does occur in the inputs. The post-hoc
  evidence-source check (evidence must come from the posting text) does: 0 of 169 pass.
* Consequently no alias decision may be used as sense evidence.

## 13. Knowledge-graph safety results

251 definite decisions map to candidate edges (SAME_AS 187, RELATED_TO 25, NOT_RELATED 24, PARENT_OF 15):
* 0 null endpoints, 0 self edges, 0 unknown endpoints, 0 contradictions with existing graph edges, 0 duplicates,
  0 PARENT/CHILD 2-cycles.
* 2 edges are flagged because their evidence is not grounded.
* **0 edges persisted**: the graph and the database were not written. Every candidate edge carries MODEL_SUGGESTED
  and its decision_id; nothing is labelled HUMAN_VALIDATED.

## 14. Model failures

None: 0 transport failures, 0 invalid outputs, 0 retries.

## 15. Ambiguous cases

17, all ALIAS_SENSE: .NET ×5, "IT" in pronoun or department use ("It is well suited…"), and others. The model kept
these AMBIGUOUS; they remain in the review queue.

## 16. Review-required cases

0 by state. By content, everything stays under review: all 212 alias decisions (§12), plus the wrong or inconsistent
cases in §10.

## 17. Known limitations

* **Candidate construction.** Alias candidates carry the taxonomy statement as RIGHT CONTEXT and no ESCO concept
  description; topic candidates carry only the unit label as LEFT CONTEXT and no RIGHT CONTEXT. The model therefore
  often decides with little real context.
* **Evidence-source check was added after seeing outputs.** It is analysis, not tuning: no prompt, threshold or rule
  was changed.
* **Operational mistake (mine).** The runner update that archives each invocation's outputs was reported as written
  to the Mac but did not arrive. The second invocation therefore overwrote the first invocation's `decisions.jsonl`
  and memory samples.
  * The first invocation's decisions were rebuilt exactly from the cache (the original model-call records, with
    latency and tokens).
  * Its run_meta, consistency and diagnostics files were copied before they were overwritten.
  * Its memory samples are lost.
* The deterministic extractor produced the "re" mentions from "We’re" (a curly apostrophe is not a word character).
  They were already held as ALIAS_SENSE_REVIEW_REQUIRED and never counted as demand. It is an extractor bug to fix
  separately.
* 270 candidates, one model, one prompt version, no labels: no accuracy, calibration or significance claims.

## 18. Did the model improve semantic interpretation?

**Evidence, not a score.**

Improvements:
* It rejects context-free collisions that the extractor produced: "call", "did", "it's", "JSON", most "We're".
* It picks the context-appropriate ESCO concept for several ambiguous labels (ict, ml, ppc).
* It paraphrase-matches soft-skill aliases.
* It is stable: the same relationship on re-ask 40/40, identical results on rerun.

Problems:
* On alias candidates it largely accepts the alias statement it is shown: 169 of 212 SAME_CONCEPT with no posting-text
  evidence, including clear errors (CMM, SEM, "We’re", repair processes, data collection → statistics).
* Its PARENT direction is unreliable.
* Without context it confuses containment with hierarchy (8/16 on the fixed pairs).

**Conclusion:** interpretation improved for collision rejection and label choice, but did not improve for alias
sense — where it is currently unsafe.

## 19. What should and should not be promoted downstream

* **Nothing is promoted now** (by the run rule and by the evidence above).
* **Blocked:** all 212 ALIAS_SENSE decisions (evidence-source failure); every PARENT decision (direction
  unreliable); the 2 ungrounded or evidence-free decisions.
* **Candidate for a later, reviewed step:**
  * UNRELATED decisions on ALIAS_SENSE (16), as a signal to *keep* a mention out of demand. That is the same
    direction as the current rule, so it is low risk.
  * AMBIGUOUS_TAXONOMY_LABEL SAME_CONCEPT decisions whose evidence is grounded in the surface text (13 of 15 quote
    the surface), as a review-priority ordering only, never as a mapping.
* Model output never becomes demand, coverage, a gap or a recommendation.

---

## QWEN SEMANTIC ENGINE STATUS

| | |
|---|---|
| Model | qwen2.5:7b-instruct (Q4_K_M, Ollama 0.34.4) |
| Candidates | 270 |
| Successful (schema-valid decisions) | 270 |
| Failed | 0 |
| Retries | 0 |
| Cache hits | 0 (invocation 1) / 270 (invocation 2) |
| Cache misses | 270 (invocation 1) / 0 (invocation 2) |
| Average latency | 6.33 s |
| p95 latency | 8.52 s |
| Baseline unchanged | 17 |
| Baseline changed | 253 |
| MODEL_SUGGESTED | 270 |
| REVIEW_REQUIRED | 0 by state (all 212 alias decisions blocked by content) |
| AMBIGUOUS | 17 |
| INSUFFICIENT_EVIDENCE | 2 |
| Schema failures | 0 |
| Evidence validation failures | 2 (pre-declared grounding check); 169 alias SAME_CONCEPT fail the post-hoc evidence-source check |
| Graph integrity violations | 0 (2 candidate edges flagged for ungrounded evidence; 0 persisted) |
| Existing tests | 519/519 |

**A. Did the real model process the 270 candidates?** Yes: 270/270 in 28.5 min, all schema-valid on the first
attempt, reproducible from cache, with 20/20 relationship consistency on re-ask.

**B. Did interpretation improve relative to the deterministic rules?** Partly. It resolved 251 of 270 baseline
AMBIGUOUS cases, but the alias-sense resolutions (169 SAME_CONCEPT) rest on the taxonomy statement rather than the
text, so they do not count as improved sense interpretation. Collision rejection and taxonomy-label choice did improve.

**C. Categories that benefited:** lexical-collision rejection (UNRELATED on alias candidates); ambiguous-ESCO-label
choice; soft-skill paraphrase.

**D. Categories that became worse (if the output were trusted):** alias sense (would re-open .NET-type errors:
statistics, SEM, CMM, "We’re"); PARENT direction; context-free containment pairs.

**E. Cases that require review:** all 212 alias decisions; the 15 PARENT decisions; the 22 topic-mapping decisions;
the examples in §10.

**F. Safe to pass downstream:** none now. Later and reviewed: alias UNRELATED as a keep-out signal, and grounded
taxonomy-label choices as review ordering.

**G. Must remain blocked:** all alias SAME_CONCEPT, PARENT and RELATED decisions; the ungrounded ones; anything that
would change demand, coverage, gaps or recommendations.

**H. Next engineering step (proposal — not done):**
1. **Candidate/prompt v3.** RIGHT CONTEXT = the ESCO concept's own description and type from the full taxonomy,
   *not* the alias statement. Give topic candidates their sibling topics and course title.
2. **Evidence validator v2.** A SAME_CONCEPT on an alias candidate must quote the LEFT (source-text) context.
3. **Extractor.** Treat curly apostrophes as word characters.
4. **Evaluation.** Freeze a human-labelled held-out set from these 270 before any rerun. Then run v3 as a new frozen
   experiment and compare v2 and v3 only on those labels.
