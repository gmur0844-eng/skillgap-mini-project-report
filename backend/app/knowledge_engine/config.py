"""Engine configuration: loaded from engine_config.json, hashed for provenance."""
import copy
import hashlib
import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parent / "engine_config.json"


class EngineConfigError(ValueError):
    """The engine configuration is invalid; the message lists every problem."""


_RATIOS = ["mapping.min_similarity", "mapping.ambiguous_gap", "mapping.generic_word_course_share", "concepts.distance_threshold",
           "drift.reduction_ratio", "drift.lineage.topic_match_min", "drift.lineage.related_min_share",
           "drift.lineage.renamed_min_share", "health.max_ocr_required_page_ratio", "health.min_titled_course_ratio",
           "health.max_topic_noise_ratio", "health.max_quarantine_ratio", "health.min_provenance_completeness",
           "health.max_baseline_drop_ratio", "industry.esco_semantic_min_similarity",
           "semantic_ai.promotion.gate.min_precision_same_concept_alias",
           "semantic_ai.promotion.gate.min_unrelated_precision_alias",
           "semantic_ai.promotion.gate.min_schema_valid_rate", "peers.candidate_min_similarity",
           "peers.related_min_similarity", "peers.course_context_min_similarity", "peers.same_member_share"]
_POSITIVE_INTS = ["curriculum_scope.min_agreeing_documents", "topics.min_alpha_chars", "topics.max_words", "families.k_min", "families.k_max",
                  "concepts.min_support", "mapping.top_k_candidates", "drift.min_support", "drift.lineage.min_topics",
                  "health.min_valid_courses", "health.min_industry_postings", "intelligence.adjudication_limit",
                  "peers.top_k", "peers.list_limit", "industry_v2.min_group_postings", "industry_v2.top_n",
                  "industry_v2.clusters.min_skill_postings", "industry_v2.clusters.min_cooccurring_postings",
                  "occupations_v2.min_context_skills", "occupations_v2.min_context_overlap",
                  "occupations_v2.max_profile_candidates", "occupations_v2.min_postings_per_group", "occupations_v2.top_n"]


def _get(cfg, dotted):
    node = cfg
    for k in dotted.split("."):
        if not isinstance(node, dict) or k not in node:
            return KeyError
        node = node[k]
    return node


def validate_engine_config(cfg):
    """Every problem in an engine configuration (empty = valid)."""
    problems = []
    for key in ("config_version", "semantic_backend", "topics", "families", "concepts", "mapping", "drift", "review",
                "health", "industry", "intelligence", "semantic_ai", "peers", "industry_v2", "occupations_v2"):
        if key not in cfg:
            problems.append(f"missing section {key!r}")
    for d in _RATIOS:
        v = _get(cfg, d)
        if v is KeyError:
            problems.append(f"missing {d}")
        elif not isinstance(v, (int, float)) or not 0 <= v <= 1:
            problems.append(f"{d} must be a number in [0, 1] (got {v!r})")
    for d in _POSITIVE_INTS:
        v = _get(cfg, d)
        if v is KeyError:
            problems.append(f"missing {d}")
        elif not isinstance(v, int) or isinstance(v, bool) or v < 1:
            problems.append(f"{d} must be a positive integer (got {v!r})")
    num = lambda d: _get(cfg, d) if isinstance(_get(cfg, d), (int, float)) else None  # noqa: E731
    kmin, kmax = num("families.k_min"), num("families.k_max")
    if kmin is not None and kmax is not None and kmin > kmax:
        problems.append("families.k_min must be <= families.k_max")
    er = num("drift.expansion_ratio")
    if er is None or er <= 1:
        problems.append("drift.expansion_ratio must be a number > 1")
    rel, ren = num("drift.lineage.related_min_share"), num("drift.lineage.renamed_min_share")
    if rel is not None and ren is not None and rel > ren:
        problems.append("drift.lineage.related_min_share must be <= renamed_min_share")
    ai = cfg.get("semantic_ai") or {}
    for p in ai.get("providers", []):
        for k in ("api_key", "token", "password", "secret"):
            if p.get(k):
                problems.append(f"semantic_ai provider {p.get('kind')!r} holds a literal {k}; use an *_env variable name")
    for r in (cfg.get("semantic_replay") or {}).get("runs", []):
        for k in ("name", "cache_file", "cache_sha256", "gate_file", "gate_sha256", "prompt_version"):
            if not r.get(k):
                problems.append(f"semantic_replay run {r.get('name')!r} lacks {k}")
    t = (cfg.get("industry_v2") or {}).get("temporal") or {}
    for k in ("min_pp_change", "persistent_min_pct"):
        if not isinstance(t.get(k), (int, float)) or not 0 < t[k] <= 100:
            problems.append(f"industry_v2.temporal.{k} must be a percentage in (0, 100]")
    if not isinstance(t.get("min_relative_change"), (int, float)) or t.get("min_relative_change", 0) <= 0:
        problems.append("industry_v2.temporal.min_relative_change must be a positive number")
    return problems


def _merge(base, patch):
    out = dict(base)
    for k, v in patch.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path=None, overrides=None):
    data = json.loads(Path(path or _DEFAULT_PATH).read_text(encoding="utf-8"))
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    for dotted, value in (overrides or {}).items():
        node = data
        keys = dotted.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        if isinstance(value, dict) and isinstance(node.get(keys[-1]), dict):
            node[keys[-1]] = _merge(node[keys[-1]], value)   # a partial section overrides only the keys it names
        else:
            node[keys[-1]] = value
    problems = validate_engine_config(data)
    if problems:
        raise EngineConfigError("invalid engine configuration:\n  - " + "\n  - ".join(problems))
    return data


def config_hash(config):
    """Stable SHA-256 of the effective configuration (sorted keys)."""
    blob = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def frozen(config):
    return copy.deepcopy(config)
