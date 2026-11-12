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

"""Carefold domain-pack host bridges delegating execution to yarvelle_core."""

from __future__ import annotations

import collections
import json
from pathlib import Path
import re
import threading
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence, Union

from fastapi import APIRouter, Depends, Request, Response, status
from langgraph.store.base import BaseStore
from sqlalchemy import select

try:
    from yarvelle_core import identity as _yc_identity
except ImportError:  # pragma: no cover - yarvelle-core <=0.2.4
    _yc_identity = None  # type: ignore[assignment]

import yarvelle_core.api.admin as _yc_admin
import yarvelle_core.api.auth as _yc_auth
from yarvelle_core.api.deps import get_auth

try:
    from yarvelle_core.api.errors import ProblemDetailsRoute as _ProblemDetailsRoute
except ImportError:  # pragma: no cover - yarvelle-core <=0.2.4
    _ProblemDetailsRoute = None  # type: ignore[assignment]
from yarvelle_core.auth.ports import AuthPort
from yarvelle_core.db.models import Note
import yarvelle_core.engine.job_runner as _yc_job_runner
import yarvelle_core.loaders.skill_loader as _yc_skill_loader
from yarvelle_core.resources.loader import ResourceLoader as _CoreResourceLoader
import yarvelle_core.storage.extract as _yc_extract
from yarvelle_core.storage.extract import ExtractionResult
from yarvelle_core.templates.engine import TemplateEngine as _CoreTemplateEngine
from yarvelle_core.workflows.nodes.input_guardrail_node import (
    InputGuardrailNode as _CoreInputGuardrailNode,
)
from yarvelle_core.workflows.nodes.refusal_node import (
    RefusalNode as _CoreRefusalNode,
)

from carefold.constants.defaults import DEFAULT_VERSION

_SKILL_LOADER_LOCK = threading.RLock()
_CAREFOLD_RESOURCES_DIR = (Path(__file__).resolve().parent.parent / "resources").resolve()
_CAREFOLD_TEMPLATES_DIR = (_CAREFOLD_RESOURCES_DIR / "prompts" / "templates").resolve()


def _session_cookie_name() -> str:
    if _yc_identity is not None and hasattr(_yc_identity, "session_cookie_name"):
        return str(_yc_identity.session_cookie_name())
    return "carefold_session"


def _replace_session_cookie(response: Response, token: Optional[str]) -> None:
    """Rewrites yarvelle_session Set-Cookie header to Carefold's brand session cookie."""
    cookie_name = _session_cookie_name()
    response.raw_headers[:] = [
        (k, v)
        for k, v in response.raw_headers
        if not (k.lower() == b"set-cookie" and v.startswith(b"yarvelle_session="))
    ]
    if token:
        response.set_cookie(
            key=cookie_name,
            value=token,
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=60 * 60 * 24 * 7,
            path="/",
        )


