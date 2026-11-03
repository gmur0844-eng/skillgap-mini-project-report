"""Conversations, pending actions and drafts, as JSON files under data/assistant/ (git-ignored, machine-local)."""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "data/assistant"
_ID = re.compile(r"^(conv|draft|act)-[0-9a-f]{12}$")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def valid_id(value, prefix):
    return isinstance(value, str) and bool(_ID.match(value)) and value.startswith(prefix + "-")


class Store:
    def __init__(self, root=None):
        self.root = Path(root or ROOT)

    def _path(self, kind, item_id):
        return self.root / kind / f"{item_id}.json"

    def _write(self, kind, item):
        p = self._path(kind, item["id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(item, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return item

    def _read(self, kind, item_id):
        try:
            return json.loads(self._path(kind, item_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _list(self, kind, limit=50):
        d = self.root / kind
        items = []
        for p in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit] if d.exists() else []:
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return items

    # conversations
    def new_conversation(self, run_id=None, title=None):
        return self._write("conversations", {"id": new_id("conv"), "title": title or "New conversation",
                                             "run_id": run_id, "created_at": now(), "updated_at": now(),
                                             "messages": [], "turns": [], "pending_action": None})

    def conversation(self, conv_id):
        return self._read("conversations", conv_id) if valid_id(conv_id, "conv") else None

    def save_conversation(self, conv):
        conv["updated_at"] = now()
        return self._write("conversations", conv)

    def conversations(self, limit=50):
        return [{k: c.get(k) for k in ("id", "title", "run_id", "created_at", "updated_at")} for c in
                self._list("conversations", limit)]

    # drafts
    def save_draft(self, draft):
        draft.setdefault("id", new_id("draft"))
        draft.setdefault("created_at", now())
        return self._write("drafts", draft)

    def draft(self, draft_id):
        return self._read("drafts", draft_id) if valid_id(draft_id, "draft") else None

    def drafts(self, limit=50):
        return [{k: d.get(k) for k in ("id", "kind", "title", "created_at", "run_id", "model")} for d in
                self._list("drafts", limit)]
