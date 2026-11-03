"""
The assistant's tools. Three kinds:

  read    answers from one analysis run (or the job list); runs at once
  action  changes something (starts an analysis); never runs from the model's request alone: the agent stores it as a
          pending action and the user confirms or rejects it
  draft   writes a syllabus draft with the local model (syllabus.py); saved, never an analysis result

Every tool returns {"data": ..., "sources": [...]} with small, citable payloads (the model sees them; the user sees the
sources). Results come from stored run files through the same services the app's screens use; nothing is recomputed.
"""
from app.assistant import syllabus
from app.assistant.relevance import HOW as RELEVANCE_HOW
from app.assistant.relevance import RunRelevance
from app.services import analysis_jobs
from app.services import knowledge_service as ks

SUPPORTED = syllabus.SUPPORTED


class ToolError(RuntimeError):
    pass


class Tool:
    def __init__(self, name, kind, description, parameters, fn, confirm_text=None):
        self.name, self.kind, self.description, self.parameters, self.fn = name, kind, description, parameters, fn
        self.confirm_text = confirm_text

    def spec(self):
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def _obj(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required)}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}


class Context:
    """What tools work on: one run (the conversation's, else the published one) and the model for drafting."""

    def __init__(self, run_id=None, model=None, store=None):
        self.run_id, self.model, self.store = run_id, model, store
        self._run = None
        self._relevance = None

    @property
    def run(self):
        if self._run is None:
            self._run = ks.load_run(self.run_id)
        return self._run

    @property
    def relevance(self):
        if self._relevance is None:
            self._relevance = RunRelevance(self.run)
        return self._relevance


def _gap_rows(run):
    return syllabus._gap_rows(run)


def _confirmed(g):
    return g.get("classification_v2") in ("PARTIAL", "MISSING") and g.get("support_state") in SUPPORTED \
        and g.get("evidence_status") != "REVIEW_REQUIRED"


def _demand(run):
    return {d["skill_key"]: d for d in (run.industry or {}).get("demand") or []}


def _find_skill(run, name):
    name = (name or "").strip().lower()
    rows = list(_demand(run).values())
    exact = [d for d in rows if (d.get("skill_label") or "").lower() == name]
    part = [d for d in rows if name and name in (d.get("skill_label") or "").lower()]
    hits = exact or sorted(part, key=lambda d: -(d.get("posting_count") or 0))
    if not hits:
        raise ToolError(f"no skill named '{name}' has demand evidence in this analysis")
    return hits[0]


# ---------------------------------------------------------------- read tools
def overview(ctx, _args):
    run = ctx.run
    gaps = _gap_rows(run)
    demand = _demand(run)
    target = next((d for d in run.report.get("documents") or [] if d.get("role") == "TARGET"), {})
    confirmed = sorted((g for g in gaps.values() if _confirmed(g)),
                       key=lambda g: -(demand.get(g["skill_key"], {}).get("posting_count") or 0))
    counts = {}
    for g in gaps.values():
        counts[g.get("classification_v2")] = counts.get(g.get("classification_v2"), 0) + 1
    data = {"run_id": run.run_id, "curriculum": {k: target.get(k) for k in ("institution", "programme", "curriculum_version")},
            "eligible_job_postings": next(iter(demand.values()), {}).get("eligible_postings"),
            "skills_compared": len(gaps), "gap_classification_counts": counts,
            "confirmed_gaps": [{"skill": g["skill_label"], "classification": g["classification_v2"],
                                "postings": demand.get(g["skill_key"], {}).get("posting_count"),
                                "syllabus_relevance": ctx.relevance.of(g["skill_key"])["relevance"]} for g in confirmed],
            "syllabus_relevance_meaning": dict(RELEVANCE_HOW),
            "recommendations": len((run.industry or {}).get("recommendations") or [])}
    return {"data": data, "sources": [f"analysis {run.run_id}: skill gaps, industry demand"]}


