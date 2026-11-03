"""
The agent loop: the model reads the conversation, calls tools, and answers.

* read and draft tools run at once; their results go back to the model
* an action tool never runs from the model's request: it becomes the conversation's pending action, the turn ends
  with a request for confirmation, and only confirm_action() (the user's click) runs it
* every figure in the final answer is checked against the tool results of the turn and the user's own message;
  figures found nowhere are reported with the answer ("not found in the analysis data")
"""
import json
import re

from app.assistant import store as store_mod
from app.assistant.llm import ModelUnavailable
from app.assistant.syllabus import DraftError
from app.assistant.tools import ToolError, registry
from app.services.knowledge_service import RunNotFound

MAX_STEPS = 6
HISTORY = 24          # model-facing messages kept from earlier turns
RESULT_CHARS = 6000   # a tool result is truncated to this for the model (the user sees the sources)

SYSTEM = """You are the curriculum analysis assistant of a university skill-gap application.
Rules:
- Facts about this analysis (job-posting counts, skill gaps, courses, recommendations) come ONLY from tool results.
  Call a tool before answering such a question. Never invent or estimate numbers.
- If the tools do not have the answer, say so plainly.
- To draft a syllabus, programme structure or course revision, call the matching draft tool; then summarise the draft
  in a few sentences and say it is an AI-generated draft for faculty review.
- start_analysis changes data: call it only when the user asks to start an analysis; the user confirms it in the app.
- "Confirmed gap" means partial or missing coverage of a skill with supported industry demand.
- Each skill has a syllabus relevance: CORE_CONTENT (teach as topics), SUPPORTING_CONTENT (a neighbouring field),
  PROFESSIONAL_PRACTICE (develop through projects and team work, not as topics), OTHER_FIELD (another field: an
  elective at most). Say this when you recommend what to add to a syllabus.
- Be concise. Use the user's words. Mention which analysis or course an answer comes from."""

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(%?)")


def _figures(text):
    """Figures worth checking: two or more digits, a decimal, or a percentage (not 'unit 3' or '2 courses')."""
    out = set()
    for num, pct in _NUM.findall(text or ""):
        n = num.replace(",", "")
        if pct or "." in n or len(n) >= 2:
            out.add(n)
    return out


def ungrounded_figures(answer, evidence_texts):
    pool = set()
    for t in evidence_texts:
        pool |= {m.replace(",", "") for m, _ in _NUM.findall(t or "")}
    return sorted(f for f in _figures(answer) if f not in pool and f.rstrip("0").rstrip(".") not in pool)


def _tool_message(content):
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    return {"role": "tool", "content": text[:RESULT_CHARS]}


