"""
Job postings: RAW -> BRONZE -> SILVER, reusing the project's existing
validation (validate_job_posting_row), cleaning (clean_job_description) and
near-duplicate detection (find_near_duplicates: same title + company AND
5-gram Jaccard >= threshold -- never similarity of description alone).

Identity / deduplication (deterministic, documented order):
  1. platform + external posting id parsed from the posting URL
       linkedin.com/jobs/view/<digits>        -> linkedin:<digits>
       indeed.com ... jk=<hex> | -<16 hex>    -> indeed:<hex>
       naukri.com/job-listings-...-<digits>   -> naukri:<digits>
       ...?gh_jid=<digits> (Greenhouse job id) -> greenhouse:<digits>
  2. otherwise the canonical URL (scheme/host lower-cased, query and
     fragment dropped, trailing slash removed)            -> url:<canonical>
  3. no URL at all -> the record is QUARANTINED (no stable identity)
A second record with an identity already seen is DUPLICATE (the first by
file name, then row order, is kept). duplicate_kind says which:
  SAME_IDENTITY    the same posting twice in one snapshot / dataset
  SNAPSHOT_REPEAT  the same posting still open in a snapshot of another date: one
                   posting, kept once; the snapshot dates it was open on are
                   listed in the posting's open_on_snapshots (trends count it in
                   each of those snapshots). Not a data-quality defect, so the
                   duplicate-rate health check leaves these out.
  NEAR_DUPLICATE   same title + company and near-identical text Records failing validation are
REJECTED with the validator's reason. Every record gets exactly one of
ACCEPTED / DUPLICATE / REJECTED / QUARANTINED and a reason.
"""
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

from app.knowledge_engine.silver import uid
from app.pipelines.preprocessing.deduplication import find_near_duplicates
from app.pipelines.preprocessing.text_cleaning import clean_job_description
from app.pipelines.preprocessing.validation import validate_job_posting_row

# supplied export column -> project schema key (the files' own column names)
COLUMN_MAP = {
    "job_title": "job_title", "url": "url", "source_url": "source_url", "posted_date": "posted_date",
    "job_country_code": "country_code", "is_remote": "is_remote", "employment_status": "employment_status",
    "seniority": "seniority", "job_location": "location", "job_description": "raw_description",
    "salary": "salary_raw", "company_name": "company_name", "company_industry": "company_industry",
    "company_employee_count": "company_employee_count",
}
# personal data present in the export that the analysis does not need: not carried beyond RAW
DROPPED_PERSONAL_COLUMNS = ["hiring_manager_full_name", "hiring_manager_first_name", "hiring_manager_role",
                            "hiring_manager_linkedin_url"]

_LINKEDIN_RE = re.compile(r"linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d+)", re.I)
_INDEED_HEX_RE = re.compile(r"-([0-9a-f]{16})(?:[/?#]|$)", re.I)
_NAUKRI_RE = re.compile(r"naukri\.com/job-listings-(?:.*-)?(\d{6,})(?:[/?#]|$)", re.I)


def canonical_url(url):
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def posting_identity(url):
    """Returns (platform, external_id, method) or (None, None, reason)."""
    if not url or not str(url).strip():
        return None, None, "NO_URL"
    url = str(url).strip()
    host = urlsplit(url).netloc.lower()
    m = _LINKEDIN_RE.search(url)
    if m:
        return "linkedin", m.group(1), "url_external_id"
    if "indeed." in host:
        jk = parse_qs(urlsplit(url).query).get("jk")
        if jk:
            return "indeed", jk[0].lower(), "url_external_id"
        m = _INDEED_HEX_RE.search(url)
        if m:
            return "indeed", m.group(1).lower(), "url_external_id"
    m = _NAUKRI_RE.search(url)
    if m:
        return "naukri", m.group(1), "url_external_id"
    gh = parse_qs(urlsplit(url).query).get("gh_jid")  # Greenhouse job id on an employer's own careers page
    if gh and gh[0].isdigit():
        return "greenhouse", gh[0], "url_external_id"
    return (host[4:] if host.startswith("www.") else host) or "unknown", canonical_url(url), "canonical_url"


def _iso_date(value):
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def _value(v):
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def read_raw_file(path):
    """Read one posting file (.xlsx export, or .csv in the same column layout). Returns raw row dicts (file order)."""
    if str(path).lower().endswith(".csv"):
        import csv
        with open(path, newline="", encoding="utf-8") as fh:
            return [{k: _value(v) for k, v in row.items()} for row in csv.DictReader(fh)]
    import pandas as pd
    frame = pd.read_excel(path, sheet_name=0, dtype=object)
    return [{k: _value(v) for k, v in row.items()} for row in frame.to_dict("records")]


