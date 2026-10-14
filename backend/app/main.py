import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api import auth, messages, sources, workspaces
from app.config import get_settings
from app.core.logging import configure_logging
from app.jobs.app import job_app

log = logging.getLogger(__name__)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """CSRF defence in depth on top of SameSite=Lax cookies: browsers always send Origin on
    cross-site unsafe requests, so reject those that don't come from our app."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in get_settings().allowed_origins:
                return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
        return await call_next(request)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with job_app.open_async():
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Enquiry Inbox API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.env != "prod" else None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(OriginCheckMiddleware)
    for router in (auth.router, workspaces.router, sources.router, messages.router):
        app.include_router(router, prefix="/api")

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
