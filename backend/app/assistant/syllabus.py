"""
Grounded syllabus drafting: course syllabus, programme structure, or a revision of an existing course.

1. The code builds an evidence pack from one analysis run, each item with an id:
     D#  industry demand of a skill (posting count, support, gap classification) -- from the run's industry outputs
     R#  a reference-curriculum topic, T# a topic of the analysed curriculum, P# a peer topic (with page provenance)
     C#  a reference-programme course (programme drafts)
   Topics are retrieved by similarity (the engine's semantic backend) to the request.
2. The local model writes the draft as JSON against a fixed schema, citing evidence ids.
3. The code validates it: unknown ids are removed and reported; every item is labelled EVIDENCE (cites at least one
   valid id) or MODEL_SUGGESTION; totals and which requested skills the draft addresses are computed here, never by
   the model; a revision may only change or remove topics the course really has.

A draft is never an analysis result. Reading lists are model-suggested and marked unverified (models invent
references).
"""
import json
import re

from app.assistant.llm import _extract_json
from app.knowledge_engine.semantic_backend import get_backend

LABEL = ("AI-generated draft. It must be reviewed and approved by faculty before any use. It is not an analysis "
         "result: items marked MODEL_SUGGESTION have no evidence in the analysis, and the reading list is unverified.")
READING_NOTE = "unverified: model-suggested; check that it exists, and its edition and availability, before use"
SUPPORTED = ("HIGH_SUPPORT", "SUPPORTED")


class DraftError(RuntimeError):
    pass


# ---------------------------------------------------------------- evidence
def _docs_by_role(run):
    out = {}
    for d in run.report.get("documents") or []:
        out.setdefault(d.get("role"), []).append(d.get("doc_id"))
    return out


def _clean_topics(run, doc_ids):
    ids = set(doc_ids)
    return [t for t in run.topics.values() if t.get("doc_id") in ids and t.get("noise_label") == "TOPIC"]


def _rank(query, items, text_of, k):
    """Top-k items by similarity of their text to the query (the engine's TF-IDF backend; lexical)."""
    if not items or not query.strip():
        return []
    backend, _ = get_backend("tfidf")
    texts = [text_of(i) for i in items]
    backend.fit(texts + [query])
    sim = backend.similarity(backend.embed([query]), backend.embed(texts))
    sim = sim.toarray() if hasattr(sim, "toarray") else sim
    row = list(sim[0])
    order = sorted(range(len(items)), key=lambda j: (-row[j], j))
    return [(items[j], round(float(row[j]), 3)) for j in order[:k] if row[j] > 0]


def _gap_rows(run):
    """skill_key -> gap row (v2 when the run has it)."""
    from app.services import intelligence_service as svc
    try:
        rows = svc.IntelligenceRun(run).rows("skill_gaps_v2.jsonl")
    except Exception:  # noqa: BLE001 -- older runs have no v2 gaps
        rows = []
    return {g["skill_key"]: g for g in rows}


def demand_evidence(run, terms, limit=12):
    demand = (run.industry or {}).get("demand") or []
    if not demand:
        return []
    gaps = _gap_rows(run)
    from app.assistant.relevance import RunRelevance
    relevance = RunRelevance(run)
    wanted = [t.lower().strip() for t in terms if t and t.strip()]
    hits = []
    for d in demand:
        label = (d.get("skill_label") or "").lower()
        if any(w == label or w in label or (len(label) > 3 and label in w) for w in wanted):
            hits.append(d)
    if not hits:  # no label match: the most similar demanded skills
        hits = [d for d, _ in _rank(" ".join(terms), demand, lambda d: d.get("skill_label") or "", limit)]
    hits.sort(key=lambda d: (-(d.get("posting_count") or 0), d.get("skill_label") or ""))
    out = []
    for d in hits[:limit]:
        g = gaps.get(d["skill_key"], {})
        out.append({"type": "industry_demand", "skill": d.get("skill_label"), "skill_key": d["skill_key"],
                    "posting_count": d.get("posting_count"), "eligible_postings": d.get("eligible_postings"),
                    "support_state": d.get("support_state"),
                    "gap": g.get("classification_v2"), "curriculum_coverage": g.get("coverage_level"),
                    "syllabus_relevance": relevance.of(d["skill_key"])["relevance"],
                    "statement": d.get("statement")})
    return out


def topic_evidence(run, roles, query, limit):
    by_role = _docs_by_role(run)
    out = []
    for role in roles:
        topics = _clean_topics(run, by_role.get(role, []))
        for t, score in _rank(query, topics, lambda t: t.get("clean_text") or "", limit):
            course = run.courses.get(t.get("course_uid"), {})
            out.append({"type": "curriculum_topic", "role": role, "text": t.get("clean_text"), "doc_id": t.get("doc_id"),
                        "course_code": t.get("course_code"), "course_title": course.get("title"),
                        "unit": t.get("unit_label"), "page": t.get("page_number"), "similarity": score,
                        "topic_uid": t.get("topic_uid")})
    return out


