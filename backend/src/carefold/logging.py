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

"""Carefold structured logging framework using structlog.

Provides unified logging for Carefold, FastAPI, Uvicorn, and LangGraph with:
- Configurable log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Colored, human-readable terminal output during local development
- Machine-readable structured JSON output in production
- Context variables (thread_id, agent_id, run_id) tracing across async graph execution
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

import structlog
from structlog.types import EventDict, Processor


def _add_log_level(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Ensures log level is recorded consistently."""
    if "level" not in event_dict:
        event_dict["level"] = method_name
    return event_dict


def configure_logging(
    log_level: Optional[str] = None,
    json_format: Optional[bool] = None,
) -> None:
    """Configures structlog and standard library logging handlers."""
    from carefold.config import settings

    effective_level_str = (log_level or settings.log_level).upper()
    numeric_level = getattr(logging, effective_level_str, logging.INFO)
    use_json = json_format if json_format is not None else settings.log_json

    # Shared processors for both structlog and stdlib
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        _add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    if use_json:
        # Production JSON renderer
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        # Development colored console renderer
        renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(),
            pad_event_to=28,
        )

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure root standard library handler to route through structlog
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    # Set specific third-party logger levels to avoid excessive noise
    logging.getLogger("uvicorn.error").handlers.clear()
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Retrieves a bound structlog logger."""
    return structlog.get_logger(name or "carefold")


def sanitize_log_value(value: Any) -> str:
    """Sanitizes user input for safe logging by removing CRLF characters.

    Neutralizes log injection vulnerabilities (CWE-117 / py/log-injection)
    by stripping carriage return and newline characters that could allow
    attackers to forge log entries or corrupt log parsing.
    """
    if value is None:
        return ""
    return str(value).replace("\r", "").replace("\n", "")


__all__ = [
    "configure_logging",
    "get_logger",
    "sanitize_log_value",
]

