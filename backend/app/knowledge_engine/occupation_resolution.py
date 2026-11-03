"""
Occupation resolution v2 (improvement release).

  job title + description context (the posting's own established ESCO skills)
      -> occupation candidates (ESCO occupation labels in the title; ESCO occupation skill profiles)
      -> taxonomy evidence (essential / optional skills of each candidate occupation, ISCO groups)
      -> contextual validation (does the posting's content agree with the candidate?)
      -> occupation decision

States: EXACT, VARIANT, CANDIDATE, AMBIGUOUS, UNMAPPED, INSUFFICIENT_EVIDENCE. A title match alone never
overrides contradicting context, and a single occupation is never forced:

  EXACT / VARIANT   the title names an ESCO occupation label. If the posting has enough skills to judge
                    (>= min_context_skills) and NONE of them is in that occupation's ESCO profile while another
                    candidate has >= min_context_overlap profile skills, the decision becomes AMBIGUOUS
                    (context contradicts the title); otherwise it stands, with its context support recorded.
  CANDIDATE         an occupation label sits inside a longer title (a dropped modifier can change the
                    occupation). It is ESTABLISHED BY CONTEXT only when >= min_context_overlap of the posting's
                    skills are in that occupation's ESCO profile; otherwise it stays a candidate (not used).
  AMBIGUOUS         several occupations share the label (or context contradicts the title). Context may
                    single one out (unique best overlap >= min_context_overlap): it is then marked
                    context_preferred and established by context; all candidates are kept.
  UNMAPPED          no occupation label in the title; occupations whose ESCO profiles overlap the posting's
                    skills are listed as skill-profile candidates, never established.
  INSUFFICIENT_EVIDENCE  no occupation label in the title and too few skills to judge.

Scope: ESCO is a European taxonomy; mapping an Indian posting to it describes the posting in ESCO's
vocabulary, it does not make the population European (or US, for O*NET) representative.
No function names an occupation, title word, skill or subject.
"""
from collections import Counter, defaultdict

from app.knowledge_engine import esco_full

STATES = ("EXACT", "VARIANT", "CANDIDATE", "AMBIGUOUS", "UNMAPPED", "INSUFFICIENT_EVIDENCE")
_V1 = {"OCCUPATION_EXACT": "EXACT", "OCCUPATION_VARIANT": "VARIANT", "OCCUPATION_CANDIDATE": "CANDIDATE",
       "OCCUPATION_AMBIGUOUS": "AMBIGUOUS", "OCCUPATION_UNMAPPED": "UNMAPPED"}


def _profile(store, uri):
    o = store["occupations"][uri]
    return set(o["essential_skills"]), set(o["optional_skills"])


def _isco3(store, uri):
    path = esco_full.isco_path(store, uri)
    g3 = next((g for g in path if len(g["code"]) == 3), None)
    return (f"{g3['code']} {g3['label']}" if g3 else None), path


def posting_skills(posting_mentions, skills):
    """posting_uid -> set of ESCO skill URIs with an established SKILL mention (the posting's context)."""
    out = defaultdict(set)
    for m in posting_mentions:
        s = skills.get(m["skill_key"])
        if s and s.get("eligible_for_analytics") and s.get("esco_uri") and m["mention_role"] == "SKILL" and m["sense_established"]:
            out[m["source_uid"]].add(s["esco_uri"])
    return out


def _skill_profile_index(store):
    idx = defaultdict(set)
    for uri, o in store["occupations"].items():
        for s in o["essential_skills"]:
            idx[s].add(uri)
    return idx


