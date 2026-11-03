"""
Centralized configuration.

Per Section 36 of the project spec: every threshold used anywhere in the pipeline
(skill matching, coverage classification, demand classification, drift) must be
defined ONCE here and imported everywhere else — never hardcoded inline in a
service/module.
"""
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised at startup when the configuration is invalid; the message lists every problem."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    environment: str = "development"          # development | test | production
    debug: bool = False                       # never true in production (validated)
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"    # public base URL of this API (documentation / clients)
    # schema management: None = create tables at startup only outside production; production uses
    # Alembic migrations (`alembic upgrade head`) and never create_all
    auto_create_schema: bool | None = None

    # --- Semantic model (overrides engine_config.json semantic_ai providers; empty = use the config file) ---
    ollama_url: str = ""
    model_name: str = ""

    # --- Database ---
    database_url: str = "sqlite:///./data/skillgap_dev.db"

    # --- Skill-gap / alignment thresholds (Section 17, 18) ---
    skill_match_threshold: float = 0.75
    partial_coverage_threshold: float = 0.4
    high_demand_threshold: float = 0.15
    high_coverage_threshold: float = 0.15  # curriculum-coverage counterpart to high_demand_threshold; same default until real data justifies a different value

    # --- Temporal trend sufficiency (Section 7) ---
    # Illustrative defaults, not derived from any real dataset -- see
    # docs/temporal_methodology.md. A trend is only ever labeled TRENDING_UP/
    # TRENDING_DOWN when all three are satisfied; otherwise INSUFFICIENT_DATA.
    min_periods_for_trend: int = 2
    min_eligible_postings_per_period: int = 30
    min_skill_postings_for_trend: int = 5
    emerging_skill_growth_threshold: float = 0.20
    declining_skill_growth_threshold: float = -0.20
    drift_threshold: float = 0.10

    # --- Preprocessing thresholds ---
    # 0.85 (the module default) missed a real near-duplicate pair in testing
    # against the Naukri fixture (two postings of the same role differing only
    # by an HTML/URL/email wrapper scored 0.83 Jaccard on 5-gram shingles).
    # 0.75 catches that case; revisit with a larger real dataset before Phase 2.
    near_duplicate_similarity_threshold: float = 0.75

    # --- Model / pipeline versioning (Section 37, 42) ---
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_version: str = "1"
    taxonomy_version: str = "ESCO-v1.2.1"
    pipeline_version: str = "0.1.0"

    # --- Upload validation (Section 39) ---
    max_upload_size_mb: int = 25
    allowed_curriculum_extensions: str = ".pdf,.txt"  # .csv/.docx not genuinely implemented yet -- see app.pipelines.ingestion.curriculum

    # --- Jooble (job posting source, India) ---
    # Never a real key here or anywhere in source control -- loaded strictly
    # from the environment at runtime. Empty string means "not configured";
    # any Jooble ingestion code must refuse to run rather than silently
    # proceed when this is unset.
    jooble_api_key: str = ""
    jooble_api_base_url: str = "https://in.jooble.org/api"

    @field_validator("auto_create_schema", mode="before")
    @classmethod
    def _blank_means_default(cls, v):
        # .env.example ships `AUTO_CREATE_SCHEMA=` and documents empty as "the default"; it must not fail to parse
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def create_schema_at_startup(self) -> bool:
        if self.auto_create_schema is not None:
            return self.auto_create_schema
        return self.environment != "production"

    @property
    def cors_origin_regex(self) -> str | None:
        """Outside production any localhost port may call the API (Flutter web dev servers pick random ports)."""
        return None if self.environment == "production" else r"http://(localhost|127\.0\.0\.1)(:\d+)?"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_curriculum_extensions_list(self) -> list[str]:
        return [e.strip() for e in self.allowed_curriculum_extensions.split(",") if e.strip()]


RATIO_FIELDS = ("skill_match_threshold", "partial_coverage_threshold", "high_demand_threshold",
                "high_coverage_threshold", "emerging_skill_growth_threshold", "drift_threshold",
                "near_duplicate_similarity_threshold")


def validate_settings(s: Settings) -> list[str]:
    """Every problem in the configuration (empty list = valid). Messages never contain secret values."""
    problems = []
    if s.environment not in ("development", "test", "production"):
        problems.append(f"ENVIRONMENT must be development, test or production (got {s.environment!r})")
    if s.environment == "production" and s.debug:
        problems.append("DEBUG must be false in production")
    if s.log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        problems.append(f"LOG_LEVEL {s.log_level!r} is not a logging level")
    scheme = urlparse(s.database_url).scheme.split("+")[0]
    if scheme not in ("sqlite", "postgresql"):
        problems.append(f"DATABASE_URL scheme must be sqlite or postgresql (got {scheme or 'none'!r})")
    if s.environment == "production" and scheme == "sqlite":
        problems.append("production requires a PostgreSQL DATABASE_URL")
    origins = s.cors_origins_list
    if "*" in origins and s.environment == "production":
        problems.append("CORS_ORIGINS must list explicit origins in production (no '*')")
    for o in origins:
        if o != "*" and urlparse(o).scheme not in ("http", "https"):
            problems.append(f"CORS origin {o!r} is not an http(s) origin")
    for url_field in ("api_url", "ollama_url", "jooble_api_base_url"):
        v = getattr(s, url_field)
        if v and urlparse(v).scheme not in ("http", "https"):
            problems.append(f"{url_field.upper()} must be an http(s) URL")
    for f in RATIO_FIELDS:
        v = getattr(s, f)
        if f == "emerging_skill_growth_threshold":
            ok = v > 0
        else:
            ok = 0.0 <= v <= 1.0
        if not ok:
            problems.append(f"{f.upper()} out of range ({v})")
    if s.declining_skill_growth_threshold >= 0:
        problems.append("DECLINING_SKILL_GROWTH_THRESHOLD must be negative")
    for f in ("min_periods_for_trend", "min_eligible_postings_per_period", "min_skill_postings_for_trend"):
        if getattr(s, f) < 1:
            problems.append(f"{f.upper()} must be >= 1")
    if s.min_periods_for_trend < 2:
        problems.append("MIN_PERIODS_FOR_TREND must be >= 2 (a trend needs two periods)")
    if s.max_upload_size_mb <= 0 or s.max_upload_size_mb > 500:
        problems.append("MAX_UPLOAD_SIZE_MB must be in 1..500")
    for ext in s.allowed_curriculum_extensions_list:
        if not ext.startswith(".") or "/" in ext:
            problems.append(f"invalid extension {ext!r} in ALLOWED_CURRICULUM_EXTENSIONS")
    return problems


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    problems = validate_settings(s)
    if problems:
        raise ConfigurationError("invalid configuration:\n  - " + "\n  - ".join(problems))
    return s
