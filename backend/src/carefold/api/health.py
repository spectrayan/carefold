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

"""Health check endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Dict
from fastapi import APIRouter
import httpx

from carefold.config import settings
from carefold.constants.api import HTTP_OK, ROUTE_HEALTH
from carefold.constants.defaults import DEFAULT_VERSION
from carefold.constants.models import HEALTH_CHECK_TIMEOUT_SECONDS, OLLAMA_MODELS_PATH
from carefold.schemas.health import HealthResponse, OllamaHealthStatus, WorkspaceInfo

router = APIRouter(tags=["Health"])

START_TIME = time.time()


@router.get(ROUTE_HEALTH, response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Returns system health, model reachability, and workspace stats."""
    uptime = time.time() - START_TIME
    ws_root = settings.workspace_root
    agents_dir = settings.get_agents_dir()
    skills_dir = settings.get_skills_dir()

    agents_count = len([d for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]) if agents_dir.is_dir() else 0
    skills_count = len([d for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]) if skills_dir.is_dir() else 0

    workspace_info = WorkspaceInfo(
        root=str(ws_root),
        agentsCount=agents_count,
        skillsCount=skills_count,
    )

    # Check Ollama connectivity
    ollama_status: OllamaHealthStatus
    try:
        raw_url = settings.ollama_url.rstrip("/")
        clean_endpoint = raw_url.removesuffix("/v1")
        async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT_SECONDS) as client:
            models: list[str] = []
            connected = False
            last_err: str | None = None

            # First attempt native Ollama /api/tags
            try:
                res_tags = await client.get(f"{clean_endpoint}/api/tags")
                if res_tags.status_code == HTTP_OK:
                    data = res_tags.json()
                    models = [
                        m.get("name")
                        for m in data.get("models", [])
                        if isinstance(m, dict) and "name" in m
                    ]
                    connected = True
                else:
                    last_err = f"HTTP {res_tags.status_code}"
            except Exception as e:
                last_err = str(e)

            # Fallback to OpenAI-compatible /v1/models if native probe was unsuccessful
            if not connected:
                try:
                    res_v1 = await client.get(f"{clean_endpoint}/v1/models")
                    if res_v1.status_code == HTTP_OK:
                        data = res_v1.json()
                        models = [
                            m.get("id")
                            for m in data.get("data", [])
                            if isinstance(m, dict) and "id" in m
                        ]
                        connected = True
                    else:
                        last_err = f"HTTP {res_v1.status_code}"
                except Exception as e:
                    last_err = str(e)

            if connected:
                ollama_status = OllamaHealthStatus(
                    status="connected",
                    endpoint=settings.ollama_url,
                    reachable=True,
                    activeModel=settings.default_model,
                    availableModels=models,
                    error=None,
                )
            else:
                ollama_status = OllamaHealthStatus(
                    status="unreachable",
                    endpoint=settings.ollama_url,
                    reachable=False,
                    activeModel=settings.default_model,
                    availableModels=[],
                    error=last_err or "Ollama unreachable",
                )
    except Exception as err:
        ollama_status = OllamaHealthStatus(
            status="unreachable",
            endpoint=settings.ollama_url,
            reachable=False,
            activeModel=settings.default_model,
            availableModels=[],
            error=str(err),
        )

    overall_status = "ok" if ollama_status.reachable else "degraded"

    return HealthResponse(
        status=overall_status,
        version=DEFAULT_VERSION,
        uptime=round(uptime, 2),
        timestamp=datetime.now(timezone.utc).isoformat(),
        modelReachable=ollama_status.reachable,
        workspace=workspace_info,
        ollama=ollama_status,
        backendReachable=True,
    )
