"""
Semantic Engine V3 -- candidate context, prompt and deterministic evidence validation.

V2 failure (run qwen-270-v1): alias candidates carried "'X' is an English ESCO altLabel of 'Y'" as RIGHT CONTEXT, and
the model used that taxonomy fact as evidence of meaning. V3 separates four kinds of input and never lets the model
see a taxonomy fact as evidence:

  SOURCE (LEFT)      what the text says: SOURCE_TEXT, JOB_TITLE, COURSE_TITLE, UNIT_TITLE, LEARNING_OUTCOME
  CONCEPT (RIGHT)    what the candidate concept is: ESCO_DESCRIPTION, ESCO_HIERARCHY, ESCO_RELATION, or for a reference
                     topic its own SOURCE_TEXT / COURSE_TITLE / UNIT_TITLE
  METADATA           why the pair was generated: TAXONOMY_METADATA, NORMALIZATION_METADATA -- shown, never evidence
Every input item has an id (L1.., R1.., M1..). The model cites items by id with an exact quote; the validator checks
the quote against the item and takes the source type from OUR item, not from the model.

The validator is authoritative over the model. Nothing here names a skill, subject or institution.
"""
import json
import re

from app.knowledge_engine.semantic_provider import RELATIONSHIPS

PROMPT_VERSION = "adjudicate-v3"
SCHEMA_VERSION = "decision-schema-v2"
VALIDATOR_VERSION = "evidence-validator-v2.1"

SOURCE_TYPES = ("SOURCE_TEXT", "COURSE_TITLE", "UNIT_TITLE", "LEARNING_OUTCOME", "JOB_TITLE", "ESCO_DESCRIPTION",
                "ESCO_HIERARCHY", "ESCO_RELATION", "TAXONOMY_METADATA", "NORMALIZATION_METADATA")
METADATA_TYPES = ("TAXONOMY_METADATA", "NORMALIZATION_METADATA")
DEFINITE = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED")
MEANING_RELATIONS = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP")

OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "relationship": {"type": "string", "enum": list(RELATIONSHIPS)},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "ref": {"type": "string"}, "source_type": {"type": "string", "enum": list(SOURCE_TYPES)},
            "quote": {"type": "string"}}, "required": ["ref", "source_type", "quote"]}},
        "direction_justification": {"type": "string"},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "uncertainty": {"type": "string"},
    },
    "required": ["relationship", "reason", "evidence", "direction_justification", "alternatives", "uncertainty"],
}

# ------------------------------------------------------------------ context builders

_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+|\s[••\-–]\s")


def _clean(t):
    return re.sub(r"[ \t]+", " ", (t or "").replace(" ", " ")).strip(" \n*#>-•")  # noqa: B005 -- a set of characters to trim, as intended