def _number(items, prefix_of):
    numbered, counters = {}, {}
    for it in items:
        p = prefix_of(it)
        counters[p] = counters.get(p, 0) + 1
        numbered[f"{p}{counters[p]}"] = it
    return numbered


_ROLE_PREFIX = {"REFERENCE": "R", "TARGET": "T", "PEER": "P", "PREVIOUS_VERSION": "V"}


_TYPE_PREFIX = {"industry_demand": "D", "programme_course": "C", "book": "B", "web_link": "L",
                "curated_resource": "W", "plan_topic": "S"}


def _prefix(item):
    return _TYPE_PREFIX.get(item["type"]) or _ROLE_PREFIX.get(item.get("role"), "X")


def _evidence_text(evidence):
    lines = []
    for eid, e in evidence.items():
        if e["type"] == "industry_demand":
            lines.append(f"{eid}: skill '{e['skill']}': {e['posting_count']} of {e['eligible_postings']} job postings "
                         f"({e['support_state']}); curriculum gap: {e['gap']}, coverage {e['curriculum_coverage']}; "
                         f"syllabus relevance: {e.get('syllabus_relevance', 'UNCLASSIFIED')}")
        elif e["type"] == "programme_course":
            lines.append(f"{eid}: reference course '{e['title']}' ({e.get('course_code')}), semester {e.get('semester')}")
        elif e["type"] == "book":
            lines.append(f"{eid}: textbook printed in {e.get('doc_id')} {e.get('course_code')} (page {e.get('page')}): "
                         f"{e['text']}")
        elif e["type"] == "web_link":
            lines.append(f"{eid}: link printed in {e.get('doc_id')} {e.get('course_code')} (page {e.get('page')}): "
                         f"{e['url']}")
        elif e["type"] == "curated_resource":
            lines.append(f"{eid}: {e.get('kind')} '{e['title']}' {e['url']} (topics: {', '.join(e.get('tags') or [])})")
        elif e["type"] == "plan_topic":
            lines.append(f"{eid}: course topic '{e['text']}'" + (f" (unit: {e['unit']})" if e.get("unit") else ""))
        else:
            lines.append(f"{eid}: {e['role'].lower()} topic '{e['text']}' ({e.get('course_code')} "
                         f"{e.get('course_title') or ''}, page {e.get('page')})")
    return "\n".join(lines)


# ---------------------------------------------------------------- schemas
_EVID = {"type": "array", "items": {"type": "string"}}
COURSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "description": {"type": "string"},
        "objectives": {"type": "array", "items": {"type": "string"}},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "units": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "hours": {"type": "integer"},
            "topics": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "evidence": _EVID}, "required": ["text", "evidence"]}}},
            "required": ["title", "hours", "topics"]}},
        "outcomes": {"type": "array", "items": {"type": "string"}},
        "lab_experiments": {"type": "array", "items": {"type": "string"}},
        "assessment": {"type": "array", "items": {"type": "string"}},
        "reading": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "authors": {"type": "string"}}, "required": ["title"]}},
    },
    "required": ["title", "objectives", "units", "outcomes"],
}
PROGRAMME_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "summary": {"type": "string"},
        "semesters": {"type": "array", "items": {"type": "object", "properties": {
            "number": {"type": "integer"},
            "courses": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "category": {"type": "string"}, "credits": {"type": "number"},
                "rationale": {"type": "string"}, "evidence": _EVID}, "required": ["title", "credits", "evidence"]}}},
            "required": ["number", "courses"]}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "semesters"],
}
REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "add": {"type": "array", "items": {"type": "object", "properties": {
            "topic": {"type": "string"}, "unit": {"type": "string"}, "reason": {"type": "string"}, "evidence": _EVID},
            "required": ["topic", "reason", "evidence"]}},
        "update": {"type": "array", "items": {"type": "object", "properties": {
            "from": {"type": "string"}, "to": {"type": "string"}, "reason": {"type": "string"}, "evidence": _EVID},
            "required": ["from", "to", "reason", "evidence"]}},
        "remove": {"type": "array", "items": {"type": "object", "properties": {
            "topic": {"type": "string"}, "reason": {"type": "string"}, "evidence": _EVID},
            "required": ["topic", "reason", "evidence"]}},
    },
    "required": ["summary", "add", "update", "remove"],
}

