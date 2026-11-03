"""
Learning resources for a course, from three kinds of source, each with an honest status:

  LISTED_IN_CURRICULUM  a textbook or link printed in a curriculum of the run (reference, peer or the analysed one),
                        read from the course's own pages (bronze page text), with page provenance
  CURATED               an entry of data/metadata/learning_resources.json (official documentation, open course
                        platforms, well-known channels), chosen by the code by topic
  MODEL_SUGGESTION      proposed by the model; then checked online when the machine is online:
                          books  -> Open Library search (FOUND_IN_OPEN_LIBRARY / NOT_FOUND_IN_OPEN_LIBRARY)
                          links  -> an HTTP request (LINK_OK / LINK_NOT_FOUND)
                        NOT_CHECKED when offline or RESOURCE_CHECK=off. A link that does not exist is removed.

Nothing here is an analysis result; the drafts that use it say so.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CATALOGUE = REPO / "data/metadata/learning_resources.json"
BRONZE = REPO / "data/bronze/curricula"
USER_AGENT = "skill-gap-curriculum-assistant/1.0 (resource link check)"

_HEADING = re.compile(r"(?im)^\s*(?:suggested\s+)?(?:text\s*-?\s*books?|reference\s*books?|references|"
                      r"suggested\s+(?:reading|books)|recommended\s+books|books|online\s+resources|web\s*links?|"
                      r"e-?resources)\b[^\n]{0,60}$")
_STOP = re.compile(r"(?im)^\s*(?:course\s+(?:outcomes?|objectives?|code|title)|unit\s*[-–]?\s*[ivx\d]+|module\s*\d|"
                   r"the\s+discipline\s+graduate|other\s+discipline|semester\s+[ivx]+|co\s*\d|list\s+of\s+experiments)")
_TRAILING_HEADING = re.compile(r"\s+(?:suggested\s+reading|online\s+resources|text\s*books?|reference\s*books?|"
                               r"web\s*links?|e-?resources|references)\s*:?\s*$", re.I)
_BROKEN_URL = re.compile(r"(https?://\S*[-_])[ \t]*\n[ \t]*(?=[a-z0-9%~#?=&./-])(?![a-z0-9]{1,4}[.)]\s)")
_ITEM = re.compile(r"^\s*(?:\d{1,2}|[ivx]{1,4}|[a-h])[.)]\s+")
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_BOOKISH = re.compile(r"\b(?:19|20)\d\d\b|edition|\bed\.|press|publish|wiley|mcgraw|pearson|springer|o'?reilly|"
                      r"prentice|elsevier|cengage|oxford|cambridge|morgan|addison|packt|manning|phi\b|tata", re.I)


@lru_cache(maxsize=16)
def _pages(sha16):
    d = BRONZE / sha16
    files = sorted(d.glob("pages.*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))["pages"]
    except (OSError, ValueError, KeyError):
        return None


def _entries(block):
    """Numbered entries of a list block; continuation lines are joined to their entry."""
    items, cur = [], None
    for line in block.splitlines():
        if not line.strip():
            continue
        if _ITEM.match(line):
            if cur:
                items.append(cur)
            cur = _ITEM.sub("", line).strip()
        elif cur is not None:
            cur += " " + line.strip()
    if cur:
        items.append(cur)
    return [_TRAILING_HEADING.sub("", re.sub(r"\s+", " ", i)).strip(" ;,.") for i in items]


def course_resources(run, course, max_pages=4):
    """Books and links listed under a resources heading (text books, references, online resources...) on the course's
    pages and the following ones (a syllabus ends where the next course starts)."""
    pages = _pages((course.get("source_sha256") or "")[:16])
    if not pages:
        return []
    start = max(course.get("pages") or [course.get("first_page") or 1])
    out, seen = [], set()
    for pno in range(start, min(start + max_pages, len(pages) + 1)):
        text = _BROKEN_URL.sub(r"\1", pages[pno - 1])  # a link broken across two lines is one link
        for m in _HEADING.finditer(text):
            rest = text[m.end():]
            stop = _STOP.search(rest)
            block = rest[:stop.start()] if stop else rest[:3000]
            for e in _entries(block)[:15]:
                for url in _URL.findall(e):
                    url = url.rstrip(".,;")
                    if url not in seen:
                        seen.add(url)
                        out.append({"type": "web_link", "url": url, "text": e[:200], "page": pno})
                if not _URL.search(e) and 20 <= len(e) <= 300 and _BOOKISH.search(e) and e not in seen:
                    seen.add(e)
                    out.append({"type": "book", "text": e, "page": pno})
    roles = {d.get("doc_id"): d.get("role") for d in run.report.get("documents") or []}
    for o in out:
        o.update(doc_id=course.get("doc_id"), role=roles.get(course.get("doc_id")), course_code=course.get("course_code"),
                 course_title=course.get("title"), status="LISTED_IN_CURRICULUM")
    return out


def curriculum_resources(run, query, courses=4):
    """Resources printed in the curricula for the courses most similar to the query."""
    from app.assistant.syllabus import _rank
    candidates = [c for c in run.courses.values() if c.get("title")]
    ranked = _rank(query, candidates, lambda c: c.get("title") or "", courses)
    out = []
    for c, _score in ranked:
        out += course_resources(run, c)
    return out


@lru_cache(maxsize=1)
def catalogue():
    try:
        return json.loads(CATALOGUE.read_text(encoding="utf-8"))["resources"]
    except (OSError, ValueError, KeyError):
        return []


def curated(query, limit=10):
    from app.assistant.syllabus import _rank
    items = catalogue()
    ranked = _rank(query, items, lambda r: " ".join([r.get("title", ""), " ".join(r.get("tags", [])),
                                                       r.get("note", "")]), limit)
    general = [r for r in items if "general" in r.get("tags", [])]
    out = [dict(r, status="CURATED") for r, _ in ranked]
    ids = {r["id"] for r in out}
    out += [dict(r, status="CURATED") for r in general if r["id"] not in ids][:3]
    return out


# ---------------------------------------------------------------- online checks
def checks_enabled():
    return (os.environ.get("RESOURCE_CHECK") or "").strip().lower() not in ("off", "0", "false", "no")


def check_link(url, timeout=6):
    if not url or not re.match(r"^https?://", url):
        return {"check": "LINK_NOT_FOUND", "detail": "not a web address"}
    if not checks_enabled():
        return {"check": "NOT_CHECKED", "detail": "checks are switched off (RESOURCE_CHECK=off)"}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {"check": "LINK_OK", "detail": f"HTTP {r.status}", "final_url": r.geturl()}
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                return {"check": "LINK_NOT_FOUND", "detail": f"HTTP {exc.code}"}
            if method == "GET":
                return {"check": "NOT_CHECKED", "detail": f"HTTP {exc.code}"}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            if "Name or service not known" in str(reason) or "nodename nor servname" in str(reason):
                return {"check": "LINK_NOT_FOUND", "detail": "the site does not exist"}
            return {"check": "NOT_CHECKED", "detail": f"could not be reached ({type(exc).__name__})"}
    return {"check": "NOT_CHECKED", "detail": "no answer"}


def check_book(title, authors="", timeout=8):
    if not checks_enabled():
        return {"check": "NOT_CHECKED", "detail": "checks are switched off (RESOURCE_CHECK=off)"}
    q = {"title": title, "limit": "1", "fields": "title,author_name,first_publish_year,key"}
    if authors:
        q["author"] = authors.split(",")[0].strip()
    url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        return {"check": "NOT_CHECKED", "detail": f"Open Library could not be reached ({type(exc).__name__})"}
    docs = data.get("docs") or []
    if not docs:
        return {"check": "NOT_FOUND_IN_OPEN_LIBRARY", "detail": "no matching record"}
    d = docs[0]
    return {"check": "FOUND_IN_OPEN_LIBRARY", "detail": f"{d.get('title')} — {', '.join(d.get('author_name') or [])}"
                                                         f" ({d.get('first_publish_year') or 'year unknown'})",
            "record": f"https://openlibrary.org{d.get('key')}" if d.get("key") else None}


def check_all(items, workers=8):
    """Adds item["check"] to model suggestions and curated links (in parallel). Books listed in a curriculum are
    printed evidence and are not looked up."""
    def one(it):
        if it.get("status") == "LISTED_IN_CURRICULUM" and it.get("kind") == "book":
            return {"check": "NOT_NEEDED", "detail": "printed in the curriculum"}
        if it.get("kind") == "book":
            return check_book(it.get("title") or "", it.get("authors") or "")
        return check_link(it.get("url"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, items))
    for it, res in zip(items, results):
        it["check"] = res
    return items
