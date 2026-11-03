#!/usr/bin/env python3
"""Run the experimental layers of the analysis agents over one GOLD run, in the agents' order.

    python3 scripts/pipeline/run_agents.py [--run <run_id>]

The authoritative layers of all five agents run inside the knowledge pipeline
(scripts/pipeline/run_knowledge_pipeline.py). Their experimental layers then run here, each reading the previous
layer's stored output. They write only to data/experiments/<layer>/<run_id>/ and never change the run.

  2 Discipline-to-Industry Relevance   scripts/analysis/relevance_audit.py
  3 Skill Intelligence                 scripts/analysis/skill_evidence_audit.py --final-holdout
  1+4 Curriculum Understanding,
      Skill-Gap Reasoning              scripts/analysis/gap_reasoning_audit.py

The Curriculum Recommendation agent (5) has no separate experimental layer: its existing-course-first reasoning
runs inside the pipeline. A failed layer stops the chain; later layers never run on missing inputs.
Writes data/experiments/agents/<run_id>/manifest.json (each layer's outputs and their sha256).
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAYERS = [
    ("discipline_relevance", ["scripts/analysis/relevance_audit.py"], "relevance"),
    ("skill_intelligence", ["scripts/analysis/skill_evidence_audit.py", "--final-holdout"], "skill_evidence"),
    ("curriculum_understanding+gap_reasoning", ["scripts/analysis/gap_reasoning_audit.py"], "gap_reasoning"),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=json.loads((REPO / "data/gold/knowledge/latest_run.json").read_text())["run_id"])
    args = ap.parse_args()
    if not (REPO / "data/gold/knowledge" / args.run / "run_report.json").exists():
        raise SystemExit(f"run {args.run} has no GOLD outputs; run the knowledge pipeline first")
    manifest = {"run_id": args.run, "layers": []}
    for name, cmd, out_dir in LAYERS:
        t0 = time.time()
        r = subprocess.run([sys.executable, *cmd, "--run", args.run], cwd=REPO, capture_output=True, text=True)
        d = REPO / "data/experiments" / out_dir / args.run
        layer = {"agent": name, "command": " ".join(cmd + ["--run", args.run]), "exit_code": r.returncode,
                 "seconds": round(time.time() - t0, 1),
                 "outputs": {f.name: sha(f) for f in sorted(d.glob("*")) if f.is_file() and f.name != "provenance.json"}
                 if d.exists() else {}}
        manifest["layers"].append(layer)
        print(f"{name}: exit {r.returncode} in {layer['seconds']} s")
        if r.returncode != 0:
            print(r.stdout[-2000:], r.stderr[-4000:], sep="\n")
            break
    ok = all(l["exit_code"] == 0 for l in manifest["layers"]) and len(manifest["layers"]) == len(LAYERS)
    manifest["status"] = "COMPLETE" if ok else "FAILED"
    out = REPO / "data/experiments/agents" / args.run
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(manifest["status"], out / "manifest.json")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