def build_carefold_auth_router() -> APIRouter:
    """Builds the auth router issuing Carefold's brand session cookie (`carefold_session`)."""
    router = (
        APIRouter(route_class=_ProblemDetailsRoute)
        if _ProblemDetailsRoute is not None
        else APIRouter()
    )

    @router.post("/register", status_code=status.HTTP_201_CREATED)
    async def register(
        body: _yc_auth.RegisterUserRequest,
        request: Request,
        response: Response,
        auth_port: AuthPort = Depends(get_auth),
    ) -> Dict[str, Any]:
        result = await _yc_auth.register(
            body=body,
            request=request,
            response=response,
            auth_port=auth_port,
        )
        if result.get("token"):
            _replace_session_cookie(response, str(result["token"]))
        return result

    @router.post("/login")
    async def login(
        body: _yc_auth.LoginRequest,
        request: Request,
        response: Response,
        auth_port: AuthPort = Depends(get_auth),
    ) -> Dict[str, Any]:
        result = await _yc_auth.login(
            body=body,
            request=request,
            response=response,
            auth_port=auth_port,
        )
        if result.get("token"):
            _replace_session_cookie(response, str(result["token"]))
        return result

    @router.post("/logout")
    async def logout(
        request: Request,
        response: Response,
        auth_port: AuthPort = Depends(get_auth),
    ) -> Dict[str, Any]:
        cookie_name = _session_cookie_name()
        token: Optional[str] = request.cookies.get(cookie_name) or request.cookies.get(
            "yarvelle_session"
        )
        if not token:
            auth_header = request.headers.get("Authorization") or request.headers.get(
                "authorization"
            )
            if auth_header:
                if auth_header.lower().startswith("bearer "):
                    token = auth_header[7:].strip()
                else:
                    token = auth_header.strip()

        if token:
            await auth_port.revoke_session(token)

        response.delete_cookie(key=cookie_name, path="/")
        return {"success": True}

    overridden_paths = {"/register", "/login", "/logout"}
    for route in _yc_auth.router.routes:
        if getattr(route, "path", None) not in overridden_paths:
            router.routes.append(route)

    return router


def configure_carefold_admin_router() -> APIRouter:
    """Aligns admin diagnostics DEFAULT_VERSION with Carefold's host runtime version."""
    _yc_admin.DEFAULT_VERSION = DEFAULT_VERSION
    return _yc_admin.router


_EXTRACT_SYNC_ATTRS = (
    "is_ocr_available",
    "is_pypdf_available",
    "Image",
    "pytesseract",
    "pypdf",
    "_OCR_AVAILABLE",
    "_PYPDF_AVAILABLE",
    "read_cas_file",
    "extract_text_from_pdf_bytes",
)


def extract_document_text_compat(*args: Any, **kwargs: Any) -> ExtractionResult:
    """Delegates document extraction to yarvelle_core while syncing patched module attributes."""
    import carefold.storage.extract as _cf_extract

    saved: Dict[str, Any] = {}
    for attr in _EXTRACT_SYNC_ATTRS:
        if attr in _cf_extract.__dict__ and hasattr(_yc_extract, attr):
            orig = getattr(_yc_extract, attr)
            cur = _cf_extract.__dict__[attr]
            if cur is not orig:
                saved[attr] = orig
                setattr(_yc_extract, attr, cur)
    try:
        return _yc_extract.extract_document_text(*args, **kwargs)
    finally:
        for attr, orig in saved.items():
            setattr(_yc_extract, attr, orig)


def extract_cas_document_compat(
    yarvelle_home: Optional[Path] = None,
    user_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    sha256_hash: str = "",
    filename: str = "",
    mime_type: Optional[str] = None,
    *,
    carefold_home: Optional[Path] = None,
) -> ExtractionResult:
    """Delegates CAS extraction to yarvelle_core while accepting legacy carefold_home kwarg."""
    home = yarvelle_home if yarvelle_home is not None else carefold_home
    if home is None:
        raise TypeError("extract_cas_document() missing required home path ('yarvelle_home' or 'carefold_home')")
    import carefold.storage.extract as _cf_extract

    saved: Dict[str, Any] = {}
    for attr in _EXTRACT_SYNC_ATTRS:
        if attr in _cf_extract.__dict__ and hasattr(_yc_extract, attr):
            orig = getattr(_yc_extract, attr)
            cur = _cf_extract.__dict__[attr]
            if cur is not orig:
                saved[attr] = orig
                setattr(_yc_extract, attr, cur)
    try:
        return _yc_extract.extract_cas_document(
            yarvelle_home=home,
            user_id=user_id,
            profile_id=profile_id,
            sha256_hash=sha256_hash,
            filename=filename,
            mime_type=mime_type,
        )
    finally:
        for attr, orig in saved.items():
            setattr(_yc_extract, attr, orig)


extract_cas_attachment_compat = extract_cas_document_compat


