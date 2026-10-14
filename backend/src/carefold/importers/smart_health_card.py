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

"""SMART Health Card (`.smart-health-card` / `shc:/` QR) JWS ES256 Verifier & Parser (AU-77 / E10.6).

Implements the W3C / HL7 SMART Health Cards specification:
- Compact JWS (`alg="ES256"`, `zip="DEF"`) signing and verification using P-256 ECDSA (`SECP256R1`)
  and IEEE P1363 64-byte `r || s` signatures per RFC 7515.
- Raw deflate decompression (`wbits=-zlib.MAX_WBITS`) with a strict 256 KB decompressed size cap
  to prevent zip-bomb denial-of-service attacks.
- Numeric `shc:/...` QR URI decoding (pairs of digits `int(pair) + 45` mapped to ASCII JWS characters)
  as well as `.smart-health-card` JSON container (`{"verifiableCredential": [...]}`) and compact JWS input.
- Extraction and validation of embedded FHIR R4 `Bundle` clinical resources (`Immunization`, `Observation`,
  `Condition`, `MedicationStatement`, `AllergyIntolerance`) via `fhir.resources.R4B`.
- Provenance tagging (`From <source_name> (<issuer>, <verification_status>), <YYYY-MM-DD>`) and
  `"trust": "untrusted"` for Review-Before-Save (`AU-38`).
"""

from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import uuid
import zlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDSA,
    SECP256R1,
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
    EllipticCurvePublicNumbers,
)
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from fhir.resources.R4B.allergyintolerance import AllergyIntolerance as FhirAllergyIntolerance
from fhir.resources.R4B.condition import Condition as FhirCondition
from fhir.resources.R4B.immunization import Immunization as FhirImmunization
from fhir.resources.R4B.medicationstatement import MedicationStatement as FhirMedicationStatement
from fhir.resources.R4B.observation import Observation as FhirObservation
from fhir.resources.R4B.provenance import Provenance as FhirProvenance

MAX_SHC_DECOMPRESSED_BYTES = 256 * 1024  # 256 KB zip-bomb defense cap
ES256_RAW_SIGNATURE_LEN = 64  # 32-byte r || 32-byte s

_SHC_FHIR_MODELS: Dict[str, Any] = {
    "Immunization": FhirImmunization,
    "Observation": FhirObservation,
    "Condition": FhirCondition,
    "MedicationStatement": FhirMedicationStatement,
    "AllergyIntolerance": FhirAllergyIntolerance,
}

SUPPORTED_SHC_RESOURCE_TYPES = frozenset(_SHC_FHIR_MODELS.keys())


