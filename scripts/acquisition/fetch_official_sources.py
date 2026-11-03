#!/usr/bin/env python3
"""
Fetch evidence from OFFICIAL sources only (data/metadata/official_sources.json) into the drop folders.

  python3 scripts/acquisition/fetch_official_sources.py [--peers] [--jobs] [--snapshot-date YYYY-MM-DD] [--dry-run]

  peers  downloads the institution's own curriculum PDF to data/raw/curricula/incoming/<file>
  jobs   reads each employer's own job board through its ATS's documented public read API (Greenhouse Job Board API,
         Lever Postings API, Ashby Job Postings API, SmartRecruiters Posting API; no key, no login), keeps postings
         located in India, and writes one CSV per board to data/raw/jobs/incoming/ in the pipeline's posting layout
  --discover  checks the candidate boards in data/metadata/job_board_candidates.json and reports which answer with
         postings located in India; --add-verified also adds those to official_sources.json (with verified_on)

Every file gets a <file>.source.json sidecar (source URL, licence note, retrieval time, SHA-256, what was kept and
why). Nothing here is analysed: `scripts/acquisition/acquire_evidence.py --register --manifest <copy>` registers the
files in a manifest copy and the pipeline ingests them through its normal gates.

Rules enforced here:
* the posting date comes ONLY from the source (Greenhouse first_published, Lever createdAt); a posting without one is
  written with an empty date (UNDATED), never given one;
* nothing is inferred that the source does not state (no industry, no seniority, no country guessed beyond the
  location text the employer published);
* requests are sequential with a pause (request_interval_seconds) and an identifying User-Agent;
* a board that fails is recorded with its reason and skipped -- the run never fails because one source is down.
Standard library only, so it runs with any Python 3.9+.
"""
import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "data/metadata/official_sources.json"
JOBS_DIR = ROOT / "data/raw/jobs/incoming"
CURRICULA_DIR = ROOT / "data/raw/curricula/incoming"
REPORT = ROOT / "artifacts/acquisition/official_sources_report.json"

# the pipeline's posting column layout (backend/app/knowledge_engine/jobs.py COLUMN_MAP keys)
COLUMNS = ["job_title", "url", "source_url", "posted_date", "job_country_code", "is_remote", "employment_status",
           "seniority", "job_location", "job_description", "salary", "company_name", "company_industry",
           "company_employee_count"]

_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|li|ul|ol|br|h[1-6]|tr)[^>]*>", re.I)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def html_to_text(s):
    """Greenhouse 'content' is HTML that is itself entity-escaped; Lever list items are HTML."""
    if not s:
        return ""
    text = html.unescape(html.unescape(s))
    text = _BLOCK.sub("\n", text)
    text = html.unescape(_TAG.sub(" ", text))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


class Fetcher:
    def __init__(self, cfg, dry_run=False):
        self.ua = cfg["user_agent"]
        self.pause = float(cfg.get("request_interval_seconds", 1.5))
        self.dry = dry_run
        self._last = 0.0

    def get(self, url, binary=False, timeout=60):
        try:
            return self._get(url, binary, timeout)
        except urllib.error.URLError as e:
            # Python's own CA bundle can lack a certificate the operating system trusts (common with python.org
            # builds on macOS). Retry once with the system curl, which uses the system trust store. TLS
            # verification is never disabled.
            if "CERTIFICATE_VERIFY_FAILED" not in str(e) or not shutil.which("curl"):
                raise
            res = subprocess.run(["curl", "-fsSL", "--max-time", str(timeout), "-A", self.ua, url],
                                 capture_output=True, timeout=timeout + 10)
            if res.returncode != 0:
                raise urllib.error.URLError(f"{e.reason}; system curl also failed: "
                                            f"{res.stderr.decode('utf-8', 'replace').strip()[:200]}") from e
            return res.stdout if binary else json.loads(res.stdout.decode("utf-8"))

    def _get(self, url, binary=False, timeout=60):
        wait = self.pause - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 -- fixed https URLs from the config
            data = r.read()
            return data if binary else json.loads(data.decode("utf-8"))


