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

"""FastAPI Internationalization (i18n) endpoints for locale discovery, RFC 4647 negotiation, and ICU catalogs."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from carefold.i18n.catalog import (
    get_catalog,
    get_localized_disclaimer,
    get_localized_emergency_directive,
)
from carefold.i18n.locale import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    canonicalize_locale,
    get_text_direction,
    negotiate_locale,
)

router = APIRouter(prefix="/i18n", tags=["i18n"])


class LocaleMetadataItem(BaseModel):
    """Metadata descriptor for a supported Carefold locale."""

    code: str = Field(..., description="Canonical IETF BCP 47 locale tag")
    name: str = Field(..., description="English display name of the locale")
    native_name: str = Field(..., description="Native autonym display name")
    direction: Literal["ltr", "rtl"] = Field(..., description="Script layout direction (ltr or rtl)")
    region: str = Field(..., description="ISO 3166-1 alpha-2 region code")


class SupportedLocalesResponse(BaseModel):
    """Response payload for GET /i18n/locales."""

    default_locale: str = Field(default=DEFAULT_LOCALE, description="System fallback locale")
    negotiated_locale: str = Field(..., description="Negotiated locale via RFC 4647 lookup")
    locales: List[LocaleMetadataItem] = Field(..., description="List of supported locales")


class LocaleCatalogResponse(BaseModel):
    """Response payload for GET /i18n/catalog/{locale}."""

    locale: str = Field(..., description="Resolved canonical BCP 47 locale tag")
    requested_locale: str = Field(..., description="Canonicalized requested locale tag")
    direction: Literal["ltr", "rtl"] = Field(..., description="Text layout direction (ltr or rtl)")
    disclaimer: str = Field(..., description="Localized non-clinical disclaimer banner")
    emergency_directive: str = Field(..., description="Localized acute emergency refusal directive")
    messages: Dict[str, Any] = Field(..., description="ICU MessageFormat translation catalog")


@router.get("/locales", response_model=SupportedLocalesResponse)
async def list_supported_locales(
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    profile_locale: Optional[str] = Query(default=None, description="Optional active profile locale override"),
    user_locale: Optional[str] = Query(default=None, description="Optional user preferred locale"),
) -> SupportedLocalesResponse:
    """Returns supported locales metadata, default locale, and negotiated locale via RFC 4647."""
    negotiated = negotiate_locale(
        accept_language=accept_language,
        profile_locale=profile_locale,
        user_locale=user_locale,
        default=DEFAULT_LOCALE,
    )
    items = [
        LocaleMetadataItem(
            code=meta["code"],
            name=meta["name"],
            native_name=meta["native_name"],
            direction=get_text_direction(meta["code"]),
            region=meta["region"],
        )
        for meta in SUPPORTED_LOCALES.values()
    ]
    return SupportedLocalesResponse(
        default_locale=DEFAULT_LOCALE,
        negotiated_locale=negotiated,
        locales=items,
    )


@router.get("/catalog/{locale}", response_model=LocaleCatalogResponse)
async def get_locale_catalog(locale: str) -> LocaleCatalogResponse:
    """Returns canonical locale, text direction, ICU messages catalog, disclaimer, and emergency directive."""
    try:
        canonical_req = canonicalize_locale(locale, strict=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid or malformed BCP 47 locale tag.",
        ) from exc

    resolved_locale = negotiate_locale(profile_locale=canonical_req, default=DEFAULT_LOCALE)
    catalog_data = get_catalog(resolved_locale)
    direction = get_text_direction(resolved_locale)

    messages: Dict[str, Any] = {
        k: v
        for k, v in catalog_data.items()
        if k not in ("locale", "direction")
    }

    return LocaleCatalogResponse(
        locale=resolved_locale,
        requested_locale=canonical_req,
        direction=direction,
        disclaimer=get_localized_disclaimer(resolved_locale),
        emergency_directive=get_localized_emergency_directive(resolved_locale),
        messages=messages,
    )


__all__ = [
    "LocaleCatalogResponse",
    "LocaleMetadataItem",
    "SupportedLocalesResponse",
    "get_locale_catalog",
    "list_supported_locales",
    "router",
]
