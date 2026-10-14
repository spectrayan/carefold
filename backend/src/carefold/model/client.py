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

"""OpenAI-compatible HTTP SSE streaming client targeting local Ollama."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx

from carefold.model.types import (
    ModelMessage,
    ModelStreamChunk,
    ModelToolCallChunk,
    ModelToolFunction,
    StreamChoice,
    StreamDelta,
)

logger = logging.getLogger(__name__)


class OpenAIModelClient:
    """Async streaming client for OpenAI-compatible endpoints (defaulting to Ollama)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434/v1",
        model: str = "llama3.2",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def get_model_name(self) -> str:
        return self.model

    async def check_health(self) -> Dict[str, Any]:
        """Checks if upstream model server is reachable."""
        endpoint = f"{self.base_url}/models"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(endpoint)
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("id") for m in data.get("data", []) if "id" in m]
                    return {
                        "status": "connected",
                        "endpoint": self.base_url,
                        "reachable": True,
                        "activeModel": self.model,
                        "availableModels": models,
                        "error": None,
                    }
                return {
                    "status": "degraded",
                    "endpoint": self.base_url,
                    "reachable": False,
                    "activeModel": self.model,
                    "availableModels": [],
                    "error": f"HTTP {res.status_code}",
                }
        except Exception as err:
            return {
                "status": "unreachable",
                "endpoint": self.base_url,
                "reachable": False,
                "activeModel": self.model,
                "availableModels": [],
                "error": str(err),
            }

    async def stream_chat(
        self,
        messages: List[ModelMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[ModelStreamChunk]:
        """Streams chat completion chunks from the model server."""
        url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise RuntimeError(
                            f"Model server error (HTTP {response.status_code}): {body.decode('utf-8', errors='replace')}"
                        )

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue

                        data_str = line[len("data:") :].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk_dict = json.loads(data_str)
                        except Exception:
                            continue

                        choices: List[StreamChoice] = []
                        for ch in chunk_dict.get("choices", []):
                            idx = ch.get("index", 0)
                            finish_reason = ch.get("finish_reason")
                            d_dict = ch.get("delta", {})

                            tool_chunks: Optional[List[ModelToolCallChunk]] = None
                            if "tool_calls" in d_dict and isinstance(d_dict["tool_calls"], list):
                                tool_chunks = []
                                for tc in d_dict["tool_calls"]:
                                    fn_dict = tc.get("function", {})
                                    tool_chunks.append(
                                        ModelToolCallChunk(
                                            index=tc.get("index", 0),
                                            id=tc.get("id"),
                                            type=tc.get("type", "function"),
                                            function=ModelToolFunction(
                                                name=fn_dict.get("name", ""),
                                                arguments=fn_dict.get("arguments", ""),
                                            ),
                                        )
                                    )

                            delta = StreamDelta(
                                content=d_dict.get("content"),
                                tool_calls=tool_chunks,
                            )
                            choices.append(
                                StreamChoice(
                                    index=idx,
                                    delta=delta,
                                    finish_reason=finish_reason,
                                )
                            )

                        yield ModelStreamChunk(
                            id=chunk_dict.get("id"),
                            choices=choices,
                        )

        except httpx.ConnectError as conn_err:
            raise RuntimeError(
                f"Model server unreachable at {self.base_url}. Ensure Ollama or compatible server is running."
            ) from conn_err