def _b64url_encode(data: bytes) -> str:
    """Encodes bytes using RFC 7515 unpadded base64url encoding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    """Decodes an unpadded base64url string into raw bytes."""
    clean = (segment or "").strip()
    if not clean:
        raise ValueError("Empty base64url segment in SMART Health Card JWS.")
    padding = "=" * ((4 - (len(clean) % 4)) % 4)
    try:
        return base64.urlsafe_b64decode((clean + padding).encode("ascii"))
    except Exception as exc:
        raise ValueError(f"Invalid base64url encoding in SMART Health Card JWS: {exc}") from exc


def _raw_deflate_compress(data: bytes) -> bytes:
    """Compresses bytes using raw RFC 1951 DEFLATE (no zlib header or trailer, wbits=-15)."""
    compressor = zlib.compressobj(
        level=zlib.Z_DEFAULT_COMPRESSION,
        method=zlib.DEFLATED,
        wbits=-zlib.MAX_WBITS,
    )
    return compressor.compress(data) + compressor.flush()


def _raw_deflate_decompress(compressed: bytes, max_bytes: int = MAX_SHC_DECOMPRESSED_BYTES) -> bytes:
    """Decompresses raw RFC 1951 DEFLATE bytes (`zip="DEF"`) enforcing a strict size cap."""
    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
    try:
        output = decompressor.decompress(compressed, max_bytes + 1)
        if len(output) > max_bytes or decompressor.unconsumed_tail:
            raise ValueError(
                f"SMART Health Card payload exceeds maximum decompressed size limit ({max_bytes} bytes)."
            )
        tail = decompressor.flush()
        if len(output) + len(tail) > max_bytes:
            raise ValueError(
                f"SMART Health Card payload exceeds maximum decompressed size limit ({max_bytes} bytes)."
            )
        return output + tail
    except zlib.error as exc:
        raise ValueError(f"Failed to decompress SMART Health Card DEFLATE payload: {exc}") from exc


def export_public_jwk(key: Union[EllipticCurvePrivateKey, EllipticCurvePublicKey], kid: str = "shc-key-1") -> Dict[str, Any]:
    """Exports an EC P-256 public or private key as a RFC 7517 JWK dictionary for SMART Health Card verification."""
    pub_key = key.public_key() if isinstance(key, EllipticCurvePrivateKey) else key
    pub_nums = pub_key.public_numbers()
    x_bytes = pub_nums.x.to_bytes(32, byteorder="big")
    y_bytes = pub_nums.y.to_bytes(32, byteorder="big")
    return {
        "kty": "EC",
        "crv": "P-256",
        "use": "sig",
        "alg": "ES256",
        "kid": kid,
        "x": _b64url_encode(x_bytes),
        "y": _b64url_encode(y_bytes),
    }


def encode_shc_qr_uri(jws: str) -> str:
    """Encodes a compact JWS string into a numeric `shc:/...` QR URI per SMART Health Cards specification."""
    clean_jws = (jws or "").strip()
    if not clean_jws:
        raise ValueError("Cannot encode empty JWS into shc:/ URI.")
    digits: List[str] = []
    for ch in clean_jws:
        code = ord(ch) - 45
        if code < 0 or code > 99:
            raise ValueError(f"Invalid JWS character '{ch}' for numeric shc:/ encoding.")
        digits.append(f"{code:02d}")
    return "shc:/" + "".join(digits)


def decode_shc_qr_uri(shc_uri: str) -> str:
    """Decodes a numeric `shc:/5676...` QR URI into a compact JWS string (`ord = int(pair) + 45`)."""
    clean = (shc_uri or "").strip()
    if not clean.lower().startswith("shc:/"):
        raise ValueError("Invalid SMART Health Card QR URI: must start with 'shc:/'.")

    body = clean[5:].strip()
    # Handle multi-chunk prefix e.g. shc:/1/2/<digits> if present
    if "/" in body:
        parts = body.split("/")
        body = parts[-1].strip()

    if not body or len(body) % 2 != 0 or not body.isdigit():
        raise ValueError(
            "Invalid SMART Health Card numeric QR payload: expected an even number of decimal digits after 'shc:/'."
        )

    chars: List[str] = []
    for idx in range(0, len(body), 2):
        pair_val = int(body[idx : idx + 2])
        ascii_code = pair_val + 45
        if ascii_code < 32 or ascii_code > 126:
            raise ValueError(f"Invalid numeric pair '{body[idx:idx+2]}' in shc:/ QR payload.")
        chars.append(chr(ascii_code))

    return "".join(chars)


def create_signed_shc_jws(
    vc_payload: Dict[str, Any],
    private_key: Any,
    kid: str = "shc-key-1",
) -> str:
    """Creates a raw-deflated (`zip="DEF"`), P-256 ECDSA (`alg="ES256"`) signed SMART Health Card compact JWS.

    Args:
        vc_payload: Either full SHC JWT claims (`{"iss": ..., "nbf": ..., "vc": {...}}`) or the inner `vc`
            object containing `credentialSubject.fhirBundle`.
        private_key: `cryptography` `EllipticCurvePrivateKey` on `SECP256R1` (P-256).
        kid: Key identifier placed in the JWS header (`kid`).

    Returns:
        Compact JWS string (`header.payload.signature`).
    """
    if not isinstance(vc_payload, dict) or not vc_payload:
        raise ValueError("vc_payload must be a non-empty dictionary.")

    if "vc" in vc_payload and isinstance(vc_payload["vc"], dict):
        claims = copy.deepcopy(vc_payload)
        claims.setdefault("iss", "https://spec.smarthealth.cards/examples/issuer")
        claims.setdefault("nbf", 1700000000)
    else:
        claims = {
            "iss": vc_payload.get("iss", "https://spec.smarthealth.cards/examples/issuer"),
            "nbf": vc_payload.get("nbf", 1700000000),
            "vc": copy.deepcopy(vc_payload),
        }

    header = {
        "alg": "ES256",
        "zip": "DEF",
        "kid": str(kid or "shc-key-1"),
    }
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_json_bytes = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    deflated_payload = _raw_deflate_compress(payload_json_bytes)

    header_b64 = _b64url_encode(header_bytes)
    payload_b64 = _b64url_encode(deflated_payload)
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    der_signature = private_key.sign(signing_input, ECDSA(hashes.SHA256()))
    r_int, s_int = decode_dss_signature(der_signature)
    raw_signature = r_int.to_bytes(32, byteorder="big") + s_int.to_bytes(32, byteorder="big")
    sig_b64 = _b64url_encode(raw_signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _jwk_to_ec_public_key(jwk: Dict[str, Any]) -> EllipticCurvePublicKey:
    """Constructs a `SECP256R1` `EllipticCurvePublicKey` from a RFC 7517 JWK dictionary."""
    kty = str(jwk.get("kty") or "").strip().upper()
    crv = str(jwk.get("crv") or "").strip().upper()
    if kty != "EC" or crv not in ("P-256", "SECP256R1"):
        raise ValueError(f"Unsupported JWK key type/curve ({kty}/{crv}); expected EC P-256.")

    x_b64 = jwk.get("x")
    y_b64 = jwk.get("y")
    if not x_b64 or not y_b64:
        raise ValueError("EC JWK is missing 'x' or 'y' coordinate.")

    x_bytes = _b64url_decode(str(x_b64))
    y_bytes = _b64url_decode(str(y_b64))
    x_int = int.from_bytes(x_bytes, byteorder="big")
    y_int = int.from_bytes(y_bytes, byteorder="big")

    try:
        pub_numbers = EllipticCurvePublicNumbers(x_int, y_int, SECP256R1())
        return pub_numbers.public_key()
    except Exception as exc:
        raise ValueError(f"Invalid EC P-256 public key coordinates in JWK: {exc}") from exc


def _resolve_candidate_public_keys(
    trusted_jwks: Any,
    header_kid: Optional[str],
) -> List[EllipticCurvePublicKey]:
    """Resolves one or more candidate P-256 public keys from `trusted_jwks`."""
    if isinstance(trusted_jwks, EllipticCurvePublicKey):
        return [trusted_jwks]
    if isinstance(trusted_jwks, EllipticCurvePrivateKey):
        return [trusted_jwks.public_key()]
    if not isinstance(trusted_jwks, dict):
        raise ValueError("trusted_jwks must be a JWKS dictionary or EC public key.")

    if "keys" in trusted_jwks and isinstance(trusted_jwks["keys"], list):
        raw_keys = [k for k in trusted_jwks["keys"] if isinstance(k, dict)]
    elif trusted_jwks.get("kty") == "EC":
        raw_keys = [trusted_jwks]
    else:
        raw_keys = []

    if not raw_keys:
        raise ValueError("SMART Health Card JWS signature verification failed: no trusted keys in JWKS.")

    # Prefer keys matching header 'kid' when present
    if header_kid:
        matching_kid_keys = [k for k in raw_keys if k.get("kid") == header_kid]
        if matching_kid_keys:
            raw_keys = matching_kid_keys
        elif any(k.get("kid") for k in raw_keys):
            raise ValueError(
                f"SMART Health Card JWS signature verification failed: no key matching kid '{header_kid}'."
            )

    pub_keys: List[EllipticCurvePublicKey] = []
    for jwk in raw_keys:
        pub_keys.append(_jwk_to_ec_public_key(jwk))
    return pub_keys


def _verify_es256_jws_signature(
    header_b64: str,
    payload_b64: str,
    sig_bytes: bytes,
    candidate_keys: Sequence[EllipticCurvePublicKey],
) -> None:
    """Verifies a 64-byte IEEE P1363 `r || s` ECDSA SHA-256 signature against candidate P-256 public keys."""
    if len(sig_bytes) != ES256_RAW_SIGNATURE_LEN:
        raise ValueError("SMART Health Card JWS signature verification failed: invalid ES256 signature length.")

    r_int = int.from_bytes(sig_bytes[:32], byteorder="big")
    s_int = int.from_bytes(sig_bytes[32:], byteorder="big")
    der_sig = encode_dss_signature(r_int, s_int)
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    for pub_key in candidate_keys:
        try:
            pub_key.verify(der_sig, signing_input, ECDSA(hashes.SHA256()))
            return
        except InvalidSignature:
            continue
        except Exception:
            continue

    raise ValueError("SMART Health Card JWS signature verification failed.")


def _extract_jws_list(raw_content: Union[str, bytes]) -> List[str]:
    """Extracts one or more compact JWS strings from `.smart-health-card` JSON, `shc:/` QR URI, or raw JWS."""
    if isinstance(raw_content, bytes):
        text = raw_content.decode("utf-8", errors="replace").strip()
    elif isinstance(raw_content, str):
        text = raw_content.strip()
    else:
        raise ValueError("SMART Health Card input must be str or bytes.")

    if not text:
        raise ValueError("SMART Health Card content is empty.")

    # 1. Numeric QR URI: shc:/...
    if text.lower().startswith("shc:/"):
        return [decode_shc_qr_uri(text)]

    # 2. JSON .smart-health-card container: {"verifiableCredential": ["eyJ..."]}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid .smart-health-card JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ValueError("Invalid .smart-health-card JSON: root must be an object.")

        vc_list = parsed.get("verifiableCredential")
        if isinstance(vc_list, str) and vc_list.strip():
            vc_list = [vc_list.strip()]
        if not isinstance(vc_list, list) or not vc_list:
            raise ValueError(
                "Invalid .smart-health-card JSON: missing non-empty 'verifiableCredential' array."
            )

        resolved: List[str] = []
        for item in vc_list:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Each entry in 'verifiableCredential' must be a non-empty JWS string.")
            clean_item = item.strip()
            if clean_item.lower().startswith("shc:/"):
                resolved.append(decode_shc_qr_uri(clean_item))
            else:
                resolved.append(clean_item)
        return resolved

    # 3. Direct compact JWS string
    if text.count(".") == 2:
        return [text]

    raise ValueError(
        "Unrecognized SMART Health Card format: expected .smart-health-card JSON, 'shc:/' QR URI, or compact JWS."
    )


def _extract_effective_iso(resource: Dict[str, Any]) -> Tuple[str, str]:
    """Extracts an ISO-8601 timestamp and YYYY-MM-DD date string from a FHIR resource."""
    candidates = [
        resource.get("occurrenceDateTime"),
        resource.get("effectiveDateTime"),
        (resource.get("effectivePeriod") or {}).get("start")
        if isinstance(resource.get("effectivePeriod"), dict)
        else None,
        resource.get("recordedDate"),
        resource.get("onsetDateTime"),
        resource.get("authoredOn"),
        resource.get("issued"),
        resource.get("date"),
    ]
    for raw in candidates:
        if raw and isinstance(raw, str) and raw.strip():
            clean = raw.strip()
            date_part = clean[:10] if len(clean) >= 10 else clean
            if "T" not in clean and len(clean) == 10:
                return f"{clean}T00:00:00+00:00", date_part
            return clean, date_part

    now = datetime.now(timezone.utc)
    return now.isoformat(), now.strftime("%Y-%m-%d")


def _extract_coding_and_display(resource: Dict[str, Any], rtype: str) -> Tuple[Optional[str], str]:
    """Extracts primary code (e.g., CVX / LOINC) and human-readable display string from a FHIR resource."""
    code_obj = (
        resource.get("vaccineCode")
        or resource.get("code")
        or resource.get("medicationCodeableConcept")
    )
    if isinstance(code_obj, list) and code_obj:
        code_obj = code_obj[0]

    code_val: Optional[str] = None
    display_val: Optional[str] = None

    if isinstance(code_obj, dict):
        display_val = code_obj.get("text")
        codings = code_obj.get("coding") or []
        if isinstance(codings, list) and codings:
            first_coding = codings[0] if isinstance(codings[0], dict) else {}
            code_val = first_coding.get("code")
            if not display_val:
                display_val = first_coding.get("display")

    if not display_val:
        if rtype == "Immunization" and code_val:
            display_val = f"Immunization (CVX {code_val})"
        else:
            display_val = f"{rtype} ({code_val or resource.get('id') or 'record'})"

    if rtype == "Observation":
        vq = resource.get("valueQuantity")
        if isinstance(vq, dict) and vq.get("value") is not None:
            unit = vq.get("unit") or vq.get("code") or ""
            display_val = f"{display_val}: {vq['value']} {unit}".strip()
        elif resource.get("valueString"):
            display_val = f"{display_val}: {resource['valueString']}".strip()
        elif isinstance(resource.get("valueCodeableConcept"), dict):
            vcc = resource["valueCodeableConcept"]
            vcc_text = vcc.get("text") or ((vcc.get("coding") or [{}])[0].get("display"))
            if vcc_text:
                display_val = f"{display_val}: {vcc_text}".strip()

    return code_val, str(display_val)


def _validate_shc_fhir_resource(resource: Dict[str, Any], rtype: str) -> Dict[str, Any]:
    """Validates an embedded SMART Health Card FHIR resource using `fhir.resources.R4B`."""
    model_cls = _SHC_FHIR_MODELS.get(rtype)
    if model_cls is None:
        return copy.deepcopy(resource)

    candidate = copy.deepcopy(resource)
    if rtype == "Immunization":
        candidate.setdefault("status", "completed")
        candidate.setdefault("vaccineCode", {"text": "Immunization"})
        candidate.setdefault("patient", {"reference": "resource:0"})
        if "occurrenceDateTime" not in candidate and "occurrenceString" not in candidate:
            candidate["occurrenceDateTime"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif rtype == "Observation":
        candidate.setdefault("status", "final")
        candidate.setdefault("code", {"text": "Clinical Observation"})
    elif rtype == "Condition":
        candidate.setdefault("subject", {"reference": "resource:0"})
    elif rtype == "MedicationStatement":
        candidate.setdefault("status", "active")
        candidate.setdefault("subject", {"reference": "resource:0"})
    elif rtype == "AllergyIntolerance":
        candidate.setdefault("patient", {"reference": "resource:0"})

    validated = model_cls.model_validate(candidate)
    normalized = validated.model_dump(mode="json", exclude_none=True)
    merged = copy.deepcopy(resource)
    merged.update(normalized)
    return merged


def verify_and_parse_smart_health_card(
    raw_content: Union[str, bytes],
    trusted_jwks: Optional[Dict[str, Any]] = None,
    source_name: str = "SMART Health Card",
) -> Dict[str, Any]:
    """Verifies a SMART Health Card JWS (`ES256` + `DEF`) and extracts validated FHIR R4 clinical records.

    Accepts:
    - `.smart-health-card` JSON container (`{"verifiableCredential": ["eyJ..."]}`),
    - Numeric `shc:/5676...` QR URI, or
    - Direct compact JWS string (`header.payload.signature`).

    Args:
        raw_content: Raw `.smart-health-card` JSON, `shc:/` URI, or compact JWS string/bytes.
        trusted_jwks: Optional RFC 7517 JWKS dictionary (`{"keys": [...]}`) or EC P-256 public key.
            When provided, verifies the ES256 signature and raises `ValueError` on tampering.
            When `None`, validates structure/deflate/FHIR and marks `verification_status="unverified_issuer"`.
        source_name: Human-readable provenance label.

    Returns:
        Dictionary containing `format`, `issuer`, `verification_status`, `records`, `summary`, and `provenance`.
    """
    jws_list = _extract_jws_list(raw_content)
    clean_source = (source_name or "SMART Health Card").strip()

    staged_records: List[Dict[str, Any]] = []
    counts_by_type: Dict[str, int] = {}
    dates: List[str] = []
    primary_issuer = "unknown-issuer"
    overall_verification_status = "verified" if trusted_jwks is not None else "unverified_issuer"

    for vc_idx, jws_compact in enumerate(jws_list):
        parts = jws_compact.split(".")
        if len(parts) != 3 or not all(parts):
            raise ValueError("Invalid SMART Health Card JWS: expected 3 dot-separated segments.")

        header_b64, payload_b64, sig_b64 = parts

        # 1. Decode and validate JWS header
        header_bytes = _b64url_decode(header_b64)
        try:
            header = json.loads(header_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Invalid SMART Health Card JWS header JSON: {exc}") from exc

        if not isinstance(header, dict):
            raise ValueError("Invalid SMART Health Card JWS header: must be a JSON object.")
        if header.get("alg") != "ES256" or header.get("zip") != "DEF":
            raise ValueError(
                f"Invalid SMART Health Card JWS header: expected alg='ES256' and zip='DEF', "
                f"got alg={header.get('alg')!r}, zip={header.get('zip')!r}."
            )

        # 2. Decode and verify JWS signature
        sig_bytes = _b64url_decode(sig_b64)
        if len(sig_bytes) != ES256_RAW_SIGNATURE_LEN:
            raise ValueError(
                "SMART Health Card JWS signature verification failed: invalid ES256 signature length."
            )

        if trusted_jwks is not None:
            candidate_keys = _resolve_candidate_public_keys(trusted_jwks, header.get("kid"))
            _verify_es256_jws_signature(header_b64, payload_b64, sig_bytes, candidate_keys)
            verification_status = "verified"
        else:
            verification_status = "unverified_issuer"

        overall_verification_status = verification_status

        # 3. Decompress raw-deflated payload with 256 KB zip-bomb defense cap
        compressed_payload = _b64url_decode(payload_b64)
        decompressed_bytes = _raw_deflate_decompress(compressed_payload, MAX_SHC_DECOMPRESSED_BYTES)
        try:
            claims = json.loads(decompressed_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Invalid SMART Health Card JWS payload JSON: {exc}") from exc

        if not isinstance(claims, dict):
            raise ValueError("Invalid SMART Health Card JWS payload: root must be a JSON object.")

        issuer = str(claims.get("iss") or "unknown-issuer").strip()
        if vc_idx == 0:
            primary_issuer = issuer

        vc_obj = claims.get("vc") if isinstance(claims.get("vc"), dict) else claims
        cred_subj = vc_obj.get("credentialSubject") if isinstance(vc_obj, dict) else None
        fhir_bundle = cred_subj.get("fhirBundle") if isinstance(cred_subj, dict) else None

        if not isinstance(fhir_bundle, dict) or fhir_bundle.get("resourceType") != "Bundle":
            raise ValueError(
                "Invalid SMART Health Card payload: missing 'vc.credentialSubject.fhirBundle' FHIR Bundle."
            )

        entries = fhir_bundle.get("entry") or []
        if not isinstance(entries, list):
            raise ValueError("Invalid SMART Health Card FHIR Bundle: 'entry' must be a list.")

        for entry_idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            resource = entry.get("resource")
            if not isinstance(resource, dict):
                continue

            rtype = str(resource.get("resourceType") or "").strip()
            if rtype not in SUPPORTED_SHC_RESOURCE_TYPES:
                continue

            validated_fhir = _validate_shc_fhir_resource(resource, rtype)
            effective_iso, date_str = _extract_effective_iso(validated_fhir)
            dates.append(date_str)
            code_val, display_val = _extract_coding_and_display(validated_fhir, rtype)

            raw_id = resource.get("id") or entry.get("fullUrl")
            if raw_id and str(raw_id).strip():
                source_id = f"{rtype}:shc:{vc_idx}:{str(raw_id).strip()}"
            else:
                digest = hashlib.sha256(
                    json.dumps(validated_fhir, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()[:16]
                source_id = f"{rtype}:shc:{vc_idx}:{entry_idx}:{digest}"

            source_display = f"From {clean_source} ({issuer}, {verification_status}), {date_str}"
            validated_fhir.setdefault("meta", {})
            if isinstance(validated_fhir["meta"], dict):
                validated_fhir["meta"]["source"] = clean_source
                validated_fhir["meta"]["trust"] = "untrusted"
            validated_fhir["_carefold_provenance"] = {
                "source_name": clean_source,
                "source_display": source_display,
                "issuer": issuer,
                "verification_status": verification_status,
                "trust": "untrusted",
            }

            staged_records.append({
                "resource_type": rtype,
                "source_id": source_id,
                "effective_at": effective_iso,
                "display": display_val,
                "code": code_val,
                "issuer": issuer,
                "verification_status": verification_status,
                "data": validated_fhir,
                "source_display": source_display,
                "trust": "untrusted",
            })
            counts_by_type[rtype] = counts_by_type.get(rtype, 0) + 1

    now_iso = datetime.now(timezone.utc).isoformat()
    now_date = now_iso[:10]
    prov_id = str(uuid.uuid4())
    prov_targets = [{"reference": r["source_id"]} for r in staged_records] or [{"display": clean_source}]
    prov_model = FhirProvenance.model_validate({
        "resourceType": "Provenance",
        "id": f"prov-shc-{prov_id[:8]}",
        "recorded": now_iso,
        "target": prov_targets,
        "agent": [
            {
                "who": {"display": f"{clean_source} ({primary_issuer}, {overall_verification_status})"},
            }
        ],
    })
    provenance_data = prov_model.model_dump(mode="json", exclude_none=True)
    provenance_record = {
        "resource_type": "Provenance",
        "source_id": f"Provenance:shc:{prov_id[:8]}",
        "effective_at": now_iso,
        "display": f"Provenance: {clean_source} ({primary_issuer}, {overall_verification_status})",
        "issuer": primary_issuer,
        "verification_status": overall_verification_status,
        "data": provenance_data,
        "source_display": f"From {clean_source} ({primary_issuer}, {overall_verification_status}), {now_date}",
        "trust": "untrusted",
    }

    sorted_dates = sorted(d for d in dates if d)
    date_range = {
        "min": sorted_dates[0] if sorted_dates else now_date,
        "max": sorted_dates[-1] if sorted_dates else now_date,
    }

    return {
        "format": "smart_health_card",
        "source_name": clean_source,
        "issuer": primary_issuer,
        "verification_status": overall_verification_status,
        "records": staged_records,
        "provenance": provenance_record,
        "summary": {
            "format": "smart_health_card",
            "issuer": primary_issuer,
            "verification_status": overall_verification_status,
            "total_records": len(staged_records),
            "clinical_records": len(staged_records),
            "counts_by_type": counts_by_type,
            "date_range": date_range,
            "source_name": clean_source,
        },
    }


__all__ = [
    "MAX_SHC_DECOMPRESSED_BYTES",
    "SUPPORTED_SHC_RESOURCE_TYPES",
    "create_signed_shc_jws",
    "decode_shc_qr_uri",
    "encode_shc_qr_uri",
    "export_public_jwk",
    "verify_and_parse_smart_health_card",
]