RELEVANCE_RULES = ("Syllabus relevance of a skill: CORE_CONTENT and SUPPORTING_CONTENT become topics; "
                   "PROFESSIONAL_PRACTICE skills (leadership, decision making, communication) are developed through "
                   "activities, labs and assessment, never as topics; OTHER_FIELD skills belong to another field: leave "
                   "them out unless the course is about that field.")
SYSTEM = ("You draft university curricula for faculty review. Use ONLY the evidence listed for facts about industry "
          "demand and existing curricula, and cite evidence ids (like D1, R3) in each item's evidence list. When an "
          "item is your own suggestion without evidence, give it an empty evidence list. Never state numbers of job "
          "postings or percentages. " + RELEVANCE_RULES + " Reply with JSON only.")


def _generate(model, prompt, schema, retries=1):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    last = None
    for _ in range(retries + 1):
        reply = model.chat(messages, json_schema=schema, temperature=0.3)
        try:
            obj = _extract_json(reply["content"])
            missing = [k for k in schema.get("required", []) if k not in obj]
            if missing:
                raise ValueError(f"missing fields: {', '.join(missing)}")
            return obj
        except ValueError as exc:
            last = exc
            messages += [{"role": "assistant", "content": reply["content"]},
                         {"role": "user", "content": f"That reply was not valid ({exc}). Reply again with JSON only, "
                                                     "matching the schema."}]
    raise DraftError(f"the model did not return a valid draft: {last}")


def _check_ids(ids, evidence, removed):
    ids = [str(i).strip() for i in ids or [] if str(i).strip()]
    good = [i for i in ids if i in evidence]
    removed.extend(i for i in ids if i not in evidence)
    return sorted(set(good), key=ids.index)


def _basis(ids):
    return "EVIDENCE" if ids else "MODEL_SUGGESTION"


def _texts(values):
    return [str(v).strip() for v in values or [] if str(v).strip()]


# ---------------------------------------------------------------- course
def draft_course(model, run, title, skills=(), level=None, hours=None):
    title = (title or "").strip()
    if not title and not skills:
        raise DraftError("give a course title or at least one skill")
    query = " ".join([title, *skills])
    evidence = _number(demand_evidence(run, list(skills) or [title]) +
                       topic_evidence(run, ("REFERENCE", "PEER", "TARGET"), query, 8), _prefix)
    prompt = (f"Draft a one-semester course syllabus.\nCourse: {title or 'choose a title'}\n"
              f"Skills it should address: {', '.join(skills) or 'from the evidence'}\n"
              f"Level: {level or 'undergraduate engineering'}\nTotal contact hours: {hours or 'about 45'}\n"
              "Use 4 to 6 units. Prefer topics the evidence supports; existing topics of the analysed curriculum (T#) "
              "show what is already taught.\n\nEvidence:\n" + (_evidence_text(evidence) or "(none)"))
    raw = _generate(model, prompt, COURSE_SCHEMA)
    removed = []
    units = []
    for u in raw.get("units") or []:
        topics = []
        for t in u.get("topics") or []:
            text = str(t.get("text") or "").strip() if isinstance(t, dict) else str(t).strip()
            if not text:
                continue
            ids = _check_ids(t.get("evidence") if isinstance(t, dict) else [], evidence, removed)
            topics.append({"text": text, "evidence": ids, "basis": _basis(ids)})
        try:
            unit_hours = max(0, int(u.get("hours") or 0))
        except (TypeError, ValueError):
            unit_hours = 0
        units.append({"title": str(u.get("title") or "").strip(), "hours": unit_hours, "topics": topics})
    if not units:
        raise DraftError("the model returned no units")
    cited = {i for u in units for t in u["topics"] for i in t["evidence"]}
    demand_ids = [i for i, e in evidence.items() if e["type"] == "industry_demand"]
    syllabus = {
        "title": str(raw.get("title") or title).strip(), "description": str(raw.get("description") or "").strip(),
        "objectives": _texts(raw.get("objectives")), "prerequisites": _texts(raw.get("prerequisites")),
        "units": units, "outcomes": _texts(raw.get("outcomes")), "lab_experiments": _texts(raw.get("lab_experiments")),
        "assessment": _texts(raw.get("assessment")),
        "reading": [{"title": str(r.get("title")).strip(), "authors": str(r.get("authors") or "").strip(),
                     "status": READING_NOTE} for r in raw.get("reading") or [] if isinstance(r, dict) and r.get("title")],
    }
    topics_all = [t for u in units for t in u["topics"]]
    checks = {
        "total_hours": sum(u["hours"] for u in units),
        "topics": len(topics_all), "topics_with_evidence": sum(1 for t in topics_all if t["evidence"]),
        "unknown_evidence_ids_removed": sorted(set(removed)),
        "skills_addressed": [evidence[i]["skill"] for i in demand_ids if i in cited],
        "skills_not_addressed": [evidence[i]["skill"] for i in demand_ids if i not in cited and
                                 evidence[i].get("syllabus_relevance") in ("CORE_CONTENT", "SUPPORTING_CONTENT")],
        "professional_practice_skills": [evidence[i]["skill"] for i in demand_ids
                                         if evidence[i].get("syllabus_relevance") == "PROFESSIONAL_PRACTICE"],
        "other_field_skills": [evidence[i]["skill"] for i in demand_ids
                               if evidence[i].get("syllabus_relevance") == "OTHER_FIELD"],
    }
    return _draft("course", syllabus["title"], run, model, {"title": title, "skills": list(skills), "level": level,
                                                            "hours": hours}, evidence, syllabus, checks)


