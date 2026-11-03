import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import errors
from app.core.config import get_settings
from app.db.health import db_check
from app.db.session import Base, engine
from app.knowledge_engine.config import load_config
from app.api.v1 import (
    data_sources,
    data_quality,
    ingestion,
    pipeline_runs,
    datasets,
    jobs,
    curricula,
    skills,
    skill_mentions,
    analytics,
    core_knowledge,
    curriculum_knowledge,
    improvement_api,
    intelligence_api,
    health_api,
    evidence_api,
    assistant_api,
    semantic_validation_api,
)
import app.models  # noqa: F401  (ensures all models are registered on Base before create_all)

settings = get_settings()   # raises ConfigurationError on an invalid environment (fails startup clearly)
load_config()               # raises EngineConfigError on an invalid engine configuration

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("skillgap")

def _database_location():
    """The configured database without credentials (for log messages)."""
    url = engine.url
    if url.get_backend_name() == "sqlite":
        from pathlib import Path
        db = url.database or ""
        return f"sqlite file {Path(db).resolve() if db and db != ':memory:' else ':memory:'}"
    return f"{url.get_backend_name()} database {url.database!r} on {url.host or 'localhost'}"


def ensure_development_schema():
    """create_all for development. A database that cannot be opened must not take the API down: the file-backed
    knowledge endpoints keep working, database routes answer 503 DATABASE_UNAVAILABLE and /ready reports it (the same
    policy as a database outage at runtime). Returns None, or the error recorded in app.state.schema_error."""
    from sqlalchemy.exc import SQLAlchemyError
    try:
        Base.metadata.create_all(bind=engine)
    except (SQLAlchemyError, OSError) as exc:
        reason = f"{type(exc).__name__}: {str(getattr(exc, 'orig', None) or exc).splitlines()[0][:200]}"
        logger.error(
            "Database schema not ensured -- %s (%s). The API is running: knowledge endpoints are served from the GOLD "
            "files; database routes answer 503 until a database is reachable. To use the release database set "
            "DATABASE_URL=postgresql+psycopg2://localhost/skillgap_<run_id> (see README, 'Running locally'), or "
            "copy .env.example to backend/.env and edit DATABASE_URL.", _database_location(), reason)
        return reason
    logger.info("Development schema ensured with create_all (%s). Environment=%s", _database_location(),
                settings.environment)
    return None


@asynccontextmanager
async def lifespan(_app):
    # Production schemas are managed by Alembic (`alembic upgrade head`); create_all is only a development
    # convenience and never runs in production.
    if settings.create_schema_at_startup:
        _app.state.schema_error = ensure_development_schema()
    else:
        _app.state.schema_error = None
        logger.info("Schema managed by Alembic migrations. Environment=%s", settings.environment)
    yield


app = FastAPI(
    title="Skill-Gap & Curriculum Drift Intelligence API",
    version=settings.pipeline_version,
    debug=settings.debug,
    lifespan=lifespan,
)
app.state.db_check, app.state.db_required = db_check, True

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-ms"],
)
errors.install(app)


app.include_router(health_api.router)
app.include_router(data_sources.router)
app.include_router(data_quality.router)
app.include_router(ingestion.router)
app.include_router(pipeline_runs.router)
app.include_router(datasets.router)
app.include_router(jobs.router)
app.include_router(curricula.router)
app.include_router(skills.router)
app.include_router(skill_mentions.router)
app.include_router(analytics.router)
app.include_router(core_knowledge.router)
app.include_router(curriculum_knowledge.router)
app.include_router(curriculum_knowledge.industry_router)
app.include_router(intelligence_api.semantic_router)
app.include_router(intelligence_api.intelligence_router)
app.include_router(intelligence_api.curriculum_v2_router)
app.include_router(intelligence_api.industry_v2_router)
app.include_router(intelligence_api.agents_router)
app.include_router(improvement_api.router)
app.include_router(evidence_api.metadata_router)
app.include_router(evidence_api.analysis_router)
app.include_router(evidence_api.settings_router)
app.include_router(assistant_api.router)
app.include_router(semantic_validation_api.router)

# Further routers (drift, recommendations, lineage) are added as each
# analysis phase is implemented — see README status table.


# Optional single-origin deployment: serve the Flutter web build from this API under /app/ (WEB_DIR=<build/web>).
# Build it with: flutter build web --base-href /app/ --dart-define=API_URL=<this API's public URL>
def _mount_web():
    import os
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles
    web = os.environ.get("WEB_DIR", "")
    if web and (Path(web) / "index.html").exists():
        app.mount("/app", StaticFiles(directory=web, html=True), name="web")


_mount_web()
