"""FastAPI application factory.

``create_app`` wires configuration, the database, GitHub service, LLM
provider, and the analysis service. Tests inject mocks (transport and/or
provider) through the same factory.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.core.config import Settings, get_settings
from app.core.errors import GitPilotError
from app.core.logging import setup_logging
from app.db.database import create_engine_for, init_db, make_session_factory
from app.services.analysis_service import AnalysisService
from app.services.github_service import GitHubService
from app.services.llm import get_llm_provider
from app.services.llm.base import LLMProvider

logger = logging.getLogger("gitpilot")


def create_app(
    settings: Settings | None = None,
    *,
    github_transport=None,
    llm_provider: LLMProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    engine = create_engine_for(settings.database_path)
    init_db(engine)
    session_factory = make_session_factory(engine)

    github = GitHubService(
        token=settings.github_token,
        base_url=settings.github_api_base_url,
        timeout_seconds=settings.github_timeout_seconds,
        transport=github_transport,
    )
    provider = llm_provider or get_llm_provider(settings)
    service = AnalysisService(session_factory, github, provider, settings)

    app = FastAPI(
        title="GitPilot",
        description="AI GitHub Issue Resolution & Triage Agent",
        version="0.1.0",
    )
    app.state.analysis_service = service
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": "GitPilot",
            "docs": "/docs",
            "health": "/api/health",
        }

    # ---------------- error handlers: consistent error shapes ----------------
    @app.exception_handler(GitPilotError)
    async def gitpilot_error_handler(_request: Request, exc: GitPilotError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", []))
        message = f"Invalid request: {field}: {first.get('msg', 'validation error')}"
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "validation_error",
                    "message": message,
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "internal_error",
                    "message": "Internal server error.",
                }
            },
        )

    return app


app = create_app()