def write_sidecar(path, meta):
    meta = {**meta, "sha256": sha256(path), "bytes": Path(path).stat().st_size}
    Path(str(path) + ".source.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


# ------------------------------------------------------------------ peers

def fetch_peers(cfg, f, retrieved_at, manual=None):
    """manual: {doc_id: path} -- the official PDF downloaded by a person in a browser (when the site cannot be read
    from a script); it is checked to be a PDF and recorded with the same official URL and a note that a person
    downloaded it."""
    out = []
    manual = manual or {}
    CURRICULA_DIR.mkdir(parents=True, exist_ok=True)
    for d in cfg.get("peer_documents", []):
        if d.get("status") != "USE":
            continue
        dest = CURRICULA_DIR / d["file"]
        row = {"doc_id": d["doc_id"], "url": d["url"], "file": str(dest.relative_to(ROOT))}
        try:
            if d["doc_id"] in manual:
                data = Path(manual[d["doc_id"]]).expanduser().read_bytes()
                if not data.startswith(b"%PDF"):
                    out.append({**row, "status": "REJECTED", "reason": "the supplied file is not a PDF"})
                    continue
                dest.write_bytes(data)
                write_sidecar(dest, {
                    "doc_id": d["doc_id"], "role": d["role"], "institution": d["institution"], "programme": d["programme"],
                    "discipline": d["discipline"], "curriculum_version": d["curriculum_version"],
                    "academic_year": d.get("academic_year"), "source_url": d["url"], "license": d["licence_note"],
                    "retrieved_at": retrieved_at, "collected_by": "downloaded by the project owner in a browser from the "
                                                                   "official URL; registered by fetch_official_sources.py",
                    "why": d.get("why")})
                out.append({**row, "status": "SUPPLIED_BY_OWNER", "sha256": sha256(dest), "bytes": len(data)})
                continue
            if f.dry:
                out.append({**row, "status": "DRY_RUN"})
                continue
            data = f.get(d["url"], binary=True, timeout=120)
            if not data.startswith(b"%PDF"):
                out.append({**row, "status": "REJECTED", "reason": "the response is not a PDF"})
                continue
            dest.write_bytes(data)
            write_sidecar(dest, {
                "doc_id": d["doc_id"], "role": d["role"], "institution": d["institution"], "programme": d["programme"],
                "discipline": d["discipline"], "curriculum_version": d["curriculum_version"],
                "academic_year": d.get("academic_year"), "source_url": d["url"], "license": d["licence_note"],
                "retrieved_at": retrieved_at, "collected_by": "scripts/acquisition/fetch_official_sources.py",
                "why": d.get("why")})
            out.append({**row, "status": "FETCHED", "sha256": sha256(dest), "bytes": len(data)})
        except (urllib.error.URLError, OSError, ValueError) as e:
            out.append({**row, "status": "FAILED", "reason": f"{type(e).__name__}: {e}"})
    return out


# ------------------------------------------------------------------ job boards

def _india(texts, terms):
    blob = " ".join(t for t in texts if t).lower()
    return any(re.search(rf"\b{re.escape(t)}\b", blob) for t in terms)


def greenhouse_rows(board, employer, data, terms):
    rows, skipped = [], 0
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name") or ""
        offices = [o.get("name") or "" for o in j.get("offices") or []]
        if not _india([loc, *offices], terms):
            skipped += 1
            continue
        first = j.get("first_published")
        rows.append({
            "job_title": j.get("title"), "url": j.get("absolute_url"),
            "source_url": f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{j.get('id')}",
            "posted_date": first[:10] if first else "", "job_country_code": "IN", "is_remote": "",
            "employment_status": "", "seniority": "", "job_location": loc,
            "job_description": html_to_text(j.get("content")), "salary": "", "company_name": employer,
            "company_industry": "", "company_employee_count": ""})
    return rows, skipped


def lever_rows(board, employer, data, terms):
    rows, skipped = [], 0
    for j in data if isinstance(data, list) else []:
        cat = j.get("categories") or {}
        locs = [cat.get("location") or "", *(cat.get("allLocations") or [])]
        if not (j.get("country") == "IN" or _india(locs, terms)):
            skipped += 1
            continue
        created = j.get("createdAt")
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()
                  if isinstance(created, (int, float)) else "")
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text') or ''}\n{html_to_text(lst.get('content'))}")
        parts.append(j.get("additionalPlain") or "")
        wt = (j.get("workplaceType") or "").lower()
        rows.append({
            "job_title": j.get("text"), "url": j.get("hostedUrl"),
            "source_url": f"https://api.lever.co/v0/postings/{board}/{j.get('id')}",
            "posted_date": posted, "job_country_code": "IN",
            "is_remote": "true" if wt == "remote" else ("false" if wt in ("onsite", "on-site", "hybrid") else ""),
            "employment_status": cat.get("commitment") or "", "seniority": "", "job_location": cat.get("location") or "",
            "job_description": "\n\n".join(p.strip() for p in parts if p and p.strip()), "salary": "",
            "company_name": employer, "company_industry": "", "company_employee_count": ""})
    return rows, skipped