def skill_gaps(ctx, args):
    run = ctx.run
    demand = _demand(run)
    rows = list(_gap_rows(run).values())
    if args.get("confirmed_only"):
        rows = [g for g in rows if _confirmed(g)]
    if args.get("classification"):
        rows = [g for g in rows if g.get("classification_v2") == str(args["classification"]).upper()]
    if args.get("syllabus_relevance"):
        rows = [g for g in rows if ctx.relevance.of(g["skill_key"])["relevance"] == str(args["syllabus_relevance"]).upper()]
    rows.sort(key=lambda g: -(demand.get(g["skill_key"], {}).get("posting_count") or 0))
    limit = max(1, min(int(args.get("limit") or 15), 50))
    data = [{"skill": g["skill_label"], "classification": g.get("classification_v2"),
             "coverage": g.get("coverage_level"), "support": g.get("support_state"),
             "postings": demand.get(g["skill_key"], {}).get("posting_count"), "confirmed": _confirmed(g),
             "syllabus_relevance": ctx.relevance.of(g["skill_key"])["relevance"]} for g in rows[:limit]]
    return {"data": {"total_matching": len(rows), "items": data}, "sources": [f"analysis {run.run_id}: skill gaps"]}


def industry_demand(ctx, args):
    run = ctx.run
    rows = sorted(_demand(run).values(), key=lambda d: -(d.get("posting_count") or 0))
    limit = max(1, min(int(args.get("limit") or 15), 50))
    return {"data": [{"skill": d["skill_label"], "postings": d.get("posting_count"), "of": d.get("eligible_postings"),
                      "support": d.get("support_state")} for d in rows[:limit]],
            "sources": [f"analysis {run.run_id}: industry demand"]}


def explain_skill(ctx, args):
    run = ctx.run
    d = _find_skill(run, args.get("skill"))
    g = _gap_rows(run).get(d["skill_key"], {})
    trace = ((run.industry or {}).get("traces") or {}).get(d["skill_key"]) or {}
    cur = trace.get("curriculum") or {}
    why_not = None
    try:
        why_not = ks.why_no_recommendation(run, d["skill_key"])
    except Exception:  # noqa: BLE001 -- a skill with a recommendation has no why-not record
        why_not = None
    data = {"skill": d["skill_label"], "postings": d.get("posting_count"), "of": d.get("eligible_postings"),
            "demand_statement": d.get("statement"), "support": d.get("support_state"),
            "gap": g.get("classification_v2"), "coverage": g.get("coverage_level"), "reason": g.get("reason_v2"),
            "courses_with_skill": cur.get("target_courses_with_skill"),
            "recommended": any(r["skill_key"] == d["skill_key"] for r in (run.industry or {}).get("recommendations") or []),
            "why_not_recommended": (why_not or {}).get("reasons") if isinstance(why_not, dict) else None,
            "syllabus_relevance": ctx.relevance.of(d["skill_key"])}
    return {"data": data, "sources": [f"analysis {run.run_id}: evidence trace for {d['skill_label']}"]}


def recommendations(ctx, _args):
    run = ctx.run
    recs = (run.industry or {}).get("recommendations") or []
    return {"data": [{"skill": r.get("skill_label"), "action": r.get("action_type"), "gap": r.get("classification"),
                      "courses": r.get("target_course_codes"), "support": r.get("support_state")} for r in recs],
            "sources": [f"analysis {run.run_id}: recommendations"]}


def search_curriculum(ctx, args):
    run = ctx.run
    q = str(args.get("query") or "").strip()
    if not q:
        raise ToolError("give a search query")
    role = str(args.get("role") or "TARGET").upper()
    hits = syllabus.topic_evidence(run, (role,), q, max(1, min(int(args.get("limit") or 8), 20)))
    return {"data": [{k: h[k] for k in ("text", "course_code", "course_title", "unit", "page", "role")} for h in hits],
            "sources": [f"{h['doc_id']} {h['course_code']} p.{h['page']}" for h in hits]}


def get_course(ctx, args):
    run = ctx.run
    code = syllabus._norm(args.get("course_code"))
    matches = [c for c in run.courses.values() if syllabus._norm(c.get("course_code")) == code]
    if not matches:
        raise ToolError(f"no course {args.get('course_code')} in this analysis")
    roles = {d.get("doc_id"): d.get("role") for d in run.report.get("documents") or []}
    out = []
    for c in matches[:3]:
        topics = [t for t in run.topics.values() if t.get("course_uid") == c["course_uid"] and t.get("noise_label") == "TOPIC"]
        units = {}
        for t in sorted(topics, key=lambda t: (t.get("page_number") or 0)):
            units.setdefault(t.get("unit_label") or "(no unit)", []).append(t.get("clean_text"))
        out.append({"course_code": c.get("course_code"), "title": c.get("title"), "semester": c.get("semester"),
                    "document": c.get("doc_id"), "role": roles.get(c.get("doc_id")), "units": units})
    return {"data": out, "sources": [f"{c['doc_id']} {c['course_code']}" for c in matches[:3]]}