def sentence_at(text, start, end, max_chars=320):
    """The sentence (or list item) containing text[start:end], then the one before and after."""
    text = text or ""
    bounds = [0] + [m.end() for m in _SENT_SPLIT.finditer(text)] + [len(text)]
    i = max(k for k in range(len(bounds) - 1) if bounds[k] <= start)
    lo, hi = bounds[i], bounds[i + 1]
    if hi - lo > max_chars:  # a long sentence: keep a window centred on the mention (the mention is always inside)
        half = max(0, (max_chars - (end - start)) // 2)
        lo, hi = max(lo, start - half), min(hi, end + half)
    cur = _clean(text[lo:hi])
    prev = _clean(text[bounds[i - 1]:bounds[i]]) if i > 0 else ""
    nxt = _clean(text[bounds[i + 1]:bounds[i + 2]]) if i + 2 < len(bounds) else ""
    return cur, prev[:max_chars], nxt[:max_chars]


def esco_concept_items(store, uri, prefix="R"):
    node = (store.get("skills", {}).get(uri) or store.get("skill_groups", {}).get(uri) or {})
    items = []
    if not node:
        return items, {"uri": uri, "label": None}
    if node.get("description"):
        items.append({"source_type": "ESCO_DESCRIPTION", "text": node["description"][:600]})
    broader = [store["skill_groups"].get(b) or store["skills"].get(b) for b in node.get("broader", [])]
    labels = [b["pref_label"] for b in broader if b]
    if labels:
        items.append({"source_type": "ESCO_HIERARCHY", "text": "broader concepts: " + "; ".join(labels[:4])})
    concept = {"uri": uri, "label": node.get("pref_label"), "type": node.get("skill_type") or node.get("kind"),
               "reuse_level": node.get("reuse_level"), "alt_labels": node.get("alt_labels", [])[:12]}
    return [{"id": f"{prefix}{i + 1}", **it} for i, it in enumerate(items)], concept


def _ids(items, prefix):
    return [{"id": f"{prefix}{i + 1}", **it} for i, it in enumerate(items) if it.get("text")]


def alias_candidate(mention, posting_text, job_title, mapping_uri, store, generation_note):
    """A posting mention whose ESCO alias sense the deterministic rules could not establish."""
    cur, prev, nxt = sentence_at(posting_text, *mention["span"])
    left = _ids([{"source_type": "SOURCE_TEXT", "text": cur}, {"source_type": "SOURCE_TEXT", "text": prev},
                 {"source_type": "SOURCE_TEXT", "text": nxt}, {"source_type": "JOB_TITLE", "text": job_title}], "L")
    right, concept = esco_concept_items(store, mapping_uri)
    meta = _ids([{"source_type": "TAXONOMY_METADATA", "text": generation_note}], "M")
    return {"kind": "ALIAS_SENSE", "left": mention["raw_mention"], "left_items": left, "right": concept["label"],
            "right_concept": concept, "right_items": right, "metadata_items": meta,
            "question": ("Does the LEFT expression, in THIS source context, mean or require the RIGHT concept? The ESCO "
                         "alias relationship only identified this candidate and is NOT evidence of meaning.")}


def taxonomy_label_candidate(surface, occurrences, uri, store, generation_note):
    """A surface whose ESCO label belongs to several concepts;
    occurrences = [(text, span, title, title_type)] with title_type JOB_TITLE or COURSE_TITLE."""
    items = []
    for text, span, title, title_type in occurrences[:2]:
        cur, _, _ = sentence_at(text, *span)
        items += [{"source_type": "SOURCE_TEXT", "text": cur}, {"source_type": title_type, "text": title}]
    left = _ids(items, "L")
    right, concept = esco_concept_items(store, uri)
    meta = _ids([{"source_type": "TAXONOMY_METADATA", "text": generation_note}], "M")
    return {"kind": "AMBIGUOUS_TAXONOMY_LABEL", "left": surface, "left_items": left, "right": concept["label"],
            "right_concept": concept, "right_items": right, "metadata_items": meta,
            "question": "Does the LEFT expression, as used in these sources, mean the RIGHT concept?"}


def topic_candidate(topic, course, siblings, outcomes, ref_topic, ref_course, ref_siblings, generation_note):
    left = _ids([{"source_type": "SOURCE_TEXT", "text": topic["clean_text"]},
                 {"source_type": "COURSE_TITLE", "text": course.get("title")},
                 {"source_type": "UNIT_TITLE", "text": topic.get("unit_label")}]
                + [{"source_type": "SOURCE_TEXT", "text": s} for s in siblings[:4]]
                + [{"source_type": "LEARNING_OUTCOME", "text": o} for o in outcomes[:2]], "L")
    right = _ids([{"source_type": "SOURCE_TEXT", "text": ref_topic["clean_text"]},
                  {"source_type": "COURSE_TITLE", "text": ref_course.get("title")},
                  {"source_type": "UNIT_TITLE", "text": ref_topic.get("unit_label")}]
                 + [{"source_type": "SOURCE_TEXT", "text": s} for s in ref_siblings[:4]], "R")
    meta = _ids([{"source_type": "NORMALIZATION_METADATA", "text": generation_note}], "M")
    return {"kind": "AMBIGUOUS_TOPIC_MAPPING", "left": topic["clean_text"], "left_items": left,
            "right": ref_topic["clean_text"], "right_concept": {"topic_uid": ref_topic["topic_uid"]},
            "right_items": right, "metadata_items": meta,
            "question": "Does the LEFT curriculum topic, in its course context, teach the same thing as the RIGHT topic?"}


def candidate_hashes(c, sha):
    """input_hash: the pair and question; context_hash: every item shown to the model (metadata included)."""
    return (sha({k: c.get(k) for k in ("kind", "left", "right", "question")}),
            sha({k: c.get(k) for k in ("left_items", "right_items", "metadata_items", "right_concept")}))


# ------------------------------------------------------------------ prompt

DEFINITIONS = {
    "SAME_CONCEPT": "in this context LEFT expresses the RIGHT concept itself",
    "PARENT": "LEFT is a broader, more general concept that contains RIGHT",
    "CHILD": "LEFT is a narrower, more specific concept contained by RIGHT",
    "RELATED": "clearly associated (used together, a tool of, a prerequisite of), neither contains the other",
    "PARTIAL_OVERLAP": "the meanings share part of their content",
    "UNRELATED": "LEFT in this context means something else (for example a different word sense)",
    "AMBIGUOUS": "the source context supports more than one reading",
    "INSUFFICIENT_EVIDENCE": "the source context does not allow a judgement",
}


def _block(items):
    return "\n".join(f"  [{it['id']}] ({it['source_type']}) {it['text']}" for it in items) or "  (none)"


def build_prompt(c):
    defs = "\n".join(f"- {k}: {v}" for k, v in DEFINITIONS.items())
    concept = c.get("right_concept") or {}
    head = f"RIGHT: {c['right']}" + (f"   (ESCO type: {concept.get('type')}; URI {concept.get('uri')})" if concept.get("uri") else "")
    return (
        "You decide how an expression found in a source text relates to a candidate concept.\n"
        f"QUESTION: {c['question']}\n\n"
        f"LEFT: {c['left']}\nSOURCE CONTEXT (evidence you may cite):\n{_block(c['left_items'])}\n\n"
        f"{head}\nCONCEPT CONTEXT (evidence you may cite):\n{_block(c['right_items'])}\n\n"
        "CANDIDATE-GENERATION METADATA (explains why this pair was proposed; it is NOT evidence of meaning and must "
        f"not be used to support SAME_CONCEPT, PARENT, CHILD, RELATED or PARTIAL_OVERLAP):\n{_block(c['metadata_items'])}\n\n"
        f"Relationships (LEFT relative to RIGHT):\n{defs}\n\n"
        "Rules:\n"
        "- Judge by meaning in THIS context. A string contained in another string is NOT a hierarchy: "
        "a shared word does not make one concept broader than the other.\n"
        "- A short form, acronym or alias may mean something else in the source (another expansion, a product "
        "name, a word inside a longer word, a pronoun). Check the source context.\n"
        "- For PARENT or CHILD explain the direction in direction_justification; otherwise leave it empty.\n"
        "- Cite evidence as items: {\"ref\": \"<id>\", \"source_type\": \"<its type>\", \"quote\": \"<exact words from "
        "that item>\"}. Cite at least one SOURCE CONTEXT item for any definite relationship.\n"
        "- If the source context does not decide it, answer AMBIGUOUS or INSUFFICIENT_EVIDENCE.\n\n"
        "Reply with one JSON object only: {\"relationship\": \"...\", \"reason\": \"<one sentence>\", "
        "\"evidence\": [{\"ref\": \"...\", \"source_type\": \"...\", \"quote\": \"...\"}], "
        "\"direction_justification\": \"<text or empty>\", \"alternatives\": [\"...\"], "
        "\"uncertainty\": \"<one sentence as text>\"}. Every value is text or a list; no numbers or null.")


# ------------------------------------------------------------------ prompt v4 (opt-in experiment)
#
# adjudicate-v4 changes only the prompt; the schema, the inputs and validate_decision are v3's, so a v4 decision is
# checked exactly as strictly as a v3 one. It is not the production prompt (engine_config semantic_ai.prompt_version
# stays adjudicate-v3, so recorded decisions and their replay are unchanged); it is run on the frozen candidates with
# scripts/semantic/run_frozen_adjudication.py --protocol adjudicate-v4.
#
# Declared 2026-10-22, before any v4 output existed, from two findings on the v3 run (docs/SEMANTIC_PROMPT_V4.md):
#   1. the v3 prompt asked for SOURCE evidence only, while the validator also requires CONCEPT evidence for the
#      meaning relations, a directional item for PARENT/CHILD and source text for SAME_CONCEPT of a short form: v4
#      states the validator's actual rules;
#   2. the reviewers' (AI-assisted, development-only) answers showed v3 calling a narrower concept SAME_CONCEPT,
#      partial overlap SAME_CONCEPT, and a broader concept RELATED: v4 gives an ordered decision procedure.
# It names no skill, concept, discipline or benchmark pair.
PROMPT_VERSION_V4 = "adjudicate-v4"

DECISION_PROCEDURE_V4 = (
    "Decide in this order:\n"
    "1. Does LEFT, as used in the SOURCE CONTEXT, mean the RIGHT concept or something connected to it? If the source "
    "uses LEFT in another sense, answer UNRELATED. If the source does not let you tell, answer AMBIGUOUS (several "
    "readings fit) or INSUFFICIENT_EVIDENCE (nothing decides it).\n"
    "2. SAME_CONCEPT only if LEFT and RIGHT are interchangeable here: the same thing at the same breadth.\n"
    "3. CHILD if LEFT is one specific kind, instance, part, product, platform, vendor or tool of RIGHT. A named "
    "product or provider of a technology category is CHILD of that category, not SAME_CONCEPT.\n"
    "4. PARENT if LEFT is a broader area or category that includes RIGHT as one of its kinds or parts.\n"
    "5. PARTIAL_OVERLAP if they share part of their meaning but each also covers things the other does not.\n"
    "6. RELATED if they are associated (used together, a tool for, a prerequisite of) without sharing meaning.\n")

EVIDENCE_RULES_V4 = (
    "Evidence rules (your answer is checked against them; an answer that breaks one is discarded):\n"
    "- Quote exact words copied from the item you cite. Cite items by their id.\n"
    "- Never cite CANDIDATE-GENERATION METADATA items.\n"
    "- Any definite relationship (SAME_CONCEPT, PARENT, CHILD, RELATED, PARTIAL_OVERLAP, UNRELATED) needs at least "
    "one SOURCE CONTEXT item.\n"
    "- SAME_CONCEPT, PARENT, CHILD, RELATED and PARTIAL_OVERLAP also need at least one CONCEPT CONTEXT item.\n"
    "- PARENT and CHILD also need direction_justification and a cited item of type ESCO_HIERARCHY, ESCO_RELATION, "
    "COURSE_TITLE, UNIT_TITLE or LEARNING_OUTCOME that shows the direction.\n"
    "- SAME_CONCEPT for a short form, acronym or alias also needs a cited SOURCE_TEXT or JOB_TITLE item.\n"
    "- If you cannot cite what a relationship needs, answer INSUFFICIENT_EVIDENCE instead.\n")


def build_prompt_v4(c):
    defs = "\n".join(f"- {k}: {v}" for k, v in DEFINITIONS.items())
    concept = c.get("right_concept") or {}
    head = f"RIGHT: {c['right']}" + (f"   (ESCO type: {concept.get('type')}; URI {concept.get('uri')})" if concept.get("uri") else "")
    return (
        "You decide how an expression found in a source text relates to a candidate concept.\n"
        f"QUESTION: {c['question']}\n\n"
        f"LEFT: {c['left']}\nSOURCE CONTEXT (evidence you may cite):\n{_block(c['left_items'])}\n\n"
        f"{head}\nCONCEPT CONTEXT (evidence you may cite):\n{_block(c['right_items'])}\n\n"
        "CANDIDATE-GENERATION METADATA (explains why this pair was proposed; it is NOT evidence of meaning):\n"
        f"{_block(c['metadata_items'])}\n\n"
        f"Relationships (LEFT relative to RIGHT):\n{defs}\n\n"
        f"{DECISION_PROCEDURE_V4}\n"
        "A string contained in another string, or a shared word, is never by itself a hierarchy or the same "
        "concept. A short form may mean something else in the source: check the source context.\n\n"
        f"{EVIDENCE_RULES_V4}\n"
        "Reply with one JSON object only: {\"relationship\": \"...\", \"reason\": \"<one sentence>\", "
        "\"evidence\": [{\"ref\": \"...\", \"source_type\": \"...\", \"quote\": \"...\"}], "
        "\"direction_justification\": \"<text or empty>\", \"alternatives\": [\"...\"], "
        "\"uncertainty\": \"<one sentence as text>\"}. Every value is text or a list; no numbers or null.")


def validate_output(obj):
    """Schema check for decision-schema-v2 (no external dependency)."""
    errs = []
    if not isinstance(obj, dict):
        return ["output is not a JSON object"]
    for k in OUTPUT_JSON_SCHEMA["required"]:
        if k not in obj:
            errs.append(f"missing field {k}")
    if obj.get("relationship") not in RELATIONSHIPS:
        errs.append(f"relationship {obj.get('relationship')!r} not allowed")
    for k in ("reason", "direction_justification", "uncertainty"):
        if k in obj and not isinstance(obj[k], str):
            errs.append(f"{k} must be a string")
    if not isinstance(obj.get("alternatives", []), list):
        errs.append("alternatives must be a list")
    ev = obj.get("evidence", [])
    if not isinstance(ev, list) or not all(isinstance(e, dict) and isinstance(e.get("ref"), str)
                                           and isinstance(e.get("quote"), str) for e in ev):
        errs.append("evidence must be a list of {ref, source_type, quote}")
    return errs


# ------------------------------------------------------------------ evidence validator v2 (authoritative)

def _norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[“”\"'`’‘]|\.\.\.|…", " ", (t or "").lower())).strip()


