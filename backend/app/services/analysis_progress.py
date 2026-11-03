"""
Live progress of an analysis job, built ONLY from the pipeline's real stage events (RunObserver listener).

Phases are listed in the order the pipeline actually executes them, each tied to the agent it serves. Nothing is
estimated: there are no percentages and no completion is reported before the stage that produces it has ended. A
phase's state is one of

  PENDING       not reached yet
  RUNNING       one of its stages is running
  COMPLETED     its stages ended and a later phase has started (or the run finished)
  NEEDS_REVIEW  it completed, but its result needs a person (the analysed curriculum failed the document checks)
  FAILED        one of its stages raised an error
  NOT_RUN       the run finished without reaching it; the reason comes from the run's own gates
                (e.g. peer curricula were not available, or the curriculum failed its checks)
  NOT_REQUESTED the person left this capability out of the analysis (curriculum-only, or no peer comparison)

Counts shown with a step are the stage's own record (pages read, courses validated, postings read, ...); a document
step says "document k of n" where n is the number of documents the run verified.
"""
from datetime import datetime, timezone

PHASES = [
    {"id": "extraction", "label": "Reading the documents", "agent": None,
     "explains": "Each PDF is read page by page and its courses, units, topics and outcomes are recognised.",
     "stages": ("raw.verify", "bronze.extract", "silver.structure")},
    {"id": "skill_intelligence", "label": "Skill intelligence", "agent": "Skill Intelligence",
     "explains": "Job postings are read and the skills they ask for are identified and matched to ESCO.",
     "stages": ("industry.esco", "industry.silver", "industry.extract")},
    {"id": "curriculum_understanding", "label": "Curriculum understanding", "agent": "Curriculum Understanding",
     "explains": "Document checks, then the curriculum's concepts, reference mapping, prerequisites and changes.",
     "stages": ("health.gate", "gold.concepts", "gold.reference_mapping", "gold.prerequisites", "gold.skills",
                "gold.drift", "gold.programme_comparison")},
    {"id": "gap_reasoning", "label": "Skill-gap reasoning", "agent": "Skill-Gap Reasoning",
     "explains": "Industry demand is compared with what the curriculum teaches to classify each skill gap.",
     "stages": ("industry.gold",)},
    {"id": "recommendations", "label": "Recommendations", "agent": "Curriculum Recommendation",
     "explains": "Gaps are reasoned over again with coverage depth and turned into course-level recommendations.",
     "stages": ("intelligence",)},
    {"id": "peer_comparison", "label": "Peer comparison", "agent": None,
     "explains": "The curriculum is compared with the supplied peer and reference curricula.",
     "stages": ("peers.semantic_benchmark",)},
    {"id": "discipline_relevance", "label": "Discipline-to-industry relevance", "agent": "Discipline-to-Industry Relevance",
     "explains": "Postings are resolved to occupations and their relevance to the programme's discipline.",
     "stages": ("industry.v2",)},
    {"id": "finalisation", "label": "Finalising", "agent": None,
     "explains": "Results are checked, written as a new versioned analysis run and linked to the run before it.",
     "stages": ("gold.review_and_versioning", "evaluation", "gold.write", "publish.postgres", "lineage")},
]
_PHASE_OF = {stage: p["id"] for p in PHASES for stage in p["stages"]}
_ORDER = {p["id"]: i for i, p in enumerate(PHASES)}
# which gates explain a phase that never ran
_PHASE_GATES = {"skill_intelligence": ("industry_demand", "skill_taxonomy"), "gap_reasoning": ("industry_gap",),
                "recommendations": ("recommendations", "industry_gap"), "peer_comparison": ("peer_benchmark",),
                "discipline_relevance": ("industry_demand",)}
# stage-record keys worth showing as counts (all are the stage's own numbers)
_COUNT_KEYS = ("documents", "pages", "valid_courses", "units", "clean_topics", "noise_topics", "job_files",
               "skill_concepts", "records_read", "mentions_all", "unique_normalized_skills", "esco_mapped_skills",
               "demand_rows", "recommendations", "suppressed", "concepts", "families", "mappings", "edges",
               "gaps_v2", "peers", "occupations")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initial_phases():
    return [{"id": p["id"], "label": p["label"], "agent": p["agent"], "explains": p["explains"], "status": "PENDING",
             "started_at": None, "finished_at": None, "duration_s": 0.0, "steps": []} for p in PHASES]


def phase_of(stage):
    return _PHASE_OF.get(stage)


def _counts(record):
    out = {}
    for k in _COUNT_KEYS:
        v = record.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
    if record.get("cache"):
        out["cache"] = record["cache"]
    return out


