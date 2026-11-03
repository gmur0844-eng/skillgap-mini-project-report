# Assistant and syllabus drafting

A conversational agent over the analysis, running on a local model (Ollama). It answers questions about an analysis,
starts analyses after the user confirms, and drafts course syllabi, programme structures and course revisions.
Code: `backend/app/assistant/`, API `/api/v1/assistant`, screen **Assistant** (`assistant_screen.dart`).

## Setup

```
ollama pull qwen2.5:7b-instruct        # the configured default (engine_config.json, semantic_ai.providers)
ASSISTANT_MODEL=<another model> bash scripts/local/run.sh   # optional: any installed Ollama model
```

`GET /api/v1/assistant/status` (and the notice on the screen) says whether the service runs, whether the model is
installed and whether it supports tool calling. A model without tool support is used through a JSON protocol instead.

## What it can do

| Kind | Tools | Runs |
|---|---|---|
| Read | analysis overview, skill gaps, industry demand, evidence for one skill, recommendations, curriculum search, a course's units and topics, analyses, uploads | at once, read-only, from the stored run files |
| Action | start an analysis of an uploaded curriculum | only after the user clicks **Confirm**; a new message instead lets it lapse |
| Draft | course syllabus, 8-semester programme structure, revision of a course of the analysed curriculum, session-by-session lesson plan, learning resources (books, websites, documentation, YouTube channels) | saved under `data/assistant/drafts/` (git-ignored) |

## Guarantees, enforced in code

* **Facts come from tools.** Every figure in an answer is compared with the turn's tool results and the user's own
  message; a figure found in neither is shown under the answer as "figures not found in the analysis data".
* **Actions wait for the user.** The model can only propose `start_analysis`; it runs from the Confirm button.
* **Drafts cite evidence.** The code builds an evidence pack from the run (D# demand of a skill, R#/T#/P# reference,
  analysed or peer topics with page, C# reference-programme courses); the model writes JSON citing ids; citations
  that do not exist are removed and listed; uncited items are marked *model suggestion*.
* **Figures in drafts are computed, not written:** total hours and credits, topics with evidence, which requested
  skills the draft addresses.
* **A revision cannot invent the course:** updates and removals must quote a topic the course really has; others are
  rejected and listed.
* **Reading lists are checked or marked:** a course draft's reading list is marked unverified (models invent
  references); a resources draft checks links and books online and says what it found (below).
* **A draft is never an analysis result.** Each carries the label "AI-generated draft … must be reviewed and approved
  by faculty"; the pipeline never reads drafts.

## Syllabus relevance

Every demanded skill carries a label from ESCO's own classification recorded in the run (reuse level, collections,
top-level skill group) and the discipline's map in `data/metadata/syllabus_relevance.json`
(`backend/app/assistant/relevance.py`):

| Label | Meaning | Drafts treat it as |
|---|---|---|
| CORE_CONTENT | the discipline's own field (ICT for CSE; a technology tool such as Docker) | topics |
| SUPPORTING_CONTENT | a neighbouring field (mathematics for CSE) | topics where the course draws on it |
| PROFESSIONAL_PRACTICE | transversal or generic skills (lead others, make decisions, communication) | activities and assessment, never topics |
| OTHER_FIELD | another field's knowledge (financial analysis for CSE) | left out unless the course is about it |

On the CSE run published on 2026-10-10 (`0534d6e1d06a617f`), the 11 confirmed gaps are 8 CORE_CONTENT, 2 PROFESSIONAL_PRACTICE ("lead others", "make
decisions") and 1 OTHER_FIELD ("financial analysis"). The label never changes a gap classification.

## Lesson plans and resources

* **Lesson plan** (`draft_lesson_plan`, from a course of the analysed curriculum or a course syllabus draft): sessions
  with the course topics they cover, objectives, activities, resources and assessment. The code renumbers sessions,
  keeps only real topic ids and reports the course topics no session covers.
* **Resources** (`find_resources`): textbooks and links **printed in the curricula** for the most similar courses
  (read from the course's own pages under "Text Books", "References", "Online resources"...: status
  LISTED_IN_CURRICULUM, with page), **curated** official documentation, open course platforms and YouTube channels
  (`data/metadata/learning_resources.json`: CURATED), and the model's own suggestions (MODEL_SUGGESTION). When the
  machine is online, links are requested and model-suggested books are looked up in Open Library; a link that does not
  exist is removed, a book not found is marked "verify before use". `RESOURCE_CHECK=off` skips the checks
  (NOT_CHECKED).

## Limits

* Quality depends on the local model; a 7-billion-parameter model writes plausible but generic syllabi and can call a
  wrong tool. Nothing about the quality of answers or drafts has been evaluated yet.
* Topic retrieval for the evidence pack is lexical (TF-IDF): a request worded differently from the curricula finds
  less evidence, and more items become model suggestions.
* Answers are synchronous: a local model takes seconds per step and a draft up to a few minutes.

## Tests

`backend/tests/test_assistant.py` (synthetic run, scripted model: tools, confirmation, figure check, citation
checks, revision limits, lesson plans, resources and link checks, relevance labels, JSON-protocol fallback, API) and `flutter_app/test/assistant_test.dart` (screen).
