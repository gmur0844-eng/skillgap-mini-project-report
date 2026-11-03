# Curriculum decoder

The decoder turns any supported curriculum PDF into provenance-carrying records. It is generic: the only inputs
are the PDF and its manifest entry (role, institution, programme, discipline, version, academic year). Nothing in the
code names an institution or a subject (static audit: 0 forbidden conditionals).

## Stages

| Stage | What happens | Where |
|---|---|---|
| RAW | the PDF's SHA-256 must equal the manifest's `expected_sha256`; otherwise the document is quarantined | `pipeline.run`, `evidence_guard` |
| BRONZE | `pdftotext -layout` per page; `pdfplumber` table isolation only on pages with a detected Topics/Content column; table and prose blocks ordered by vertical position; header-less continuation tables joined across page breaks; running headers/footers removed except structural lines | `app/pipelines/preprocessing/layout_aware_extraction.py` |
| SILVER | course headers vs code mentions, semester headings, unit headings (`UNIT`, `Module`, with `-`, `:`, en/em dash), topics, course outcomes, prerequisite statements (incl. explicit "Nil"), section boundaries (text books, references, CO-PO matrix, …) | `curriculum_structuring.py`, `silver.py` |
| contracts | every record validated (pydantic); failures quarantined with the reason, the run continues | `contracts.py`, `quarantine.py` |
| noise labels | TOPIC vs NOISE_BIBLIOGRAPHY / URL / LAYOUT_INTERLEAVED / FRAGMENT / ADMINISTRATIVE … | `noise.py` |
| health gate | per-document checks (courses, units, topics, outcomes, provenance, baseline regression) → analytics gates | `health.py` |
| topic hierarchy (2.0) | explicit `Head: item, item` lines → parent topic + subtopics | `intelligence.topic_hierarchy` |

## Output hierarchy and provenance

`document → course (code, title, semester, pages) → unit (label, title, page) → topic (raw text, clean text,
source line, page, extraction method, noise label) → subtopic (2.0) → concept (cluster) → skill mention → ESCO`.
Every topic keeps `doc_id`, `course_uid`, `unit_label`, `page_number`, `source_line`, `extraction_method` and the
document hash; the API returns this as `provenance`.

## Real run (final run, 3 documents, 527 pages)

| | AICTE model (REFERENCE) | CBIT R22 (PREVIOUS_VERSION) | CBIT R22A (TARGET) |
|---|---|---|---|
| health | PASS | PASS | PASS |
| courses / units / topics / clean topics — totals across the three | 189 courses · 662 units · 8,982 topic fragments · 7,667 clean topics | | |
| course outcomes extracted | used as depth evidence (80 outcome mentions of demand skills) | | |

Quarantine (unchanged from engine 1.1): 1,132 AICTE appendix topics without a course code (ORPHAN_ATTRIBUTION),
2 code-shaped strings without structure, 1 course without a title; 0 contract violations.

## Evaluation (assistant-labelled, not ground truth)

Golden pages (4 real pages, 36 expected topics, attribution-aware): recall 1.0, 0 topics attributed to another
course. Topic noise filter (75 random fragments): accuracy 0.827. These are assistant labels, not human validation.

## Limits

Scanned (image-only) pages are detected and counted but not OCR-ed. Practical/lab hours in `L-T-P` columns are
kept in `title_raw` but not parsed into fields, so `INTRODUCE_LAB` recommendations cannot be produced. Continuation
rows that pdfplumber does not detect as a table stay as layout text. Only three PDFs were available; "works across
disciplines" is by construction (no subject logic) and tested on synthetic fixtures, not demonstrated on a
non-computing curriculum.
