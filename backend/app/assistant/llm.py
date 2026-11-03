"""
Local chat model for the assistant.

OllamaChat talks to Ollama's /api/chat. Models that support tools get Ollama's native tool calling; for a model that
does not (Ollama answers "does not support tools"), the same tools are described in the system prompt and the model
answers with one JSON object, {"tool": name, "arguments": {...}} or {"answer": "..."}. Either way the agent receives
the same shape: {"content": str, "tool_calls": [{"name": str, "arguments": dict}]}.

Configuration: ASSISTANT_MODEL (default: the first semantic_ai provider's model in engine_config.json),
OLLAMA_HOST (default http://127.0.0.1:11434), ASSISTANT_TIMEOUT seconds (default 300).
"""
import json
import os
import re
import urllib.error
import urllib.request


class ModelUnavailable(RuntimeError):
    pass


def default_settings():
    from app.knowledge_engine.config import load_config
    providers = (load_config().get("semantic_ai") or {}).get("providers") or []
    first = next((p for p in providers if p.get("kind") == "ollama"), {})
    return {
        "base_url": (os.environ.get("OLLAMA_HOST") or first.get("base_url") or "http://127.0.0.1:11434").rstrip("/"),
        "model": os.environ.get("ASSISTANT_MODEL") or first.get("model") or "qwen2.5:7b-instruct",
        "timeout": float(os.environ.get("ASSISTANT_TIMEOUT") or 300),
    }


def _extract_json(text):
    """The first JSON object in a model reply (models sometimes wrap it in prose or ``` fences)."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in the reply")


class OllamaChat:
    kind = "ollama"

    def __init__(self, base_url=None, model=None, timeout=None):
        s = default_settings()
        self.base_url = (base_url or s["base_url"]).rstrip("/")
        self.model = model or s["model"]
        self.timeout = timeout or s["timeout"]
        self.native_tools = True  # switched off for the session when the model reports it has no tool support

    def describe(self):
        return {"provider": "ollama", "model": self.model, "base_url": self.base_url,
                "tool_calling": "native" if self.native_tools else "json_protocol"}

    def _request(self, path, payload=None, timeout=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:500]
            raise ModelUnavailable(f"HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ModelUnavailable(f"the model service at {self.base_url} could not be reached ({exc})") from exc

    def status(self):
        """Is the service running, is the model installed, does it support tools? Never raises."""
        out = {**self.describe(), "service": "UNREACHABLE", "installed": False, "tools": None, "installed_models": []}
        try:
            tags = self._request("/api/tags", timeout=3)
        except ModelUnavailable as exc:
            out["reason"] = str(exc)
            return out
        names = [m.get("name") for m in tags.get("models") or []]
        out.update(service="RUNNING", installed_models=names,
                   installed=self.model in names or f"{self.model}:latest" in names)
        if out["installed"]:
            try:
                caps = self._request("/api/show", {"model": self.model}, timeout=5).get("capabilities")
                out["tools"] = ("tools" in caps) if isinstance(caps, list) else None
            except ModelUnavailable:
                pass
        else:
            out["reason"] = f"model {self.model} is not installed: run `ollama pull {self.model}`"
        return out

    def chat(self, messages, tools=None, json_schema=None, temperature=0.2):
        """{"content": str, "tool_calls": [{"name", "arguments"}]}. json_schema constrains the reply (no tools)."""
        payload = {"model": self.model, "messages": messages, "stream": False, "options": {"temperature": temperature}}
        if json_schema is not None:
            payload["format"] = json_schema
        if tools and self.native_tools and json_schema is None:
            try:
                msg = self._request("/api/chat", {**payload, "tools": [
                    {"type": "function", "function": t} for t in tools]})["message"]
            except ModelUnavailable as exc:
                if "does not support tools" not in str(exc):
                    raise
                self.native_tools = False
            else:
                calls = [{"name": c["function"]["name"], "arguments": c["function"].get("arguments") or {}}
                         for c in msg.get("tool_calls") or [] if c.get("function")]
                for c in calls:
                    if isinstance(c["arguments"], str):
                        try:
                            c["arguments"] = json.loads(c["arguments"])
                        except ValueError:
                            c["arguments"] = {}
                return {"content": msg.get("content") or "", "tool_calls": calls}
        if tools and json_schema is None:
            return self._chat_json_protocol(payload, tools)
        msg = self._request("/api/chat", payload)["message"]
        return {"content": msg.get("content") or "", "tool_calls": []}

    def _chat_json_protocol(self, payload, tools):
        catalogue = "\n".join(f"- {t['name']}: {t['description']} Arguments (JSON schema): "
                              f"{json.dumps(t['parameters'])}" for t in tools)
        instruction = ("You can call tools. Reply with exactly ONE JSON object and nothing else: either "
                       '{"tool": "<name>", "arguments": {...}} to call a tool, or {"answer": "<your reply>"} '
                       "when you can answer. Tools:\n" + catalogue)
        def plain(m):
            # in this protocol tool calls are the model's own JSON replies and tool results are user turns
            if m["role"] == "tool":
                return {"role": "user", "content": f"Tool result: {m['content']}"}
            if m["role"] == "assistant" and m.get("tool_calls"):
                f = m["tool_calls"][0]["function"]
                return {"role": "assistant", "content": json.dumps({"tool": f["name"], "arguments": f["arguments"]})}
            return {"role": m["role"], "content": m.get("content") or ""}
        messages = [{"role": "system", "content": instruction}] + [plain(m) for m in payload["messages"]]
        msg = self._request("/api/chat", {**payload, "messages": messages, "format": "json"})["message"]
        try:
            obj = _extract_json(msg.get("content"))
        except ValueError:
            return {"content": msg.get("content") or "", "tool_calls": []}
        if isinstance(obj.get("tool"), str):
            args = obj.get("arguments") if isinstance(obj.get("arguments"), dict) else {}
            return {"content": "", "tool_calls": [{"name": obj["tool"], "arguments": args}]}
        return {"content": str(obj.get("answer") or ""), "tool_calls": []}
