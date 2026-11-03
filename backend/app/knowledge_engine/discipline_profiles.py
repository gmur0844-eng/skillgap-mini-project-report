"""
Discipline profiles (data/metadata/discipline_profiles.json): one shared engine, configured per discipline.

  resolve(text)            the profile a curriculum's free-text discipline names, or None. Aliases match whole
                           phrases; a short alias ("it", "me", "ce", ...) matches only when it is the whole text. When
                           two different profiles match equally well the result is None: an ambiguous discipline is
                           never guessed.
  comparable(a, b)         may two curricula be compared? Same profile; with no profile, the same normalised text.
  industry_sources_for()   the job-posting sources relevant to a profile (their population is listed in the profile)
  summary()                every profile with its honest support status, computed from the evidence actually present

A profile's knowledge areas and occupation examples are orientation for readers, never demand evidence.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PROFILES_FILE = REPO / "data/metadata/discipline_profiles.json"
SHORT_ALIAS = 3  # aliases this short match only the whole text


def normalise(text):
    t = str(text or "").lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


@lru_cache(maxsize=4)
def _load(path_str, mtime):
    data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    return data


def load(path=None):
    p = Path(path or PROFILES_FILE)
    if not p.exists():
        return {"version": None, "profiles": [], "evidence_populations": {}}
    return _load(str(p), p.stat().st_mtime)


_DEGREE_WORDS = {"b", "tech", "btech", "be", "e", "m", "mtech", "me_degree", "bachelor", "bachelors", "master", "masters",
                 "of", "in", "programme", "program", "hons", "honours", "degree", "ug", "pg"}


def resolve(text, path=None):
    """The profile naming this discipline text, or None (unknown or ambiguous). Two profiles named in separate parts
    of the text ("Computer Science and Information Technology") make it ambiguous."""
    t = normalise(re.sub(r"\([^)]*\)", " ", str(text or "")))  # a bracketed specialisation: "CSE (AI & ML)" -> "cse"
    if not t:
        return None
    core = " ".join(w for w in t.split() if w not in _DEGREE_WORDS)  # "B.Tech CSE" -> "cse"
    matches = []  # (profile id, alias length, span)
    for prof in load(path)["profiles"]:
        for alias in prof.get("aliases", []):
            a = normalise(alias)
            if not a:
                continue
            if len(a) <= SHORT_ALIAS:
                if t == a or core == a:
                    matches.append((prof["id"], len(a), (0, len(t))))
                continue
            m = re.search(rf"\b{re.escape(a)}\b", t)
            if m:
                matches.append((prof["id"], len(a), m.span()))
    if not matches:
        return None
    winner = max(matches, key=lambda m: m[1])
    for pid, _, (s0, e0) in matches:
        ws, we = winner[2]
        if pid != winner[0] and (e0 <= ws or s0 >= we):
            return None  # another discipline named elsewhere in the text: ambiguous, never guessed
    if any(m[0] != winner[0] and m[1] == winner[1] for m in matches):
        return None
    return next(p for p in load(path)["profiles"] if p["id"] == winner[0])


def profile_ref(profile):
    """What a run records about the profile it used (id, version, registry version)."""
    if profile is None:
        return None
    return {"id": profile["id"], "version": profile.get("version"), "name": profile["name"],
            "registry_version": load().get("version")}


def comparable(discipline_a, discipline_b, path=None):
    """Two curricula are comparable when they resolve to the same profile; when either has no profile, only when
    their discipline texts are the same."""
    pa, pb = resolve(discipline_a, path), resolve(discipline_b, path)
    if pa is not None and pb is not None:
        return pa["id"] == pb["id"]
    return bool(normalise(discipline_a)) and normalise(discipline_a) == normalise(discipline_b)


def industry_sources_for(profile, job_sources):
    """(relevant, excluded) job sources for a profile; with no profile, none is relevant."""
    wanted = set((profile or {}).get("industry_populations") or [])
    relevant = [j for j in job_sources if j.get("population_id") in wanted]
    excluded = [j for j in job_sources if j.get("population_id") not in wanted]
    return relevant, excluded


def not_applicable_industry_reason(discipline, profile):
    name = profile["name"] if profile else (discipline or "this discipline")
    if profile is None:
        return (f"the discipline '{discipline}' does not match a discipline profile, so no job-posting evidence can be "
                "judged relevant to it; add it as an alias of the right profile (data/metadata/discipline_profiles.json)")
    return (f"no job-posting evidence relevant to {name} has been supplied (the available postings are not evidence of "
            f"this discipline's demand); the curriculum is analysed on its own")


def summary(manifest=None, path=None):
    """Every profile with what the analysis can actually do for it, from the evidence present in `manifest`."""
    data = load(path)
    manifest = manifest or {}
    pops = data.get("evidence_populations") or {}
    sources = list(manifest.get("industry_sources") or [])
    docs = list(manifest.get("documents") or [])
    out = []
    for prof in data["profiles"]:
        relevant, _ = industry_sources_for(prof, sources)
        same = [d for d in docs if (resolve(d.get("discipline"), path) or {}).get("id") == prof["id"]]
        refs = [d["doc_id"] for d in same if d.get("role") == "REFERENCE"]
        peers = [d["doc_id"] for d in same if d.get("role") == "PEER"]
        out.append({
            "id": prof["id"], "name": prof["name"], "short": prof.get("short"), "version": prof.get("version"),
            "aliases": prof.get("aliases", []), "specialisations": prof.get("specialisations", []),
            "knowledge_areas": prof.get("knowledge_areas", []), "occupation_examples": prof.get("occupation_examples", []),
            "capabilities": {
                "curriculum_analysis": "AVAILABLE",
                "industry_analysis": "AVAILABLE" if relevant else "NO_RELEVANT_EVIDENCE",
                "reference_mapping": "AVAILABLE" if refs else "NO_REFERENCE_CURRICULUM",
                "peer_comparison": "AVAILABLE" if peers else "NO_PEER_CURRICULUM",
            },
            "evidence": {"industry_sources": len(relevant),
                         "industry_populations": [{"population_id": p, **pops.get(p, {})}
                                                  for p in prof.get("industry_populations", [])],
                         "reference_curricula": refs, "peer_curricula": peers},
            "validation": prof.get("validation"),
            "orientation_note": "knowledge areas and occupation examples describe the discipline; they are not "
                                "evidence of demand",
        })
    return {"version": data.get("version"), "profiles": out}


# ---- the pipeline's discipline guard (pipeline.py calls these; kept here so they are tested on their own) ----
INDUSTRY_GATES = ("industry_gap", "industry_demand", "recommendations", "skill_taxonomy")


def scope_industry(documents, job_sources, path=None):
    """(target profile, job sources to use, exclusion record or None). Job postings whose population is not listed in
    the analysed curriculum's profile are left out; with no TARGET nothing is changed."""
    target = next((d for d in documents if d.get("role") == "TARGET"), None)
    if target is None:
        return None, list(job_sources), None
    profile = resolve(target.get("discipline"), path)
    if not job_sources:
        return profile, [], None
    relevant, excluded = industry_sources_for(profile, job_sources)
    if not excluded:
        return profile, relevant, None
    return profile, relevant, {
        "excluded_sources": sorted(j["source_id"] for j in excluded),
        "reason": (not_applicable_industry_reason(target.get("discipline"), profile) if not relevant else
                   "job-posting populations not listed for this discipline's profile were left out")}


