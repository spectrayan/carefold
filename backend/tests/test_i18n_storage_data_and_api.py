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

"""Unit and integration tests for Carefold i18n engine, UAX #15 NFC storage, ICU catalogs, and REST APIs."""

from __future__ import annotations

import hashlib
import json
from typing import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from carefold.api.i18n import router as i18n_router
from carefold.api.notes import router as notes_router
from carefold.api.profiles import router as profiles_router
from carefold.db.models import Attachment, HealthResource, Note, Profile, User
from carefold.db.session import get_session_factory, init_db
from carefold.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    canonicalize_locale,
    detect_multilingual_red_flag,
    format_icu_message,
    get_catalog,
    get_localized_disclaimer,
    get_localized_emergency_directive,
    get_text_direction,
    negotiate_locale,
    normalize_text_nfc,
    translate,
    validate_bcp47_tag,
)
from carefold.search.chunker import ClinicalChunker


@pytest.fixture
def i18n_test_client() -> Generator[TestClient, None, None]:
    """Creates an isolated FastAPI test client mounting i18n, profiles, and notes routers."""
    import asyncio
    from carefold.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER

    async def _setup_db() -> None:
        await init_db()
        factory = get_session_factory()
        async with factory() as session:
            existing = await session.get(User, DEFAULT_STEWARD_USER.id)
            if existing is None:
                session.add(
                    User(
                        id=DEFAULT_STEWARD_USER.id,
                        email=DEFAULT_STEWARD_USER.email,
                        username=DEFAULT_STEWARD_USER.username,
                        hashed_password="disabled-auth-placeholder",
                        full_name=DEFAULT_STEWARD_USER.full_name,
                        role=DEFAULT_STEWARD_USER.role,
                        preferred_locale="en-US",
                    )
                )
                await session.commit()

    asyncio.run(_setup_db())
    test_app = FastAPI()
    test_app.include_router(i18n_router, prefix="/api/v1")
    test_app.include_router(profiles_router, prefix="/api/v1/profiles", tags=["profiles"])
    test_app.include_router(notes_router, prefix="/api/v1")
    with TestClient(test_app) as client:
        yield client


def test_bcp47_validation_and_canonicalization() -> None:
    """Verifies IETF BCP 47 tag validation, case normalization, bare subtag mapping, and RTL detection."""
    assert validate_bcp47_tag("en-US") is True
    assert validate_bcp47_tag("es-ES") is True
    assert validate_bcp47_tag("zh-Hans-CN") is True
    assert validate_bcp47_tag("es-419") is True
    assert validate_bcp47_tag("invalid_tag_12345") is False
    assert validate_bcp47_tag("") is False
    assert validate_bcp47_tag("1234") is False

    assert canonicalize_locale("en_us") == "en-US"
    assert canonicalize_locale("es-es") == "es-ES"
    assert canonicalize_locale("es") == "es-ES"
    assert canonicalize_locale("fr") == "fr-FR"
    assert canonicalize_locale("hi") == "hi-IN"
    assert canonicalize_locale("ar") == "ar-SA"
    assert canonicalize_locale("en") == "en-US"
    assert canonicalize_locale(None) == DEFAULT_LOCALE

    assert get_text_direction("en-US") == "ltr"
    assert get_text_direction("es-ES") == "ltr"
    assert get_text_direction("hi-IN") == "ltr"
    assert get_text_direction("ar-SA") == "rtl"
    assert get_text_direction("he-IL") == "rtl"

    with pytest.raises(ValueError, match="Invalid IETF BCP 47 locale tag"):
        canonicalize_locale("invalid_tag_12345", strict=True)

    with pytest.raises(ValueError, match="non-empty"):
        canonicalize_locale("   ", strict=True)


def test_rfc4647_locale_negotiation_hierarchy() -> None:
    """Verifies RFC 4647 quality-weighted lookup and Profile -> User -> Accept-Language -> default priority."""
    # 1. Accept-Language q-weight sorting and prefix fallback (fr-CA -> fr-FR)
    negotiated_fr = negotiate_locale(accept_language="fr-CA,fr;q=0.9,en-US;q=0.8")
    assert negotiated_fr == "fr-FR"

    # 2. Higher q-weight wins regardless of position
    negotiated_es = negotiate_locale(accept_language="en-US;q=0.5, es-MX;q=0.95, fr-FR;q=0.8")
    assert negotiated_es == "es-ES"

    # 3. User locale overrides Accept-Language
    negotiated_user = negotiate_locale(
        accept_language="fr-CA,fr;q=0.9",
        user_locale="es-ES",
    )
    assert negotiated_user == "es-ES"

    # 4. Profile locale overrides both user_locale and Accept-Language
    negotiated_profile = negotiate_locale(
        accept_language="fr-CA,fr;q=0.9",
        user_locale="es-ES",
        profile_locale="hi-IN",
    )
    assert negotiated_profile == "hi-IN"

    # 5. Unsupported tags fall back cleanly to en-US
    assert negotiate_locale(accept_language="de-DE,ja-JP;q=0.8") == "en-US"
    assert negotiate_locale(accept_language=None, profile_locale=None, user_locale=None) == "en-US"