# ---------------------------------------------------------------- programme
def draft_programme(model, run, discipline=None, focus=None):
    by_role = _docs_by_role(run)
    ref_courses = sorted((c for c in run.courses.values() if c.get("doc_id") in set(by_role.get("REFERENCE", []))),
                         key=lambda c: (str(c.get("semester") or "~"), c.get("course_code") or ""))
    items = [{"type": "programme_course", "title": c.get("title"), "course_code": c.get("course_code"),
              "semester": c.get("semester"), "doc_id": c.get("doc_id")} for c in ref_courses[:60]]
    gaps = _gap_rows(run)
    demand = sorted(((run.industry or {}).get("demand") or []), key=lambda d: -(d.get("posting_count") or 0))
    confirmed = [d for d in demand if d.get("support_state") in SUPPORTED and
                 (gaps.get(d["skill_key"], {}).get("classification_v2") in ("PARTIAL", "MISSING"))]
    items += demand_evidence(run, [d["skill_label"] for d in confirmed[:12]]) if confirmed else []
    evidence = _number(items, _prefix)
    prompt = (f"Draft an 8-semester undergraduate programme structure for {discipline or 'the analysed discipline'}"
              f"{f' with a focus on {focus}' if focus else ''}. About 160 credits in total. Base the core on the "
              "reference programme's courses (C#) and add courses that address the skill gaps (D#).\n\nEvidence:\n"
              + (_evidence_text(evidence) or "(none)"))
    raw = _generate(model, prompt, PROGRAMME_SCHEMA)
    removed, semesters, seen = [], [], set()
    for s in raw.get("semesters") or []:
        try:
            n = int(s.get("number"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= 10 or n in seen:
            continue
        seen.add(n)
        courses = []
        for c in s.get("courses") or []:
            if not isinstance(c, dict) or not str(c.get("title") or "").strip():
                continue
            try:
                credits = float(c.get("credits") or 0)
            except (TypeError, ValueError):
                credits = 0.0
            ids = _check_ids(c.get("evidence"), evidence, removed)
            courses.append({"title": str(c["title"]).strip(), "category": str(c.get("category") or "").strip(),
                            "credits": credits, "rationale": str(c.get("rationale") or "").strip(),
                            "evidence": ids, "basis": _basis(ids)})
        semesters.append({"number": n, "courses": courses, "credits": sum(c["credits"] for c in courses)})
    if not semesters:
        raise DraftError("the model returned no semesters")
    semesters.sort(key=lambda s: s["number"])
    all_courses = [c for s in semesters for c in s["courses"]]
    cited = {i for c in all_courses for i in c["evidence"]}
    demand_ids = [i for i, e in evidence.items() if e["type"] == "industry_demand"]
    programme = {"title": str(raw.get("title") or "Programme structure").strip(),
                 "summary": str(raw.get("summary") or "").strip(), "semesters": semesters,
                 "notes": _texts(raw.get("notes"))}
    checks = {"total_credits": sum(s["credits"] for s in semesters), "semesters": len(semesters),
              "courses": len(all_courses), "courses_with_evidence": sum(1 for c in all_courses if c["evidence"]),
              "unknown_evidence_ids_removed": sorted(set(removed)),
              "skills_addressed": [evidence[i]["skill"] for i in demand_ids if i in cited],
              "skills_not_addressed": [evidence[i]["skill"] for i in demand_ids if i not in cited]}
    return _draft("programme", programme["title"], run, model, {"discipline": discipline, "focus": focus}, evidence,
                  programme, checks)


# ---------------------------------------------------------------- revision
def _norm(s):
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def draft_revision(model, run, course_code):
    by_role = _docs_by_role(run)
    target_docs = set(by_role.get("TARGET", []))
    course = next((c for c in run.courses.values() if c.get("doc_id") in target_docs and
                   _norm(c.get("course_code")) == _norm(course_code)), None)
    if course is None:
        raise DraftError(f"course {course_code} is not in the analysed curriculum")
    own = [t for t in run.topics.values() if t.get("course_uid") == course["course_uid"] and t.get("noise_label") == "TOPIC"]
    items = [{"type": "curriculum_topic", "role": "TARGET", "text": t.get("clean_text"), "doc_id": t.get("doc_id"),
              "course_code": t.get("course_code"), "course_title": course.get("title"), "unit": t.get("unit_label"),
              "page": t.get("page_number"), "topic_uid": t.get("topic_uid")} for t in own[:40]]
    query = " ".join([course.get("title") or ""] + [t.get("clean_text") or "" for t in own[:40]])
    demand = (run.industry or {}).get("demand") or []
    related = [d["skill_label"] for d, _ in _rank(query, demand, lambda d: d.get("skill_label") or "", 8)]
    items += demand_evidence(run, related or [course.get("title") or ""], limit=8)
    items += topic_evidence(run, ("REFERENCE", "PEER"), query, 6)
    evidence = _number(items, _prefix)
    prompt = (f"Propose a revision of the course '{course.get('title')}' ({course.get('course_code')}). Its current "
              "topics are the T# items. Suggest topics to ADD (cite D#, R# or P#), topics to UPDATE (quote the "
              "current topic exactly in 'from') and topics to REMOVE (quote exactly). Keep it focused: at most 6 "
              "additions.\n\nEvidence:\n" + _evidence_text(evidence))
    raw = _generate(model, prompt, REVISION_SCHEMA)
    existing = {_norm(t.get("clean_text")): t.get("clean_text") for t in own}
    removed, rejected = [], []

    def change(item, kind):
        ids = _check_ids(item.get("evidence"), evidence, removed)
        return {**{k: str(item.get(k) or "").strip() for k in ("topic", "unit", "from", "to", "reason") if k in item},
                "evidence": ids, "basis": _basis(ids), "kind": kind}

    adds = [change(a, "add") for a in raw.get("add") or [] if isinstance(a, dict) and str(a.get("topic") or "").strip()]
    updates, removals = [], []
    for u in raw.get("update") or []:
        if isinstance(u, dict) and _norm(u.get("from")) in existing:
            updates.append({**change(u, "update"), "from": existing[_norm(u.get("from"))]})
        elif isinstance(u, dict):
            rejected.append({"kind": "update", "topic": u.get("from"), "reason": "not a topic of this course"})
    for r in raw.get("remove") or []:
        if isinstance(r, dict) and _norm(r.get("topic")) in existing:
            removals.append({**change(r, "remove"), "topic": existing[_norm(r.get("topic"))]})
        elif isinstance(r, dict):
            rejected.append({"kind": "remove", "topic": r.get("topic"), "reason": "not a topic of this course"})
    revision = {"course_code": course.get("course_code"), "course_title": course.get("title"),
                "summary": str(raw.get("summary") or "").strip(), "current_topics": [t.get("clean_text") for t in own],
                "add": adds, "update": updates, "remove": removals}
    changes = adds + updates + removals
    checks = {"changes": len(changes), "changes_with_evidence": sum(1 for c in changes if c["evidence"]),
              "rejected_changes": rejected, "unknown_evidence_ids_removed": sorted(set(removed))}
    return _draft("revision", f"Revision of {course.get('course_code')} {course.get('title')}", run, model,
                  {"course_code": course_code}, evidence, revision, checks)


# ---------------------------------------------------------------- resources
RESOURCE_KINDS = ("book", "website", "youtube", "course_platform", "documentation", "other")
RESOURCES_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string"}, "title": {"type": "string"}, "authors": {"type": "string"},
            "url": {"type": "string"}, "use": {"type": "string"}, "evidence": _EVID}, "required": ["title", "evidence"]}},
    },
    "required": ["items"],
}