async def handle_extract_text_job_compat(
    job: Any,
    session_factory: Optional[Any] = None,
    yarvelle_home: Optional[Path] = None,
    *,
    carefold_home: Optional[Path] = None,
) -> None:
    """Delegates extract_text job execution to yarvelle_core with carefold_home kwarg support."""
    home = yarvelle_home if yarvelle_home is not None else carefold_home
    await _yc_job_runner.handle_extract_text_job(
        job=job,
        session_factory=session_factory,
        yarvelle_home=home,
    )


def create_extract_text_handler_compat(
    session_factory: Optional[Any] = None,
    yarvelle_home: Optional[Path] = None,
    *,
    carefold_home: Optional[Path] = None,
) -> Callable[[Any], Coroutine[Any, Any, None]]:
    """Factory creating an extract_text job handler accepting yarvelle_home or carefold_home."""
    home = yarvelle_home if yarvelle_home is not None else carefold_home

    async def extract_text_job_handler(job: Any) -> None:
        await handle_extract_text_job_compat(
            job=job,
            session_factory=session_factory,
            yarvelle_home=home,
        )

    return extract_text_job_handler


async def handle_index_doc_job_compat(
    job: Any,
    session_factory: Optional[Any] = None,
) -> None:
    """Delegates index_doc job execution to yarvelle_core with Carefold clinical_note source tag."""
    if isinstance(job, dict):
        payload: Dict[str, Any] = dict(job)
    else:
        raw_payload = getattr(job, "payload", {})
        if isinstance(raw_payload, str):
            try:
                payload = dict(json.loads(raw_payload))
            except Exception:
                payload = {}
        elif hasattr(raw_payload, "payload_dict"):
            payload = dict(raw_payload.payload_dict)
        elif isinstance(raw_payload, dict):
            payload = dict(raw_payload)
        else:
            payload = {}
        if not payload.get("profile_id") and getattr(job, "profile_id", None):
            payload["profile_id"] = getattr(job, "profile_id")

    doc_type = payload.get("doc_type")
    document_id = payload.get("document_id")
    sf = session_factory or getattr(job, "_session_factory", None)
    if sf is None:
        try:
            from carefold.db.session import get_session_factory

            sf = get_session_factory()
        except Exception:
            sf = None

    if payload.get("text") is None and document_id and doc_type in ("note", None) and sf is not None:
        async with sf() as session:
            note = (await session.execute(select(Note).where(Note.id == document_id))).scalar_one_or_none()
            if note is not None:
                title_prefix = f"# {note.title}\n\n" if note.title else ""
                meta = dict(payload.get("metadata") or {})
                meta.update(
                    {
                        "title": note.title or "",
                        "slug": note.slug or "",
                        "type": note.type or "scratchpad",
                        "source": "clinical_note",
                        "doc_type": "note",
                        "created_at": note.created_at.isoformat()
                        if hasattr(note.created_at, "isoformat")
                        else str(note.created_at),
                        "updated_at": note.updated_at.isoformat()
                        if hasattr(note.updated_at, "isoformat")
                        else str(note.updated_at),
                    }
                )
                enriched = dict(payload)
                enriched["doc_type"] = "note"
                enriched["profile_id"] = str(note.profile_id or payload.get("profile_id") or "").strip()
                enriched["user_id"] = payload.get("user_id") or note.user_id
                enriched["text"] = f"{title_prefix}{note.content or ''}"
                enriched["metadata"] = meta
                await _yc_job_runner.handle_index_doc_job(job=enriched, session_factory=sf)
                return

    await _yc_job_runner.handle_index_doc_job(job=job, session_factory=session_factory)


