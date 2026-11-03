"""
Industry intelligence v2 (improvement release): temporal demand, population-scoped dimensions and skill
co-occurrence clusters, computed on top of the run's established skill mentions.

Populations. Every job-posting source belongs to an explicit POPULATION (manifest industry_sources[].population_id,
e.g. one collection method over one geography). Periods, trends and comparisons are computed WITHIN one
population only; two populations are never merged silently, even when their dates would line up.

Denominator. Demand is always DISTINCT ELIGIBLE POSTINGS: a skill mentioned five times in one posting is one
posting containing the skill. Raw mention frequency is reported next to it and labelled as such, never as demand.

None vs zero. None means the population or period does not exist (no evidence); 0 means the population exists
and the skill is absent from it.

Temporal buckets: week (ISO), month, quarter. The finest granularity that yields at least
min_periods_for_trend periods of at least min_eligible_postings_per_period postings is used; the evaluation of
every granularity is reported. A skill is classified only when the population passes that gate AND the skill has
at least min_skill_postings_for_trend postings over the qualifying periods:
  EMERGING       absent in the first qualifying period, present in the last, change >= min_pp_change
  DECLINING      present in the first, absent in the last, drop >= min_pp_change
  TRENDING_UP    present in both, change >= min_pp_change AND relative change >= min_relative_change AND
                 never decreasing between consecutive periods (when require_monotonic)
  TRENDING_DOWN  the mirror image
  PERSISTENT     present in every qualifying period at >= persistent_min_pct and no trend above
  STABLE         present, |change| < min_pp_change
  INSUFFICIENT_DATA  anything else, with the reason (population gate, skill postings, inconsistent direction)
Open-posting snapshots. A posting open on the boards on several snapshot dates is one posting (kept once) and a
member of each of those snapshots (posting_dates). Board panel: when the snapshots of a population cover different
sets of job boards, trends use only the boards present in every snapshot, so a board added later cannot pose as a
change in demand; the boards left out are reported in the scope (board_panel).
No trend arrow exists without these numbers: every trend row carries both periods, both denominators, both
counts, the population and the source files.

Skill clusters: two skills are linked when they co-occur in >= min_cooccurring_postings postings with
lift >= min_lift; clusters are connected components. The relationship is CO_OCCURS_IN_POSTINGS -- association
in this population, never semantic equivalence.

No function names a skill, occupation, company, location or subject.
"""
import re
from collections import Counter, defaultdict
from datetime import date

UNDATED = "UNDATED"
TREND_STATES = ("TRENDING_UP", "TRENDING_DOWN", "STABLE", "EMERGING", "DECLINING", "PERSISTENT", "INSUFFICIENT_DATA")
GRANULARITIES = ("week", "month", "quarter")


# ------------------------------------------------------------------ populations and periods

def population_of(posting, sources):
    """population_id of a posting's source (manifest), or the source id itself when none is declared."""
    src = sources.get(posting.get("source_id")) or {}
    return src.get("population_id") or f"SOURCE:{posting.get('source_id')}"


def temporal_date(posting):
    """Date that places a posting in a period: the snapshot date for open-posting snapshots (jobs.temporal_date_of),
    else the publication date."""
    return posting["temporal_date"] if "temporal_date" in posting else posting.get("posted_date")


def posting_dates(posting):
    """Every date that places a posting in a period: each snapshot it was open on (jobs: open_on_snapshots), else its
    single temporal date."""
    return posting.get("open_on_snapshots") or [temporal_date(posting)]


def _board(src):
    prov = (src or {}).get("provenance") or {}
    return prov.get("source_url") or None


def board_panel(population_id, postings, sources):
    """For an open-postings snapshot population whose snapshots cover different job boards: the boards present in
    every snapshot date, and the postings of the others. None when there is nothing to restrict."""
    by_date = defaultdict(set)
    for src in sources.values():
        prov = src.get("provenance") or {}
        if ((src.get("population_id") or prov.get("population_id")) != population_id
                or (prov.get("date_semantics") or src.get("date_semantics")) != "OPEN_POSTINGS_SNAPSHOT"):
            continue
        when, board = prov.get("collected_on") or src.get("collected_on"), _board(src)
        if not when or not board:
            return None  # a snapshot without a date or a board: no panel can be defined
        by_date[str(when)[:10]].add(board)
    if len(by_date) < 2:
        return None
    every = set.intersection(*by_date.values())
    allb = set.union(*by_date.values())
    if every == allb:
        return None
    keep = [p for p in postings if _board(sources.get(p.get("source_id"))) in every]
    return {"postings": keep, "scope": {
        "snapshot_dates": sorted(by_date), "boards_in_every_snapshot": len(every), "boards_in_some_snapshots": len(allb),
        "boards_left_out": sorted(allb - every), "postings_left_out": len(postings) - len(keep),
        "why": "trends compare the same job boards on every snapshot date; boards collected on only some dates are "
               "left out of the trend (they still count everywhere else)"}}


