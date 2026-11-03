"""
Full ESCO classification (v1.2.1, English, CSV) -> an in-memory ESCO knowledge store.

The FULL classification is the current taxonomy; the DELTA (esco_delta.py) is change
information only. Neither replaces the other:

  full  -> concepts, labels, descriptions, types, hierarchies, occupation-skill and
           skill-skill relations, collections, concept schemes (what ESCO IS)
  delta -> which English labels were Added / Updated / Removed in v1.2.1 (what CHANGED)

Field meanings are taken from the dictionary shipped inside the ZIP (dictionary_en.csv,
which names the RDF property of every column) and from the ESCO Model 2.0.0 documentation;
see docs/ESCO_INTEGRATION.md. Nothing here names a skill, occupation or subject.

Separators (observed in the files, recorded in the audit):
  skills_en / occupations_en / skillGroups_en  altLabels, hiddenLabels: newline
  *Collection_en files                          altLabels, broaderConcept*: " | "
  inScheme                                      comma and/or newline
Duplicate concept rows (same URI, differing only in modifiedDate) are collapsed to the row
with the latest modifiedDate; the collapse is counted in the audit.
"""
import csv
import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict

from app.pipelines.preprocessing.skill_normalization import normalize_skill_text as normalize_label

csv.field_size_limit(10 ** 9)

_QUALIFIER_RE = re.compile(r"^(?P<base>[^()]+?)\s*\((?P<qualifier>[^()]+)\)\s*$")
_WS_RE = re.compile(r"\s+")

REQUIRED_FILES = ("skills_en.csv", "occupations_en.csv", "skillGroups_en.csv", "ISCOGroups_en.csv",
                  "broaderRelationsSkillPillar_en.csv", "broaderRelationsOccPillar_en.csv",
                  "occupationSkillRelations_en.csv", "skillSkillRelations_en.csv", "skillsHierarchy_en.csv",
                  "conceptSchemes_en.csv", "dictionary_en.csv")
COLLECTION_FILES = ("digitalSkillsCollection_en.csv", "digCompSkillsCollection_en.csv", "greenSkillsCollection_en.csv",
                    "languageSkillsCollection_en.csv", "researchSkillsCollection_en.csv",
                    "transversalSkillsCollection_en.csv", "researchOccupationsCollection_en.csv")


def _clean(text):
    return _WS_RE.sub(" ", (text or "").replace(" ", " ")).strip()


def _split(value, sep):
    if not value:
        return []
    parts = re.split(sep, value)
    return [p for p in (_clean(x) for x in parts) if p]


def _split_lines(value):
    return _split(value, r"\n")


def _split_pipe(value):
    return _split(value, r"\s\|\s")


def _split_scheme(value):
    return _split(value, r"[,\n]+")


def read_classification(zip_path):
    """{filename: [row dict]} for every CSV in the ZIP, plus the member list and hashes."""
    tables, members = {}, []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            raw = zf.read(info)
            name = info.filename.rsplit("/", 1)[-1]
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text, newline=""))
            tables[name] = list(reader)
            members.append({"file": name, "bytes": info.file_size, "sha256": hashlib.sha256(raw).hexdigest(),
                            "rows": len(tables[name]), "columns": reader.fieldnames})
    return tables, sorted(members, key=lambda m: m["file"])


def _dedupe(rows, audit_key, audit):
    by_uri = {}
    dup = 0
    for r in rows:
        uri = r["conceptUri"].strip()
        if uri in by_uri:
            dup += 1
            if (r.get("modifiedDate") or "") > (by_uri[uri].get("modifiedDate") or ""):
                by_uri[uri] = r
        else:
            by_uri[uri] = r
    audit["duplicate_rows_collapsed"][audit_key] = dup
    return by_uri


