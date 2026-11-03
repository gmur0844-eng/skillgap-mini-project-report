"""Blind human-review set for the Phase 6 gap states (prepares Phase 11; no labels are produced here).

    python3 scripts/analysis/gap_review_sample.py

Every analytically eligible skill of the release run goes into the review set, shown with its curriculum evidence and
demand but WITHOUT the system's state. The system states are written to a separate file, hashed, so agreement can be
computed after review without the reviewer seeing them.

Writes data/evaluation/gap_state_review_v1/{review_items.csv, system_states.jsonl, MANIFEST.json}.
"""
import csv
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN = json.loads((REPO / "data/gold/knowledge/latest_run.json").read_text())["run_id"]
SRC = REPO / "data/experiments/gap_reasoning" / RUN
OUT = REPO / "data/evaluation/gap_state_review_v1"


def main():
    stages = {json.loads(l)["skill_key"]: json.loads(l) for l in (SRC / "skill_stages.jsonl").read_text().splitlines() if l}
    gaps = [json.loads(l) for l in (SRC / "gap_states.jsonl").read_text().splitlines() if l]
    items = sorted((g for g in gaps if stages[g["skill_key"]]["eligible"]), key=lambda g: hashlib.sha256(
        g["skill_key"].encode()).hexdigest())
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "review_items.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id", "skill", "postings", "companies", "courses_naming_or_teaching_it", "coverage_evidence",
                    "course_access", "practical_evidence", "other_curricula", "reviewer_state", "reviewer_confidence",
                    "reviewer_note"])
        for i, g in enumerate(items, 1):
            st = stages[g["skill_key"]]
            ev = "; ".join(f"{k} x{v}" for k, v in (g.get("evidence_types") or {}).items()) or "none found"
            other = "; ".join(f"{role}: {txt}" for role, txt in (g.get("corroboration") or {}).get("summary", {}).items())
            w.writerow([f"G{i:03d}", g["skill_label"], st["postings"], st["companies"], ", ".join(g["carrying_courses"]),
                        ev, g["access"], g["practice"], other, "", "", ""])
    with open(OUT / "system_states.jsonl", "w") as fh:
        for i, g in enumerate(items, 1):
            fh.write(json.dumps({"item_id": f"G{i:03d}", "skill_key": g["skill_key"], "gap_state": g["gap_state"]},
                                sort_keys=True) + "\n")
    manifest = {"run_id": RUN, "items": len(items), "states": ["NO_GAP", "LIMITED_COVERAGE", "DEPTH_GAP",
                                                                   "STRUCTURAL_GAP", "INSUFFICIENT_EVIDENCE",
                                                                   "REVIEW_REQUIRED", "OUTDATED_COVERAGE"],
                "instructions": "Read the syllabus for each skill and choose the state you would assign; do not open "
                                "system_states.jsonl before finishing. Two reviewers, independently.",
                "system_states_sha256": hashlib.sha256((OUT / "system_states.jsonl").read_bytes()).hexdigest(),
                "label_source": "none yet (human labels pending, Phase 11)"}
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
