"""
SemanticModelProvider -- interchangeable model providers for semantic ADJUDICATION of candidate
pairs that the deterministic layers could not settle (alias senses, ambiguous taxonomy labels,
ambiguous topic mappings).

Providers
  OllamaProvider              HTTP  {base}/api/chat           (base from config / OLLAMA_HOST)
  OpenAICompatibleProvider    HTTP  {base}/v1/chat/completions (LM Studio, llama.cpp server, vLLM, ...)
  LocalLLMProvider            a local model directory loaded with `transformers` (when installed)
  EmbeddingProvider           wraps semantic_backend.EmbeddingBackend (similarity only, never a decision)
  DeterministicFallbackProvider  no model: returns the rule layer's own verdict, marked
                              AI_PROVIDER_UNAVAILABLE -- it never pretends to be a model

Contract
  * candidates are generated BEFORE adjudication (never "compare everything with everything")
  * a model answer must be JSON matching DECISION_SCHEMA; invalid output is retried
    (max_retries) and then recorded as REVIEW_REQUIRED
  * every decision is a SemanticDecision record (ids, model, prompt version, hashes, evidence,
    alternatives, uncertainty) and is cached by hash(model, model_version, prompt_version,
    config, input, context) -- a rerun with identical inputs reuses the cached decision
  * a model decision is MODEL_SUGGESTED evidence, never HUMAN_VALIDATED and never "confidence"
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA_VERSION = "decision-schema-v1"  # DECISION_SCHEMA / OUTPUT_JSON_SCHEMA contract
PROMPT_VERSION = "adjudicate-v2"  # v2: field types stated; schema-constrained output where the runtime supports it
RELATIONSHIPS = ("SAME_CONCEPT", "PARENT", "CHILD", "RELATED", "PARTIAL_OVERLAP", "UNRELATED", "AMBIGUOUS",
                 "INSUFFICIENT_EVIDENCE")
RELATIONSHIP_DEFINITIONS = {
    "SAME_CONCEPT": "LEFT and RIGHT denote the same thing in this context",
    "PARENT": "LEFT is broader than RIGHT (RIGHT is a kind or part of LEFT)",
    "CHILD": "LEFT is narrower than RIGHT (LEFT is a kind or part of RIGHT)",
    "RELATED": "clearly associated, neither contains the other",
    "PARTIAL_OVERLAP": "they share part of their meaning",
    "UNRELATED": "different meanings (for example a different word sense)",
    "AMBIGUOUS": "the context supports more than one reading",
    "INSUFFICIENT_EVIDENCE": "the text does not allow a judgement",
}
DECISION_SCHEMA = {
    "type": "object",
    "required": ["relationship", "reason", "evidence", "uncertainty"],
    "properties": {
        "relationship": {"enum": list(RELATIONSHIPS)},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "uncertainty": {"type": "string"},
    },
}


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def validate_decision(obj):
    """Minimal JSON-schema check for DECISION_SCHEMA (no external dependency). Returns list of errors."""
    errors = []
    if not isinstance(obj, dict):
        return ["output is not a JSON object"]
    for key in DECISION_SCHEMA["required"]:
        if key not in obj:
            errors.append(f"missing field {key}")
    if "relationship" in obj and obj["relationship"] not in RELATIONSHIPS:
        errors.append(f"relationship {obj['relationship']!r} not in {RELATIONSHIPS}")
    for key in ("reason", "uncertainty"):
        if key in obj and not isinstance(obj[key], str):
            errors.append(f"{key} must be a string")
    for key in ("evidence", "alternatives"):
        if key in obj and not (isinstance(obj[key], list) and all(isinstance(x, str) for x in obj[key])):
            errors.append(f"{key} must be a list of strings")
    return errors


def build_prompt(candidate):
    defs = "\n".join(f"- {k}: {v}" for k, v in RELATIONSHIP_DEFINITIONS.items())
    return (
        "You compare two items and classify how LEFT relates to RIGHT, using ONLY the context given.\n"
        f"Allowed relationships:\n{defs}\n\n"
        f"LEFT: {candidate['left']}\nLEFT CONTEXT: {candidate.get('left_context') or '(none)'}\n"
        f"RIGHT: {candidate['right']}\nRIGHT CONTEXT: {candidate.get('right_context') or '(none)'}\n"
        f"QUESTION: {candidate.get('question') or 'How does LEFT relate to RIGHT?'}\n\n"
        "Quote the words of the context you rely on in `evidence`. If the context does not decide it, answer "
        "INSUFFICIENT_EVIDENCE or AMBIGUOUS. Reply with one JSON object only, with exactly these fields and types:\n"
        '{"relationship": "<one of the allowed relationships>", "reason": "<one sentence>", '
        '"evidence": ["<quoted words from the contexts>"], "alternatives": ["<other relationships you considered>"], '
        '"uncertainty": "<one sentence, as text: what could make this answer wrong>"}\n'
        "Every value is a string or a list of strings; do not use numbers, booleans or null.")


# JSON Schema of the decision, sent to runtimes that constrain generation (Ollama `format`).
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "relationship": {"type": "string", "enum": list(RELATIONSHIPS)},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "uncertainty": {"type": "string"},
    },
    "required": ["relationship", "reason", "evidence", "alternatives", "uncertainty"],
}


class ProviderUnavailable(Exception):
    pass


class _HTTPChatProvider:
    kind = "http"

    def __init__(self, base_url, model, timeout=60, temperature=0.0):
        self.base_url, self.model, self.timeout, self.temperature = base_url.rstrip("/"), model, timeout, temperature

    model_digest = None   # set by probe() when the endpoint reports one; part of the description, so a re-pulled
    #                       model with the same tag but different weights gets a different cache key

    def describe(self):
        d = {"provider": self.name, "model": self.model, "model_version": self.model, "base_url": self.base_url,
             "temperature": self.temperature}
        if self.model_digest:
            d["model_digest"] = self.model_digest
        return d

    def _post(self, path, payload):
        req = urllib.request.Request(self.base_url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", **self._auth()})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def _auth(self):
        return {}

    def probe(self):
        try:
            self._get_models()
            return {"available": True}
        except Exception as e:  # noqa: BLE001 -- any failure = unavailable, reason recorded
            return {"available": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}


class OllamaProvider(_HTTPChatProvider):
    name = "ollama"

    def _get_models(self):
        with urllib.request.urlopen(self.base_url + "/api/tags", timeout=3) as r:
            models = json.loads(r.read().decode()).get("models", [])
        self.model_digest = next((m.get("digest") for m in models if m.get("name") == self.model and m.get("digest")),
                                 None)
        return [m["name"] for m in models]

    def complete(self, prompt, schema=None):
        out = self._post("/api/chat", {"model": self.model, "stream": False, "format": schema or "json",
                                       "options": {"temperature": self.temperature},
                                       "messages": [{"role": "user", "content": prompt}]})
        self.last_meta = {"prompt_tokens": out.get("prompt_eval_count"), "output_tokens": out.get("eval_count"),
                          "total_duration_ns": out.get("total_duration"), "load_duration_ns": out.get("load_duration")}
        return out["message"]["content"]


class OpenAICompatibleProvider(_HTTPChatProvider):
    name = "openai_compatible"

    def __init__(self, base_url, model, api_key_env=None, **kw):
        super().__init__(base_url, model, **kw)
        self.api_key_env = api_key_env

    def _auth(self):
        key = os.environ.get(self.api_key_env or "", "")
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _get_models(self):
        req = urllib.request.Request(self.base_url + "/v1/models", headers=self._auth())
        with urllib.request.urlopen(req, timeout=3) as r:
            return [m["id"] for m in json.loads(r.read().decode()).get("data", [])]

    def complete(self, prompt, schema=None):  # schema: json_object mode only (widest server support)
        out = self._post("/v1/chat/completions", {"model": self.model, "temperature": self.temperature,
                                                  "response_format": {"type": "json_object"},
                                                  "messages": [{"role": "user", "content": prompt}]})
        return out["choices"][0]["message"]["content"]


class LocalLLMProvider:
    name = "local_transformers"
    kind = "local"

    def __init__(self, model_dir, max_new_tokens=256):
        self.model_dir, self.max_new_tokens, self._pipe = model_dir, max_new_tokens, None

    def describe(self):
        return {"provider": self.name, "model": self.model_dir, "model_version": Path(self.model_dir).name if self.model_dir else None}

    def probe(self):
        try:
            import transformers  # noqa: F401
        except ImportError:
            return {"available": False, "reason": "python package 'transformers' is not installed"}
        if not self.model_dir or not Path(self.model_dir).is_dir():
            return {"available": False, "reason": f"model directory not found: {self.model_dir!r}"}
        return {"available": True}

    def complete(self, prompt, schema=None):
        if self._pipe is None:
            from transformers import pipeline
            self._pipe = pipeline("text-generation", model=self.model_dir)
        return self._pipe(prompt, max_new_tokens=self.max_new_tokens, do_sample=False)[0]["generated_text"][len(prompt):]


class EmbeddingProvider:
    """Similarity only; used for candidate generation, never returns a relationship decision."""
    name = "embedding"
    kind = "embedding"

    def __init__(self, backend_name="sentence_transformer"):
        self.backend_name = backend_name

    def describe(self):
        return {"provider": self.name, "backend": self.backend_name}

    def probe(self):
        from app.knowledge_engine.semantic_backend import available_backends
        status = available_backends().get(self.backend_name, "UNAVAILABLE: unknown backend")
        return {"available": status == "AVAILABLE",
                "reason": None if status == "AVAILABLE" else status.split(":", 1)[-1].strip()}


class DeterministicFallbackProvider:
    """No model. Echoes the verdict the rule layer already reached, so a decision record exists and
    the absence of a model is explicit (AI_PROVIDER_UNAVAILABLE)."""
    name = "deterministic_fallback"
    kind = "rules"

    def describe(self):
        return {"provider": self.name, "model": None, "model_version": None}

    def probe(self):
        return {"available": True}

    def decide(self, candidate):
        rel = candidate.get("rule_relationship") or "INSUFFICIENT_EVIDENCE"
        return {"relationship": rel if rel in RELATIONSHIPS else "INSUFFICIENT_EVIDENCE",
                "reason": candidate.get("rule_reason") or "deterministic rule layer verdict; no model adjudicated this pair",
                "evidence": list(candidate.get("rule_evidence") or []), "alternatives": [],
                "uncertainty": "AI_PROVIDER_UNAVAILABLE: no language model was available; this is the rule verdict"}


def discover_providers(cfg):
    """Probe every configured provider; returns [(provider, probe)] in preference order."""
    out = []
    ai = cfg.get("semantic_ai", {})
    for spec in ai.get("providers", []):
        kind = spec.get("kind")
        base = os.environ.get(spec.get("base_url_env") or "", "") or spec.get("base_url")
        if kind == "ollama":
            # OLLAMA_URL / MODEL_NAME (see .env.example) override the file; a different model is a different
            # cache key, so recorded decisions of another model are never reused
            base = os.environ.get("OLLAMA_URL", "") or base
        if kind == "ollama" and base:
            p = OllamaProvider(base, os.environ.get("MODEL_NAME", "") or spec.get("model") or "",
                               timeout=spec.get("timeout", 60))
        elif kind == "openai_compatible" and base:
            p = OpenAICompatibleProvider(base, spec.get("model") or "", api_key_env=spec.get("api_key_env"),
                                         timeout=spec.get("timeout", 60))
        elif kind == "local_transformers":
            p = LocalLLMProvider(os.environ.get(spec.get("model_dir_env") or "", "") or spec.get("model_dir"))
        else:
            out.append((None, {"available": False, "kind": kind, "reason": "not configured (no base_url / model)"}))
            continue
        probe = p.probe()
        if probe.get("available") and isinstance(p, _HTTPChatProvider) and not p.model:
            probe = {"available": False, "reason": "endpoint reachable but no model name configured"}
        out.append((p, {**probe, "kind": kind, **{k: v for k, v in p.describe().items() if k != "base_url"}}))
    return out


class Protocol:
    """Prompt + output schema + hashing + (optional) authoritative post-validation, versioned together."""

    def __init__(self, prompt_version, schema_version, build_prompt, output_schema, validate_output, hashes,
                 post_validate=None, fallback=None):
        self.prompt_version, self.schema_version = prompt_version, schema_version
        self.build_prompt, self.output_schema, self.validate_output = build_prompt, output_schema, validate_output
        self.hashes, self.post_validate, self.fallback = hashes, post_validate, fallback


def _v2_hashes(candidate):
    return (sha({k: candidate.get(k) for k in ("left", "right", "question")}),
            sha({k: candidate.get(k) for k in ("left_context", "right_context", "rule_relationship", "rule_reason",
                                               "rule_evidence")}))


def v2_protocol():
    return Protocol(PROMPT_VERSION, SCHEMA_VERSION, build_prompt, OUTPUT_JSON_SCHEMA, validate_decision, _v2_hashes)


def v3_protocol():
    from app.knowledge_engine import semantic_v3 as v3
    return Protocol(v3.PROMPT_VERSION, v3.SCHEMA_VERSION, v3.build_prompt, v3.OUTPUT_JSON_SCHEMA, v3.validate_output,
                    lambda c: v3.candidate_hashes(c, sha), post_validate=v3.validate_decision)


def v4_protocol():
    """adjudicate-v4: v3's schema, inputs and validator with the v4 prompt (semantic_v3.build_prompt_v4)."""
    from app.knowledge_engine import semantic_v3 as v3
    return Protocol(v3.PROMPT_VERSION_V4, v3.SCHEMA_VERSION, v3.build_prompt_v4, v3.OUTPUT_JSON_SCHEMA, v3.validate_output,
                    lambda c: v3.candidate_hashes(c, sha), post_validate=v3.validate_decision)