def resolve(postings, posting_mentions, skills, store, cfg):
    ocfg = cfg["occupations_v2"]
    index = esco_full.occupation_index(store)
    ctx = posting_skills(posting_mentions, skills)
    prof_index = _skill_profile_index(store)
    rows = []
    for p in sorted(postings, key=lambda x: x["posting_uid"]):
        S = ctx.get(p["posting_uid"], set())
        assessable = len(S) >= ocfg["min_context_skills"]
        r = esco_full.match_occupation(p.get("job_title"), index)
        v1 = _V1[r["status"]]
        title_uris = ([r["occupation_uri"]] if r.get("occupation_uri") else []) + list(r.get("other_candidates") or []) \
            + ([u for u in r.get("candidates") or [] if isinstance(u, str)])
        title_uris = list(dict.fromkeys(title_uris))

        def evidence(uri, source):
            ess, opt = _profile(store, uri)
            group, path = _isco3(store, uri)
            return {"occupation_uri": uri, "label": store["occupations"][uri]["pref_label"], "source": source,
                    "essential_overlap": sorted(S & ess), "optional_overlap": sorted(S & opt),  # noqa: B023 -- called within this iteration
                    "overlap": len(S & (ess | opt)), "profile_size": len(ess | opt),  # noqa: B023 -- called within this iteration
                    "isco_group": group, "isco_major": next((g["code"] + " " + g["label"] for g in path if len(g["code"]) == 1), None)}
        cands = [evidence(u, "title_label") for u in title_uris]
        # skill-profile candidates: occupations whose ESSENTIAL skills include >= min_context_overlap posting skills
        prof_counts = Counter(o for s in S for o in prof_index.get(s, ()))
        prof = [u for u, n in sorted(prof_counts.items(), key=lambda kv: (-kv[1], kv[0]))  # ties ordered, not by hash
                if n >= ocfg["min_context_overlap"] and u not in title_uris]
        prof = sorted(prof, key=lambda u: (-prof_counts[u], store["occupations"][u]["pref_label"]))[: ocfg["max_profile_candidates"]]
        prof_ev = [evidence(u, "skill_profile") for u in prof]
        state, established, chosen, why, context = v1, False, None, r.get("reason"), "NOT_ASSESSABLE"
        best_other = max((c["overlap"] for c in prof_ev), default=0)
        if v1 in ("EXACT", "VARIANT"):
            c = cands[0]
            if assessable and c["overlap"] == 0 and best_other >= ocfg["min_context_overlap"]:
                state, why, context = "AMBIGUOUS", ("title names an occupation, but none of the posting's skills is in its ESCO "
                                                    "profile while another occupation's profile matches; context contradicts the title"), "CONTRADICTED"
            else:
                established, chosen = True, c
                context = ("CONFIRMED" if c["overlap"] >= ocfg["min_context_overlap"] else
                           "NOT_ASSESSABLE" if not assessable else "NEUTRAL")
                why = f"title matches an ESCO occupation label ({v1.lower()}); context {context.lower()}"
        elif v1 == "CANDIDATE":
            c = cands[0]
            if c["overlap"] >= ocfg["min_context_overlap"]:
                established, chosen, context = True, c, "CONFIRMED"
                why = (f"occupation label inside a longer title; {c['overlap']} of the posting's skills are in its ESCO profile "
                       f"(>= {ocfg['min_context_overlap']}): established by context")
            else:
                context = "NOT_ASSESSABLE" if not assessable else "NOT_CONFIRMED"
                why = (f"occupation label inside a longer title (uncovered words: {r.get('uncovered_title_words')}); "
                       f"{c['overlap']} profile skill(s) in the posting -- not established")
        elif v1 == "AMBIGUOUS":
            ranked = sorted(cands, key=lambda c: -c["overlap"])
            if ranked and ranked[0]["overlap"] >= ocfg["min_context_overlap"] and (len(ranked) == 1 or ranked[0]["overlap"] > ranked[1]["overlap"]):
                established, chosen, context = True, ranked[0], "CONFIRMED"
                ranked[0]["context_preferred"] = True
                why = "label shared by several occupations; the posting's skills single one out (context_preferred)"
            else:
                why = "label shared by several occupations; context does not single one out"
        else:  # UNMAPPED
            if not assessable:
                state = "INSUFFICIENT_EVIDENCE"
                why = (f"no ESCO occupation label in the title and {len(S)} established skill(s) in the posting "
                       f"(< {ocfg['min_context_skills']}) -- cannot be judged")
            else:
                why = "no ESCO occupation label in the title; skill-profile candidates listed, not established"
        rows.append({"posting_uid": p["posting_uid"], "job_title": p.get("job_title"), "state": state,
                     "title_match_v1": r["status"], "matched_label": r.get("matched_label"),
                     "established": established, "established_by": (None if not established else
                                                                    "title" if state in ("EXACT", "VARIANT") else "context"),
                     "occupation_uri": chosen["occupation_uri"] if chosen else None,
                     "occupation_label": chosen["label"] if chosen else None,
                     "occupation_group": chosen["isco_group"] if chosen else None,
                     "context_support": context, "posting_context_skills": len(S),
                     "title_candidates": cands, "skill_profile_candidates": prof_ev, "reason": why,
                     "method": "occupation_resolution_v2: ESCO title labels + ESCO occupation skill profiles as context",
                     "taxonomy_scope": "ESCO v1.2.1 (EU taxonomy; describes, does not re-scope, the posting population)"})
    by_state = Counter(r["state"] for r in rows)
    est = [r for r in rows if r["established"]]
    summary = {"postings": len(rows), "by_state": dict(by_state),
               "established": len(est), "established_by_title": sum(1 for r in est if r["established_by"] == "title"),
               "established_by_context": sum(1 for r in est if r["established_by"] == "context"),
               "title_contradicted_by_context": sum(1 for r in rows if r["context_support"] == "CONTRADICTED"),
               "established_share": round(len(est) / len(rows), 4) if rows else None,
               "established_share_title_only": round(sum(1 for r in est if r["established_by"] == "title") / len(rows), 4) if rows else None,
               "distinct_occupations": len({r["occupation_uri"] for r in est}),
               "config": ocfg}
    return rows, summary