def _run_tool(tool, args, ctx):
    try:
        return tool.fn(ctx, args or {}), None
    except (ToolError, DraftError, RunNotFound, ModelUnavailable, ValueError, KeyError, TypeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def run_turn(conv, text, model, ctx, tools=None, store=None):
    """Runs one user turn; updates conv (not saved here). Returns the turn record."""
    tools = tools or registry()
    specs = [t.spec() for t in tools.values()]
    text = (text or "").strip()
    turn = {"at": store_mod.now(), "user": text, "reply": "", "tool_trace": [], "sources": [], "draft_ids": [],
            "warnings": [], "pending_action": None}
    if conv.get("pending_action"):
        # a new message instead of confirming: the pending action lapses
        turn["warnings"].append(f"the pending action was not confirmed and has lapsed: "
                                f"{conv['pending_action']['description']}")
        conv["pending_action"] = None
    history = conv.get("messages") or []
    new = [{"role": "user", "content": text}]
    evidence_texts = [text]
    reply = None
    try:
        for _ in range(MAX_STEPS):
            resp = model.chat([{"role": "system", "content": SYSTEM}] + history[-HISTORY:] + new, tools=specs)
            calls = resp.get("tool_calls") or []
            if not calls:
                reply = (resp.get("content") or "").strip()
                break
            new.append({"role": "assistant", "content": resp.get("content") or "",
                        "tool_calls": [{"function": {"name": c["name"], "arguments": c.get("arguments") or {}}}
                                       for c in calls]})
            stop = False
            for c in calls:
                tool = tools.get(c["name"])
                entry = {"tool": c["name"], "arguments": c.get("arguments") or {}, "kind": tool.kind if tool else None}
                if tool is None:
                    entry["error"] = "unknown tool"
                    new.append(_tool_message(f"error: there is no tool named {c['name']}"))
                elif tool.kind == "action":
                    action = {"id": store_mod.new_id("act"), "tool": tool.name, "arguments": entry["arguments"],
                              "description": tool.confirm_text(entry["arguments"]) if tool.confirm_text else tool.name,
                              "created_at": store_mod.now()}
                    conv["pending_action"] = turn["pending_action"] = action
                    entry["status"] = "AWAITING_CONFIRMATION"
                    new.append(_tool_message("waiting for the user to confirm this action in the app"))
                    stop = True
                else:
                    result, error = _run_tool(tool, entry["arguments"], ctx)
                    if error:
                        entry["error"] = error
                        new.append(_tool_message(f"error: {error}"))
                    else:
                        entry["sources"] = result.get("sources") or []
                        turn["sources"] += entry["sources"]
                        if result.get("draft_id"):
                            turn["draft_ids"].append(result["draft_id"])
                        msg = _tool_message(result.get("data"))
                        evidence_texts.append(msg["content"])
                        new.append(msg)
                turn["tool_trace"].append(entry)
            if stop:
                reply = f"I need your confirmation to: {turn['pending_action']['description']}."
                break
        if reply is None:
            reply = "I could not finish this within the allowed number of steps. Try a more specific question."
    except ModelUnavailable as exc:
        reply = None
        turn["error"] = {"code": "MODEL_UNAVAILABLE", "message": str(exc)}
    if reply is not None:
        if not turn["pending_action"]:
            missing = ungrounded_figures(reply, evidence_texts)
            if missing:
                turn["warnings"].append("figures not found in the analysis data: " + ", ".join(missing))
        new.append({"role": "assistant", "content": reply})
        turn["reply"] = reply
        conv["messages"] = history + new
    conv.setdefault("turns", []).append(turn)
    if conv.get("title") in (None, "", "New conversation") and text:
        conv["title"] = text[:60] + ("…" if len(text) > 60 else "")
    return turn


def confirm_action(conv, action_id, approve, ctx, tools=None):
    """The user's decision on the pending action. Returns the turn record, or None when no such action is pending."""
    tools = tools or registry()
    pending = conv.get("pending_action")
    if not pending or pending.get("id") != action_id:
        return None
    conv["pending_action"] = None
    turn = {"at": store_mod.now(), "user": None, "action": pending, "tool_trace": [], "sources": [], "draft_ids": [],
            "warnings": []}
    if not approve:
        turn["reply"] = f"Cancelled: {pending['description']}."
    else:
        result, error = _run_tool(tools[pending["tool"]], pending["arguments"], ctx)
        entry = {"tool": pending["tool"], "arguments": pending["arguments"], "kind": "action", "confirmed": True}
        if error:
            entry["error"] = error
            turn["reply"] = f"That did not work: {error}"
        else:
            entry["sources"] = result.get("sources") or []
            turn["sources"] = entry["sources"]
            data = result.get("data") or {}
            turn["reply"] = (f"Done: {pending['description']}. Job {data.get('job_id')} is "
                             f"{str(data.get('status') or '').lower() or 'running'}; follow it under History.")
        turn["tool_trace"].append(entry)
    conv.setdefault("messages", []).append({"role": "assistant", "content": turn["reply"]})
    conv.setdefault("turns", []).append(turn)
    return turn