def resource_evidence(run, query, skills=()):
    from app.assistant import resources as res
    items = []
    for r in res.curriculum_resources(run, query):
        items.append(dict(r))
    for r in res.curated(query):
        items.append({"type": "curated_resource", **{k: r.get(k) for k in ("id", "kind", "title", "url", "tags", "note")}})
    if skills:
        items += demand_evidence(run, list(skills), limit=6)
    return _number(items, _prefix)


def _resource_from_evidence(e):
    if e["type"] == "book":
        return {"kind": "book", "title": e["text"], "authors": "", "url": None, "status": "LISTED_IN_CURRICULUM",
                "where": f"{e.get('doc_id')} {e.get('course_code')} p.{e.get('page')}"}
    if e["type"] == "web_link":
        return {"kind": "website", "title": e.get("text") or e["url"], "authors": "", "url": e["url"],
                "status": "LISTED_IN_CURRICULUM", "where": f"{e.get('doc_id')} {e.get('course_code')} p.{e.get('page')}"}
    if e["type"] == "curated_resource":
        return {"kind": e.get("kind") or "website", "title": e["title"], "authors": "", "url": e["url"],
                "status": "CURATED", "where": "learning_resources.json"}
    return None


def build_resources(raw_items, evidence, check=True, limit=20):
    """Resolve the model's choices: cited evidence gives the canonical title and link (never the model's version);
    uncited items are model suggestions; then online checks; links that do not exist are removed."""
    from app.assistant import resources as res
    removed_ids, chosen, seen = [], [], set()
    for it in raw_items or []:
        if not isinstance(it, dict):
            continue
        ids = _check_ids(it.get("evidence"), evidence, removed_ids)
        resolved = next((_resource_from_evidence(evidence[i]) for i in ids if _resource_from_evidence(evidence[i])), None)
        if resolved is None:
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            kind = str(it.get("kind") or "other").strip().lower()
            resolved = {"kind": kind if kind in RESOURCE_KINDS else "other", "title": title,
                        "authors": str(it.get("authors") or "").strip(),
                        "url": str(it.get("url") or "").strip() or None, "status": "MODEL_SUGGESTION", "where": None}
        resolved["use"] = str(it.get("use") or "").strip()
        resolved["evidence"] = ids
        key = (resolved.get("url") or resolved["title"]).lower()
        if key in seen:
            continue
        seen.add(key)
        chosen.append(resolved)
    chosen = chosen[:limit]
    if check:
        res.check_all([c for c in chosen if c["status"] != "LISTED_IN_CURRICULUM" or c.get("url")])
    removed = [c for c in chosen if (c.get("check") or {}).get("check") == "LINK_NOT_FOUND"]
    kept = [c for c in chosen if c not in removed]
    return kept, removed, removed_ids