# item types that can carry direction (a taxonomy hierarchy/relation, or curriculum structure: a unit inside a
# course, an outcome of a course)
DIRECTIONAL_TYPES = ("ESCO_HIERARCHY", "ESCO_RELATION", "COURSE_TITLE", "UNIT_TITLE", "LEARNING_OUTCOME")


def validate_decision(out, c):
    """
    Deterministic gate over a model decision. Returns (final_state, findings).

    final_state:
      MODEL_SUPPORTED        definite relationship whose evidence passes every rule
      MODEL_SUGGESTED        AMBIGUOUS / INSUFFICIENT_EVIDENCE answered by the model (kept for review, no effect)
      REVIEW_REQUIRED        schema failure or evidence that cannot be traced to the inputs
      INSUFFICIENT_EVIDENCE  definite relationship without the required source evidence (downgraded)
    Rules: evidence present; each cited ref exists; the quote occurs in that item; the source type is OUR item's type
    (a model-claimed type that differs is recorded); metadata items never count; any definite relationship needs a
    SOURCE-side item; meaning relations (SAME/PARENT/CHILD/RELATED/PARTIAL) also need a CONCEPT-side item;
    PARENT/CHILD need a direction justification AND a cited directional item (DIRECTIONAL_TYPES); SAME_CONCEPT on alias/label candidates needs SOURCE_TEXT or JOB_TITLE.
    """
    findings = []
    schema = validate_output(out)
    if schema:
        return "REVIEW_REQUIRED", [f"SCHEMA: {e}" for e in schema]
    rel = out["relationship"]
    if rel not in DEFINITE:
        return "MODEL_SUGGESTED", ["NON_DEFINITE_RELATIONSHIP"]
    items = {it["id"]: ("LEFT", it) for it in c["left_items"]}
    items.update({it["id"]: ("RIGHT", it) for it in c["right_items"]})
    items.update({it["id"]: ("META", it) for it in c["metadata_items"]})
    valid = []
    for e in out.get("evidence", []):
        side_it = items.get(e["ref"])
        if side_it is None:
            findings.append(f"UNKNOWN_REF:{e['ref']}")
            continue
        side, it = side_it
        if len(_norm(e["quote"])) < 2:
            findings.append(f"EMPTY_QUOTE:{e['ref']}")
            continue
        if _norm(e["quote"]) not in _norm(it["text"]):
            findings.append(f"QUOTE_NOT_IN_ITEM:{e['ref']}")
            continue
        if e.get("source_type") and e.get("source_type") != it["source_type"]:
            findings.append(f"SOURCE_TYPE_MISLABELLED:{e['ref']}:{e.get('source_type')}->{it['source_type']}")
        if side == "META" or it["source_type"] in METADATA_TYPES:
            findings.append(f"METADATA_CITED:{e['ref']}")
            continue
        valid.append((side, it["source_type"]))
    untraceable = any(f.startswith(("UNKNOWN_REF", "QUOTE_NOT_IN_ITEM")) for f in findings)  # invented evidence
    has_left = any(s == "LEFT" for s, _ in valid)
    has_right = any(s == "RIGHT" for s, _ in valid)
    if not out.get("evidence"):
        findings.append("NO_EVIDENCE")
    if not has_left:
        findings.append("NO_SOURCE_EVIDENCE")
    if rel in MEANING_RELATIONS and not has_right:
        findings.append("NO_CONCEPT_EVIDENCE")
    if rel == "SAME_CONCEPT" and c["kind"] in ("ALIAS_SENSE", "AMBIGUOUS_TAXONOMY_LABEL") \
            and not any(s == "LEFT" and t in ("SOURCE_TEXT", "JOB_TITLE") for s, t in valid):
        findings.append("ALIAS_SAME_CONCEPT_WITHOUT_SOURCE_TEXT")
    if rel in ("PARENT", "CHILD") and not (out.get("direction_justification") or "").strip():
        findings.append("NO_DIRECTION_JUSTIFICATION")
    if rel in ("PARENT", "CHILD") and not any(t in DIRECTIONAL_TYPES for _, t in valid):
        # a shared word or one string inside another is never hierarchy: direction needs a structural fact
        findings.append("NO_DIRECTIONAL_EVIDENCE")
    blocking = {"NO_EVIDENCE", "NO_SOURCE_EVIDENCE", "NO_CONCEPT_EVIDENCE", "ALIAS_SAME_CONCEPT_WITHOUT_SOURCE_TEXT",
                "NO_DIRECTION_JUSTIFICATION", "NO_DIRECTIONAL_EVIDENCE"}
    if untraceable:
        return "REVIEW_REQUIRED", findings
    if any(f in blocking for f in findings):
        return "INSUFFICIENT_EVIDENCE", findings
    return "MODEL_SUPPORTED", findings


def effective_relationship(out, final_state):
    """What downstream may read: the model's relationship only when MODEL_SUPPORTED."""
    return out["relationship"] if final_state == "MODEL_SUPPORTED" else final_state


def dumps(c):
    return json.dumps(c, ensure_ascii=False, sort_keys=True)
