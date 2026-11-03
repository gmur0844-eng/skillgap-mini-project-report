"""
Manual evidence-chain acceptance test: print the complete chain for one skill
from the latest (or a given) GOLD run, through the read-only service layer.

    job posting -> raw mention (span) -> normalized skill -> ESCO -> industry demand
    -> curriculum topics / concepts / courses -> coverage -> gap -> recommendation
    (or the structured reason why there is none)

Usage: python3 scripts/evaluation/trace_skill.py "SQL" ["Angular" ...] [--run-id ID] [--markdown out.md]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services import knowledge_service as ks  # noqa: E402


def find_key(run, label):
    for key, s in run.industry["skills"].items():
        if s["label"].lower() == label.lower() or label.lower() in [x.lower() for x in s["surfaces"]]:
            return key
    raise SystemExit(f"skill {label!r} not found in run {run.run_id}")


def chain(run, label):
    key = find_key(run, label)
    skill = run.industry["skills"][key]
    demand = next((d for d in run.industry["demand"] if d["skill_key"] == key), None)
    gap = next((g for g in run.industry["gaps"] if g["skill_key"] == key), None)
    rec = next((r for r in run.industry["recommendations"] if r["skill_key"] == key), None)
    trace = ks.evidence_trace(run, key)
    if trace is None:  # traces are stored for recommendations and high-demand gaps; rebuild the posting part here
        postings = {p["posting_uid"]: p for p in ks._jsonl(run.dir / "industry" / "postings.jsonl")}
        mentions = [m for m in ks._jsonl(run.dir / "industry" / "skill_mentions.jsonl")
                    if m["skill_key"] == key and m["mention_role"] == "SKILL"]
        trace = {"job_postings": [{"posting_uid": m["source_uid"], "url": postings[m["source_uid"]]["url"],
                                   "source_file": postings[m["source_uid"]]["source_file"],
                                   "row_number": postings[m["source_uid"]]["row_number"],
                                   "job_title": postings[m["source_uid"]]["job_title"],
                                   "company": postings[m["source_uid"]]["company_name"], "raw_mention": m["raw_mention"],
                                   "span": m["span"], "context": m["context"], "extraction_method": m["method"]}
                                  for m in mentions]}
    coverage = [c for c in run.industry["coverage"] if c["skill_key"] == key]
    raw_mentions = [m for m in ks._jsonl(run.dir / "industry" / "skill_mentions.jsonl")
                    if m["skill_key"] == key and m["mention_role"] == "SKILL"]
    return {"run_id": run.run_id, "skill": skill, "industry_demand": demand, "trace": trace, "raw_mentions": raw_mentions,
            "coverage_by_document_role": coverage, "gap": gap, "recommendation": rec,
            "why_no_recommendation": None if rec else ks.why_no_recommendation(run, key),
            "population_scope": ks._scope_header(run)}


def to_markdown(c):
    s, d, g = c["skill"], c["industry_demand"], c["gap"]
    t = c["trace"] or {}
    lines = [f"### {s['label']}  (`{s['skill_key']}`)", "", f"Run `{c['run_id']}`. {c['population_scope']['representativeness_warning']}", ""]
    posts = t.get("job_postings") or []
    if d is None:
        raw = [m for m in c.get("raw_mentions", [])]
        lines.append(f"1. **Job postings**: {len({m['source_uid'] for m in raw})} postings contain the text, but none counts as "
                     f"demand (ESCO status **{s['esco_status']}**); no demand row, gap or recommendation:")
        for m in raw[:5]:
            ev = m.get("sense_evidence") or {}
            lines.append(f"   - `{m['source_uid']}` `{m['raw_mention']}` chars {m['span'][0]}–{m['span'][1]} — sense "
                         f"**{m['sense_state']}**: “…{m['context'].strip()[:120]}…”")
        if raw and (raw[0].get("sense_evidence") or {}).get("esco_evidence"):
            ev = raw[0]["sense_evidence"]
            lines.append(f"2. **ESCO taxonomy fact (kept)**: {ev['esco_evidence']} — candidate `{ev['esco_uri']}`")
            lines.append(f"3. **Review question**: {ev['question']}")
        return "\n".join(lines) + "\n"
    lines.append(f"1. **Job postings** ({d['posting_count']} of {d['eligible_postings']} eligible supplied postings):")
    for p in posts[:5]:
        lines.append(f"   - `{p['posting_uid']}` {p['source_file']} row {p['row_number']} — {p['job_title']} ({p['company']}) — {p['url']}")
        lines.append(f"     raw mention `{p['raw_mention']}` at chars {p['span'][0]}–{p['span'][1]} via `{p['extraction_method']}`: “…{p['context'].strip()[:140]}…”")
    lines.append(f"2. **Normalized skill**: `{s['skill_uid']}` label “{s['label']}”, surfaces {s['surfaces']}, category {s['skill_category']}")
    lines.append(f"3. **ESCO**: status **{s['esco_status']}**, URI `{s['esco_uri']}`, prefLabel “{s['esco_pref_label']}”, method `{s['mapping_method']}` (delta subset)")
    lines.append(f"4. **Industry demand**: {d['statement']}; company prevalence {d['company_count']}/{d['eligible_companies']} "
                 f"= {d['company_prevalence_pct']}%; support **{d['support_state']}**")
    for cov in c["coverage_by_document_role"]:
        lines.append(f"5. **Curriculum ({cov['role']})**: {cov['courses_with_skill']} of {cov['curriculum_population']} courses "
                     f"({cov['coverage_percentage']}%), courses {cov['course_codes']}, concepts {cov['concept_uids'][:4]}")
        for e in cov["topic_evidence"][:4]:
            lines.append(f"   - {e['course_code']} {e['course_title']} p.{e['page']} {e['unit'] or ''}: “{e['text'][:100]}” (mention `{e['raw_mention']}`)")
    if not c["coverage_by_document_role"]:
        lines.append("5. **Curriculum**: no topic text in the target, previous-version or reference curriculum names this skill")
    lines.append(f"6. **Coverage used for the gap**: {g['curriculum_count']} of {g['curriculum_population']} target courses = {g['curriculum_coverage_pct']}%")
    lines.append(f"7. **Gap**: **{g['classification']}** ({g['evidence_state']}) — " + " ".join(g["reasons"]))
    if c["recommendation"]:
        r = c["recommendation"]
        lines.append(f"8. **Recommendation**: **{r['action_type']}** → {r['target_course_codes']} ({r['evidence_status']}, "
                     f"is_source_evidence={r['is_source_evidence']}); uncertainty: {r['uncertainty']}")
    else:
        lines.append("8. **No recommendation**: " + "; ".join(f"{w['code']}: {w.get('detail', '')}" for w in c["why_no_recommendation"]["reasons"]))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("skills", nargs="+")
    ap.add_argument("--run-id")
    ap.add_argument("--markdown")
    args = ap.parse_args()
    run = ks.KnowledgeRun(args.run_id)
    chains = [chain(run, s) for s in args.skills]
    if args.markdown:
        Path(args.markdown).write_text("\n".join(to_markdown(c) for c in chains), encoding="utf-8")
    print(json.dumps(chains, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