def ashby_rows(board, employer, data, terms):
    rows, skipped = [], 0
    for j in (data or {}).get("jobs", []) if isinstance(data, dict) else []:
        if j.get("isListed") is False:
            continue
        country = (((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or "")
        locs = [j.get("location") or "", country, *[(x or {}).get("location") or "" for x in j.get("secondaryLocations") or []]]
        if not _india(locs, terms):
            skipped += 1
            continue
        published = j.get("publishedAt") or ""
        rows.append({
            "job_title": j.get("title"), "url": j.get("jobUrl"),
            "source_url": f"https://api.ashbyhq.com/posting-api/job-board/{board}#{j.get('id')}",
            "posted_date": published[:10], "job_country_code": "IN",
            "is_remote": "true" if j.get("isRemote") is True else ("false" if j.get("isRemote") is False else ""),
            "employment_status": j.get("employmentType") or "", "seniority": "", "job_location": j.get("location") or "",
            "job_description": j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")), "salary": "",
            "company_name": employer, "company_industry": "", "company_employee_count": ""})
    return rows, skipped


def smartrecruiters_rows(board, employer, f, terms, max_postings=150):
    """SmartRecruiters lists postings (filtered to India by the API's country parameter, then checked here) and
    gives each posting's text in a second request; at most max_postings detail requests per board."""
    base = f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
    listed, offset = [], 0
    while len(listed) < max_postings:
        page = f.get(f"{base}?country=in&limit=100&offset={offset}")
        items = page.get("content") or []
        listed += items
        offset += len(items)
        if not items or offset >= (page.get("totalFound") or 0):
            break
    rows, skipped = [], 0
    for j in listed[:max_postings]:
        loc = j.get("location") or {}
        if not _india([loc.get("country") or "", loc.get("city") or "", loc.get("region") or ""], terms) \
                and (loc.get("country") or "").lower() != "in":
            skipped += 1
            continue
        detail = f.get(f"{base}/{j.get('id')}")
        sections = ((detail.get("jobAd") or {}).get("sections") or {})
        text = "\n\n".join(html_to_text((sections.get(k) or {}).get("text")) for k in
                            ("jobDescription", "qualifications", "additionalInformation"))
        released = j.get("releasedDate") or ""
        rows.append({
            "job_title": j.get("name"), "url": detail.get("postingUrl") or detail.get("applyUrl") or "",
            "source_url": f"{base}/{j.get('id')}", "posted_date": released[:10], "job_country_code": "IN",
            "is_remote": "true" if loc.get("remote") is True else ("false" if loc.get("remote") is False else ""),
            "employment_status": ((j.get("typeOfEmployment") or {}).get("label") or ""), "seniority":
                ((j.get("experienceLevel") or {}).get("label") or ""),
            "job_location": ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x),
            "job_description": text.strip(), "salary": "", "company_name": employer, "company_industry": "",
            "company_employee_count": ""})
    return rows, skipped, len(listed)


API = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{board}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{board}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{board}/postings",
}
DATE_BASIS = {"greenhouse": "Greenhouse first_published", "lever": "Lever createdAt", "ashby": "Ashby publishedAt",
              "smartrecruiters": "SmartRecruiters releasedDate"}


def board_rows(prov, board, employer, f, terms):
    """(rows, skipped, total postings on the board) for one board."""
    if prov == "smartrecruiters":
        return smartrecruiters_rows(board, employer, f, terms)
    data = f.get(API[prov].format(board=board))
    rows, skipped = {"greenhouse": greenhouse_rows, "lever": lever_rows, "ashby": ashby_rows}[prov](
        board, employer, data, terms)
    total = len(data.get("jobs", [])) if isinstance(data, dict) else len(data) if isinstance(data, list) else 0
    return rows, skipped, total


