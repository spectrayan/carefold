# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Carefold FastAPI Application Entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncIterator, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from yarvelle_core.api.http_security import build_cors_options, enforce_bind_safety

from carefold import __version__
from carefold.api.router import api_router
from carefold.config import settings
from carefold.db import close_db, init_db
from carefold.db.seeding import sync_bundled_assets_to_db
from carefold.constants.api import API_PREFIX, API_V1_PREFIX, ROUTE_ROOT_HEALTH
from carefold.constants.defaults import (
    APP_DESCRIPTION,
    APP_TITLE,
    DEFAULT_HOST,
    DEFAULT_PORT,
)

from carefold.logging import configure_logging, get_logger
from carefold.migration import run_first_launch_migration

configure_logging()
logger = get_logger("carefold.main")


INSECURE_BIND_OVERRIDE_ENV = "CAREFOLD_ALLOW_UNAUTHENTICATED_NETWORK_BIND"


def check_host_binding_security(host: str, auth_provider: Optional[str] = None) -> None:
    """Refuses to start when auth is disabled on a non-loopback bind (explicit override only)."""
    enforce_bind_safety(
        (host or DEFAULT_HOST).strip(),
        auth_provider or getattr(settings, "auth_provider", "local"),
        override_env=INSECURE_BIND_OVERRIDE_ENV,
        product="Carefold",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    active_host = (
        os.getenv("CAREFOLD_HOST")
        or os.getenv("CAREFOLD_BACKEND_HOST")
        or os.getenv("HOST")
        or DEFAULT_HOST
    )
    check_host_binding_security(active_host, getattr(settings, "auth_provider", None))
    logger.info("starting_carefold_backend", version=__version__, log_level=settings.log_level)
    logger.info(
        "workspace_configuration",
        root=str(settings.workspace_root),
        home=str(settings.home_dir),
        ollama=settings.ollama_url,
    )
    logger.info(
        "audit_configuration",
        path=str(settings.get_audit_log_path()),
        store_bodies=settings.audit_store_bodies,
    )
    try:
        migrated = run_first_launch_migration(
            home_dir=settings.home_dir,
            workspace_root=settings.workspace_root,
        )
        if migrated:
            logger.info("first_launch_migration_completed_successfully")
    except Exception as migration_err:
        logger.error(
            "first_launch_migration_failed",
            error=str(migration_err),
            exc_info=True,
        )
    try:
        from yarvelle_core.pack.loader import discover_and_load_packs
        discover_and_load_packs(enabled_pack_ids=["health"])
        logger.info("packs_loaded_successfully", packs=["health"])
    except Exception as pack_err:
        logger.warning("packs_discovery_warning", error=str(pack_err))

    await init_db()
    try:
        await sync_bundled_assets_to_db()
    except Exception as err:
        logger.warning("bundled_assets_seeding_failed", error=str(err))
    yield
    await close_db()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application."""
    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )

    # Configure CORS middleware for Next.js frontend communication
    app.add_middleware(CORSMiddleware, **build_cors_options(settings.cors_origins))

    # Mount canonical versioned API routes under /api/v1
    app.include_router(api_router, prefix=API_V1_PREFIX)

    # Mount transparent legacy unversioned alias under /api for backward compatibility
    app.include_router(api_router, prefix=API_PREFIX, include_in_schema=False)

    # Root redirect / alias for health check
    @app.get(ROUTE_ROOT_HEALTH, include_in_schema=False)
    async def root_health():
        from carefold.api.health import get_health
        return await get_health()

    return app


app = create_app()


def run() -> None:
    """Runs the server using uvicorn."""
    env_port = os.getenv("CAREFOLD_BACKEND_PORT") or os.getenv("PORT")
    port = int(env_port) if env_port and env_port.isdigit() else DEFAULT_PORT
    host = (
        os.getenv("CAREFOLD_HOST")
        or os.getenv("CAREFOLD_BACKEND_HOST")
        or os.getenv("HOST")
        or DEFAULT_HOST
    )
    check_host_binding_security(host, getattr(settings, "auth_provider", None))
    uvicorn.run(
        "carefold.main:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    run()
