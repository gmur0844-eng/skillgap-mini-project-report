"""
/api/v1/assistant: the conversational agent and syllabus drafting (app/assistant).

  GET  /status                                   is the local model running and installed?
  GET  /conversations, POST /conversations       list / start (optionally on a given analysis run)
  GET  /conversations/{id}                       the turns (with tool trace, sources, warnings, pending action)
  POST /conversations/{id}/messages              {"text"} -> the turn (synchronous; a local model takes seconds)
  POST /conversations/{id}/actions/{action_id}   {"approve": true|false} -> runs or cancels the pending action
  POST /drafts                                   {"kind": course|programme|revision|lesson_plan|resources, ...}
                                                 -> a draft, without chat
  GET  /drafts, /drafts/{id}, /drafts/{id}/markdown
"""
from fastapi import APIRouter, Body
from fastapi.responses import PlainTextResponse

from app.assistant import agent, syllabus, tools
from app.assistant.llm import ModelUnavailable, OllamaChat
from app.assistant.store import Store
from app.assistant.tools import Context
from app.core.errors import ApiError
from app.services import knowledge_service as ks

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

# replaced in tests
model_factory = OllamaChat
store = Store()


def _conv(conv_id):
    conv = store.conversation(conv_id)
    if conv is None:
        raise ApiError(404, "NOT_FOUND", f"no conversation {conv_id!r}")
    return conv


def _public(conv):
    return {k: conv.get(k) for k in ("id", "title", "run_id", "created_at", "updated_at", "turns", "pending_action")}


def _check_run(run_id):
    if run_id is None:
        return None
    try:
        return ks.load_run(run_id).run_id
    except ks.InvalidRunId as exc:
        raise ApiError(400, "INVALID_RUN_ID", str(exc)) from exc
    except ks.RunNotFound as exc:
        raise ApiError(404, ks.not_found_code(exc), str(exc)) from exc


@router.get("/status")
def status():
    s = model_factory().status()
    ready = s["service"] == "RUNNING" and s["installed"]
    return {**s, "ready": ready, "how_to_fix": None if ready else (
        "Install Ollama (https://ollama.com), start it, and run `ollama pull " + s["model"] + "`. Another model: set "
        "ASSISTANT_MODEL before starting the server.")}


@router.get("/conversations")
def conversations():
    return {"items": store.conversations()}


@router.post("/conversations")
def new_conversation(body: dict = Body(default={})):  # noqa: B008
    return _public(store.new_conversation(run_id=_check_run((body or {}).get("run_id"))))


@router.get("/conversations/{conv_id}")
def conversation(conv_id: str):
    return _public(_conv(conv_id))


@router.post("/conversations/{conv_id}/messages")
def send(conv_id: str, body: dict = Body(...)):  # noqa: B008
    conv = _conv(conv_id)
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise ApiError(422, "EMPTY_MESSAGE", "the message is empty")
    if len(text) > 4000:
        raise ApiError(422, "MESSAGE_TOO_LONG", "the message is longer than 4000 characters")
    model = model_factory()
    turn = agent.run_turn(conv, text, model, Context(conv.get("run_id"), model, store))
    store.save_conversation(conv)
    return {"turn": turn, "conversation": _public(conv)}


@router.post("/conversations/{conv_id}/actions/{action_id}")
def decide(conv_id: str, action_id: str, body: dict = Body(...)):  # noqa: B008
    conv = _conv(conv_id)
    approve = (body or {}).get("approve")
    if not isinstance(approve, bool):
        raise ApiError(422, "INVALID_DECISION", "approve must be true or false")
    model = model_factory()
    turn = agent.confirm_action(conv, action_id, approve, Context(conv.get("run_id"), model, store))
    if turn is None:
        raise ApiError(409, "NO_PENDING_ACTION", "this action is not pending (it was decided or has lapsed)")
    store.save_conversation(conv)
    return {"turn": turn, "conversation": _public(conv)}


@router.post("/drafts")
def create_draft(body: dict = Body(...)):  # noqa: B008
    body = body or {}
    kind = body.get("kind")
    run_id = _check_run(body.get("run_id"))
    model = model_factory()
    try:
        run = ks.load_run(run_id)
    except ks.RunNotFound as exc:
        raise ApiError(404, ks.not_found_code(exc), str(exc)) from exc
    try:
        if kind == "course":
            skills = [s for s in body.get("skills") or [] if isinstance(s, str) and s.strip()]
            draft = syllabus.draft_course(model, run, body.get("title"), skills, body.get("level"), body.get("hours"))
        elif kind == "programme":
            draft = syllabus.draft_programme(model, run, body.get("discipline"), body.get("focus"))
        elif kind == "revision":
            draft = syllabus.draft_revision(model, run, body.get("course_code"))
        elif kind in ("lesson_plan", "resources"):
            ctx = Context(run.run_id, model, store)
            ctx._run = run
            result = (tools.draft_lesson_plan if kind == "lesson_plan" else tools.find_resources)(ctx, body)
            return store.draft(result["draft_id"])
        else:
            raise ApiError(422, "INVALID_KIND", "kind must be course, programme, revision, lesson_plan or resources")
    except (syllabus.DraftError, tools.ToolError) as exc:
        raise ApiError(422, "DRAFT_NOT_POSSIBLE", str(exc)) from exc
    except ModelUnavailable as exc:
        raise ApiError(503, "MODEL_UNAVAILABLE", str(exc)) from exc
    return store.save_draft(draft)


@router.get("/drafts")
def drafts():
    return {"items": store.drafts()}


@router.get("/drafts/{draft_id}")
def draft(draft_id: str):
    d = store.draft(draft_id)
    if d is None:
        raise ApiError(404, "NOT_FOUND", f"no draft {draft_id!r}")
    return d


@router.get("/drafts/{draft_id}/markdown", response_class=PlainTextResponse)
def draft_markdown(draft_id: str):
    d = draft(draft_id)
    return PlainTextResponse(syllabus.to_markdown(d), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{draft_id}.md"'})