def temporal_date_of(src):
    """The date that places a posting in a time period, by the source's declared date semantics.

    Default: the posting's own publication date. OPEN_POSTINGS_SNAPSHOT (a snapshot of the postings that were open
    on a job board on one day): the snapshot date. Publication dates of still-open postings say which postings
    survived until the snapshot, not how demand changed, so periods of such a population are snapshots; one snapshot
    is one period and can never show a trend."""
    prov = src.get("provenance") or {}
    if (prov.get("date_semantics") or src.get("date_semantics")) == "OPEN_POSTINGS_SNAPSHOT":
        return _iso_date(prov.get("collected_on") or src.get("collected_on")) or "UNDATED_SNAPSHOT"
    return None


def company_key(name):
    if not name:
        return None
    return re.sub(r"\s+", " ", str(name)).strip().lower() or None


# Wording that only appears in employer statements, never in a job's own requirements: equal-opportunity and
# disability-accommodation statements, and invitations to follow the employer. A genre lexicon of job postings; it
# names no skill, discipline or employer. Broader cues ("regardless of", a bare "accommodation") were checked on the
# 2026-10 postings and also matched job text ("decisive feedback regardless of seniority", "travel and accommodation
# bookings"), and so did "follow ... on" without a social network ("follow up on outstanding receivables"); they are
# not used.
EMPLOYER_STATEMENT = re.compile(
    r"\b(?:discriminat\w*|equal (?:employment )?opportunit\w*|reasonable accommodations?|accommodations? may include|"
    r"protected (?:veteran )?status|without regard to|applicants? with disabilit\w*|affirmative action|"
    r"follow us on|(?:follow|find) \w+ on (?:linkedin|twitter|x|instagram|youtube|facebook)|connect with us|"
    r"like us on)\b", re.I)


def employer_boilerplate(postings, cfg):
    """Removes, from the text skills are read from, text that describes the employer rather than the job, so that one
    employer with many postings cannot turn its about-us paragraph, values or legal statements into demand.

      REPEATED   per employer with >= min_employer_postings postings in this population: a sentence (normalised,
                 >= min_words words) that occurs in >= min_share of the employer's postings, under >= min_titles
                 different job titles. Employers are never compared with each other, so a requirement line several
                 employers happen to share is never touched; a block shared by a few related roles stays.
      STATEMENT  in any posting: a sentence with equal-opportunity, accommodation or follow-us wording
                 (EMPLOYER_STATEMENT). Catches the same statement written differently in different postings.
    The sentence is replaced by spaces in clean_description, so every character offset of the remaining text is
    unchanged; raw_description is kept as read. Each affected posting records boilerplate_chars_removed. Returns a
    summary. cfg None or enabled false: nothing changes."""
    from app.knowledge_engine.relevance import _norm, segments
    if not cfg or not cfg.get("enabled", True):
        return {"enabled": False}
    segs = {p["posting_uid"]: segments(p.get("clean_description")) for p in postings}
    repeated = {}
    by_employer = {}
    for p in postings:
        if p.get("company_key"):
            by_employer.setdefault(p["company_key"], []).append(p)
    for emp, ps in sorted(by_employer.items()):
        if len(ps) < cfg["min_employer_postings"]:
            continue
        where = {}
        for p in ps:
            for _, _, sent in segs[p["posting_uid"]]:
                n = _norm(sent)
                if len(n.split()) >= cfg["min_words"]:
                    where.setdefault(n, set()).add(p["posting_uid"])
        title = {p["posting_uid"]: (p.get("job_title") or "").strip().lower() for p in ps}
        found = {n for n, uids in where.items() if len(uids) >= cfg["min_share"] * len(ps)
                 and len({title[u] for u in uids}) >= cfg["min_titles"]}
        if found:
            repeated[emp] = found
    statements = cfg.get("statements", True)
    employers, counts, removed_postings, chars = {}, {"REPEATED": 0, "STATEMENT": 0}, 0, 0
    for p in postings:
        text, cut, emp_text = p["clean_description"], 0, repeated.get(p.get("company_key"), ())
        for a, b, sent in segs[p["posting_uid"]]:
            kind = ("REPEATED" if emp_text and _norm(sent) in emp_text
                    else "STATEMENT" if statements and EMPLOYER_STATEMENT.search(sent) else None)
            if kind:
                text, cut = text[:a] + " " * (b - a) + text[b:], cut + (b - a)
                counts[kind] += 1
        if cut:
            p["clean_description"], p["boilerplate_chars_removed"] = text, cut
            removed_postings, chars = removed_postings + 1, chars + cut
    for emp, found in repeated.items():
        employers[emp] = {"postings": len(by_employer[emp]), "repeated_sentences": len(found)}
    rule = ("min_employer_postings", "min_share", "min_titles", "min_words")
    return {"enabled": True, "rule": {k: cfg[k] for k in rule} | {"statements": statements},
            "employers": employers, "sentences_removed": counts, "postings_affected": removed_postings,
            "characters_removed": chars}


