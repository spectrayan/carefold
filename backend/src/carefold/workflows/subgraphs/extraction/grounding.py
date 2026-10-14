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

"""Grounding verification for extracted document dossiers (Feature F-37 & Domain 6).

Validates that numerical values, currency amounts, percentages, and clinical
units extracted into Pydantic dossiers match raw source text spans, flagging
hallucinated figures, transposed digits, and ungrounded data.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Regular expression matching numerical tokens with currency, commas, decimals, and units
NUM_TOKEN_REGEX = re.compile(
    r"(?P<prefix>[-+]?\$|USD\s*|[-+])?"
    r"(?P<number>\b\d{1,3}(?:,\d{3})+\b|\b\d+\b)(?:\.(?P<decimal>\d+))?"
    r"(?P<suffix>\s*(?:%|percent(?:age)?|dollars?|usd|weeks?|days?|hours?|months?|years?|bpm|mmhg|ml|mg|f|c))?",
    re.IGNORECASE,
)


class GroundingValidationResult(BaseModel):
    """Result of grounding verification comparing extracted values to raw source text."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    is_grounded: bool = Field(
        ...,
        description="True if all verified numerical values are grounded in the source text.",
    )
    matched_spans: List[Any] = Field(
        default_factory=list,
        description="List of matched spans, source tokens, or coordinate dictionaries.",
    )
    unmatched_values: List[str] = Field(
        default_factory=list,
        description="List of extracted values or field paths that could not be grounded.",
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional diagnostic metadata or validation breakdowns.",
    )


def extract_numeric_tokens(text: str) -> List[Dict[str, Any]]:
    """Extract normalized numerical tokens with formatting metadata from text.

    Args:
        text: Raw document text or extracted string value.

    Returns:
        List of token dictionaries containing numeric value, raw span, and unit flags.
    """
    tokens: List[Dict[str, Any]] = []
    if not text or not isinstance(text, str):
        return tokens

    for m in NUM_TOKEN_REGEX.finditer(text):
        num_str = m.group("number")
        if not num_str:
            continue
        cleaned_num = num_str.replace(",", "")
        dec = m.group("decimal")
        if dec:
            val = float(f"{cleaned_num}.{dec}")
        else:
            val = float(cleaned_num)

        prefix = (m.group("prefix") or "").strip().lower()
        if "-" in prefix:
            val = -val

        suffix = (m.group("suffix") or "").strip().lower()
        is_curr = bool("$" in prefix or "usd" in prefix or "dollar" in suffix or "usd" in suffix)
        is_pct = bool("%" in suffix or "percent" in suffix)

        tokens.append({
            "raw": m.group(0).strip(),
            "val": val,
            "start": m.start(),
            "end": m.end(),
            "is_currency": is_curr,
            "is_percentage": is_pct,
            "suffix": suffix,
        })
    return tokens


class GroundingValidator:
    """Verifies that extracted structured values are grounded in raw document text."""

    @classmethod
    def validate_numerical_value(
        cls, val_str: str, raw_text: str
    ) -> GroundingValidationResult:
        """Validate whether a single numerical string is grounded in source text.

        Handles currency formatting ($1,500 vs 1500 dollars), percentages
        (20% vs 20 percent), commas ($1,000,000 vs 1000000), decimals (20.5%),
        zero dollar amounts ($0), and unit quantities ('4 weeks'). Rejects
        transposed digits (1050 vs $1,500) and hallucinated figures.

        Args:
            val_str: The extracted numerical string value.
            raw_text: The authoritative raw document text.

        Returns:
            GroundingValidationResult with is_grounded and matched/unmatched tokens.
        """
        if not val_str or not str(val_str).strip():
            return GroundingValidationResult(is_grounded=True)

        val_tokens = extract_numeric_tokens(str(val_str))
        raw_tokens = extract_numeric_tokens(str(raw_text))

        # If val_str contains no digits, perform substring or token presence check
        if not val_tokens:
            target = str(val_str).strip().lower()
            in_text = target in str(raw_text).lower()
            return GroundingValidationResult(
                is_grounded=in_text,
                matched_spans=[val_str] if in_text else [],
                unmatched_values=[] if in_text else [str(val_str)],
            )

        matched: List[Dict[str, Any]] = []
        unmatched: List[str] = []

        for vt in val_tokens:
            found = False
            for rt in raw_tokens:
                # Compare numerical magnitude within floating point tolerance
                if abs(vt["val"] - rt["val"]) < 1e-6:
                    # Enforce semantic unit consistency: prevent % matching $
                    if vt["is_percentage"] and rt["is_currency"]:
                        continue
                    if vt["is_currency"] and rt["is_percentage"]:
                        continue
                    # If both have explicit non-empty suffixes, do they match?
                    if vt["suffix"] and rt["suffix"]:
                        vt_s = vt["suffix"].rstrip("s")
                        rt_s = rt["suffix"].rstrip("s")
                        if vt["is_percentage"] and rt["is_percentage"]:
                            pass
                        elif vt["is_currency"] and rt["is_currency"]:
                            pass
                        elif vt_s != rt_s:
                            continue

                    found = True
                    matched.append({
                        "target": vt["raw"],
                        "matched": rt["raw"],
                        "span": (rt["start"], rt["end"]),
                    })
                    break
            if not found:
                unmatched.append(vt["raw"])

        return GroundingValidationResult(
            is_grounded=len(unmatched) == 0,
            matched_spans=matched,
            unmatched_values=unmatched,
        )

    @classmethod
    def validate(
        cls, dossier: Union[BaseModel, Dict[str, Any]], raw_text: str
    ) -> GroundingValidationResult:
        """Validate all numerical values in an extracted dossier against source text.

        Recursively traverses fields, lists, and nested dictionaries of the
        dossier, extracting all numerical figures and verifying source grounding.

        Args:
            dossier: Pydantic BaseDossier model or dictionary representation.
            raw_text: Raw un-sanitized source document text.

        Returns:
            GroundingValidationResult summarizing grounding status across all fields.
        """
        all_matched: List[Any] = []
        all_unmatched: List[str] = []

        if hasattr(dossier, "model_dump"):
            data = dossier.model_dump()
        elif hasattr(dossier, "dict"):
            data = dossier.dict()
        elif isinstance(dossier, dict):
            data = dossier
        else:
            data = {}

        def _scan(val: Any, path: str) -> None:
            if isinstance(val, str):
                tokens = extract_numeric_tokens(val)
                if tokens:
                    res = cls.validate_numerical_value(val, raw_text)
                    if res.is_grounded:
                        all_matched.extend(res.matched_spans)
                    else:
                        for u in res.unmatched_values:
                            all_unmatched.append(f"{path}: {u}" if path else str(u))
            elif isinstance(val, dict):
                for k, v in val.items():
                    _scan(v, f"{path}.{k}" if path else str(k))
            elif isinstance(val, list):
                for i, v in enumerate(val):
                    _scan(v, f"{path}[{i}]")

        _scan(data, "")
        return GroundingValidationResult(
            is_grounded=len(all_unmatched) == 0,
            matched_spans=all_matched,
            unmatched_values=all_unmatched,
        )


__all__ = [
    "GroundingValidationResult",
    "GroundingValidator",
    "extract_numeric_tokens",
]