def draft_resources(model, run, title, skills=(), topics=(), check=True):
    title = (title or "").strip()
    if not title and not skills and not topics:
        raise DraftError("give a course title, skills or topics")
    query = " ".join([title, *skills, *topics])
    evidence = resource_evidence(run, query, skills)
    prompt = (f"Choose learning resources for the course '{title or 'see the topics'}'"
              + (f" covering: {', '.join(list(topics)[:25])}" if topics else "")
              + ". Pick 8 to 15 items: textbooks (B#), links printed in the curricula (L#), and curated websites, "
                "documentation and YouTube channels (W#); cite exactly one id for each such item. You may add up to 4 "
                "well-known items of your own with an empty evidence list (give title, authors for books, and url). "
                "Say in 'use' what each is for.\n\nEvidence:\n" + (_evidence_text(evidence) or "(none)"))
    raw = _generate(model, prompt, RESOURCES_SCHEMA)
    kept, removed, removed_ids = build_resources(raw.get("items"), evidence, check=check)
    if not kept:
        raise DraftError("the model chose no usable resources")
    by_status = {}
    for k in kept:
        by_status[k["status"]] = by_status.get(k["status"], 0) + 1
    content = {"summary": str(raw.get("summary") or "").strip(), "items": kept}
    checks = {"items": len(kept), "by_source": by_status,
              "online_checks": {k["title"]: (k.get("check") or {}).get("check") for k in kept if k.get("check")},
              "removed_links_not_found": [r.get("url") for r in removed],
              "unknown_evidence_ids_removed": sorted(set(removed_ids))}
    return _draft("resources", f"Resources: {title or 'course'}", run, model,
                  {"title": title, "skills": list(skills)}, evidence, content, checks)


# ---------------------------------------------------------------- lesson plan
LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "sessions": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "covers": _EVID, "objectives": {"type": "array", "items": {"type": "string"}},
            "activities": {"type": "array", "items": {"type": "string"}},
            "resources": {"type": "array", "items": {"type": "string"}},
            "assessment": {"type": "string"}, "minutes": {"type": "integer"}}, "required": ["title", "covers"]}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sessions"],
}


def _plan_topics(run, course_code=None, source=None):
    """(title, [(unit, topic)]) from a course draft's content, or from a course of the analysed curriculum."""
    if source:
        out = [(u.get("title"), t.get("text")) for u in source.get("units") or [] for t in u.get("topics") or []]
        return source.get("title") or "course", [(u, t) for u, t in out if t]
    by_role = _docs_by_role(run)
    target_docs = set(by_role.get("TARGET", []))
    course = next((c for c in run.courses.values() if c.get("doc_id") in target_docs and
                   _norm(c.get("course_code")) == _norm(course_code)), None)
    if course is None:
        raise DraftError(f"course {course_code} is not in the analysed curriculum")
    own = sorted((t for t in run.topics.values() if t.get("course_uid") == course["course_uid"]
                  and t.get("noise_label") == "TOPIC"), key=lambda t: (t.get("page_number") or 0))
    return f"{course.get('course_code')} {course.get('title')}", [(t.get("unit_label"), t.get("clean_text")) for t in own]