def build_store(tables, members=None):
    """Normalised ESCO store + audit. Raises KeyError naming a missing required file."""
    missing = [f for f in REQUIRED_FILES if f not in tables]
    if missing:
        raise KeyError(f"ESCO classification is missing required files: {missing}")
    audit = {"files": members or [], "duplicate_rows_collapsed": {}, "integrity": {}}

    skills_raw = _dedupe(tables["skills_en.csv"], "skills_en.csv", audit)
    occ_raw = _dedupe(tables["occupations_en.csv"], "occupations_en.csv", audit)
    groups_raw = _dedupe(tables["skillGroups_en.csv"], "skillGroups_en.csv", audit)
    isco_raw = _dedupe(tables["ISCOGroups_en.csv"], "ISCOGroups_en.csv", audit)

    skills = {}
    for uri, r in sorted(skills_raw.items()):
        skills[uri] = {
            "uri": uri, "kind": "skill", "pref_label": _clean(r["preferredLabel"]),
            "alt_labels": _split_lines(r.get("altLabels")), "hidden_labels": _split_lines(r.get("hiddenLabels")),
            "skill_type": _clean(r.get("skillType")) or None, "reuse_level": _clean(r.get("reuseLevel")) or None,
            "status": _clean(r.get("status")) or None, "modified": _clean(r.get("modifiedDate")) or None,
            "description": _clean(r.get("description")) or None, "scope_note": _clean(r.get("scopeNote")) or None,
            "definition": _clean(r.get("definition")) or None, "in_scheme": _split_scheme(r.get("inScheme")),
            "collections": [], "broader": [], "narrower": [],
        }
    groups = {}
    for uri, r in sorted(groups_raw.items()):
        groups[uri] = {"uri": uri, "kind": "skill_group", "pref_label": _clean(r["preferredLabel"]),
                       "alt_labels": _split_lines(r.get("altLabels")), "hidden_labels": _split_lines(r.get("hiddenLabels")),
                       "code": _clean(r.get("code")) or None, "status": _clean(r.get("status")) or None,
                       "description": _clean(r.get("description")) or None, "scope_note": _clean(r.get("scopeNote")) or None,
                       "in_scheme": _split_scheme(r.get("inScheme")), "broader": [], "narrower": []}
    occupations = {}
    for uri, r in sorted(occ_raw.items()):
        occupations[uri] = {"uri": uri, "kind": "occupation", "pref_label": _clean(r["preferredLabel"]),
                            "alt_labels": _split_lines(r.get("altLabels")), "hidden_labels": _split_lines(r.get("hiddenLabels")),
                            "isco_code": _clean(r.get("iscoGroup")) or None, "code": _clean(r.get("code")) or None,
                            "status": _clean(r.get("status")) or None, "description": _clean(r.get("description")) or None,
                            "regulated": (_clean(r.get("regulatedProfessionNote")).rsplit("/", 1)[-1] or None),
                            "nace": _split_scheme(r.get("naceCode")), "in_scheme": _split_scheme(r.get("inScheme")),
                            "broader": [], "narrower": [], "essential_skills": [], "optional_skills": []}
    isco = {}
    for uri, r in sorted(isco_raw.items()):
        isco[uri] = {"uri": uri, "kind": "isco_group", "code": _clean(r["code"]), "pref_label": _clean(r["preferredLabel"]),
                     "description": _clean(r.get("description")) or None, "broader": [], "narrower": []}
    isco_by_code = {g["code"]: uri for uri, g in isco.items()}

    all_nodes = {**skills, **groups, **occupations, **isco}
    dangling = Counter()

    # ---- hierarchies (skos:broader, as exported)
    for fname in ("broaderRelationsSkillPillar_en.csv", "broaderRelationsOccPillar_en.csv"):
        seen = set()
        dups = 0
        for r in tables[fname]:
            child, parent = r["conceptUri"].strip(), r["broaderUri"].strip()
            if (child, parent) in seen:
                dups += 1
                continue
            seen.add((child, parent))
            if child not in all_nodes or parent not in all_nodes:
                dangling[fname] += 1
                continue
            all_nodes[child]["broader"].append(parent)
            all_nodes[parent]["narrower"].append(child)
        audit["duplicate_rows_collapsed"][fname] = dups

    # ---- occupation -> skill (esco:relatedEssentialSkill / relatedOptionalSkill)
    occ_skill = []
    seen = set()
    for r in tables["occupationSkillRelations_en.csv"]:
        o, s, rel = r["occupationUri"].strip(), r["skillUri"].strip(), _clean(r["relationType"])
        if (o, s, rel) in seen:
            continue
        seen.add((o, s, rel))
        if o not in occupations or s not in skills:
            dangling["occupationSkillRelations_en.csv"] += 1
            continue
        occupations[o]["essential_skills" if rel == "essential" else "optional_skills"].append(s)
        occ_skill.append({"occupation_uri": o, "skill_uri": s, "relation": rel})

    # ---- skill -> skill (originalSkill esco:related{Essential,Optional}Skill relatedSkill)
    skill_skill = []
    self_rel = 0
    for r in tables["skillSkillRelations_en.csv"]:
        a, b, rel = r["originalSkillUri"].strip(), r["relatedSkillUri"].strip(), _clean(r["relationType"])
        if a == b:
            self_rel += 1
        if a not in skills or b not in skills:
            dangling["skillSkillRelations_en.csv"] += 1
            continue
        skill_skill.append({"skill_uri": a, "related_skill_uri": b, "relation": rel})

    # ---- collections (membership tags)
    collection_counts = {}
    for fname in COLLECTION_FILES:
        rows = tables.get(fname, [])
        name = fname.replace("_en.csv", "")
        n = 0
        for r in rows:
            uri = r["conceptUri"].strip()
            node = skills.get(uri) or occupations.get(uri)
            if node is None:
                dangling[fname] += 1
                continue
            node.setdefault("collections", []).append(name)
            n += 1
        collection_counts[name] = n

    # ---- ISCO link for occupations (code column)
    unknown_isco = 0
    for o in occupations.values():
        o["isco_uri"] = isco_by_code.get(o["isco_code"])
        if o["isco_code"] and o["isco_uri"] is None:
            unknown_isco += 1

    schemes = [{"uri": r["conceptSchemeUri"].strip(), "pref_label": _clean(r["preferredLabel"]),
                "title": _clean(r.get("title")) or None, "status": _clean(r.get("status")) or None,
                "description": _clean(r.get("description")) or None,
                "top_concepts": len(_split_scheme(r.get("hasTopConcept"))) }
               for r in tables["conceptSchemes_en.csv"]]

    # ---- integrity (facts about the supplied files; nothing is repaired silently)
    cycles = _broader_cycles({**skills, **groups})
    occ_cycles = _broader_cycles({**occupations, **isco})
    audit["integrity"] = {
        "dangling_references_by_file": dict(sorted(dangling.items())),
        "skill_skill_self_relations": self_rel,
        "occupations_with_unknown_isco_code": unknown_isco,
        "skill_pillar_broader_cycles": len(cycles), "occupation_pillar_broader_cycles": len(occ_cycles),
        "cycle_examples": [c[:6] for c in (cycles + occ_cycles)[:3]],
        "skills_without_broader": sum(1 for s in skills.values() if not s["broader"]),
        "occupations_without_skills": sum(1 for o in occupations.values()
                                          if not o["essential_skills"] and not o["optional_skills"]),
        "skills_used_by_no_occupation": len(set(skills) - {x["skill_uri"] for x in occ_skill}),
        "status_values": _keyed(Counter(n.get("status") for n in all_nodes.values())),
    }
    audit["counts"] = {
        "skills": len(skills), "skill_groups": len(groups), "occupations": len(occupations), "isco_groups": len(isco),
        "skills_by_type": _keyed(Counter(s["skill_type"] for s in skills.values())),
        "skills_by_reuse_level": _keyed(Counter(s["reuse_level"] for s in skills.values())),
        "skill_broader_edges": sum(len(s["broader"]) for s in skills.values()),
        "skill_group_broader_edges": sum(len(g["broader"]) for g in groups.values()),
        "occupation_broader_edges": sum(len(o["broader"]) for o in occupations.values()),
        "isco_broader_edges": sum(len(g["broader"]) for g in isco.values()),
        "occupation_skill_relations": dict(Counter(x["relation"] for x in occ_skill)),
        "skill_skill_relations": dict(Counter(x["relation"] for x in skill_skill)),
        "collections": collection_counts, "concept_schemes": len(schemes),
        "skill_labels": {"prefLabel": len(skills), "altLabel": sum(len(s["alt_labels"]) for s in skills.values()),
                         "hiddenLabel": sum(len(s["hidden_labels"]) for s in skills.values())},
        "occupation_labels": {"prefLabel": len(occupations),
                              "altLabel": sum(len(o["alt_labels"]) for o in occupations.values()),
                              "hiddenLabel": sum(len(o["hidden_labels"]) for o in occupations.values())},
    }
    return {"skills": skills, "skill_groups": groups, "occupations": occupations, "isco_groups": isco,
            "occupation_skill": occ_skill, "skill_skill": skill_skill, "concept_schemes": schemes}, audit