def ingest_postings(sources, bronze_root, silver_root, near_dup_threshold, boilerplate_cfg=None):
    """
    sources: manifest entries {"source_id", "path", "sha256", "platform_note"...} (already hash-verified).
    Writes BRONZE (standardized raw records, personal columns dropped) and
    SILVER (validated, cleaned, deduplicated postings) per file.
    Returns {"postings": [...ACCEPTED silver records], "records": [...all records with status], "summary": {...}}
    """
    seen_identity, records, accepted = {}, [], []
    first_snapshot, accepted_by_uid = {}, {}
    dated = lambda d: d not in (None, "UNDATED_SNAPSHOT")
    for src in sorted(sources, key=lambda s: Path(s["path"]).name):
        rows = read_raw_file(src["abs_path"])
        snapshot_date = temporal_date_of(src)
        bronze = []
        for row_number, row in enumerate(rows, start=1):
            std = {COLUMN_MAP[k]: row.get(k) for k in COLUMN_MAP}
            std.update({"source_id": src["source_id"], "source_file": Path(src["path"]).name,
                        "source_sha256": src["sha256"], "row_number": row_number})
            std["posted_date"] = _iso_date(row.get("posted_date"))
            bronze.append(std)
            platform, external_id, id_method = posting_identity(std.get("url"))
            base = {"source_id": src["source_id"], "source_file": std["source_file"], "row_number": row_number,
                    "url": std.get("url"), "job_title": std.get("job_title"), "company_name": std.get("company_name")}
            if platform is None:
                records.append({**base, "status": "QUARANTINED", "reason": f"{id_method}: no stable posting identity"})
                continue
            identity = f"{platform}:{external_id}"
            validation = validate_job_posting_row(std)
            if not validation.is_valid:
                records.append({**base, "identity": identity, "status": "REJECTED",
                                "reason": f"{validation.reason}{': ' + validation.detail if validation.detail else ''}"})
                continue
            if identity in seen_identity:
                first_uid, first_date = seen_identity[identity], first_snapshot[identity]
                if dated(snapshot_date) and dated(first_date) and snapshot_date != first_date:
                    records.append({**base, "identity": identity, "status": "DUPLICATE",
                                    "duplicate_kind": "SNAPSHOT_REPEAT", "snapshot_date": snapshot_date,
                                    "reason": (f"same posting identity as {first_uid}, still open in the "
                                               f"{snapshot_date} snapshot (first seen {first_date})")})
                    kept = accepted_by_uid.get(first_uid)
                    if kept is not None:
                        kept["open_on_snapshots"] = sorted(set(kept.get("open_on_snapshots") or [first_date])
                                                           | {snapshot_date})
                else:
                    records.append({**base, "identity": identity, "status": "DUPLICATE",
                                    "duplicate_kind": "SAME_IDENTITY",
                                    "reason": f"same posting identity as {first_uid}"})
                continue
            posting_uid = uid("posting", identity)
            seen_identity[identity] = posting_uid
            first_snapshot[identity] = snapshot_date
            clean = clean_job_description(std["raw_description"])
            posting = {
                "posting_uid": posting_uid, "identity": identity, "platform": platform, "external_id": external_id,
                "identity_method": id_method, "url": std["url"], "source_url": std.get("source_url"),
                "source_id": src["source_id"], "source_file": std["source_file"], "source_sha256": src["sha256"],
                "row_number": row_number, "job_title": std.get("job_title"), "company_name": std.get("company_name"),
                "company_key": company_key(std.get("company_name")), "company_industry": std.get("company_industry"),
                "location": std.get("location"), "country_code": std.get("country_code"),
                "posted_date": std["posted_date"], "employment_status": std.get("employment_status"),
                "seniority": std.get("seniority"), "is_remote": std.get("is_remote"),
                "raw_description": std["raw_description"], "clean_description": clean,
                "raw_description_sha256": hashlib.sha256(std["raw_description"].encode("utf-8")).hexdigest(),
                "evidence_status": "EXTRACTED",
            }
            if snapshot_date is not None:  # only for snapshot sources: baseline postings are unchanged
                posting["temporal_date"] = None if snapshot_date == "UNDATED_SNAPSHOT" else snapshot_date
                posting["date_semantics"] = "OPEN_POSTINGS_SNAPSHOT"
            records.append({**base, "identity": identity, "posting_uid": posting_uid, "status": "ACCEPTED",
                            "reason": f"new identity ({id_method})"})
            accepted.append(posting)
            accepted_by_uid[posting_uid] = posting
        _write_jsonl(Path(bronze_root) / src["sha256"][:16] / "records.jsonl", bronze)

    near = find_near_duplicates([{"id": p["posting_uid"], "job_title": p["job_title"], "company_name": p["company_name"],
                                  "clean_description": p["clean_description"]} for p in accepted], near_dup_threshold)
    if near:
        kept = []
        for p in accepted:
            if p["posting_uid"] in near:
                for r in records:
                    if r.get("posting_uid") == p["posting_uid"]:
                        r["status"], r["reason"] = "DUPLICATE", (f"near-duplicate of {near[p['posting_uid']]} "
                                                                 f"(same title + company, Jaccard >= {near_dup_threshold})")
                        r["duplicate_kind"] = "NEAR_DUPLICATE"
            else:
                kept.append(p)
        accepted = kept

    boilerplate = employer_boilerplate(accepted, boilerplate_cfg)

    for src in sources:
        _write_jsonl(Path(silver_root) / src["sha256"][:16] / "postings.jsonl",
                     [p for p in accepted if p["source_id"] == src["source_id"]])
    status_counts = {}
    for r in records:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    total = len(records)
    repeats = sum(1 for r in records if r.get("duplicate_kind") == "SNAPSHOT_REPEAT")
    distinct = total - repeats
    summary = {
        "records_read": total, "status_counts": status_counts,
        "duplicate_rate": round(status_counts.get("DUPLICATE", 0) / total, 4) if total else None,
        "snapshot_repeats": repeats,
        "duplicate_rate_excluding_snapshot_repeats": (round((status_counts.get("DUPLICATE", 0) - repeats) / distinct, 4)
                                                      if distinct else None),
        "missing_description": sum(1 for r in records if r["status"] == "REJECTED" and "description" in r["reason"]),
        "dropped_personal_columns": DROPPED_PERSONAL_COLUMNS,
        "employer_boilerplate": boilerplate,
    }
    return {"postings": accepted, "records": records, "summary": summary}


