"""
Verify a real local LLM endpoint end-to-end WITHOUT changing the engine:

  1. the endpoint answers and the model is installed (Ollama /api/tags or OpenAI-compatible /v1/models)
  2. a tiny request returns parseable JSON (latency measured)
  3. the EXISTING SemanticModelProvider classes + Adjudicator produce decision records for one test case
     (passed here as data; nothing is added to production logic)
  4. memory reported by the runtime when it exposes it (Ollama /api/ps)

Usage (on the machine that runs the model, from the repository root):
    python3 scripts/semantic/probe_llm_endpoint.py --kind ollama --base-url http://127.0.0.1:11434 --model qwen2.5:7b-instruct
    python3 scripts/semantic/probe_llm_endpoint.py --kind openai_compatible --base-url http://127.0.0.1:1234 --model <id>

Decisions go to a temporary cache directory, never to data/cache. Output: a JSON report on stdout.
"""
import argparse
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import semantic_provider as sp  # noqa: E402

TEST_CASES = [  # data for this probe only
    {"kind": "PROBE", "left": "Angular", "left_context": "Web Programming, TypeScript, components, routing",
     "right": "Angular", "right_context": "candidate concept: Angular, a TypeScript web application framework",
     "question": "Does LEFT, in its context, denote the RIGHT concept?", "expected": "SAME_CONCEPT"},
    {"kind": "PROBE", "left": "Angular", "left_context": "Web Programming, TypeScript, components, routing",
     "right": "Angular momentum", "right_context": "alternative concept: angular momentum, a quantity in rotational physics",
     "question": "Does LEFT, in its context, denote the RIGHT concept?", "expected": "UNRELATED"},
]


def get(url, timeout=5):
    t = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = json.loads(r.read().decode())
    return body, round(time.perf_counter() - t, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["ollama", "openai_compatible"], required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args()
    rep = {"kind": a.kind, "base_url": a.base_url, "model": a.model}

    # 1. connectivity + model installed
    try:
        if a.kind == "ollama":
            tags, _ = get(a.base_url.rstrip("/") + "/api/tags")
            names = [m["name"] for m in tags.get("models", [])]
        else:
            models, _ = get(a.base_url.rstrip("/") + "/v1/models")
            names = [m["id"] for m in models.get("data", [])]
        rep["connectivity"] = "REACHABLE"
        rep["models_installed"] = names
        rep["model_installed"] = a.model in names or any(n.split(":")[0] == a.model for n in names)
    except Exception as e:  # noqa: BLE001
        rep["connectivity"] = f"UNREACHABLE: {type(e).__name__}: {e}"
        print(json.dumps(rep, indent=1))
        return 2

    provider = (sp.OllamaProvider(a.base_url, a.model, timeout=a.timeout) if a.kind == "ollama"
                else sp.OpenAICompatibleProvider(a.base_url, a.model, timeout=a.timeout))

    # 2. tiny JSON request (first call includes model load time)
    t = time.perf_counter()
    raw = provider.complete('Reply with JSON only: {"ok": true, "sum": <the value of 2+3>}')
    rep["tiny_request_latency_s"] = round(time.perf_counter() - t, 2)
    rep["tiny_request_raw"] = raw[:300]
    try:
        obj = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        rep["tiny_json"] = "VALID_JSON" if obj.get("sum") == 5 else f"JSON_BUT_UNEXPECTED: {obj}"
    except Exception as e:  # noqa: BLE001
        rep["tiny_json"] = f"INVALID_JSON: {e}"

    # 3. existing Adjudicator, real provider, project decision schema
    probe = {"available": True, "kind": a.kind, **provider.describe()}
    with tempfile.TemporaryDirectory() as cache:
        adj = sp.Adjudicator({"semantic_ai": {"max_retries": 2}}, cache, "probe", providers=[(provider, probe)])
        rep["adjudicator_status"] = adj.status
        rep["decisions"] = []
        for case in TEST_CASES:
            t = time.perf_counter()
            d = adj.decide({k: v for k, v in case.items() if k != "expected"})
            rep["decisions"].append({
                "left": case["left"], "right": case["right"], "expected": case["expected"],
                "relationship": d["relationship"], "matches_expected": d["relationship"] == case["expected"],
                "decision_state": d["decision_state"], "schema_errors": sp.validate_decision(
                    {k: d[k] for k in ("relationship", "reason", "evidence", "alternatives", "uncertainty")}),
                "attempts": d["attempts"], "latency_s": round(time.perf_counter() - t, 2),
                "reason": d["reason"], "evidence": d["evidence"], "uncertainty": d["uncertainty"],
                "alternatives": d["alternatives"], "validation_errors": d["validation_errors"],
                "provider": d["provider"], "model": d["model"], "prompt_version": d["prompt_version"],
                "decision_id": d["decision_id"], "is_human_validated": d["is_human_validated"]})

    # 4. memory (Ollama exposes loaded model size)
    if a.kind == "ollama":
        try:
            ps, _ = get(a.base_url.rstrip("/") + "/api/ps")
            rep["loaded_models"] = [{"name": m.get("name"), "size_bytes": m.get("size"), "size_vram_bytes": m.get("size_vram"),
                                     "context_length": m.get("context_length")} for m in ps.get("models", [])]
        except Exception as e:  # noqa: BLE001
            rep["loaded_models"] = f"unavailable: {e}"
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return 0 if all(d["decision_state"] == "MODEL_SUGGESTED" for d in rep["decisions"]) else 1


if __name__ == "__main__":
    sys.exit(main())
