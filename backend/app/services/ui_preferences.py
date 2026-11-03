"""
Appearance of the web application (the Appearance panel): which of the two visual designs is shown and in which
mode, and which design has been finalised. Stored in data/metadata/ui_preferences.json so the choice survives page
reloads and is the same on every device. It has no effect on any analysis.

  {"version": "v1" | "v2" | null, "theme": "dark" | "light" | null, "finalised": "v1" | "v2" | null,
   "finalised_at": ISO time | null, "updated_at": ISO time | null}
"""
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PATH = REPO / "data/metadata/ui_preferences.json"
VERSIONS = ("v1", "v2")
THEMES = ("dark", "light")
DEFAULT = {"version": None, "theme": None, "finalised": None, "finalised_at": None, "updated_at": None}
_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(path=None):
    p = Path(path or PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT)
    out = dict(DEFAULT)
    out.update({k: data.get(k) for k in DEFAULT})
    return out


def update(change, path=None):
    """Apply {"version"?, "theme"?, "finalise"?: bool, "clear_final"?: bool}; returns (record, error)."""
    change = change if isinstance(change, dict) else {}
    version, theme = change.get("version"), change.get("theme")
    if version is not None and version not in VERSIONS:
        return None, f"version must be one of {', '.join(VERSIONS)}"
    if theme is not None and theme not in THEMES:
        return None, f"theme must be one of {', '.join(THEMES)}"
    p = Path(path or PATH)
    with _lock:
        rec = read(p)
        if version is not None:
            rec["version"] = version
        if theme is not None:
            rec["theme"] = theme
        if change.get("clear_final") is True:
            rec["finalised"], rec["finalised_at"] = None, None
        if change.get("finalise") is True:
            if rec["version"] is None:
                return None, "choose a version before finalising"
            rec["finalised"], rec["finalised_at"] = rec["version"], _now()
        rec["updated_at"] = _now()
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".ui_preferences.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
        os.replace(tmp, p)
    return rec, None