def period_key(posted_date, granularity):
    if not posted_date or not re.match(r"^\d{4}-\d{2}-\d{2}", str(posted_date)):
        return UNDATED
    y, m, d = (int(x) for x in str(posted_date)[:10].split("-"))
    if granularity == "month":
        return f"{y:04d}-{m:02d}"
    if granularity == "quarter":
        return f"{y:04d}-Q{(m - 1) // 3 + 1}"
    iso = date(y, m, d).isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def evaluate_granularities(postings, settings):
    """Postings per period for every granularity + whether it qualifies for trends."""
    out = {}
    for g in GRANULARITIES:
        per = Counter(k for p in postings for k in {period_key(d, g) for d in posting_dates(p)})
        dated = {k: v for k, v in sorted(per.items()) if k != UNDATED}
        qualifying = {k: v for k, v in dated.items() if v >= settings["min_eligible_postings_per_period"]}
        out[g] = {"postings_by_period": dated, "undated_postings": per.get(UNDATED, 0),
                  "qualifying_periods": sorted(qualifying), "qualifies": len(qualifying) >= settings["min_periods_for_trend"]}
    chosen = next((g for g in GRANULARITIES if out[g]["qualifies"]), None)
    return chosen, out


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def classify_trend(series, total_skill_postings, settings, tcfg):
    """series: [(period, count, denominator)] over the qualifying periods (oldest first)."""
    if len(series) < settings["min_periods_for_trend"]:
        return "INSUFFICIENT_DATA", f"{len(series)} qualifying period(s); {settings['min_periods_for_trend']} needed"
    if total_skill_postings < settings["min_skill_postings_for_trend"]:
        return "INSUFFICIENT_DATA", (f"{total_skill_postings} posting(s) with the skill over the qualifying periods; "
                                     f"{settings['min_skill_postings_for_trend']} needed")
    pcts = [100.0 * c / d for _, c, d in series]
    first, last = pcts[0], pcts[-1]
    change = last - first
    steps = [b - a for a, b in zip(pcts, pcts[1:])]
    if series[0][1] == 0 and series[-1][1] > 0 and change >= tcfg["min_pp_change"]:
        return "EMERGING", f"absent in {series[0][0]}, {last:.1f}% in {series[-1][0]} (+{change:.1f} pp)"
    if series[0][1] > 0 and series[-1][1] == 0 and -change >= tcfg["min_pp_change"]:
        return "DECLINING", f"{first:.1f}% in {series[0][0]}, absent in {series[-1][0]} ({change:.1f} pp)"
    rel = (change / first) if first else None
    monotone_up = all(s >= 0 for s in steps)
    monotone_down = all(s <= 0 for s in steps)
    if change >= tcfg["min_pp_change"] and rel is not None and rel >= tcfg["min_relative_change"]:
        if monotone_up or not tcfg["require_monotonic"]:
            return "TRENDING_UP", f"{first:.1f}% -> {last:.1f}% (+{change:.1f} pp, +{rel:.0%})"
        return "INSUFFICIENT_DATA", "overall rise, but the direction is not consistent between consecutive periods"
    if -change >= tcfg["min_pp_change"] and rel is not None and -rel >= tcfg["min_relative_change"]:
        if monotone_down or not tcfg["require_monotonic"]:
            return "TRENDING_DOWN", f"{first:.1f}% -> {last:.1f}% ({change:.1f} pp, {rel:.0%})"
        return "INSUFFICIENT_DATA", "overall fall, but the direction is not consistent between consecutive periods"
    if abs(change) < tcfg["min_pp_change"]:
        if all(c > 0 for _, c, _ in series) and min(pcts) >= tcfg["persistent_min_pct"]:
            return "PERSISTENT", f"present in all {len(series)} periods at >= {tcfg['persistent_min_pct']}% (change {change:+.1f} pp)"
        if all(c > 0 for _, c, _ in series):
            return "STABLE", f"change {change:+.1f} pp is below the {tcfg['min_pp_change']} pp trend threshold"
    return "INSUFFICIENT_DATA", f"change {change:+.1f} pp does not meet the configured trend rules"


