"""
Run the frozen adjudication candidates through the configured model provider (production classes, production
configuration), sequentially, and write every decision -- valid or not -- with timing, tokens and memory samples.

Run on the machine that hosts the model, from the repository (or bundle) root:
    python3 scripts/semantic/run_frozen_adjudication.py --frozen data/semantic_runs/qwen-270-v1 [--consistency-sample 20]

Writes <frozen>/out/ (or --out): decisions.jsonl, run_meta.json, memory_samples.jsonl, consistency.jsonl, diagnostics.jsonl, cache/.
A second invocation reuses the cache (no model calls) and must reproduce the same output hashes.
Nothing outside <frozen>/out is written; no source data is read or changed.
"""
import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_engine import semantic_provider as sp  # noqa: E402

CONFIG = ROOT / "backend/app/knowledge_engine/engine_config.json"


def _get(url, timeout=10, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def memory_sample(base):
    s = {"t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        s["ollama_ps"] = [{"name": m.get("name"), "size": m.get("size"), "size_vram": m.get("size_vram")}
                          for m in _get(base + "/api/ps").get("models", [])]
    except Exception as e:  # noqa: BLE001
        s["ollama_ps"] = f"unavailable: {e}"
    if platform.system() == "Darwin":
        for name, cmd in (("memory_pressure", ["memory_pressure", "-Q"]), ("swapusage", ["sysctl", "vm.swapusage"])):
            try:
                s[name] = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()[-300:]
            except Exception as e:  # noqa: BLE001
                s[name] = f"unavailable: {e}"
    return s


def file_sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", required=True)
    ap.add_argument("--consistency-sample", type=int, default=20)
    ap.add_argument("--diagnostics", default=str(ROOT / "data/evaluation/semantic_hard_cases_v2.json"))
    ap.add_argument("--limit", type=int, default=None, help="only for a smoke test; the real run uses all")
    ap.add_argument("--protocol", default=None, help="prompt version; default: engine_config semantic_ai.prompt_version")
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--out", default=None,
                    help="output folder (default <frozen>/out); use a new folder to keep an earlier run untouched")
    ap.add_argument("--benchmark-only", action="store_true",
                    help="only the candidates of the frozen benchmark (data/evaluation/semantic_benchmark_v1)")
    a = ap.parse_args()
    frozen = Path(a.frozen)
    manifest = json.loads((frozen / "freeze_manifest.json").read_text())
    body = (frozen / "candidates.json").read_text(encoding="utf-8")
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != manifest["candidates_sha256"]:
        sys.exit("REFUSED: candidates.json does not match the freeze manifest")
    cands = json.loads(body)
    cfg_pre = json.loads(CONFIG.read_text())
    protocol = sp.protocol_for(a.protocol or cfg_pre.get("semantic_ai", {}).get("prompt_version", "adjudicate-v2"))
    strip = ("baseline", "input_hash", "context_hash")
    for c in cands:  # inputs cannot have changed since freezing
        if protocol.hashes({k: v for k, v in c.items() if k not in strip}) != (c["input_hash"], c["context_hash"]):
            sys.exit(f"REFUSED: candidate {c['candidate_id']} changed after freezing")
    if a.benchmark_only:
        bench = json.loads((ROOT / "data/evaluation/semantic_benchmark_v1/benchmark.json").read_text(encoding="utf-8"))
        wanted = {b["candidate_id"] for b in (bench.get("cases", bench) if isinstance(bench, dict) else bench)}
        cands = [c for c in cands if c["candidate_id"] in wanted]
    if a.limit:
        cands = cands[:a.limit]
    cfg = json.loads(CONFIG.read_text())
    probes = sp.discover_providers(cfg)
    live = [(p, pr) for p, pr in probes if p is not None and pr.get("available")]
    if not live:
        sys.exit(f"REFUSED: no model provider available: {[pr for _, pr in probes]}")
    provider, probe = live[0]
    base = provider.base_url
    out = Path(a.out) if a.out else frozen / "out"
    out.mkdir(parents=True, exist_ok=True)
    if (out / "run_meta.json").exists():  # keep every earlier run's results: move them to out/archive/<n>/
        n = 1 + sum(1 for _ in (out / "archive").glob("*")) if (out / "archive").exists() else 1
        dest = out / "archive" / f"run-{n:02d}"
        dest.mkdir(parents=True)
        for name in ("decisions.jsonl", "run_meta.json", "memory_samples.jsonl", "consistency.jsonl", "diagnostics.jsonl"):
            if (out / name).exists():
                (out / name).rename(dest / name)
    meta = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": platform.platform(), "python": platform.python_version(),
            "freeze_manifest": manifest, "config_sha256": file_sha(CONFIG),
            "semantic_provider_sha256": file_sha(ROOT / "backend/app/knowledge_engine/semantic_provider.py"),
            "runner_sha256": file_sha(__file__), "provider": provider.describe(), "probes": [pr for _, pr in probes],
            "prompt_version": protocol.prompt_version, "schema_version": protocol.schema_version,
            "engine_config_version": cfg.get("config_version"), "concurrency": 1}
    try:
        tags = {m["name"]: m for m in _get(base + "/api/tags").get("models", [])}
        m = tags.get(provider.model, {})
        show = _get(base + "/api/show", data={"model": provider.model})
        meta["model_details"] = {"digest": m.get("digest"), "size": m.get("size"), **(show.get("details") or {})}
        meta["runtime_version"] = _get(base + "/api/version").get("version")
    except Exception as e:  # noqa: BLE001
        meta["model_details"] = f"unavailable: {e}"
    mem = [memory_sample(base)]
    run_name = a.run_name or frozen.name
    adj = sp.Adjudicator(cfg, out / "cache", run_name, providers=[(provider, probe)], protocol=protocol)
    meta["adjudicator"] = {"status": adj.status, "model_key": adj.model_key}
    t0 = time.perf_counter()
    rows = []
    with (out / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for i, c in enumerate(cands, 1):
            cand = {k: v for k, v in c.items() if k not in strip}
            t = time.perf_counter()
            d = adj.decide(cand)
            wall = round(time.perf_counter() - t, 3)
            row = {**d, "candidate_id": c["candidate_id"], "frozen_input_hash": c["input_hash"],
                   "frozen_context_hash": c["context_hash"], "left_context": c.get("left_context"),
                   "right_context": c.get("right_context"), "question": c.get("question"), "baseline": c.get("baseline"),
                   "kind": c.get("kind"),
                   "wall_latency_s": wall, "cache_hit": d["from_cache"],
                   "input_hash_matches_freeze": d["input_hash"] == c["input_hash"] and d["context_hash"] == c["context_hash"]}
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            rows.append(row)
            if i % 25 == 0 or i == len(cands):
                mem.append(memory_sample(base))
                print(f"{i}/{len(cands)} done, {round(time.perf_counter() - t0)} s", flush=True)
    total = time.perf_counter() - t0
    lat = sorted(r["wall_latency_s"] for r in rows if not r["cache_hit"])
    meta.update({
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "total_runtime_s": round(total, 1),
        "adjudicator_stats": adj.stats, "cache_hits": sum(r["cache_hit"] for r in rows),
        "cache_misses": sum(not r["cache_hit"] for r in rows),
        "latency_s_uncached": ({"n": len(lat), "mean": round(statistics.mean(lat), 3), "median": round(statistics.median(lat), 3),
                                "p95": round(lat[max(0, int(0.95 * len(lat)) - 1)], 3), "min": lat[0], "max": lat[-1]}
                               if lat else None),
        "tokens": {"prompt": sum((r.get("tokens") or {}).get("prompt_tokens", 0) for r in rows if not r["cache_hit"]),
                   "output": sum((r.get("tokens") or {}).get("output_tokens", 0) for r in rows if not r["cache_hit"])},
        "decisions_file_sha256": file_sha(out / "decisions.jsonl"),
        "output_hashes_sha256": hashlib.sha256("".join(sorted(r["output_hash"] for r in rows)).encode()).hexdigest(),
    })
    (out / "memory_samples.jsonl").write_text("\n".join(json.dumps(m) for m in mem) + "\n")

    # model consistency: re-ask a deterministic sample WITHOUT the cache (same prompt, temperature 0)
    sample = sorted(rows, key=lambda r: r["candidate_id"])[:a.consistency_sample]
    with tempfile.TemporaryDirectory() as tmp:
        fresh = sp.Adjudicator(cfg, tmp, run_name + "-consistency", providers=[(provider, probe)], protocol=protocol)
        cons = []
        for r in sample:
            c = next(x for x in cands if x["candidate_id"] == r["candidate_id"])
            d = fresh.decide({k: v for k, v in c.items() if k not in strip})
            cons.append({"candidate_id": r["candidate_id"], "first": r["relationship"], "second": d["relationship"],
                         "same_relationship": d["relationship"] == r["relationship"],
                         "same_output_hash": d["output_hash"] == r["output_hash"], "second_state": d["decision_state"]})
    (out / "consistency.jsonl").write_text("\n".join(json.dumps(x) for x in cons) + "\n")
    meta["consistency"] = {"n": len(cons), "same_relationship": sum(x["same_relationship"] for x in cons),
                           "same_output_hash": sum(x["same_output_hash"] for x in cons)}

    # diagnostic hard cases (separate from the 270; pairs WITHOUT context, from a fixed pre-existing file)
    diag = []
    if Path(a.diagnostics).exists() and protocol.prompt_version == "adjudicate-v2":
        with tempfile.TemporaryDirectory() as tmp:
            dadj = sp.Adjudicator(cfg, tmp, "qwen-hard-cases", providers=[(provider, probe)])
            for hc in json.loads(Path(a.diagnostics).read_text())["cases"]:
                d = dadj.decide({"kind": "HARD_CASE_DIAGNOSTIC", "left": hc["left"], "right": hc["right"],
                                 "question": "How does LEFT relate to RIGHT?"})
                diag.append({"case_id": hc["case_id"], "left": hc["left"], "right": hc["right"],
                             "expected_by_specification": hc["expected"], "relationship": d["relationship"],
                             "decision_state": d["decision_state"], "reason": d["reason"], "latency_s": d["latency_s"]})
    (out / "diagnostics.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in diag) + "\n")
    meta["diagnostics"] = len(diag)
    (out / "run_meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print(json.dumps({k: meta[k] for k in ("total_runtime_s", "adjudicator_stats", "cache_hits", "cache_misses",
                                          "latency_s_uncached", "consistency", "output_hashes_sha256")}, indent=1))


if __name__ == "__main__":
    main()