def not_comparable_documents(documents, path=None):
    """PEER and REFERENCE curricula of another discipline than the TARGET's: they are not compared with it."""
    target = next((d for d in documents if d.get("role") == "TARGET"), None)
    if target is None:
        return []
    return [d for d in documents if d.get("role") in ("PEER", "REFERENCE")
            and not comparable(d.get("discipline"), target.get("discipline"), path)]


def apply_gates(gates, not_comparable, remaining, industry_exclusion, job_sources_left):
    """Analyses whose evidence does not belong to the curriculum's discipline become NOT_APPLICABLE, with the reason.
    `remaining` = {"PEER": [...], "REFERENCE": [...]} comparable usable curricula left after the guard."""
    if industry_exclusion and not job_sources_left:
        for name in INDUSTRY_GATES:
            gates[name] = {"status": "NOT_APPLICABLE", "reasons": [industry_exclusion["reason"]]}
    for role, gate_name in (("PEER", "peer_benchmark"), ("REFERENCE", "reference_mapping")):
        dropped = [d["doc_id"] for d in not_comparable if d["role"] == role]
        if not dropped:
            continue
        if remaining.get(role):
            gates.setdefault(gate_name, {"status": "ALLOWED", "reasons": []})["not_comparable"] = dropped
            continue
        reason = (f"the supplied {role.lower()} curricula ({', '.join(dropped)}) are of another discipline, so none "
                  "is compared with this curriculum")
        gates[gate_name] = {"status": "NOT_APPLICABLE", "reasons": [reason], "not_comparable": dropped}
        if role == "REFERENCE":
            # gap classification and its recommendations are defined against a reference curriculum of the same
            # discipline; without one they do not apply (they are not failed requirements)
            for name in ("industry_gap", "recommendations"):
                if (gates.get(name) or {}).get("status") == "BLOCKED":
                    gates[name] = {"status": "NOT_APPLICABLE", "reasons": [
                        "gap classification needs a reference curriculum of the same discipline; " + reason]}
    return gates