def population_trends(population_id, postings, pairs, skills, sources, settings, tcfg, segment="ALL_POSTINGS"):
    """Trend scope + per-skill rows for ONE population (optionally one segment of it)."""
    all_postings = postings
    panel = board_panel(population_id, postings, sources)
    if panel:
        postings = panel["postings"]
    chosen, evaluation = evaluate_granularities(postings, settings)
    files = sorted({p.get("source_file") for p in all_postings if p.get("source_file")})
    geography = dict(Counter(p.get("country_code") or "UNKNOWN" for p in all_postings))
    dated = [d for p in all_postings for d in posting_dates(p) if d]
    scope = {"population_id": population_id, "segment": segment, "eligible_postings": len(all_postings),
             "date_range": {"earliest": min(dated) if dated else None, "latest": max(dated) if dated else None},
             "geographic_scope": geography, "source_files": files,
             "granularity": chosen, "granularity_evaluation": evaluation,
             "date_basis": ("snapshot date (postings open on the job boards that day)"
                            if any(p.get("date_semantics") == "OPEN_POSTINGS_SNAPSHOT" for p in postings)
                            else "posting publication date"),
             "gate": {k: settings[k] for k in ("min_periods_for_trend", "min_eligible_postings_per_period",
                                               "min_skill_postings_for_trend")},
             "thresholds": {k: tcfg[k] for k in ("min_pp_change", "min_relative_change", "persistent_min_pct", "require_monotonic")}}
    if panel:
        scope["board_panel"] = panel["scope"] | {"trend_postings": len(postings)}
    uids = {p["posting_uid"] for p in postings}
    by_skill = defaultdict(set)
    for k, pid in pairs:
        if pid in uids:
            by_skill[k].add(pid)
    if chosen is None:
        best = max(GRANULARITIES, key=lambda g: (len(evaluation[g]["qualifying_periods"]), -GRANULARITIES.index(g)))
        ev = evaluation[best]
        scope.update(trend_status="INSUFFICIENT_DATA", missing={
            "what": "job postings from more time periods of the same population",
            "have": {"granularity": best, "qualifying_periods": len(ev["qualifying_periods"]),
                     "postings_by_period": ev["postings_by_period"]},
            "required": (f">= {settings['min_periods_for_trend']} periods with >= "
                         f"{settings['min_eligible_postings_per_period']} eligible postings each (week, month or quarter)"),
            "why_it_matters": "a trend compares the same population at two or more points in time; one period has no direction",
            "sources_that_can_provide_it": "see evidence status TEMPORAL_TREND (drop folder with licence sidecar, "
                                           "credentialed job-posting connectors)"})
        rows = [{"population_id": population_id, "segment": segment, "skill_key": k, "skill_label": skills[k]["label"],
                 "trend_state": "INSUFFICIENT_DATA", "reason": "population does not pass the temporal evidence gate",
                 "periods": [], "total_postings_with_skill": len(v)} for k, v in sorted(by_skill.items())]
        return scope, rows
    scope["trend_status"] = "COMPUTED"
    periods = evaluation[chosen]["qualifying_periods"]
    period_members = defaultdict(set)
    for p in postings:
        for d in posting_dates(p):
            period_members[period_key(d, chosen)].add(p["posting_uid"])
    rows = []
    for k in sorted(set(by_skill) | set()):
        series, detail = [], []
        prev = None
        for per in periods:
            members = period_members[per]
            n = len(by_skill[k] & members)
            series.append((per, n, len(members)))
            pct = _pct(n, len(members))
            detail.append({"period": per, "posting_count": n, "eligible_postings": len(members), "demand_pct": pct,
                           "pp_change_from_previous": None if prev is None else round(pct - prev, 2)})
            prev = pct
        total = sum(n for _, n, _ in series)
        state, why = classify_trend(series, total, settings, tcfg)
        first, last = detail[0], detail[-1]
        rel = (round((last["demand_pct"] - first["demand_pct"]) / first["demand_pct"], 4)
               if first["demand_pct"] else None)
        rows.append({"population_id": population_id, "segment": segment, "skill_key": k, "skill_label": skills[k]["label"],
                     "trend_state": state, "reason": why, "periods": detail, "total_postings_with_skill": total,
                     "pp_change": round(last["demand_pct"] - first["demand_pct"], 2), "relative_change": rel,
                     "statement": (f"{skills[k]['label']}: {first['demand_pct']}% of {first['eligible_postings']} postings in "
                                   f"{first['period']} -> {last['demand_pct']}% of {last['eligible_postings']} in {last['period']} "
                                   f"(population {population_id})")})
    return scope, rows