def draft_lesson_plan(model, run, course_code=None, source=None, sessions=None, minutes=50, check=True):
    title, topics = _plan_topics(run, course_code, source)
    if not topics:
        raise DraftError("the course has no topics to plan")
    try:
        minutes = max(20, min(int(minutes or 50), 180))
    except (TypeError, ValueError):
        minutes = 50
    want = sessions
    try:
        want = max(4, min(int(sessions), 80)) if sessions else None
    except (TypeError, ValueError):
        want = None
    items = [{"type": "plan_topic", "text": t, "unit": u} for u, t in topics[:80]]
    items += [dict(e) for e in resource_evidence(run, title + " " + " ".join(t for _, t in topics[:30])).values()]
    evidence = _number(items, _prefix)
    prompt = (f"Write a session-by-session lesson plan for '{title}'. {want or 'About one session per one or two topics'}"
              f" sessions of {minutes} minutes. Every session lists the course topics it covers (S# ids) in 'covers'; "
              "together the sessions must cover every S# topic, in a sensible teaching order. For each session give "
              "learning objectives, activities (lecture, demonstration, lab, problem solving, discussion, group work, "
              "presentations: this is where professional-practice skills are developed), resources (cite B#, L# or W# "
              "ids, or name a resource) and a short assessment (quiz, exercise, lab record).\n\nEvidence:\n"
              + _evidence_text(evidence))
    raw = _generate(model, prompt, LESSON_SCHEMA)
    topic_ids = [i for i, e in evidence.items() if e["type"] == "plan_topic"]
    removed, plan, covered = [], [], set()
    for s in raw.get("sessions") or []:
        if not isinstance(s, dict) or not str(s.get("title") or "").strip():
            continue
        covers = [i for i in _check_ids(s.get("covers"), evidence, removed) if i in topic_ids]
        covered |= set(covers)
        res_items = []
        for r in s.get("resources") or []:
            r = str(r).strip()
            if r in evidence and _resource_from_evidence(evidence[r]):
                res_items.append({**_resource_from_evidence(evidence[r]), "evidence": [r]})
            elif r:
                res_items.append({"kind": "other", "title": r, "url": None, "status": "MODEL_SUGGESTION",
                                  "evidence": []})
        try:
            m = max(10, min(int(s.get("minutes") or minutes), 240))
        except (TypeError, ValueError):
            m = minutes
        plan.append({"number": len(plan) + 1, "title": str(s["title"]).strip(), "covers": covers,
                     "topics": [evidence[i]["text"] for i in covers], "objectives": _texts(s.get("objectives")),
                     "activities": _texts(s.get("activities")), "resources": res_items,
                     "assessment": str(s.get("assessment") or "").strip(), "minutes": m})
    if not plan:
        raise DraftError("the model returned no sessions")
    if check:
        from app.assistant import resources as res
        links = [r for p in plan for r in p["resources"] if r.get("url")]
        res.check_all(links)
        for p in plan:
            p["resources"] = [r for r in p["resources"] if (r.get("check") or {}).get("check") != "LINK_NOT_FOUND"]
    uncovered = [evidence[i]["text"] for i in topic_ids if i not in covered]
    checks = {"sessions": len(plan), "sessions_requested": want, "total_minutes": sum(p["minutes"] for p in plan),
              "topics": len(topic_ids), "topics_covered": len(topic_ids) - len(uncovered), "topics_not_covered": uncovered,
              "unknown_evidence_ids_removed": sorted(set(removed))}
    return _draft("lesson_plan", f"Lesson plan: {title}", run, model,
                  {"course_code": course_code, "from_draft": bool(source), "sessions": want, "minutes": minutes},
                  evidence, {"course": title, "sessions": plan, "notes": _texts(raw.get("notes"))}, checks)


def _draft(kind, title, run, model, request, evidence, content, checks):
    return {"kind": kind, "title": title, "label": LABEL, "run_id": run.run_id, "model": model.describe(),
            "request": request, "evidence": evidence, "content": content, "checks": checks}


# ---------------------------------------------------------------- markdown
def _cite(ids):
    return f" [{', '.join(ids)}]" if ids else " *(model suggestion)*"