def test_uax15_nfc_canonical_normalization_and_chunking() -> None:
    """Verifies UAX #15 NFC composition produces identical bytes, SHA-256 digests, and clinical chunks."""
    decomposed_nfd = "Cafe\u0301 cl\u0069\u0301nico: re\u0301gimen de medicacio\u0301n"
    composed_nfc = "Caf\u00e9 cl\u00ednico: r\u00e9gimen de medicaci\u00f3n"

    assert decomposed_nfd != composed_nfc
    normalized = normalize_text_nfc(decomposed_nfd)
    assert normalized == composed_nfc
    assert "\u00e9" in normalized
    assert "\u0301" not in normalized

    # Content-addressed SHA-256 hashes match after NFC normalization
    hash_from_nfd = hashlib.sha256(normalize_text_nfc(decomposed_nfd).encode("utf-8")).hexdigest()
    hash_from_nfc = hashlib.sha256(composed_nfc.encode("utf-8")).hexdigest()
    assert hash_from_nfd == hash_from_nfc

    # ClinicalChunker normalizes decomposed input text into NFC chunks
    chunker = ClinicalChunker()
    chunks = chunker.chunk("doc-nfc-1", f"CHIEF COMPLAINT\n{decomposed_nfd}")
    assert len(chunks) == 1
    assert chunks[0].text == f"CHIEF COMPLAINT\n{composed_nfc}"


def test_icu_messageformat_interpolation_and_plural_rules_all_locales() -> None:
    """Verifies ICU variable interpolation and plural formatting across en-US, es-ES, fr-FR, hi-IN, and ar-SA."""
    for loc in ("en-US", "es-ES", "fr-FR", "hi-IN", "ar-SA"):
        assert loc in SUPPORTED_LOCALES
        cat = get_catalog(loc)
        assert "safety" in cat
        assert "preventive" in cat
        assert get_localized_disclaimer(loc)
        assert get_localized_emergency_directive(loc)

    # Variable interpolation
    assert translate("common.profile_greeting", locale="en-US", params={"name": "Maya"}) == "Hello, Maya"
    assert translate("common.profile_greeting", locale="es-ES", params={"name": "Maya"}) == "Hola, Maya"
    assert translate("common.profile_greeting", locale="fr-FR", params={"name": "Maya"}) == "Bonjour, Maya"
    assert translate("common.profile_greeting", locale="hi-IN", params={"name": "माया"}) == "नमस्ते, माया"
    assert translate("common.profile_greeting", locale="ar-SA", params={"name": "سارة"}) == "مرحباً، سارة"

    # ICU Plural rules across all 5 locales
    assert translate("preventive.due_summary", locale="en-US", params={"count": 0}) == "No items due"
    assert translate("preventive.due_summary", locale="en-US", params={"count": 1}) == "1 item due"
    assert translate("preventive.due_summary", locale="en-US", params={"count": 4}) == "4 items due"

    # Case-insensitive key lookup (Preventive.due_count)
    assert translate("Preventive.due_count", locale="es-ES", params={"count": 0}) == "Sin controles pendientes"
    assert translate("Preventive.due_count", locale="es-ES", params={"count": 1}) == "1 control pendiente"
    assert translate("Preventive.due_count", locale="es-ES", params={"count": 3}) == "3 controles pendientes"

    assert translate("preventive.due_summary", locale="fr-FR", params={"count": 0}) == "Aucun élément à prévoir"
    assert translate("preventive.due_summary", locale="fr-FR", params={"count": 1}) == "1 élément à prévoir"
    assert translate("preventive.due_summary", locale="fr-FR", params={"count": 5}) == "5 éléments à prévoir"

    assert translate("preventive.due_summary", locale="hi-IN", params={"count": 0}) == "कोई जांच बाकी नहीं है"
    assert translate("preventive.due_summary", locale="hi-IN", params={"count": 1}) == "1 जांच बाकी है"
    assert translate("preventive.due_summary", locale="hi-IN", params={"count": 3}) == "3 जांचें बाकी हैं"

    assert translate("preventive.due_summary", locale="ar-SA", params={"count": 0}) == "لا توجد فحوصات مستحقة"
    assert translate("preventive.due_summary", locale="ar-SA", params={"count": 1}) == "فحص 1 مستحق"
    assert translate("preventive.due_summary", locale="ar-SA", params={"count": 2}) == "فحصان مستحقان (2)"
    assert translate("preventive.due_summary", locale="ar-SA", params={"count": 5}) == "5 فحوصات مستحقة"

    # Direct format_icu_message invocation
    custom_icu = "{count, plural, zero {Zero labs} one {# lab} other {# labs}}"
    assert format_icu_message(custom_icu, {"count": 0}) == "Zero labs"
    assert format_icu_message(custom_icu, {"count": 1}) == "1 lab"
    assert format_icu_message(custom_icu, {"count": 7}) == "7 labs"