# ------------------------------------------------------------------ dimensions

def _city(location):
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    return parts[0] if parts else None


def _region(location):
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    return parts[1] if len(parts) >= 3 else None  # "City, Region, Country"; shorter forms carry no region


DIMENSIONS = {
    "location_city": lambda p: _city(p.get("location")),
    "location_region": lambda p: _region(p.get("location")),
    "seniority": lambda p: p.get("seniority"),
    "employment_type": lambda p: p.get("employment_status"),
    "industry_domain": lambda p: p.get("company_industry"),
    "remote": lambda p: p.get("is_remote"),
}


def dimension_demand(postings, pairs, mention_counts, skills, occupation_of, min_group, top_n):
    """Skill demand within each value of each dimension (distinct postings; groups below min_group are not ranked)."""
    dims = dict(DIMENSIONS)
    dims["occupation"] = lambda p: (occupation_of.get(p["posting_uid"]) or {}).get("label")
    dims["occupation_group"] = lambda p: (occupation_of.get(p["posting_uid"]) or {}).get("group")
    by_posting = defaultdict(set)
    for k, pid in pairs:
        by_posting[pid].add(k)
    out = {}
    for name, fn in dims.items():
        groups = defaultdict(list)
        missing = 0
        for p in postings:
            v = fn(p)
            if v in (None, "", "None", "nan"):
                missing += 1
                continue
            groups[str(v)].append(p)
        rows = []
        for value, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            skill_counts = Counter(k for p in members for k in by_posting.get(p["posting_uid"], ()))
            row = {"value": value, "postings": len(members), "companies": len({p.get("company_key") for p in members if p.get("company_key")})}
            if len(members) >= min_group:
                row["evidence_state"] = "SUFFICIENT"
                row["top_skills"] = [{"skill_key": k, "skill_label": skills[k]["label"], "postings": n,
                                      "demand_pct": _pct(n, len(members)), "mentions": mention_counts.get((k, value, name))}
                                     for k, n in sorted(skill_counts.items(), key=lambda kv: (-kv[1], skills[kv[0]]["label"]))[:top_n]]
            else:
                row["evidence_state"] = "INSUFFICIENT_EVIDENCE"
                row["reason"] = f"{len(members)} posting(s); skill demand is ranked only for groups of >= {min_group}"
            rows.append(row)
        out[name] = {"dimension": name, "postings_with_value": len(postings) - missing, "postings_without_value": missing,
                     "status": ("DATA_NOT_AVAILABLE" if not groups else "AVAILABLE"),
                     "reason": ("no posting carries this field" if not groups else None), "groups": rows}
    return out


def distributions(postings, top_n):
    companies = Counter(p.get("company_name") for p in postings if p.get("company_name"))
    titles = Counter(p.get("job_title") for p in postings if p.get("job_title"))
    cities = Counter(_city(p.get("location")) for p in postings if _city(p.get("location")))
    return {"postings": len(postings), "distinct_companies": len(companies), "distinct_titles": len(titles),
            "top_companies": [{"company": c, "postings": n} for c, n in companies.most_common(top_n)],
            "top_locations": [{"location": c, "postings": n} for c, n in cities.most_common(top_n)],
            "platforms": dict(Counter(p.get("platform") or "UNKNOWN" for p in postings))}


def mention_vs_postings(mentions, pairs, skills):
    """Per skill: raw mention count (all established SKILL mentions) next to distinct postings (the demand unit)."""
    raw = Counter(m["skill_key"] for m in mentions)
    distinct = Counter(k for k, _ in pairs)
    return [{"skill_key": k, "skill_label": skills[k]["label"], "mention_count": raw.get(k, 0),
             "distinct_postings": distinct[k], "mentions_per_posting": round(raw.get(k, 0) / distinct[k], 2)}
            for k in sorted(distinct, key=lambda x: (-distinct[x], skills[x]["label"]))]


# ------------------------------------------------------------------ clusters