class CarefoldJobRunner(_yc_job_runner.JobRunner):
    """JobRunner binding Carefold's extract_text and index_doc compatibility handlers."""

    async def _default_extract_text_handler(self, job: Any) -> None:
        await handle_extract_text_job_compat(job=job, session_factory=self.session_factory)

    async def _default_index_doc_handler(self, job: Any) -> None:
        await handle_index_doc_job_compat(job=job, session_factory=self.session_factory)

    async def execute_job(self, job: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(job, "attempts", None) is None:
            try:
                job.attempts = 0
            except Exception:
                pass

        import carefold.engine.job_runner as _cf_jr

        orig_exec = _yc_job_runner.execute_tool_call
        patched_exec = getattr(_cf_jr, "execute_tool_call", orig_exec)
        if patched_exec is not orig_exec:
            _yc_job_runner.execute_tool_call = patched_exec
            try:
                return await super().execute_job(job, *args, **kwargs)
            finally:
                _yc_job_runner.execute_tool_call = orig_exec
        return await super().execute_job(job, *args, **kwargs)


class CarefoldWorkflowRefusalNode(_CoreRefusalNode):
    """Workflow RefusalNode enriching core's F-29 refusal state with Carefold's clinical advisory."""

    async def execute(self, state: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        from langchain_core.messages import AIMessage

        res = await super().execute(state, **kwargs)
        disclaimers = CarefoldResourceLoader().get_disclaimers()
        refusal_text = str(disclaimers.get("f29_refusal_template") or res.get("output") or "").strip()
        if refusal_text:
            res["messages"] = [AIMessage(content=refusal_text)]
            res["output"] = refusal_text
            res["refusal_message"] = refusal_text
        return res


class CarefoldInputGuardrailNode(_CoreInputGuardrailNode):
    """InputGuardrailNode gating clinical domain on strict allow_assist===True and formatting patient recall."""

    async def execute(
        self, state: Dict[str, Any], *, store: Optional[BaseStore] = None, **kwargs: Any
    ) -> Dict[str, Any]:
        orig_domain = state.get("target_domain") or state.get("domain")
        call_state = dict(state)
        if orig_domain == "clinical":
            call_state["target_domain"] = "assist"

        res = await super().execute(call_state, store=store, **kwargs)

        if orig_domain == "clinical" and res.get("refusal_reason") == "assist_consent_required":
            res["refusal_reason"] = "clinical_consent_required"
            res["refusal_message"] = (
                "Clinical assist features require explicit user consent (allow_assist=True)."
            )
            if isinstance(res.get("safety_metadata"), dict):
                res["safety_metadata"] = {
                    **res["safety_metadata"],
                    "reason": "clinical_consent_required",
                }

        if not res.get("is_refusal"):
            if isinstance(res.get("memory_context"), str):
                res["memory_context"] = res["memory_context"].replace(
                    "### Relevant User Context",
                    "### Relevant Patient Context",
                )
            if isinstance(res.get("system_prompt"), str):
                res["system_prompt"] = res["system_prompt"].replace(
                    "### Relevant User Context",
                    "### Relevant Patient Context",
                )

        return res


def load_skill_compat(skill_dir: Union[Path, str]) -> Any:
    """Loads a skill manifest supporting both yarvelle.yaml and legacy carefold.yaml."""
    skill_path = Path(skill_dir).resolve()
    has_yarvelle = (skill_path / "yarvelle.yaml").is_file() or (
        skill_path / "yarvelle.yaml.migrated"
    ).is_file()
    has_carefold = (skill_path / "carefold.yaml").is_file() or (
        skill_path / "carefold.yaml.migrated"
    ).is_file()

    if has_carefold and not has_yarvelle:
        with _SKILL_LOADER_LOCK:
            orig_yaml = _yc_skill_loader.YARVELLE_YAML_FILENAME
            orig_migrated = _yc_skill_loader.YARVELLE_YAML_MIGRATED_FILENAME
            _yc_skill_loader.YARVELLE_YAML_FILENAME = "carefold.yaml"
            _yc_skill_loader.YARVELLE_YAML_MIGRATED_FILENAME = "carefold.yaml.migrated"
            try:
                return _yc_skill_loader.load_skill(skill_path)
            finally:
                _yc_skill_loader.YARVELLE_YAML_FILENAME = orig_yaml
                _yc_skill_loader.YARVELLE_YAML_MIGRATED_FILENAME = orig_migrated

    return _yc_skill_loader.load_skill(skill_path)


def load_all_skills_compat(skills_dir: Union[Path, str]) -> List[Any]:
    """Loads all valid skills from skills_dir supporting both yarvelle.yaml and carefold.yaml."""
    skills_path = Path(skills_dir).resolve()
    if not skills_path.is_dir():
        return []
    skills: List[Any] = []
    for entry in sorted(skills_path.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            try:
                skills.append(load_skill_compat(entry))
            except _yc_skill_loader.ManifestValidationError:
                continue
    return skills


class CarefoldTemplateEngine(_CoreTemplateEngine):
    """TemplateEngine defaulting to Carefold's pack templates with fallback to core templates."""

    def __init__(self, templates_dir: Optional[Union[Path, str]] = None) -> None:
        super().__init__(templates_dir=templates_dir or _CAREFOLD_TEMPLATES_DIR)

    def resolve_template_source(
        self,
        template_name_or_source: str,
        custom_dir: Optional[Union[Path, str]] = None,
    ) -> str:
        try:
            return super().resolve_template_source(template_name_or_source, custom_dir)
        except FileNotFoundError:
            core_engine = _CoreTemplateEngine()
            return core_engine.resolve_template_source(template_name_or_source, custom_dir)


_DEFAULT_TEMPLATE_ENGINE: Optional[CarefoldTemplateEngine] = None
_TEMPLATE_ENGINE_LOCK = threading.Lock()


def get_carefold_template_engine(
    templates_dir: Optional[Union[Path, str]] = None,
) -> CarefoldTemplateEngine:
    global _DEFAULT_TEMPLATE_ENGINE
    if _DEFAULT_TEMPLATE_ENGINE is None or templates_dir is not None:
        with _TEMPLATE_ENGINE_LOCK:
            if _DEFAULT_TEMPLATE_ENGINE is None or templates_dir is not None:
                engine = CarefoldTemplateEngine(templates_dir)
                if templates_dir is None:
                    _DEFAULT_TEMPLATE_ENGINE = engine
                return engine
    return _DEFAULT_TEMPLATE_ENGINE


def render_carefold_template(
    template_name_or_source: str,
    context: Any,
    custom_dir: Optional[Union[Path, str]] = None,
) -> str:
    return get_carefold_template_engine().render(template_name_or_source, context, custom_dir)


class CarefoldResourceLoader(_CoreResourceLoader):
    """ResourceLoader defaulting to Carefold pack resources with Carefold agent registry lookup."""

    def __init__(self, resources_dir: Optional[Path] = None) -> None:
        super().__init__(resources_dir=resources_dir or _CAREFOLD_RESOURCES_DIR)

    def get_follow_up_suggestions(
        self,
        agent_id: str,
        prompt: str = "",
        completion: str = "",
        tools_used: Optional[List[str]] = None,
        user_queries: Optional[Sequence[str]] = None,
    ) -> List[str]:
        aid = (agent_id or "").lower().strip()
        try:
            from carefold.agents.registry import get_agent_registry as get_cf_registry

            cf_reg = get_cf_registry()
            agent_obj = cf_reg.get(aid) or cf_reg.get(aid.replace("-", "_"))
            if agent_obj and getattr(agent_obj, "suggestions", None):
                s_data = self.get_prompts().get("suggestions", {})
                aid_key = aid.replace("-", "_")
                inline = agent_obj.suggestions
                persona_def = (
                    dict(inline[aid_key])
                    if isinstance(inline, dict) and aid_key in inline
                    else dict(inline)
                    if isinstance(inline, dict)
                    else {}
                )
                if persona_def:
                    search_text = f"{(prompt or '').lower()} {(completion or '').lower()}".strip()
                    matched: List[str] = []
                    other: List[str] = []
                    hits: List[tuple[int, str]] = []
                    for k, val in persona_def.items():
                        if k.endswith("_keywords") and isinstance(val, list):
                            t_key = f"{k[:-len('_keywords')]}_chips"
                            cnt = sum(1 for w in val if isinstance(w, str) and w.lower() in search_text)
                            if cnt > 0 and t_key in persona_def:
                                hits.append((cnt, t_key))
                            elif t_key in persona_def:
                                other.extend(c for c in persona_def[t_key] if c not in other)
                    hits.sort(key=lambda x: x[0], reverse=True)
                    for _, t_key in hits:
                        matched.extend(c for c in persona_def.get(t_key, []) if c not in matched)
                    defaults = list(persona_def.get("default_chips", []))
                    pool = list(dict.fromkeys([*matched, *defaults, *other]))
                    if pool:
                        return pool[:3]
        except Exception:
            pass
        return super().get_follow_up_suggestions(
            agent_id=agent_id,
            prompt=prompt,
            completion=completion,
            tools_used=tools_used,
            user_queries=user_queries,
        )

    def format_error(self, error_key: str, **kwargs: Any) -> str:
        errors_map = self.get_errors().get("errors", {})
        if error_key in errors_map:
            err_def = errors_map[error_key]
            msg_template = str(err_def.get("template") or err_def.get("message", error_key))
            try:
                return msg_template.format_map(collections.defaultdict(str, kwargs))
            except Exception:
                return msg_template

        try:
            from yarvelle_core.errors.catalog import get_error_catalog

            spec = get_error_catalog().get(error_key)
            if spec is not None:
                msg_template = str(spec.template)
                try:
                    return msg_template.format_map(collections.defaultdict(str, kwargs))
                except Exception:
                    return msg_template
        except ImportError:
            core_errors = _CoreResourceLoader().get_errors().get("errors", {})
            if error_key in core_errors:
                err_def = core_errors[error_key]
                msg_template = str(err_def.get("template") or err_def.get("message", error_key))
                try:
                    return msg_template.format_map(collections.defaultdict(str, kwargs))
                except Exception:
                    return msg_template

        return error_key

    def get_error_status_code(self, error_key: str) -> int:
        errors_map = self.get_errors().get("errors", {})
        if error_key in errors_map:
            err_def = errors_map[error_key]
            return int(err_def.get("http_status", err_def.get("status_code", 500)))

        try:
            from yarvelle_core.errors.catalog import get_error_catalog

            spec = get_error_catalog().get(error_key)
            if spec is not None:
                return int(spec.http_status)
        except ImportError:
            core_errors = _CoreResourceLoader().get_errors().get("errors", {})
            if error_key in core_errors:
                err_def = core_errors[error_key]
                return int(err_def.get("http_status", err_def.get("status_code", 500)))

        return 500


async def record_audit_compat(
    event: Any,
    *args: Any,
    db: Any = None,
    session_factory: Any = None,
    **kwargs: Any,
) -> Any:
    """Delegates record_audit to yarvelle_core while honoring carefold.main.app get_db overrides."""
    import yarvelle_core.audit.logger as _yc_audit_logger

    if db is None and session_factory is None:
        try:
            from carefold.api.deps import get_db
            from carefold.main import app as _cf_app

            override = _cf_app.dependency_overrides.get(get_db)
            if override is not None:
                gen = override()
                if hasattr(gen, "__anext__"):
                    session = await gen.__anext__()
                    try:
                        return await _yc_audit_logger.record_audit(
                            event, *args, db=session, **kwargs
                        )
                    finally:
                        try:
                            await gen.__anext__()
                        except StopAsyncIteration:
                            pass
        except Exception:
            pass

    return await _yc_audit_logger.record_audit(
        event, *args, db=db, session_factory=session_factory, **kwargs
    )