def discover(cfg, f, add=False, today=None):
    """Check candidate boards; report those with India postings; optionally add them to the configuration."""
    cand_path = ROOT / "data/metadata/job_board_candidates.json"
    candidates = json.loads(cand_path.read_text(encoding="utf-8"))["candidates"]
    jb = cfg["job_boards"]
    terms = [t.lower() for t in jb["india_terms"]]
    known = {(b["provider"], b["board"]) for b in jb["boards"]}
    out = []
    for c in candidates:
        key = (c["provider"], c["board"])
        if key in known:
            out.append({**c, "status": "ALREADY_CONFIGURED"})
            continue
        if c["provider"] not in API:
            out.append({**c, "status": "UNKNOWN_PROVIDER"})
            continue
        try:
            rows, _skipped, total = board_rows(c["provider"], c["board"], c["employer"], f, terms)
        except (urllib.error.URLError, OSError, ValueError, AttributeError) as e:
            out.append({**c, "status": "NOT_A_BOARD", "reason": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        out.append({**c, "status": "INDIA_POSTINGS" if rows else "NO_INDIA_POSTINGS", "board_postings": total,
                    "india_postings": len(rows)})
    if add:
        added = [{"provider": o["provider"], "board": o["board"], "employer": o["employer"],
                  "verified_on": today or now_iso()[:10]} for o in out if o["status"] == "INDIA_POSTINGS"]
        if added:
            jb["boards"] += added
            CONFIG.write_text(json.dumps(cfg, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def fetch_jobs(cfg, f, retrieved_at, snapshot):
    jb = cfg["job_boards"]
    terms = [t.lower() for t in jb["india_terms"]]
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for b in jb["boards"]:
        prov, board, employer = b["provider"], b["board"], b["employer"]
        api = API.get(prov, "").format(board=board)
        row = {"provider": prov, "board": board, "employer": employer, "api": api}
        if prov not in API:
            out.append({**row, "status": "FAILED", "reason": f"unknown provider {prov}"})
            continue
        if f.dry:
            out.append({**row, "status": "DRY_RUN"})
            continue
        try:
            rows, skipped, total = board_rows(prov, board, employer, f, terms)
        except (urllib.error.URLError, OSError, ValueError, AttributeError) as e:
            out.append({**row, "status": "FAILED", "reason": f"{type(e).__name__}: {e}"})
            continue
        if not rows:
            out.append({**row, "status": "NO_INDIA_POSTINGS", "board_postings": total})
            continue
        rows.sort(key=lambda r: (r["url"] or ""))
        dest = JOBS_DIR / f"jobboard_{prov}_{board}_{snapshot}.csv"
        with dest.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        undated = sum(1 for r in rows if not r["posted_date"])
        meta = write_sidecar(dest, {
            "source_url": api.split("?")[0], "employer": employer, "provider": prov,
            "license": ("published by the employer on its public job board through its ATS's documented public read "
                        "API (no authentication); used for research analysis with attribution; raw text not "
                        "redistributed"),
            "collected_on": snapshot, "retrieved_at": retrieved_at, "geographic_scope": "IN",
            "collected_by": "scripts/acquisition/fetch_official_sources.py",
            "population_id": jb["population_id"], "population_definition": jb["population_definition"],
            "date_semantics": jb["date_semantics"],
            "date_basis": DATE_BASIS[prov] + " (from the source; postings without it are UNDATED)",
            "board_postings": total, "india_postings": len(rows), "not_in_india": skipped, "undated": undated})
        out.append({**row, "status": "FETCHED", "file": str(dest.relative_to(ROOT)), "board_postings": total,
                    "india_postings": len(rows), "undated": undated, "sha256": meta["sha256"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peers", action="store_true")
    ap.add_argument("--jobs", action="store_true")
    ap.add_argument("--snapshot-date", default=None, help="defaults to today's UTC date")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--peer-file", action="append", default=[], metavar="DOC_ID=PATH",
                    help="register an official peer PDF that a person downloaded in a browser (e.g. when the site's "
                         "certificate chain cannot be verified from a script)")
    ap.add_argument("--discover", action="store_true",
                    help="check data/metadata/job_board_candidates.json and report boards with India postings")
    ap.add_argument("--add-verified", action="store_true", help="with --discover: add those boards to the config")
    a = ap.parse_args()
    if a.discover:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        res = discover(cfg, Fetcher(cfg, False), add=a.add_verified)
        for r in res:
            print(f"{r['provider']}:{r['board']:<20} {r['status']:<20} india={r.get('india_postings', '-')} "
                  f"{r.get('reason') or ''}")
        found = sum(1 for r in res if r["status"] == "INDIA_POSTINGS")
        print(f"{found} board(s) with India postings" + (" added to the config" if a.add_verified and found else ""))
        return 0
    if a.peer_file and not a.jobs:
        a.peers = True
    if not (a.peers or a.jobs):
        a.peers = a.jobs = True
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    retrieved_at = now_iso()
    snapshot = a.snapshot_date or retrieved_at[:10]
    f = Fetcher(cfg, a.dry_run)
    report = {"retrieved_at": retrieved_at, "snapshot_date": snapshot, "config": str(CONFIG.relative_to(ROOT)),
              "peers": fetch_peers(cfg, f, retrieved_at, dict(x.split("=", 1) for x in a.peer_file)) if a.peers else [],
              "jobs": fetch_jobs(cfg, f, retrieved_at, snapshot) if a.jobs else [],
              "not_acquired": cfg.get("peer_documents_not_acquired", [])}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORT.parent / f"official_sources_report_{retrieved_at.replace(':', '')}.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")  # every attempt is kept
    for p in report["peers"]:
        print(f"peer  {p['doc_id']:<28} {p['status']}  {p.get('reason') or p.get('bytes') or ''}")
    for j in report["jobs"]:
        print(f"board {j['provider']}:{j['board']:<14} {j['status']}  india={j.get('india_postings', '-')} "
              f"undated={j.get('undated', '-')} {j.get('reason') or ''}")
    print(f"report: {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