def list_analyses(_ctx, _args):
    latest = None
    try:
        latest = ks.latest_run_id()
    except ks.RunNotFound:
        pass
    jobs = analysis_jobs.jobs(limit=10)
    items = jobs.get("items") if isinstance(jobs, dict) else jobs
    return {"data": {"published_run": latest, "recent_jobs": [
        {k: j.get(k) for k in ("job_id", "status", "run_id", "created_at")} | {"document": j.get("document")}
        for j in items or []]}, "sources": ["analysis jobs"]}


def list_uploads(_ctx, _args):
    out = []
    for p in sorted(analysis_jobs.STAGED_DIR.glob("upl-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10] \
            if analysis_jobs.STAGED_DIR.exists() else []:
        up = analysis_jobs.upload(p.stem)
        if up:
            out.append({"upload_id": up["upload_id"], "file_name": up.get("file_name"), "role": up.get("document_role"),
                        "staged_at": up.get("staged_at"), "outcome": (up.get("outcome") or {}).get("outcome"),
                        **{k: (up.get("metadata") or {}).get(k) for k in ("institution", "programme", "discipline")}})
    return {"data": out, "sources": ["uploaded curricula"]}


# ---------------------------------------------------------------- action tools (confirmed by the user)
def start_analysis(_ctx, args):
    options = {"industry": bool(args.get("include_industry", True)), "peers": bool(args.get("include_peers", True))}
    job, err = analysis_jobs.start_job(str(args.get("upload_id") or ""), options=options)
    if err:
        raise ToolError(f"the analysis could not start: {err}")
    return {"data": {k: job.get(k) for k in ("job_id", "status", "upload_id")}, "sources": [f"job {job['job_id']}"]}


def _describe_start(args):
    up = analysis_jobs.upload(str(args.get("upload_id") or "")) or {}
    md = up.get("metadata") or {}
    what = " · ".join(x for x in (md.get("institution"), md.get("programme"), up.get("file_name")) if x) or args.get("upload_id")
    parts = ["industry evidence" if args.get("include_industry", True) else None,
             "peer comparison" if args.get("include_peers", True) else None]
    return f"Start an analysis of {what}" + (f" with {' and '.join(p for p in parts if p)}" if any(parts) else
                                             " (curriculum only)")


# ---------------------------------------------------------------- draft tools
def _save(ctx, draft):
    saved = ctx.store.save_draft(draft) if ctx.store else draft
    k = saved["checks"]
    summary = {"draft_id": saved.get("id"), "title": saved["title"], "kind": saved["kind"],
               "checks": {key: k[key] for key in k if key not in ("rejected_changes",)}}
    return {"data": summary, "sources": [f"draft {saved.get('id')}"], "draft_id": saved.get("id")}


def draft_course(ctx, args):
    skills = [s for s in (args.get("skills") or []) if isinstance(s, str)]
    return _save(ctx, syllabus.draft_course(ctx.model, ctx.run, args.get("title"), skills, args.get("level"),
                                            args.get("hours")))


def draft_programme(ctx, args):
    return _save(ctx, syllabus.draft_programme(ctx.model, ctx.run, args.get("discipline"), args.get("focus")))


def draft_revision(ctx, args):
    return _save(ctx, syllabus.draft_revision(ctx.model, ctx.run, args.get("course_code")))


def _course_draft(ctx, draft_id):
    if not draft_id:
        return None
    d = ctx.store.draft(str(draft_id)) if ctx.store else None
    if d is None or d.get("kind") != "course":
        raise ToolError(f"no course syllabus draft {draft_id}")
    return d["content"]


def draft_lesson_plan(ctx, args):
    source = _course_draft(ctx, args.get("draft_id"))
    if source is None and not args.get("course_code"):
        raise ToolError("give a course code of the analysed curriculum or the id of a course syllabus draft")
    return _save(ctx, syllabus.draft_lesson_plan(ctx.model, ctx.run, args.get("course_code"), source,
                                                 args.get("sessions"), args.get("minutes") or 50))


def find_resources(ctx, args):
    source = _course_draft(ctx, args.get("draft_id"))
    title = args.get("title") or (source or {}).get("title")
    topics = [t["text"] for u in (source or {}).get("units") or [] for t in u.get("topics") or []]
    if args.get("course_code") and not topics:
        course = get_course(ctx, {"course_code": args["course_code"]})["data"][0]
        title = title or course["title"]
        topics = [t for unit in course["units"].values() for t in unit]
    skills = [x for x in (args.get("skills") or []) if isinstance(x, str)]
    return _save(ctx, syllabus.draft_resources(ctx.model, ctx.run, title, skills, topics))


def registry():
    return {t.name: t for t in [
        Tool("analysis_overview", "read", "Summary of the current analysis: curriculum, job postings, gap counts, "
             "confirmed skill gaps, recommendation count.", _obj(), overview),
        Tool("list_skill_gaps", "read", "Skill gaps of the analysis, most demanded first. classification: PARTIAL, "
             "MISSING, COVERED or INSUFFICIENT_EVIDENCE. syllabus_relevance: CORE_CONTENT, SUPPORTING_CONTENT, "
             "PROFESSIONAL_PRACTICE, OTHER_FIELD or UNCLASSIFIED.",
             _obj({"confirmed_only": _BOOL, "classification": _STR, "syllabus_relevance": _STR, "limit": _INT}),
             skill_gaps),
        Tool("industry_demand", "read", "Skills most often asked for in the job postings, with counts.",
             _obj({"limit": _INT}), industry_demand),
        Tool("explain_skill", "read", "Evidence for one skill: demand, curriculum coverage, gap, and why it is or is "
             "not recommended.", _obj({"skill": _STR}, ["skill"]), explain_skill),
        Tool("list_recommendations", "read", "The recommendations the analysis issued.", _obj(), recommendations),
        Tool("search_curriculum", "read", "Find topics in a curriculum. role: TARGET (the analysed curriculum), "
             "REFERENCE or PEER.", _obj({"query": _STR, "role": _STR, "limit": _INT}, ["query"]), search_curriculum),
        Tool("get_course", "read", "A course's units and topics by course code.", _obj({"course_code": _STR},
                                                                                     ["course_code"]), get_course),
        Tool("list_analyses", "read", "The published analysis and recent analysis jobs.", _obj(), list_analyses),
        Tool("list_uploads", "read", "Uploaded curriculum files that can be analysed.", _obj(), list_uploads),
        Tool("start_analysis", "action", "Start an analysis of an uploaded curriculum (the user must confirm).",
             _obj({"upload_id": _STR, "include_industry": _BOOL, "include_peers": _BOOL}, ["upload_id"]),
             start_analysis, confirm_text=_describe_start),
        Tool("draft_course_syllabus", "draft", "Draft a course syllabus grounded in the analysis evidence. Give a "
             "title and/or skills (e.g. the confirmed gaps).", _obj({"title": _STR, "skills": {"type": "array",
                                                                     "items": _STR}, "level": _STR, "hours": _INT}),
             draft_course),
        Tool("draft_programme_structure", "draft", "Draft an 8-semester programme structure from the reference "
             "programme and the confirmed gaps.", _obj({"discipline": _STR, "focus": _STR}), draft_programme),
        Tool("draft_lesson_plan", "draft", "Draft a session-by-session lesson plan (objectives, activities, resources, "
             "assessment) for a course of the analysed curriculum (course_code) or a course syllabus draft (draft_id).",
             _obj({"course_code": _STR, "draft_id": _STR, "sessions": _INT, "minutes": _INT}), draft_lesson_plan),
        Tool("find_resources", "draft", "Collect learning resources for a course: textbooks and links printed in the "
             "curricula, curated documentation, websites and YouTube channels, checked online. Give a title, skills, a "
             "course_code or a course syllabus draft_id.",
             _obj({"title": _STR, "skills": {"type": "array", "items": _STR}, "course_code": _STR, "draft_id": _STR}),
             find_resources),
        Tool("propose_course_revision", "draft", "Propose additions, updates and removals for a course of the "
             "analysed curriculum.", _obj({"course_code": _STR}, ["course_code"]), draft_revision),
    ]}
