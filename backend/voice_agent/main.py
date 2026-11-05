import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from voice_agent.api import conversations, health, status
from voice_agent.config import Settings
from voice_agent.services import Services, production_services


def configure_logging() -> None:
    """Show the app's own log lines next to Uvicorn's."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
    logger = logging.getLogger("voice_agent")
    if not logger.handlers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def create_app(
    settings: Settings | None = None, services: Services | None = None
) -> FastAPI:
    """The app; tests pass their own services (e.g. fake speech) instead."""
    settings = settings or (services.settings if services else Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            current = services or await stack.enter_async_context(
                production_services(settings)
            )
            app.state.services = current
            app.state.turns = current.turns()
            yield

    configure_logging()
    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    for module in (health, status, conversations):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