def test_multilingual_emergency_red_flag_detection() -> None:
    """Verifies acute emergency red-flag detection across English, Spanish, French, Hindi, and Arabic."""
    # English
    en_match = detect_multilingual_red_flag("I am having severe chest pain right now")
    assert en_match is not None
    assert en_match["locale"] == "en-US"
    assert en_match["matched_phrase"] == "chest pain"
    assert "911" in en_match["emergency_directive"]

    # Spanish
    es_match = detect_multilingual_red_flag("Tengo fuerte dolor en el pecho y dificultad para respirar")
    assert es_match is not None
    assert es_match["locale"] == "es-ES"
    assert es_match["matched_phrase"] == "dolor en el pecho"
    assert "112" in es_match["emergency_directive"]

    # French (testing with decomposed NFD accent on 'difficulte\u0301 a\u0300 respirer')
    fr_match = detect_multilingual_red_flag("J'ai une grande difficulte\u0301 a\u0300 respirer depuis ce matin")
    assert fr_match is not None
    assert fr_match["locale"] == "fr-FR"
    assert fr_match["matched_phrase"] == "difficulté à respirer"

    # Hindi
    hi_match = detect_multilingual_red_flag("मुझे अचानक सीने में दर्द और सांस लेने में तकलीफ हो रही है")
    assert hi_match is not None
    assert hi_match["locale"] == "hi-IN"
    assert hi_match["matched_phrase"] == "सीने में दर्द"

    # Arabic
    ar_match = detect_multilingual_red_flag("أشعر بوجود ألم في الصدر وضيق في التنفس")
    assert ar_match is not None
    assert ar_match["locale"] == "ar-SA"
    assert ar_match["matched_phrase"] == "ألم في الصدر"

    # Non-emergency query returns None
    assert detect_multilingual_red_flag("What questions should I ask at my annual checkup?") is None