def occupation_lookup(rows):
    """posting_uid -> {"label", "group"} for ESTABLISHED occupations only (used to segment demand)."""
    return {r["posting_uid"]: {"label": r["occupation_label"], "group": r["occupation_group"], "uri": r["occupation_uri"]}
            for r in rows if r["established"]}


def occupation_analysis(rows, pairs, skills, store, target_skill_uris, target_depth, gaps_v2, cfg):
    """Demand, curriculum alignment and gaps per occupation and per ISCO group -- each group on its own population."""
    ocfg = cfg["occupations_v2"]
    by_posting = defaultdict(set)
    for k, pid in pairs:
        by_posting[pid].add(k)
    est = [r for r in rows if r["established"]]
    gap_by_key = {g["skill_key"]: g for g in gaps_v2}
    out = {}
    for level, key in (("occupation", "occupation_label"), ("occupation_group", "occupation_group")):
        groups = defaultdict(list)
        for r in est:
            if r[key]:
                groups[r[key]].append(r)
        rows_out = []
        for name, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            n = len(members)
            skill_counts = Counter(k for r in members for k in by_posting.get(r["posting_uid"], ()))
            entry = {"name": name, "postings": n, "occupation_uris": sorted({r["occupation_uri"] for r in members})}
            # taxonomy-profile alignment (independent of posting counts): ESCO essential skills of the occupation(s)
            # that the TARGET curriculum mentions as a direct/partial topic subject
            ess = set().union(*(store["occupations"][u]["essential_skills"] for u in entry["occupation_uris"]))
            covered = sorted(ess & target_skill_uris)
            entry["esco_profile_alignment"] = {
                "essential_skills": len(ess), "mentioned_in_target_curriculum": len(covered),
                "pct": round(100.0 * len(covered) / len(ess), 2) if ess else None,
                "examples": [(store["skills"].get(u) or {}).get("pref_label", u) for u in covered[:8]],
                "basis": "ESCO occupation profile (taxonomy), not posting demand"}
            if n >= ocfg["min_postings_per_group"]:
                demanded = [k for k, c in skill_counts.items() if c >= 2]
                levels = Counter((target_depth.get(k) or {}).get("coverage_level", "NOT_ASSESSED") for k in demanded)
                entry.update(evidence_state="SUFFICIENT",
                             top_skills=[{"skill_key": k, "skill_label": skills[k]["label"], "postings": c,
                                          "demand_pct": round(100.0 * c / n, 2)} for k, c in sorted(skill_counts.items(), key=lambda kv: (-kv[1], skills[kv[0]]["label"], kv[0]))[:ocfg["top_n"]]],
                             curriculum_alignment={"demanded_skills": len(demanded), "target_levels": dict(levels),
                                                   "covered_at_introductory_or_above": sum(levels[x] for x in ("INTRODUCTORY", "SUBSTANTIAL", "ADVANCED"))},
                             gaps=dict(Counter(gap_by_key[k]["classification_v2"] for k in demanded if k in gap_by_key)))
            else:
                entry.update(evidence_state="INSUFFICIENT_EVIDENCE",
                             reason=f"{n} posting(s); demand, alignment and gaps per {level} need >= {ocfg['min_postings_per_group']}")
            rows_out.append(entry)
        out[level] = rows_out
    out["note"] = ("occupations are kept separate unless the ESCO/ISCO hierarchy groups them; technology jobs are never "
                   "treated as one occupation")
    return out