class ProgressTracker:
    """Applies stage events to a job record (rec["phases"], rec["current"], rec["progress_seq"]) and persists it
    through save(rec) after every change. Never raises into the pipeline (RunObserver swallows listener errors)."""

    def __init__(self, rec, save):
        self.rec = rec
        self.save = save
        rec.setdefault("phases", initial_phases())
        rec.setdefault("progress_seq", 0)
        self.documents_total = None
        self.documents_done = 0

    def _phase(self, pid):
        return next(p for p in self.rec["phases"] if p["id"] == pid)

    def _close_earlier(self, pid, at):
        for p in self.rec["phases"]:
            if _ORDER[p["id"]] < _ORDER[pid] and p["status"] == "RUNNING":
                p["status"] = "COMPLETED"
                p["finished_at"] = p["finished_at"] or at

    def __call__(self, event, record):
        stage = record.get("stage")
        pid = phase_of(stage)
        if pid is None:
            return
        at = now()
        phase = self._phase(pid)
        if event == "start":
            self._close_earlier(pid, at)
            if phase["status"] in ("PENDING", "COMPLETED"):
                phase["status"] = "RUNNING"
                phase["started_at"] = phase["started_at"] or at
            step = {"stage": stage, "status": "RUNNING", "started_at": at, "finished_at": None, "duration_s": None}
            if record.get("doc_id"):
                step["doc_id"] = record["doc_id"]
                if stage == "bronze.extract" and self.documents_total:
                    step["detail"] = f"document {self.documents_done + 1} of {self.documents_total}"
            phase["steps"].append(step)
            self.rec["current"] = {"phase": pid, "label": phase["label"], "stage": stage,
                                   "detail": step.get("detail"), "since": at}
        else:
            step = next((s for s in reversed(phase["steps"]) if s["stage"] == stage and s["status"] == "RUNNING"), None)
            if step is None:
                return
            step["status"] = "FAILED" if record.get("status") == "ERROR" else "COMPLETED"
            step["finished_at"] = at
            step["duration_s"] = record.get("duration_s")
            counts = _counts(record)
            if counts:
                step["counts"] = counts
            if record.get("error"):
                step["error"] = str(record["error"])[:300]
                if stage != "lineage":  # the run exists without its lineage link (recorded as lineage_error)
                    phase["status"] = "FAILED"
            phase["duration_s"] = round(phase["duration_s"] + float(record.get("duration_s") or 0), 3)
            if stage == "raw.verify" and isinstance(record.get("documents"), int):
                self.documents_total = record["documents"]
            if stage == "bronze.extract":
                self.documents_done += 1
            if stage == "health.gate" and isinstance(record.get("documents"), dict):
                step["documents"] = record["documents"]
        self.rec["progress_seq"] += 1
        self.rec["updated_at"] = at
        self.save(self.rec)

    def stage(self, name, fn):
        """Run a job-level step (e.g. lineage) through the same events."""
        record = {"stage": name}
        self("start", record)
        try:
            result = fn()
            self("end", {**record, "status": "OK"})
            return result
        except Exception as exc:
            self("end", {**record, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
            raise


def finish(rec, gates=None, target_failed=None, failed=False):
    """Close every phase when the job ends: running phases complete (or fail with the job), unreached phases become
    NOT_RUN with the gate reason that explains them, and the curriculum phase needs review when the analysed
    curriculum failed the document checks."""
    at = now()
    gates = gates or {}
    for p in rec.get("phases") or []:
        if p["status"] == "RUNNING":
            p["status"] = "FAILED" if failed else "COMPLETED"
            p["finished_at"] = p["finished_at"] or at
        elif p["status"] == "PENDING":
            p["status"] = "NOT_RUN"
            reasons = []
            for g in _PHASE_GATES.get(p["id"], ()):
                gate = gates.get(g) or {}
                if gate.get("status") in ("BLOCKED", "NOT_REQUESTED", "NOT_APPLICABLE"):
                    reasons.extend(gate.get("reasons") or [])
            p["reason"] = (reasons[0] if reasons else
                           "the analysis stopped before this step" if failed else "not needed for this analysis")
            if any((gates.get(g) or {}).get("status") == "NOT_REQUESTED" for g in _PHASE_GATES.get(p["id"], ())):
                p["status"] = "NOT_REQUESTED"
        if p["id"] == "curriculum_understanding" and target_failed and p["status"] == "COMPLETED":
            p["status"] = "NEEDS_REVIEW"
            p["reason"] = target_failed
    rec["current"] = None
    rec["progress_seq"] = rec.get("progress_seq", 0) + 1
    rec["updated_at"] = at
    return rec
