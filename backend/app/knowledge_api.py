"""
Standalone read-only Knowledge API: every file-backed router (curriculum, industry,
semantic, intelligence) over data/gold/knowledge, with no database dependency.

    uvicorn app.knowledge_api:app --port 8000      (from backend/)

The full app (app.main) mounts the same routers plus the database-backed ones.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import curriculum_knowledge, evidence_api, health_api, improvement_api, intelligence_api
from app.core import errors
from app.core.config import get_settings
from app.knowledge_engine.config import load_config

settings = get_settings()   # raises ConfigurationError on an invalid environment
load_config()               # raises EngineConfigError on an invalid engine configuration

app = FastAPI(title="Skill-Gap & Curriculum Drift Intelligence - Knowledge API", version="2.0.0",
              debug=settings.debug)
app.state.db_check, app.state.db_required = None, False
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins_list,
                   allow_origin_regex=settings.cors_origin_regex, allow_methods=["GET"],
                   allow_headers=["*"], expose_headers=["X-Request-ID", "X-Response-Time-ms"])
errors.install(app)

for r in (health_api.router, curriculum_knowledge.router, curriculum_knowledge.industry_router,
          intelligence_api.semantic_router, intelligence_api.intelligence_router, intelligence_api.curriculum_v2_router,
          intelligence_api.industry_v2_router, intelligence_api.agents_router, improvement_api.router,
          evidence_api.metadata_router):
    app.include_router(r)


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