def protocol_for(version):
    return {"adjudicate-v3": v3_protocol, "adjudicate-v4": v4_protocol}.get(version, v2_protocol)()


def _transient_failure(rec):
    """A MODEL_FAILURE with no model output: transport or runtime errors (connection refused, timeout). It says nothing
    about the input, so it is never persisted to a decision cache. Schema-invalid model output (REVIEW_REQUIRED) is a
    real model response and is cached as before."""
    return rec.get("decision_state") == "MODEL_FAILURE" and not rec.get("rejected_raw_outputs")


class Adjudicator:
    def __init__(self, cfg, cache_dir, run_id, providers=None, protocol=None, readonly_cache=False, pinned_files=()):
        """pinned_files: hash-pinned recorded caches (config semantic_replay). They are evidence of a verified run:
        this adjudicator never appends to one, whatever its mode, and a failed cache write never fails the run."""
        self.cfg = cfg.get("semantic_ai", {})
        self.readonly_cache = readonly_cache
        self.protocol = protocol or v2_protocol()
        self.run_id = run_id
        probes = providers if providers is not None else discover_providers(cfg)
        self.probes = [pr for _, pr in probes]
        live = [p for p, pr in probes if p is not None and pr.get("available")]
        self.provider = live[0] if live else DeterministicFallbackProvider()
        self.status = "AI_PROVIDER_AVAILABLE" if live else "AI_PROVIDER_UNAVAILABLE"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        desc = self.provider.describe()
        self.model_key = sha({"model": desc, "prompt_version": self.protocol.prompt_version,
                              "schema_version": self.protocol.schema_version,
                              "config": {k: v for k, v in self.cfg.items() if k != "providers"}})[:16]
        self.cache_file = self.cache_dir / f"{self.provider.name}-{self.model_key}.jsonl"
        if self.cache_file.resolve() in {Path(f).resolve() for f in pinned_files}:
            self.readonly_cache = True
        self.cache = {}
        if self.cache_file.exists():
            for line in self.cache_file.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                if not self.readonly_cache and _transient_failure(rec):
                    # a model that could not be reached decided nothing: ask again rather than serve the failure
                    # (records written before this rule; a hash-pinned recording is always served as recorded)
                    continue
                self.cache[rec["cache_key"]] = rec
        self.stats = {"requested": 0, "cache_hits": 0, "model_calls": 0, "invalid_outputs": 0, "review_required": 0}

    def describe(self):
        return {"status": self.status, "provider": self.provider.describe(), "prompt_version": self.protocol.prompt_version,
                "schema_version": self.protocol.schema_version,
                "probes": self.probes, "cache_file": str(self.cache_file.name), "stats": self.stats}

    def decide(self, candidate):
        self.stats["requested"] += 1
        desc = self.provider.describe()
        input_hash, context_hash = self.protocol.hashes(candidate)
        cache_key = sha([self.model_key, input_hash, context_hash])
        if cache_key in self.cache:
            self.stats["cache_hits"] += 1
            return {**self.cache[cache_key], "run_id": self.run_id, "from_cache": True}
        attempts, errors, rejected_raw, tokens = 0, [], [], {"prompt_tokens": 0, "output_tokens": 0}
        started = time.perf_counter()
        if isinstance(self.provider, DeterministicFallbackProvider):
            out, decision_state = self.provider.decide(candidate), "RULE_VERDICT_NO_MODEL"
        else:
            out, decision_state = None, None
            for attempts in range(1, self.cfg.get("max_retries", 2) + 2):  # noqa: B007 -- read after the loop (record["attempts"])
                if isinstance(self.provider, RecordedProvider):
                    # replay: a missing recording is not a model call and retrying cannot help
                    self.stats["replay_misses"] = self.stats.get("replay_misses", 0) + 1
                    errors.append(["REPLAY_MISS: no recorded decision for this input"])
                    break
                try:
                    self.stats["model_calls"] += 1
                    raw = None
                    raw = self.provider.complete(self.protocol.build_prompt(candidate), schema=self.protocol.output_schema)
                    meta = getattr(self.provider, "last_meta", None) or {}
                    for k in tokens:
                        tokens[k] += meta.get(k) or 0
                    obj = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
                    errs = self.protocol.validate_output(obj)
                    if not errs:
                        out, decision_state = obj, "MODEL_SUGGESTED"
                        break
                    errors.append(errs + [f"raw output: {raw[:300]}"])
                    rejected_raw.append(raw[:4000])
                except Exception as e:  # noqa: BLE001
                    errors.append([f"{type(e).__name__}: {str(e)[:120]}"] + ([f"raw output: {raw[:300]}"] if raw else []))
                    if raw:
                        rejected_raw.append(raw[:4000])
                self.stats["invalid_outputs"] += 1
            if out is None and isinstance(self.provider, RecordedProvider):
                out = {"relationship": "INSUFFICIENT_EVIDENCE", "evidence": [], "alternatives": [], "direction_justification": "",
                       "reason": "REPLAY_MISS: no recorded decision for this exact input and context; the model was not called",
                       "uncertainty": "not decided in this run"}
                decision_state = "MODEL_FAILURE"
            elif out is None and not rejected_raw:
                # no attempt produced any model text (transport / runtime errors): a model failure, not a verdict
                self.stats["model_failures"] = self.stats.get("model_failures", 0) + 1
                out = {"relationship": "INSUFFICIENT_EVIDENCE", "reason": "the model produced no output",
                       "evidence": [], "alternatives": [], "uncertainty": f"errors: {errors}", "direction_justification": ""}
                decision_state = "MODEL_FAILURE"
            elif out is None:
                self.stats["review_required"] += 1
                out = {"relationship": "INSUFFICIENT_EVIDENCE", "reason": "model output failed schema validation",
                       "evidence": [], "alternatives": [], "uncertainty": f"errors: {errors}", "direction_justification": ""}
                decision_state = "REVIEW_REQUIRED"
        rec = {
            "decision_id": "sdec:" + cache_key[:16], "cache_key": cache_key, "run_id": self.run_id,
            "provider": desc.get("provider"), "model": desc.get("model"), "model_version": desc.get("model_version"),
            "prompt_version": self.protocol.prompt_version, "schema_version": self.protocol.schema_version,
            "provider_status": self.status, "direction_justification": out.get("direction_justification"),
            "candidate_id": candidate.get("candidate_id"),
            "input_hash": input_hash, "context_hash": context_hash, "output_hash": sha(out),
            "source_entity": candidate.get("source_entity"), "candidate_entity": candidate.get("candidate_entity"),
            "candidate_kind": candidate.get("kind"), "left": candidate["left"], "right": candidate["right"],
            "relationship": out["relationship"], "reason": out["reason"], "evidence": out.get("evidence", []),
            "alternatives": out.get("alternatives", []), "uncertainty": out.get("uncertainty"),
            "rule_relationship": candidate.get("rule_relationship"), "decision_state": decision_state,
            "attempts": attempts, "validation_errors": errors, "rejected_raw_outputs": rejected_raw,
            "latency_s": round(time.perf_counter() - started, 3), "tokens": tokens,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "is_human_validated": False, "score_is_confidence": False,
        }
        if self.protocol.post_validate and decision_state == "MODEL_SUGGESTED":
            rec["validated_state"], rec["validation_findings"] = self.protocol.post_validate(out, candidate)
        elif self.protocol.post_validate:
            rec["validated_state"], rec["validation_findings"] = decision_state, [f"MODEL_STATE:{decision_state}"]
        self.cache[cache_key] = rec   # within this run a failure is not retried (the server is down, not the input)
        if not self.readonly_cache and not _transient_failure(rec):
            try:
                with self.cache_file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
            except OSError as e:   # an unwritable cache costs a re-decision next time, never the run
                self.readonly_cache = True
                self.stats["cache_write_failed"] = f"{type(e).__name__}: {str(e)[:160]}"
        return {**rec, "from_cache": False}


class RecordedProvider:
    """Stands in for a model that ran elsewhere (e.g. on the machine hosting Ollama). It has the SAME description as
    the live provider, so the Adjudicator's cache key is identical and verified recorded decisions are served as
    cache hits; a candidate without a recorded decision cannot be answered (MODEL_FAILURE, no effect)."""
    kind = "recorded"

    def __init__(self, live, recorded_base_url=None):
        self.live, self.name, self.recorded_base_url = live, live.name, recorded_base_url

    def describe(self):
        """The description the recording was made under. The endpoint address is transport, not model identity: an
        override such as OLLAMA_URL (or a different host) must not change the recording's cache key, and a digest the
        recording never carried is not part of it."""
        d = {k: v for k, v in self.live.describe().items() if k != "model_digest"}
        if self.recorded_base_url and "base_url" in d:
            d["base_url"] = self.recorded_base_url
        return d

    def complete(self, prompt, schema=None):
        raise ProviderUnavailable("model endpoint not reachable from this host; no recorded decision for this input")
