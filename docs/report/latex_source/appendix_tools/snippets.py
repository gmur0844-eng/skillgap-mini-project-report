"""The code excerpts of Appendix A: verbatim lines of the project source, shared by the LaTeX and Word versions."""
import hashlib, json, sys
from pathlib import Path
ROOT = Path(sys.argv[1])   # copy of the repository files
SNIPPETS = [
 {"id": "A.1", "title": "Relationship label schema",
  "file": "backend/app/knowledge_engine/semantic_provider.py", "ranges": [(33, 44)],
  "text": "The eight labels and the definitions given to the model (Section 2.2, Table 2.1). The reviewer form uses the same eight labels."},
 {"id": "A.2", "title": "Ordered decision procedure of the v4 prompt experiment",
  "file": "backend/app/knowledge_engine/semantic_v3.py", "ranges": [(203, 213)],
  "text": "The decision procedure added in prompt adjudicate-v4 (Section 4.1.2). It was evaluated and not adopted; production uses adjudicate-v3."},
 {"id": "A.3", "title": "Deterministic evidence validator",
  "file": "backend/app/knowledge_engine/semantic_v3.py", "ranges": [(28, 30), (280, 354)],
  "text": "The rules every model answer must pass before it can reach the analysis (Section 4.1.1). Lines 31 to 279 of the file are omitted."},
 {"id": "A.4", "title": "Reading a model decision as downstream would",
  "file": "scripts/semantic/score_against_reviewers.py", "ranges": [(42, 53)],
  "text": "How a recorded decision becomes the validated answer that is scored in Chapters 4 and 5 (Section 3.2.2)."},
 {"id": "A.5", "title": "Cohen's kappa between two reviewers",
  "file": "backend/app/knowledge_engine/semantic_eval.py", "ranges": [(47, 54)],
  "text": "The agreement statistic of Equation 3.4, used for Table 5.6."},
 {"id": "A.6", "title": "Applying the promotion gate",
  "file": "backend/app/knowledge_engine/semantic_eval.py", "ranges": [(257, 292)],
  "text": "Every criterion of semantic-gate-v3 (Table 3.3) is checked; any failure leaves the system in SAFE_MODE (Section 3.2.5)."},
 {"id": "A.7", "title": "Storing an independent label set only with an attestation",
  "file": "scripts/evaluation/semantic_validation.py", "ranges": [(709, 731)],
  "text": "An independent label set cannot be created without a statement that the reviewer answered alone and without AI tools (Section 4.3.4)."},
]
def build():
    out = []
    for s in SNIPPETS:
        src = (ROOT / s["file"]).read_text(encoding="utf-8").splitlines()
        lines = []
        for k, (a, b) in enumerate(s["ranges"]):
            if k:
                lines.append(f"# ... lines {s['ranges'][k-1][1]+1}-{a-1} omitted ...")
            lines.extend(src[a - 1:b])
        rng = ", ".join(f"{a}-{b}" for a, b in s["ranges"])
        out.append({**s, "lines": lines, "range_text": rng,
                    "file_sha256": hashlib.sha256((ROOT / s["file"]).read_bytes()).hexdigest()})
    return out
if __name__ == "__main__":
    data = build()
    Path(sys.argv[2]).write_text(json.dumps(data, indent=1))
    for d in data: print(d["id"], d["file"], d["range_text"], len(d["lines"]), "lines, longest", max(map(len, d["lines"])))