def _keyed(counter):
    """JSON-safe counts: a missing value is reported as UNSPECIFIED, never dropped."""
    return {("UNSPECIFIED" if k is None else k): v for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def _broader_cycles(nodes):
    """Cycles in the broader graph (iterative DFS; returns node lists)."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {u: WHITE for u in nodes}
    cycles = []
    for root in nodes:
        if colour[root] != WHITE:
            continue
        stack = [(root, iter(nodes[root]["broader"]))]
        path = [root]
        colour[root] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[node] = BLACK
                stack.pop()
                path.pop()
                continue
            if nxt not in colour:
                continue
            if colour[nxt] == GREY:
                cycles.append(path[path.index(nxt):] + [nxt])
            elif colour[nxt] == WHITE:
                colour[nxt] = GREY
                stack.append((nxt, iter(nodes[nxt]["broader"])))
                path.append(nxt)
    return cycles


# ------------------------------------------------------------------ matching vocabulary

def skill_vocabulary(store, delta_vocab=None):
    """
    Same shape as esco_delta.build_skill_vocabulary ({concepts, labels, retired_labels}) so the
    extractor and mapper are unchanged, built from the FULL taxonomy. Skill groups are NOT
    matching targets (they are categories, not skills). The delta, when given, only annotates
    labels (delta_action) and supplies retired labels; a retired label that the full taxonomy
    still lists for the same concept is reported as a conflict and not retired.
    """
    concepts, labels = {}, []
    for uri, s in store["skills"].items():
        concepts[uri] = {"uri": uri, "pref_label": s["pref_label"], "skill_type": s["skill_type"],
                         "reuse_level": s["reuse_level"], "skill_type_change": None}
    delta_alt = {}
    if delta_vocab:
        for lab in delta_vocab["labels"]:
            if lab["label_kind"] == "altLabel":
                delta_alt[(lab["uri"], lab["label"])] = lab["delta_action"]
        for uri, c in delta_vocab["concepts"].items():
            if uri in concepts and c.get("skill_type_change"):
                concepts[uri]["skill_type_change"] = c["skill_type_change"]
    for uri, s in store["skills"].items():
        labels.append({"uri": uri, "label": s["pref_label"], "label_kind": "prefLabel", "delta_action": None})
        m = _QUALIFIER_RE.match(s["pref_label"])
        if m and len(m.group("base").split()) <= 3:
            labels.append({"uri": uri, "label": m.group("base").strip(), "label_kind": "qualifier_stripped",
                           "delta_action": None, "qualifier": m.group("qualifier").strip()})
        for kind, values in (("altLabel", s["alt_labels"]), ("hiddenLabel", s["hidden_labels"])):
            for v in sorted(set(values)):
                if v == s["pref_label"]:
                    continue
                labels.append({"uri": uri, "label": v, "label_kind": kind,
                               "delta_action": delta_alt.get((uri, v)) if kind == "altLabel" else None})
    retired, conflicts = [], []
    if delta_vocab:
        present = defaultdict(set)
        for lab in labels:
            present[lab["uri"]].add(lab["label"])
        for r in delta_vocab["retired_labels"]:
            if r["uri"] in concepts and r["label"] in present[r["uri"]]:
                conflicts.append({**r, "full_taxonomy_still_lists_label": True})
            else:
                retired.append(r)
    audit = {
        "matching_concepts": len(concepts),
        "labels_by_kind": dict(Counter(l["label_kind"] for l in labels)),
        "labels_annotated_with_delta_action": sum(1 for l in labels if l.get("delta_action")),
        "retired_labels_from_delta": len(retired),
        "delta_retired_labels_still_in_full": len(conflicts),
        "delta_concepts_absent_from_full_skills": (sum(1 for u in delta_vocab["concepts"] if u not in concepts)
                                                   if delta_vocab else None),
        "reconstruction_scope": "FULL_TAXONOMY",
    }
    return {"concepts": concepts, "labels": labels, "retired_labels": retired, "retired_conflicts": conflicts,
            "scope": "FULL_TAXONOMY"}, audit


def delta_vs_full(store, delta_vocab):
    """Factual comparison of the delta-reconstructed subset with the full taxonomy."""
    skills, groups, occs = store["skills"], store["skill_groups"], store["occupations"]
    d = set(delta_vocab["concepts"])
    in_skills = d & set(skills)
    return {
        "delta_reconstructed_concepts": len(d),
        "present_as_full_skill": len(in_skills),
        "present_as_full_skill_group": len(d & set(groups)),
        "present_as_full_occupation": len(d & set(occs)),
        "absent_from_full_classification": len(d - set(skills) - set(groups) - set(occs)),
        "full_skills_not_in_delta": len(set(skills) - d),
        "pref_label_equal": sum(1 for u in in_skills if delta_vocab["concepts"][u]["pref_label"] == skills[u]["pref_label"]),
        "note": ("Skill-group URIs use the same /skill/ URI form as skills, so the delta alone cannot tell them apart; "
                 "the full taxonomy can. Concepts absent from the full classification files have delta rows but no row "
                 "in skills/skillGroups/occupations; the files do not state why."),
    }


# ------------------------------------------------------------------ occupations

def occupation_index(store):
    """{normalized label: [(uri, label_kind)]} over occupation pref/alt/hidden labels."""
    idx = defaultdict(list)
    for uri, o in store["occupations"].items():
        for kind, vals in (("prefLabel", [o["pref_label"]]), ("altLabel", o["alt_labels"]), ("hiddenLabel", o["hidden_labels"])):
            for v in vals:
                key = normalize_label(v)
                if key and (uri, kind) not in idx[key]:
                    idx[key].append((uri, kind))
    return dict(idx)


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.]*")
_SEGMENT_RE = re.compile(r"\s[-\u2013\u2014|/]+\s|[(),:;|\[\]]+|\|\|")


def _stem(token):
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token


def match_occupation(title, index, max_label_tokens=8):
    """
    Map a job title to ESCO occupations using only ESCO labels. The title is split into
    segments at punctuation; each segment is compared with occupation labels.

      OCCUPATION_EXACT       a whole segment equals an occupation label
      OCCUPATION_VARIANT     a whole segment differs from a label only by a plural "s" on some tokens
                             ("human resource manager" / "human resources manager"); character
                             similarity alone is NOT used ("account manager" != "accounting manager")
      OCCUPATION_CANDIDATE   only a multi-word label INSIDE a segment matches; the uncovered words
                             of the segment are recorded. Not established: a dropped modifier can
                             change the occupation ("human resource manager" -> "resource manager").
      OCCUPATION_AMBIGUOUS   the label belongs to more than one occupation and none has it as prefLabel
      OCCUPATION_UNMAPPED    nothing matches
    """
    norm_title = normalize_label(title or "")
    if not norm_title:
        return {"status": "OCCUPATION_UNMAPPED", "reason": "empty title", "candidates": []}
    segments = [normalize_label(x) for x in _SEGMENT_RE.split((title or "").lower())]
    segments = [x for x in segments if x] or [norm_title]
    best = None  # (rank, covered tokens, label, status, uncovered)
    for seg in segments:
        tokens = _TOKEN_RE.findall(seg)
        if not tokens:
            continue
        joined = " ".join(tokens)
        if joined in index:
            cand = (3, len(tokens), joined, "OCCUPATION_EXACT", [])
        else:
            cand = None
            if len(tokens) >= 2:
                for key in _labels_by_shape(index).get((len(tokens), _stem(tokens[-1])), ()):
                    if key != joined and all(_stem(a) == _stem(b) for a, b in zip(tokens, key.split())):
                        cand = (2, len(tokens), key, "OCCUPATION_VARIANT", [])
                        break
            if cand is None:
                for n in range(min(max_label_tokens, len(tokens) - 1), 1, -1):
                    hit = next((i for i in range(0, len(tokens) - n + 1) if " ".join(tokens[i:i + n]) in index), None)
                    if hit is not None:
                        cand = (1, n, " ".join(tokens[hit:hit + n]), "OCCUPATION_CANDIDATE",
                                tokens[:hit] + tokens[hit + n:])
                        break
        if cand and (best is None or cand[:2] > best[:2]):
            best = cand
    if not best:
        return {"status": "OCCUPATION_UNMAPPED", "reason": "no ESCO occupation label matches a title segment",
                "candidates": []}
    _, _, label, status, uncovered = best
    entries = index[label]
    uris = sorted({u for u, _ in entries})
    pref = sorted({u for u, k in entries if k == "prefLabel"})
    if len(uris) > 1 and len(pref) != 1:
        return {"status": "OCCUPATION_AMBIGUOUS", "matched_label": label, "candidates": uris,
                "reason": "label belongs to more than one ESCO occupation"}
    chosen = pref[0] if len(uris) > 1 else uris[0]
    return {"status": status, "matched_label": label, "occupation_uri": chosen, "uncovered_title_words": uncovered,
            "label_kinds": sorted({k for u, k in entries if u == chosen}),
            "other_candidates": [u for u in uris if u != chosen],
            "established": status in OCCUPATION_ESTABLISHED,
            "reason": ("prefLabel precedence over other concepts' alt/hidden labels" if len(uris) > 1 else "single match")}


OCCUPATION_ESTABLISHED = ("OCCUPATION_EXACT", "OCCUPATION_VARIANT")
_SHAPE_CACHE = {}


def _labels_by_shape(index):
    key = id(index)
    if key not in _SHAPE_CACHE:
        shapes = defaultdict(list)
        for lab in index:
            toks = lab.split()
            if len(toks) >= 2:
                shapes[(len(toks), _stem(toks[-1]))].append(lab)
        _SHAPE_CACHE.clear()
        _SHAPE_CACHE[key] = shapes
    return _SHAPE_CACHE[key]


def isco_path(store, occupation_uri):
    """ISCO ancestors (most specific first) of an occupation via the broader hierarchy."""
    out, seen = [], set()
    frontier = list(store["occupations"][occupation_uri]["broader"])
    while frontier:
        u = frontier.pop(0)
        if u in seen:
            continue
        seen.add(u)
        node = store["isco_groups"].get(u) or store["occupations"].get(u)
        if node is None:
            continue
        if node["kind"] == "isco_group":
            out.append({"uri": u, "code": node["code"], "label": node["pref_label"]})
        frontier.extend(node["broader"])
    return sorted(out, key=lambda g: -len(g["code"]))


def skill_group_path(store, skill_uri, max_depth=12):
    """Skill-pillar ancestors (skill groups) of a skill, nearest first."""
    out, seen = [], set()
    frontier = [(u, 1) for u in store["skills"][skill_uri]["broader"]]
    while frontier:
        u, d = frontier.pop(0)
        if u in seen or d > max_depth:
            continue
        seen.add(u)
        node = store["skill_groups"].get(u) or store["skills"].get(u)
        if node is None:
            continue
        out.append({"uri": u, "label": node["pref_label"], "kind": node["kind"], "code": node.get("code"), "depth": d})
        frontier.extend((b, d + 1) for b in node["broader"])
    return out