def test_i18n_rest_endpoints_and_profile_note_persistence(i18n_test_client: TestClient) -> None:
    """Verifies /api/v1/i18n/* endpoints, profile preferred_locale, and note locale + NFC persistence."""
    # 1. GET /api/v1/i18n/locales with Accept-Language negotiation
    res_locales = i18n_test_client.get(
        "/api/v1/i18n/locales",
        headers={"Accept-Language": "fr-CA,fr;q=0.9,en-US;q=0.8"},
    )
    assert res_locales.status_code == 200
    locales_body = res_locales.json()
    assert locales_body["default_locale"] == "en-US"
    assert locales_body["negotiated_locale"] == "fr-FR"
    codes = {item["code"] for item in locales_body["locales"]}
    assert {"en-US", "es-ES", "fr-FR", "hi-IN", "ar-SA"}.issubset(codes)

    # 2. GET /api/v1/i18n/catalog/es-ES
    res_es = i18n_test_client.get("/api/v1/i18n/catalog/es-ES")
    assert res_es.status_code == 200
    es_body = res_es.json()
    assert es_body["locale"] == "es-ES"
    assert es_body["direction"] == "ltr"
    assert "No cambie su medicación" in es_body["disclaimer"]
    assert es_body["messages"]["navigation"]["appointments"] == "Citas"

    # 3. GET /api/v1/i18n/catalog/ar-SA
    res_ar = i18n_test_client.get("/api/v1/i18n/catalog/ar-SA")
    assert res_ar.status_code == 200
    ar_body = res_ar.json()
    assert ar_body["locale"] == "ar-SA"
    assert ar_body["direction"] == "rtl"
    assert ar_body["messages"]["navigation"]["home"] == "الرئيسية"

    # 4. Invalid locale tag on catalog endpoint returns HTTP 422
    res_invalid_cat = i18n_test_client.get("/api/v1/i18n/catalog/invalid_tag_12345")
    assert res_invalid_cat.status_code == 422

    # 5. Create Profile with preferred_locale='ar_sa' -> canonicalized to 'ar-SA' & text_direction='rtl'
    res_create_prof = i18n_test_client.post(
        "/api/v1/profiles",
        json={
            "name": "Le\u0301o Al-Mansoor",
            "relationship": "parent",
            "role": "guardian",
            "preferred_locale": "ar_sa",
        },
    )
    assert res_create_prof.status_code == 201
    prof_data = res_create_prof.json()
    profile_id = prof_data["id"]
    assert prof_data["name"] == "L\u00e9o Al-Mansoor"
    assert prof_data["preferred_locale"] == "ar-SA"
    assert prof_data["text_direction"] == "rtl"

    # 6. Reject malformed profile preferred_locale with HTTP 422
    res_bad_prof = i18n_test_client.post(
        "/api/v1/profiles",
        json={
            "name": "Invalid Locale Profile",
            "relationship": "other",
            "preferred_locale": "invalid_tag_12345",
        },
    )
    assert res_bad_prof.status_code == 422

    # 7. Update profile preferred_locale to 'es' -> canonicalized to 'es-ES' ('ltr')
    res_upd_prof = i18n_test_client.put(
        f"/api/v1/profiles/{profile_id}",
        json={"preferred_locale": "es"},
    )
    assert res_upd_prof.status_code == 200
    upd_prof_data = res_upd_prof.json()
    assert upd_prof_data["preferred_locale"] == "es-ES"
    assert upd_prof_data["text_direction"] == "ltr"

    # 8. Create Note under profile without explicit locale -> inherits profile's 'es-ES' and NFC normalizes text
    res_note = i18n_test_client.post(
        f"/api/v1/profiles/{profile_id}/notes",
        json={
            "title": "Re\u0301sumen de Cardiologi\u0301a",
            "content": "Tomar medicacio\u0301n segu\u0301n indicacio\u0301n me\u0301dica.",
            "type": "visit",
        },
    )
    assert res_note.status_code == 201
    note_data = res_note.json()
    assert note_data["locale"] == "es-ES"
    assert note_data["title"] == "R\u00e9sumen de Cardiolog\u00eda"
    assert note_data["content"] == "Tomar medicaci\u00f3n seg\u00fan indicaci\u00f3n m\u00e9dica."
    assert "\u0301" not in note_data["title"]
    assert "\u0301" not in note_data["content"]

    # 9. Create workspace note with explicit locale='hi-IN'
    res_ws_note = i18n_test_client.post(
        "/api/v1/notes",
        json={
            "title": "स्वास्थ्य नोट",
            "content": "रक्तचाप की नियमित जांच करें।",
            "profile_id": profile_id,
            "locale": "hi",
        },
    )
    assert res_ws_note.status_code == 201
    ws_note_data = res_ws_note.json()
    assert ws_note_data["locale"] == "hi-IN"


def test_fhir_r4_coding_invariant_with_localized_health_resource() -> None:
    """Verifies HealthResource and Attachment store BCP 47 locale provenance alongside standard FHIR codes."""
    import asyncio
    from datetime import datetime, timezone

    async def _verify_models() -> None:
        await init_db()
        factory = get_session_factory()
        async with factory() as session:
            user = User(
                email="multilingual@example.com",
                username="multilingual_steward",
                hashed_password="hashed_password_value",
                preferred_locale="fr-FR",
            )
            session.add(user)
            await session.flush()

            profile = Profile(
                user_id=user.id,
                name="Jean Dupont",
                relationship="self",
                role="self",
                is_primary=True,
                preferred_locale="fr-FR",
            )
            session.add(profile)
            await session.flush()

            hr = HealthResource(
                profile_id=profile.id,
                resource_type="Observation",
                source_type="manual",
                locale="fr-FR",
                effective_at=datetime.now(timezone.utc),
                data={
                    "resourceType": "Observation",
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "8480-6",
                                "display": "Systolic blood pressure",
                            }
                        ],
                        "text": "Pression artérielle systolique",
                    },
                    "valueQuantity": {"value": 118, "unit": "mmHg"},
                },
            )
            att = Attachment(
                user_id=user.id,
                profile_id=profile.id,
                filename="bilan_cardiaque.pdf",
                original_name="bilan_cardiaque.pdf",
                content_type="application/pdf",
                size_bytes=1024,
                sha256="a" * 64,
                storage_key="cas/a",
                locale="fr-FR",
            )
            note = Note(
                user_id=user.id,
                profile_id=profile.id,
                slug="consultation-cardiologie",
                title=normalize_text_nfc("Consultation de cardiologie"),
                content=normalize_text_nfc("Tension art\u00e9rielle stable."),
                locale="fr-FR",
            )
            session.add_all([hr, att, note])
            await session.commit()

            assert user.preferred_locale == "fr-FR"
            assert profile.preferred_locale == "fr-FR"
            assert hr.data["code"]["coding"][0]["system"] == "http://loinc.org"
            assert hr.data["code"]["coding"][0]["code"] == "8480-6"
            assert hr.locale == "fr-FR"
            assert att.locale == "fr-FR"
            assert note.locale == "fr-FR"

    asyncio.run(_verify_models())
