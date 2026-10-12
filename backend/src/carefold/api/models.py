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

"""Models discovery REST endpoint for dynamic local and cloud model listing."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query
import httpx

from carefold.config import settings
from carefold.constants.api import ROUTE_MODELS
from carefold.logging import get_logger

logger = get_logger("carefold.api.models")

router = APIRouter(tags=["Models"])

PREDEFINED_MODELS: Dict[str, List[Dict[str, str]]] = {
    "google": [
        {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
        {"id": "gemini-1.5-pro", "label": "Gemini 1.5 Pro"},
        {"id": "gemini-1.5-flash", "label": "Gemini 1.5 Flash"},
    ],
    "anthropic": [
        {"id": "claude-3-5-sonnet-20241022", "label": "Claude 3.5 Sonnet"},
        {"id": "claude-3-5-haiku-20241022", "label": "Claude 3.5 Haiku"},
        {"id": "claude-3-opus-20240229", "label": "Claude 3 Opus"},
    ],
    "openai": [
        {"id": "gpt-4o", "label": "GPT-4o"},
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini"},
        {"id": "o1-preview", "label": "o1-Preview"},
        {"id": "o1-mini", "label": "o1-Mini"},
    ],
}


def _is_embedding_model(name: str, capabilities: Optional[List[str]] = None) -> bool:
    """Checks if a model is exclusively for embeddings."""
    lower = name.lower()
    if "embed" in lower or "embedding" in lower:
        return True
    if capabilities and "embedding" in capabilities and "completion" not in capabilities:
        return True
    return False


def _format_model_label(name: str, parameter_size: Optional[str] = None) -> str:
    """Formats raw tag name into human-readable label with parameter size."""
    colon_idx = name.rfind(":")
    base_name = name[:colon_idx] if colon_idx != -1 else name
    tag = name[colon_idx + 1 :] if colon_idx != -1 else ""

    slash_idx = base_name.rfind("/")
    short_base = base_name[slash_idx + 1 :] if slash_idx != -1 else base_name

    # Spacing and capitalization: 'llama3.1' -> 'Llama 3.1'
    formatted = re.sub(r"^([a-zA-Z]+)(\d.*)$", r"\1 \2", short_base)
    formatted = formatted[:1].upper() + formatted[1:] if formatted else formatted

    if tag and tag != "latest":
        tag_info = f" ({tag})"
    elif parameter_size:
        tag_info = f" ({parameter_size})"
    else:
        tag_info = ""

    return f"{formatted}{tag_info}"


@router.get(ROUTE_MODELS)
async def list_models(
    provider: str = Query(default="ollama"),
    endpoint: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Lists available models for a given provider.
    
    Dynamically queries Ollama /api/tags when provider is 'ollama',
    filtering out embedding-only models.
    """
    raw_prov = provider if isinstance(provider, str) else getattr(provider, "default", "ollama")
    prov_lower = str(raw_prov).lower()

    if prov_lower != "ollama":
        models = PREDEFINED_MODELS.get(prov_lower, [])
        return {
            "provider": prov_lower,
            "models": models,
            "reachable": True,
        }

    # Resolve Ollama base URL
    ep_val = endpoint if isinstance(endpoint, str) else getattr(endpoint, "default", None)
    raw_endpoint = ep_val or settings.ollama_url or "http://127.0.0.1:11434"
    clean_endpoint = raw_endpoint.rstrip("/").removesuffix("/v1")

    # Validate Ollama endpoint against egress policy before polling tags
    from carefold.model.egress import validate_model_endpoint
    validate_model_endpoint("ollama", clean_endpoint)

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{clean_endpoint}/api/tags")

        if resp.status_code == 200:
            data = resp.json()
            raw_models = data.get("models", [])

            chat_models: List[Dict[str, str]] = []
            for m in raw_models:
                m_name = m.get("name", "")
                if not m_name or _is_embedding_model(m_name, m.get("capabilities")):
                    continue

                details = m.get("details", {})
                param_size = details.get("parameter_size")
                label = _format_model_label(m_name, param_size)

                chat_models.append({
                    "id": m_name,
                    "label": label,
                })

            logger.info("ollama_models_discovered", count=len(chat_models), endpoint=clean_endpoint)
            return {
                "provider": "ollama",
                "models": chat_models,
                "reachable": True,
            }
        else:
            logger.warning("ollama_tags_status_error", status_code=resp.status_code, endpoint=clean_endpoint)
    except Exception as err:
        logger.warning("ollama_unreachable", endpoint=clean_endpoint, error=str(err))

    # Fallback to default model option if Ollama is offline
    return {
        "provider": "ollama",
        "models": [{"id": settings.default_model, "label": f"{settings.default_model.capitalize()} (Default)"}],
        "reachable": False,
    }


__all__ = ["router", "list_models"]