def to_markdown(d):
    c, k = d["content"], d["checks"]
    out = [f"# {d['title']}", "", f"> {d['label']}", "",
           f"Analysis run `{d['run_id']}` · model `{d['model'].get('model')}` · {d.get('created_at', '')}", ""]
    if d["kind"] == "course":
        if c.get("description"):
            out += [c["description"], ""]
        for head, key in (("Objectives", "objectives"), ("Prerequisites", "prerequisites")):
            if c.get(key):
                out += [f"## {head}", *[f"- {x}" for x in c[key]], ""]
        for i, u in enumerate(c["units"], 1):
            out += [f"## Unit {i}: {u['title']} ({u['hours']} h)", *[f"- {t['text']}{_cite(t['evidence'])}" for t in u["topics"]], ""]
        for head, key in (("Course outcomes", "outcomes"), ("Laboratory", "lab_experiments"), ("Assessment", "assessment")):
            if c.get(key):
                out += [f"## {head}", *[f"- {x}" for x in c[key]], ""]
        if c.get("reading"):
            out += ["## Reading (unverified)", *[f"- {r['title']}{' — ' + r['authors'] if r['authors'] else ''}"
                                                 for r in c["reading"]], ""]
        out += [f"Total hours: {k['total_hours']}. Topics with evidence: {k['topics_with_evidence']} of {k['topics']}."]
    elif d["kind"] == "programme":
        if c.get("summary"):
            out += [c["summary"], ""]
        for s in c["semesters"]:
            out += [f"## Semester {s['number']} ({s['credits']:g} credits)",
                    *[f"- {x['title']}{' (' + x['category'] + ')' if x['category'] else ''}, {x['credits']:g} credits"
                      f"{_cite(x['evidence'])}" for x in s["courses"]], ""]
        out += [f"Total credits: {k['total_credits']:g}."]
    elif d["kind"] == "resources":
        if c.get("summary"):
            out += [c["summary"], ""]
        for kind in RESOURCE_KINDS:
            rows = [i for i in c["items"] if i["kind"] == kind]
            if rows:
                out += [f"## {kind.replace('_', ' ').capitalize()}s",
                        *[f"- {_resource_line(i)}" for i in rows], ""]
    elif d["kind"] == "lesson_plan":
        for p in c["sessions"]:
            out += [f"## Session {p['number']}: {p['title']} ({p['minutes']} min)"]
            out += [f"- Topics: {'; '.join(p['topics'])}"] if p["topics"] else ["- Topics: *(none of the course topics)*"]
            out += [f"- Objectives: {'; '.join(p['objectives'])}"] if p["objectives"] else []
            out += [f"- Activities: {'; '.join(p['activities'])}"] if p["activities"] else []
            out += [f"- Resources: {'; '.join(_resource_line(r) for r in p['resources'])}"] if p["resources"] else []
            out += [f"- Assessment: {p['assessment']}", ""] if p["assessment"] else [""]
        if k.get("topics_not_covered"):
            out += [f"Course topics no session covers: {'; '.join(k['topics_not_covered'])}.", ""]
    else:
        if c.get("summary"):
            out += [c["summary"], ""]
        def section(head, lines):
            return [head, *(lines or ["- none"]), ""]
        out += section("## Add", [f"- {a['topic']}{' (' + a['unit'] + ')' if a.get('unit') else ''}: {a['reason']}"
                                  f"{_cite(a['evidence'])}" for a in c["add"]])
        out += section("## Update", [f"- {u['from']} → {u['to']}: {u['reason']}{_cite(u['evidence'])}"
                                     for u in c["update"]])
        out += section("## Remove", [f"- {r['topic']}: {r['reason']}{_cite(r['evidence'])}" for r in c["remove"]])
    if k.get("skills_not_addressed"):
        out += ["", f"Requested skills with demand evidence that the draft does not address: "
                    f"{', '.join(k['skills_not_addressed'])}."]
    out += ["", "## Evidence", *[f"- **{i}**: " + _evidence_text({i: e}).split(': ', 1)[1] for i, e in d["evidence"].items()]]
    return "\n".join(out) + "\n"


_STATUS_WORDS = {"LISTED_IN_CURRICULUM": "listed in the curriculum", "CURATED": "curated",
                 "MODEL_SUGGESTION": "model suggestion"}
_CHECK_WORDS = {"LINK_OK": "link checked", "FOUND_IN_OPEN_LIBRARY": "found in Open Library",
                "NOT_FOUND_IN_OPEN_LIBRARY": "not found in Open Library: verify before use",
                "NOT_CHECKED": "not checked", "NOT_NEEDED": None}


def _resource_line(r):
    status = _STATUS_WORDS.get(r.get("status"), r.get("status"))
    check = _CHECK_WORDS.get((r.get("check") or {}).get("check"))
    tail = "; ".join(x for x in (status, r.get("where"), check) if x)
    text = r["title"] + (f" — {r['authors']}" if r.get("authors") else "") + (f" <{r['url']}>" if r.get("url") else "")
    return f"{text}{': ' + r['use'] if r.get('use') else ''} *({tail})*"


def evidence_json(d):
    return json.dumps(d["evidence"], indent=1, ensure_ascii=False)
