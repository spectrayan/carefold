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
from typing import AsyncIterator, Optional, Sequence
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

try:
    from yarvelle_core.api.errors import register_error_handlers
except ImportError:  # pragma: no cover - yarvelle-core <=0.2.4
    register_error_handlers = None  # type: ignore[assignment]
from yarvelle_core.api.http_security import build_cors_options, enforce_bind_safety

from carefold import __version__
from carefold.api.router import api_router
from carefold.checkpoint_env import check_checkpoint_key_at_startup
from carefold.config import settings
from carefold.data_dir import (
    DataDirInstanceLock,
    apply_data_dir,
    detect_runtime_mode,
    harden_data_dir_tree,
    parse_cli_args,
    resolve_active_host_and_port,
    resolve_data_dir,
)
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


def _resolve_active_host_and_port() -> tuple[str, int]:
    return resolve_active_host_and_port()


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
    active_host, active_port = _resolve_active_host_and_port()
    check_host_binding_security(active_host, getattr(settings, "auth_provider", None))

    # Re-evaluate canonical data directory if environment/CLI override changed after import
    if os.getenv("CAREFOLD_DATA_DIR"):
        resolved_home = resolve_data_dir()
        if settings.home_dir.resolve() != resolved_home:
            apply_data_dir(resolved_home)

    active_mode = detect_runtime_mode(settings.workspace_root)
    is_local_sqlite = settings.get_database_url().lower().startswith("sqlite")
    instance_lock: Optional[DataDirInstanceLock] = None
    if is_local_sqlite:
        instance_lock = DataDirInstanceLock(
            settings.home_dir,
            host=active_host,
            port=active_port,
            mode=active_mode,
            version=__version__,
        )
        instance_lock.acquire(check_schema=True)

    try:
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
        # Fail fast in server mode when encrypted checkpoints have no vault key.
        check_checkpoint_key_at_startup()
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
        if is_local_sqlite:
            harden_data_dir_tree(settings.home_dir)
        try:
            await sync_bundled_assets_to_db()
        except Exception as err:
            logger.warning("bundled_assets_seeding_failed", error=str(err))
        yield
    finally:
        await close_db()
        if instance_lock is not None:
            instance_lock.release()
        logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application."""
    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )
    if register_error_handlers is not None:
        register_error_handlers(app)

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


def run(argv: Optional[Sequence[str]] = None) -> None:
    """Runs the Carefold backend server using uvicorn."""
    args = parse_cli_args(argv)
    if args.data_dir:
        apply_data_dir(args.data_dir, set_cli_override=True)
    if getattr(args, "explicit_host", None) is not None:
        os.environ["CAREFOLD_BACKEND_HOST"] = str(args.host)
    if getattr(args, "explicit_port", None) is not None:
        os.environ["CAREFOLD_BACKEND_PORT"] = str(args.port)
    check_host_binding_security(args.host, getattr(settings, "auth_provider", None))
    uvicorn.run(
        "carefold.main:app",
        host=args.host,
        port=int(args.port),
        reload=False,
    )


if __name__ == "__main__":
    run()
