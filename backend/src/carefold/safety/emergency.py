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

"""Acute clinical emergency red-flag detection rules and triggers.

Provides pre-execution detection of acute life-threatening medical emergencies:
1. Cardiovascular emergencies (crushing chest pain, radiation to jaw/arm, cold sweat).
2. Neurological emergencies (stroke FAST: facial droop, slurred speech, arm weakness).
3. Airway and allergic emergencies (anaphylaxis, airway closing, tongue/lip swelling).
4. Suicidal crisis and acute self-harm emergencies (active suicidal ideation, intent to end life).

Enforces immediate diversion to 911 / 988 and emergency room services before any downstream
orchestration, planning, or model generation occurs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class EmergencyFlag(dict):
    """Structured representation of an acute clinical emergency flag.

    Supports attribute access (flag.category, flag.detected), dict subscripting
    (flag['category']), and dictionary serialization.
    """

    detected: bool
    category: str
    trigger_phrase: str
    referral_message: str

    def __init__(
        self,
        detected: bool,
        category: str,
        trigger_phrase: str,
        referral_message: str,
    ) -> None:
        super().__init__(
            detected=detected,
            category=category,
            trigger_phrase=trigger_phrase,
            referral_message=referral_message,
        )
        self.detected = detected
        self.category = category
        self.trigger_phrase = trigger_phrase
        self.referral_message = referral_message

    def to_dict(self) -> Dict[str, Any]:
        """Convert to standard dictionary."""
        return {
            "detected": self.detected,
            "category": self.category,
            "trigger_phrase": self.trigger_phrase,
            "referral_message": self.referral_message,
        }


# Negation guards: symptoms explicitly denied or qualified as past historical events
NEGATION_PATTERNS: List[str] = [
    r"\b(?:no|not|without|never|denies|negative for)\s+(?:chest\s+pain|shortness of breath|difficulty breathing|facial droop|arm weakness|slurred speech|stroke|anaphylaxis|swelling)\b",
    r"\bdenies\s+(?:any\s+)?(?:chest\s+pain|shortness of breath|difficulty breathing)\b",
    r"\b(?:years?|months?)\s+ago\b",
    r"\b(?:history\s+of|past)\s+(?:heart\s+attack|stroke|cardiac\s+arrest|myocardial infarction)\b",
]

# 1. Acute chest pain patterns
CHEST_PATTERNS: List[str] = [
    r"\b(?:crushing|squeezing|radiating|severe|acute)\s+chest\s+(?:pain|pressure|tightness)\b",
    r"\bchest\s+(?:pain|pressure|tightness)\s+(?:radiating|spreading)\s+to\s+(?:my\s+)?(?:arm|jaw|neck|back)\b",
    r"\bpressure\s+in\s+(?:my\s+)?chest\b.*\bcold\s+sweat\b",
    r"\bcold\s+sweat\b.*\bpressure\s+in\s+(?:my\s+)?chest\b",
    r"\bcrushing\s+(?:retrosternal\s+)?chest\s+pain\b",
]

# 2. Stroke FAST patterns
STROKE_PATTERNS: List[str] = [
    r"\b(?:facial\s+droop|face\s+drooping|facial\s+drooping|slurred\s+speech|arm\s+weakness|sudden\s+numbness\s+on\s+one\s+side)\b",
    r"\b(?:sudden\s+loss\s+of\s+vision|sudden\s+confusion|cannot\s+speak|unable\s+to\s+speak|unable\s+to\s+move\s+arm|can't\s+raise\s+(?:her\s+|his\s+|my\s+)?arm|cannot\s+raise\s+(?:her\s+|his\s+|my\s+)?arm)\b",
    r"\b(?:asymmetrical\s+smile|sudden\s+unilateral\s+weakness|worst\s+headache\s+of\s+life|thunderclap\s+headache)\b",
]

# 3. Anaphylaxis and airway patterns
ANAPHYLAXIS_PATTERNS: List[str] = [
    r"\b(?:throat\s+(?:is\s+)?closing(?:\s+up)?|(?:swollen\s+lips?|lips?\s+(?:are\s+)?swollen)|lip\s+edema|tongue\s+swelling|swollen\s+tongue|difficulty\s+swallowing\s+and\s+breathing)\b",
    r"\b(?:anaphylaxis|anaphylactic\s+reaction|hives\s+and\s+(?:wheezing|shortness\s+of\s+breath))\b",
    r"\b(?:respiratory\s+stridor|upper\s+airway\s+obstruction|wheezing\s+with\s+cyanosis)\b",
]

# 4. Suicidal crisis and acute self-harm patterns
SUICIDE_PATTERNS: List[str] = [
    r"\b(?:want\s+to|going\s+to|planning\s+to)\s+(?:kill|end)\s+(?:my|one)self\b",
    r"\b(?:want\s+to|going\s+to|planning\s+to)\s+die\b",
    r"\b(?:end\s+my\s+life|take\s+my\s+(?:own\s+)?life)\b",
    r"\b(?:feel|feeling|am|have)\s+suicidal\b",
    r"\b(?:commit|committing)\s+suicide\b",
    r"\b(?:suicidal\s+thoughts?|suicidal\s+ideation|suicide\s+plan)\b",
    r"\b(?:hang|shoot|poison|cut|harm)\s+myself\b",
    r"\boverdose\s+on\s+(?:pills|medications?|drugs?)\b",
]


def check_emergency_red_flags(prompt: str) -> Optional[EmergencyFlag]:
    """Evaluates user prompt against acute clinical emergency red-flag patterns.

    Detects acute crushing chest pain, stroke symptoms (FAST: facial droop, arm weakness,
    speech impairment), severe anaphylaxis / upper airway closure, and acute suicidal
    ideation / self-harm crisis.

    Args:
        prompt: Raw user input text.

    Returns:
        EmergencyFlag if acute emergency red flag detected, else None.
    """
    if not prompt or not isinstance(prompt, str):
        return None

    p_lower = prompt.lower()

    # Step 1: Check negation guards and historical event references
    for neg_pat in NEGATION_PATTERNS:
        if re.search(neg_pat, p_lower):
            return None

    # Step 2: Check acute chest pain / cardiac emergency
    for cp in CHEST_PATTERNS:
        if re.search(cp, p_lower):
            return EmergencyFlag(
                detected=True,
                category="acute_chest_pain",
                trigger_phrase="acute chest pain/pressure",
                referral_message="EMERGENCY WARNING: Acute chest pain detected. Call 911 or visit the nearest emergency room immediately.",
            )

    # Step 3: Check stroke FAST symptoms
    for sp in STROKE_PATTERNS:
        if re.search(sp, p_lower):
            return EmergencyFlag(
                detected=True,
                category="stroke_fast",
                trigger_phrase="FAST neurological symptoms",
                referral_message="EMERGENCY WARNING: Possible stroke symptoms detected. Call 911 immediately.",
            )

    # Step 4: Check acute anaphylaxis / airway obstruction
    for ap in ANAPHYLAXIS_PATTERNS:
        if re.search(ap, p_lower):
            return EmergencyFlag(
                detected=True,
                category="anaphylaxis",
                trigger_phrase="acute allergic airway reaction",
                referral_message="EMERGENCY WARNING: Severe allergic reaction detected. Administer epinephrine if prescribed and call 911 immediately.",
            )

    # Step 5: Check acute suicidal crisis / self-harm emergency
    for pattern in SUICIDE_PATTERNS:
        if re.search(pattern, p_lower):
            return EmergencyFlag(
                detected=True,
                category="suicide_crisis",
                trigger_phrase=pattern,
                referral_message="EMERGENCY WARNING: Acute crisis symptoms detected. If you are experiencing thoughts of suicide or self-harm, call or text 988 immediately to connect with the Suicide & Crisis Lifeline, or visit the nearest emergency room.",
            )

    return None


__all__ = [
    "EmergencyFlag",
    "check_emergency_red_flags",
    "SUICIDE_PATTERNS",
]