def population_scope(postings, sources, extra=None):
    """Scope that travels with every industry result."""
    dates = sorted(p["posted_date"] for p in postings if p.get("posted_date"))
    countries, industries, by_period = {}, {}, {}
    for p in postings:
        countries[p.get("country_code") or "UNKNOWN"] = countries.get(p.get("country_code") or "UNKNOWN", 0) + 1
        key = p.get("company_industry") or "NOT_PROVIDED"
        industries[key] = industries.get(key, 0) + 1
        period = (p.get("posted_date") or "UNKNOWN")[:7]
        by_period[period] = by_period.get(period, 0) + 1
    companies = {p["company_key"] for p in postings if p.get("company_key")}
    scope = {
        "population": "supplied job-posting files",
        "eligible_postings": len(postings),
        "source_files": sorted({Path(s["path"]).name for s in sources}),
        "geographic_scope": dict(sorted(countries.items())),
        "date_range": {"earliest": dates[0] if dates else None, "latest": dates[-1] if dates else None},
        "postings_by_month": dict(sorted(by_period.items())),
        "distinct_companies": len(companies),
        "postings_without_company": sum(1 for p in postings if not p.get("company_key")),
        "distinct_job_titles": len({(p.get("job_title") or "").strip().lower() for p in postings if p.get("job_title")}),
        "company_industry_distribution": dict(sorted(industries.items(), key=lambda kv: (-kv[1], kv[0]))),
        "representativeness_warning": (
            "These results describe the supplied job-posting dataset and are not necessarily representative "
            "of the entire labour market."),
    }
    if extra:
        scope.update(extra)
    return scope


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) + "\n")