def skill_clusters(pairs, skills, total_postings, ccfg):
    by_skill = defaultdict(set)
    for k, pid in pairs:
        by_skill[k].add(pid)
    eligible = sorted(k for k, v in by_skill.items() if len(v) >= ccfg["min_skill_postings"])
    edges = []
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            both = len(by_skill[a] & by_skill[b])
            if both < ccfg["min_cooccurring_postings"]:
                continue
            lift = both * total_postings / (len(by_skill[a]) * len(by_skill[b]))
            if lift < ccfg["min_lift"]:
                continue
            jac = both / len(by_skill[a] | by_skill[b])
            edges.append({"skill_a": a, "skill_b": b, "label_a": skills[a]["label"], "label_b": skills[b]["label"],
                          "cooccurring_postings": both, "postings_a": len(by_skill[a]), "postings_b": len(by_skill[b]),
                          "lift": round(lift, 3), "jaccard": round(jac, 4), "relationship": "CO_OCCURS_IN_POSTINGS"})
    parent = {k: k for k in eligible}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in edges:
        ra, rb = find(e["skill_a"]), find(e["skill_b"])
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    comps = defaultdict(list)
    for k in eligible:
        comps[find(k)].append(k)
    clusters = []
    for members in comps.values():
        if len(members) < 2:
            continue
        ms = set(members)
        member_edges = [e for e in edges if e["skill_a"] in ms and e["skill_b"] in ms]
        clusters.append({"members": [{"skill_key": k, "skill_label": skills[k]["label"], "postings": len(by_skill[k])}
                                     for k in sorted(members, key=lambda x: (-len(by_skill[x]), skills[x]["label"]))],
                         "edges": member_edges, "size": len(members),
                         "relationship": "CO_OCCURS_IN_POSTINGS",
                         "statement": "these skills are requested together in this population; co-occurrence is association, "
                                      "not semantic equivalence"})
    clusters.sort(key=lambda c: (-c["size"], c["members"][0]["skill_label"]))
    return {"edges": edges, "clusters": clusters, "eligible_skills": len(eligible), "config": ccfg}


# ------------------------------------------------------------------ stage entry

def run(postings, extraction, sources, settings, cfg, occupation_of, run_id):
    icfg = cfg["industry_v2"]
    skills = extraction["skills"]
    eligible_keys = {k for k, s in skills.items() if s["eligible_for_analytics"]}
    counted = [m for m in extraction["posting_mentions"]
               if m["skill_key"] in eligible_keys and m["mention_role"] == "SKILL" and m["sense_established"]]
    pairs = sorted({(m["skill_key"], m["source_uid"]) for m in counted})
    populations = defaultdict(list)
    for p in postings:
        populations[population_of(p, sources)].append(p)
    temporal = {"populations": [], "rows": [], "segments": []}
    for pop_id, members in sorted(populations.items()):
        scope, rows = population_trends(pop_id, members, pairs, skills, sources, settings, icfg["temporal"])
        temporal["populations"].append(scope)
        temporal["rows"] += rows
        # segmented trends: each segment is its own population slice with its own gate
        for dim in icfg["temporal"]["segment_dimensions"]:
            fn = (DIMENSIONS.get(dim) or (lambda p, d=dim: (occupation_of.get(p["posting_uid"]) or {}).get(
                "group" if d == "occupation_group" else "label")))
            groups = defaultdict(list)
            for p in members:
                v = fn(p)
                if v not in (None, "", "None"):
                    groups[str(v)].append(p)
            for value, seg_members in sorted(groups.items()):
                s_scope, _ = population_trends(pop_id, seg_members, pairs, skills, sources, settings, icfg["temporal"],
                                               segment=f"{dim}={value}")
                temporal["segments"].append({k: s_scope[k] for k in ("population_id", "segment", "eligible_postings",
                                                                     "trend_status", "granularity", "date_range")}
                                            | {"missing": s_scope.get("missing", {}).get("have")})
    mention_counts = Counter()
    dims = dimension_demand(postings, pairs, mention_counts, skills, occupation_of, icfg["min_group_postings"], icfg["top_n"])
    return {
        "populations": sorted(populations),
        "temporal": temporal,
        "dimensions": dims,
        "distributions": distributions(postings, icfg["top_n"]),
        "mentions_vs_postings": mention_vs_postings(counted, pairs, skills),
        "clusters": skill_clusters(pairs, skills, len(postings), icfg["clusters"]),
        "denominator": "distinct eligible postings (a skill counted once per posting)",
        "run_id": run_id,
    }
