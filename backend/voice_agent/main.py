from fastapi import FastAPI

from voice_agent.api import health
from voice_agent.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=settings.app_name, version=settings.version)
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
