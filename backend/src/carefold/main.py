# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Carefold FastAPI Application Entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncIterator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from carefold import __version__
from carefold.api.router import api_router
from carefold.config import settings
from carefold.db import close_db, init_db
from carefold.constants.api import API_PREFIX, ROUTE_ROOT_HEALTH
from carefold.constants.defaults import (
    APP_DESCRIPTION,
    APP_TITLE,
    DEFAULT_HOST,
    DEFAULT_PORT,
)

from carefold.logging import configure_logging, get_logger

configure_logging()
logger = get_logger("carefold.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("starting_carefold_backend", version=__version__, log_level=settings.log_level)
    logger.info("workspace_configuration", root=str(settings.workspace_root), ollama=settings.ollama_url)
    logger.info("audit_configuration", path=str(settings.get_audit_log_path()), store_bodies=settings.audit_store_bodies)
    await init_db()
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routes under /api
    app.include_router(api_router, prefix=API_PREFIX)

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
    host = os.getenv("CAREFOLD_BACKEND_HOST") or os.getenv("HOST") or DEFAULT_HOST
    uvicorn.run(
        "carefold.main:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    run()
