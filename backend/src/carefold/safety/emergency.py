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

"""Acute emergency red-flag detection.

Runs before any routing, agent or model call. A hit makes the input guardrail
answer with the emergency referral, which names 911 and the 988 Suicide &
Crisis Lifeline.

How it decides:

1. Normalize the text: lower case, straight apostrophes, collapsed spacing,
   common contractions typed without the apostrophe ("cant", "hes"), and
   one-edit typos of the key symptom words ("stroek", "siezure", "chets").
2. Split it into clauses (sentences, commas, "but", "and now"), so an acute
   clause is judged on its own: "had a stroke in 2019, and now his face is
   drooping" still triggers.
3. Match symptom patterns per category: cardiac, respiratory, stroke,
   anaphylaxis, overdose/poisoning, severe bleeding, unconsciousness,
   seizure, suicide/self-harm. Patterns describe the symptom in any person
   or tense users actually write ("I have chest pain", "he's not breathing",
   "she's having a seizure").
4. Skip a match only when its own clause clearly makes it non-acute: the
   symptom is negated just before it ("no chest pain", "denies"), the clause
   is historical with no "now"/"today" ("in 2019", "years ago", "history
   of"), or it is a general question or hypothetical about someone else
   ("what are signs of a stroke?", "what to do if someone is choking").

When in doubt it errs toward safety: a bare symptom statement triggers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Pattern, Sequence, Tuple


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


# --------------------------------------------------------------- normalizing

_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "`": "'"})

_CONTRACTIONS: Tuple[Tuple[str, str], ...] = (
    (r"\bcan\s+not\b", "cannot"),
    (r"\bcant\b", "can't"),
    (r"\bwont\b", "won't"),
    (r"\bisnt\b", "isn't"),
    (r"\bdoesnt\b", "doesn't"),
    (r"\bdont\b", "don't"),
    (r"\bcouldnt\b", "couldn't"),
    (r"\bhes\b", "he's"),
    (r"\bshes\b", "she's"),
    (r"\bim\b", "i'm"),
    (r"\bive\b", "i've"),
    (r"\bhav\b", "have"),
    (r"\bod(?:'?d|'?ed)\b", "overdosed"),
    (r"\bepi\s+pen\b", "epipen"),
)

# Key symptom words; a token one edit away (same first letter) is read as the word.
_VOCABULARY: Tuple[str, ...] = (
    "anaphylactic", "anaphylaxis", "bleeding", "breath", "breathe", "breathing", "chest",
    "choking", "collapsed", "convulsing", "drooping", "overdose", "overdosed",
    "overdosing", "seizing", "seizure", "seizures", "slurred", "slurring",
    "stroke", "suicidal", "suicide", "swelling", "swollen", "unconscious",
    "unresponsive",
)
_VOCAB_SET = frozenset(_VOCABULARY)
_TOKEN_RE = re.compile(r"[a-z]+")


def _one_edit_apart(a: str, b: str) -> bool:
    """Optimal string alignment distance of at most one (incl. one transposition)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _correct_token(token: str) -> str:
    if len(token) < 5 or token in _VOCAB_SET:
        return token
    for word in _VOCABULARY:
        if word[0] == token[0] and _one_edit_apart(token, word):
            return word
    return token


def normalize(text: str) -> str:
    """Lower-cased text with straight apostrophes, contractions and key typos fixed."""
    out = (text or "").translate(_APOSTROPHES).lower()
    out = re.sub(r"\s+", " ", out).strip()
    for pattern, repl in _CONTRACTIONS:
        out = re.sub(pattern, repl, out)
    return _TOKEN_RE.sub(lambda m: _correct_token(m.group(0)), out)


_CLAUSE_SPLIT = re.compile(r"[.!?;,\n]+|\b(?:but|however|although|though|yet)\b|\band\s+(?=now\b)")


def _clauses(text: str) -> List[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(text) if c and c.strip()]


# ------------------------------------------------------------------- guards

_NEGATOR_BEFORE = re.compile(
    r"\b(?:no|not|without|never|denies|denied|deny|negative\s+for|free\s+of|isn't|is\s+not|"
    r"doesn't|does\s+not|don't|do\s+not|didn't|did\s+not|no\s+longer|hasn't|has\s+not|haven't|"
    r"have\s+not|wasn't|was\s+not|aren't|are\s+not|i'm\s+not|am\s+not)\b(?:\s+\S+){0,3}\s*$"
)

_HISTORICAL = re.compile(
    r"\b(?:in|since|back\s+in|during)\s+(?:19|20)\d{2}\b"
    r"|\b(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|a\s+few|few|several|many|a\s+couple\s+of)?\s*"
    r"(?:years?|months?|weeks?)\s+ago\b"
    r"|\blast\s+(?:year|month|week|spring|summer|fall|autumn|winter)\b"
    r"|\bhistory\s+of\b|\bused\s+to\b|\bin\s+the\s+past\b|\bpreviously\b|\bprior\b"
    r"|\brecover(?:ing|ed)?\s+from\b|\bsurvivor\b"
)

_ACUTE_TIME = re.compile(
    r"\b(?:right\s+now|now|today|tonight|currently|at\s+the\s+moment|this\s+(?:morning|afternoon|evening)|"
    r"suddenly|sudden|just|again)\b"
)

_QUESTION_START = re.compile(
    r"^(?:what|how|why|which|when|where|who|can\s+you|could\s+you|tell\s+me|explain|is\s+it|are\s+there|"
    r"does|do|should|is|are|can)\b"
)

_PERSON_CUE = re.compile(
    r"\b(?:i|i'm|i've|me|my|we|our|us|he|she|they|he's|she's|they're|his|her|their|him|them|"
    r"mom|mum|mother|dad|father|son|daughter|husband|wife|baby|child|kid|toddler|grandma|grandpa|"
    r"grandmother|grandfather|friend|brother|sister|partner|patient)\b"
)

_GENERIC_HYPOTHETICAL = re.compile(
    r"\b(?:if|in\s+case|when|whether)\s+(?:someone|somebody|a\s+person|people|you|anyone|a\s+child|a\s+loved\s+one)\b"
)


def _negated(clause: str, start: int) -> bool:
    return bool(_NEGATOR_BEFORE.search(clause[:start]))


def _non_acute_clause(clause: str) -> bool:
    if _HISTORICAL.search(clause) and not _ACUTE_TIME.search(clause):
        return True
    if _GENERIC_HYPOTHETICAL.search(clause):
        return True
    return bool(_QUESTION_START.search(clause) and not _PERSON_CUE.search(clause))


# ------------------------------------------------------------------ patterns

_POSS = r"(?:my|his|her|their|the|our|your)"
_SELF = r"(?:my|him|her|them|your|our)sel(?:f|ves)"

CHEST_PATTERNS: List[str] = [
    r"\bchest\s+(?:pains?|pressure|tightness|discomfort|heaviness)\b",
    rf"\b(?:pain|pressure|tightness|heaviness)\s+in\s+{_POSS}\s+chest\b",
    r"\bchest\s+(?:hurts?|is\s+hurting|feels\s+(?:tight|heavy))\b",
    r"\bhaving\s+(?:a\s+)?heart\s+attack\b",
    r"\b(?:just|recently)\s+had\s+(?:a\s+)?heart\s+attack\b",
    r"\bcardiac\s+arrest\b",
    r"\b(?:no|doesn't\s+have\s+a|does\s+not\s+have\s+a|can't\s+find\s+a)\s+pulse\b",
]

RESPIRATORY_PATTERNS: List[str] = [
    r"\b(?:can't|cannot|couldn't|unable\s+to|struggling\s+to|hard\s+to|difficult\s+to)\s+breath(?:e|ing)?\b",
    r"\b(?:trouble|difficulty|struggling)\s+breathing\b",
    r"\b(?:not|isn't|stopped|wasn't)\s+breathing\b",
    r"\b(?:severe|sudden|extreme|very|really\s+bad)\s+short(?:ness)?\s+of\s+breath\b",
    r"\b(?:acute|severe|sudden|extreme|bad|worsening)\s+short(?:ness)?\s+of\s+breath\b",
    r"\b(?:i'm|i\s+am|he's|she's|they're|is|are|am|getting|feels?|feeling)\s+(?:very\s+|really\s+|so\s+|too\s+)?short\s+of\s+breath\b",
    r"\b(?:i|he|she|they|we|you)\s+(?:have|has|am\s+having|is\s+having|are\s+having)\s+(?:\w+\s+){0,2}?short(?:ness)?\s+of\s+breath\b",
    r"\bgasping\b",
    r"\bchoking\b(?!\s+(?:hazard|risk))",
    r"\b(?:lips|face|skin|fingers?)\s+(?:are\s+|is\s+)?(?:turning\s+)?blue\b",
    r"\bturning\s+blue\b",
]

_STROKE_MOD = (
    r"(?:mini[-\s]+|(?:minor|major|massive|acute|ischemic|hemorrhagic|embolic|cerebellar|"
    r"brain\s*stem|suspected|possible|another|second)\s+)?"
)
_NON_CV_STROKE_BEFORE = (
    r"(?<!heat\s)(?<!sun\s)(?<!swimming\s)(?<!swim\s)(?<!breast\s)(?<!back\s)"
    r"(?<!butterfly\s)(?<!freestyle\s)(?<!golf\s)(?<!putting\s)(?<!brush\s)"
    r"(?<!paint\s)(?<!key\s)(?<!pedal\s)(?<!piston\s)(?<!two\s)(?<!two-)"
    r"(?<!four\s)(?<!four-)(?<!2-)(?<!4-)"
)
_NON_CV_STROKE_AFTER = r"(?!\s+of\s+(?:luck|genius|midnight|a\s+pen|the\s+pen|the\s+brush|bad\s+luck))"
_STROKE_WORD = rf"{_NON_CV_STROKE_BEFORE}stroke{_NON_CV_STROKE_AFTER}"

STROKE_PATTERNS: List[str] = [
    rf"(?<!of\s)(?<!about\s)(?<!from\s)(?<!prevent\s)(?<!avoid\s)\b(?:having|experiencing|suffering(?:\s+from)?|going\s+through)\s+(?:a\s+|an\s+)?{_STROKE_MOD}{_STROKE_WORD}\b",
    r"(?<!of\s)(?<!about\s)(?<!from\s)(?<!prevent\s)(?<!avoid\s)\b(?:having|experiencing|suffering(?:\s+from)?)\s+(?:a\s+|an\s+)?(?:tia|transient\s+ischemic\s+attack|cerebrovascular\s+accident|brain\s+attack)\b",
    rf"(?<!of\s)(?<!for\s)(?<!prevent\s)\b(?:acute|massive|suspected|possible)\s+(?:(?:ischemic|hemorrhagic|embolic|cerebellar|brain\s*stem)\s+)?{_STROKE_WORD}\b(?!\s+(?:risk|prevention|history|workup|rehab|recovery|scale|unit|center|protocol|guidelines?))",
    r"\b(?:acute|suspected)\s+(?:tia|transient\s+ischemic\s+attack|cerebrovascular\s+accident)\b",
    rf"\b(?:just|recently)\s+had\s+(?:a\s+|an\s+)?{_STROKE_MOD}{_STROKE_WORD}\b",
    r"\b(?:just|recently)\s+had\s+(?:a\s+|an\s+)?(?:tia|transient\s+ischemic\s+attack)\b",
    rf"\bhad\s+(?:a\s+|an\s+)?{_STROKE_MOD}{_STROKE_WORD}\s+(?:just\s+now|right\s+now|today|tonight|this\s+(?:morning|afternoon|evening)|an?\s+(?:hour|few\s+minutes)\s+ago|\w+\s+minutes?\s+ago|\d+\s+hours?\s+ago)\b",
    rf"\b{_STROKE_WORD}\s+(?:right\s+now|symptoms\s+(?:right\s+)?now|emergency|alert)\b",
    rf"(?<!of\s)(?<!about\s)\b(?:have|has|having|experiencing|showing|getting|developed)\s+(?:\w+\s+){{0,2}}?(?:{_STROKE_WORD}\s+symptoms|signs\s+of\s+(?:a\s+|an\s+)?{_STROKE_WORD})\b",
    rf"\b(?:think|thinks|suspect|suspects|looks\s+like|acting\s+like|might\s+be|could\s+be)\s+(?:(?:it's|it\s+is|this\s+is|that's|that\s+is|(?:i'm|he's|she's|they're)\s+having|(?:i|he|she|they|mom|mother|dad|father|husband|wife|my\s+\w+)\s+(?:am\s+having|is\s+having|are\s+having|just\s+had|had))\s+)?(?:a\s+|an\s+)?{_STROKE_MOD}{_STROKE_WORD}\b",
    r"\bcode\s+stroke\b",
    r"\b(?:face|mouth|smile)\s+(?:is\s+|looks\s+)?(?:drooping|droopy|crooked|lopsided)\b",
    r"\b(?:facial|face)\s+droop\w*\b",
    r"\bslurr(?:ed|ing)\b",
    rf"\b(?:can't|cannot|unable\s+to|couldn't)\s+(?:lift|raise|move)\s+(?:{_POSS}|one)\s+(?:arm|leg)\b",
    r"\barm\s+weakness\b",
    r"\b(?:weakness|numbness)\s+on\s+one\s+side\b",
    rf"\bone\s+side\s+of\s+{_POSS}\s+(?:body|face)\b",
    r"\bsudden(?:ly)?\b.*\b(?:numb(?:ness)?|weak(?:ness)?|confus(?:ed|ion)|trouble\s+speaking|can't\s+speak|vision\s+loss|loss\s+of\s+vision|can't\s+see)\b",
    r"\b(?:cannot|can't|unable\s+to)\s+speak\b",
    r"\b(?:worst\s+headache\s+of\s+(?:my|his|her|their)?\s*life|thunderclap\s+headache|asymmetrical\s+smile)\b",
]

ANAPHYLAXIS_PATTERNS: List[str] = [
    r"\bthroat\s+(?:is\s+|feels\s+)?(?:closing|swelling|swollen|tight(?:ening)?)\b",
    r"\b(?:tongue|lips?|face|mouth)\s+(?:is\s+|are\s+)?(?:swelling|swollen)\b",
    r"\b(?:swollen\s+(?:lips?|tongue)|lip\s+edema)\b",
    r"\banaphyla(?:xis|ctic)\b",
    r"\ballergic\s+reaction\b.*\b(?:can't\s+breathe|trouble\s+breathing|throat|swelling|swollen|hives)\b",
    r"\b(?:need|needs|needed|used|use)\s+(?:an?\s+|my\s+|his\s+|her\s+|their\s+)?epipen\b",
    r"\b(?:hives\s+and\s+(?:wheezing|shortness\s+of\s+breath)|respiratory\s+stridor|upper\s+airway\s+obstruction)\b",
]

OVERDOSE_PATTERNS: List[str] = [
    r"\boverdos(?:ed|ing|e)\b",
    r"\btook\s+(?:a\s+(?:whole|full)\s+bottle|an\s+entire\s+bottle|too\s+many|too\s+much|all\s+(?:of\s+)?(?:my|his|her|their|the))\b",
    r"\b(?:swallowed|ate|drank|ingested|chugged)\s+(?:a\s+|an\s+|some\s+|the\s+)?(?:button\s+batter(?:y|ies)|batter(?:y|ies)|bleach|poison|antifreeze|detergent|laundry\s+pods?|drain\s+cleaner|rat\s+poison|pesticide|lighter\s+fluid|gasoline|a\s+handful\s+of\s+pills|handful\s+of\s+pills|bunch\s+of\s+pills)\b",
    r"\bpoisoned\b",
]

BLEEDING_PATTERNS: List[str] = [
    r"\b(?:won't|will\s+not|can't|cannot|doesn't|does\s+not|isn't)\s+stop(?:ping)?\s+(?:the\s+)?bleeding\b",
    r"\bbleeding\s+(?:won't|will\s+not|doesn't|does\s+not|isn't|hasn't)\s+stop(?:ping|ped)?\b",
    r"\bbleeding\s+(?:heavily|badly|profusely|a\s+lot|everywhere|nonstop|non-stop|so\s+much)\b",
    r"\b(?:heavy|severe|uncontrolled|massive)\s+bleeding\b",
    r"\b(?:vomiting|throwing\s+up|coughing\s+up)\s+blood\b",
    r"\bblood\s+(?:is\s+)?(?:spurting|gushing|pouring)\b",
    r"\b(?:spurting|gushing|pouring)\s+blood\b",
    r"\blosing\s+(?:a\s+lot\s+of|lots\s+of|so\s+much)\s+blood\b",
]

SUICIDE_PATTERNS: List[str] = [
    rf"\b(?:want|wants|wanted|going|planning|plans|trying|tried|threatening|threatened)\s+to\s+(?:kill|end|hurt|harm)\s+{_SELF}\b",
    r"\b(?:want|wants)\s+to\s+die\b",
    r"\b(?:don't|do\s+not|doesn't|does\s+not)\s+want\s+to\s+(?:live|be\s+alive|wake\s+up)\b",
    rf"\b(?:end|take|ending|taking)\s+(?:my|his|her|their)\s+(?:own\s+)?life\b",
    r"\bend\s+it\s+all\b",
    r"\bbetter\s+off\s+(?:dead|without\s+me)\b",
    rf"\b(?:thinking|thought|thoughts)\s+(?:about|of)\s+(?:suicide|killing\s+{_SELF}|ending\s+(?:my|his|her|their)\s+life)\b",
    r"\bsuicidal\b",
    r"\b(?:commit|committing)\s+suicide\b",
    r"\bsuicide\s+(?:plan|note|attempt)\b",
    rf"\b(?:kill|killing|hurt|hurting|harm|harming|cut|cutting|hang|hanging|shoot|shooting|poison|poisoning)\s+{_SELF}\b",
    r"\boverdose\s+on\s+(?:pills|medications?|drugs?)\b",
]

UNCONSCIOUS_PATTERNS: List[str] = [
    r"\bunconscious\b",
    r"\bunresponsive\b",
    r"\b(?:won't|will\s+not|isn't|is\s+not|not|can't|cannot)\s+(?:wake|waking)\s+(?:him\s+|her\s+|them\s+)?up\b",
    r"\b(?:isn't|is\s+not|not)\s+responding\b",
    r"\bcollapsed\b",
]

SEIZURE_PATTERNS: List[str] = [
    r"\bhaving\s+(?:a\s+)?seizures?\b",
    r"\bseizing\b",
    r"\bconvuls(?:ing|ions?)\b",
    r"\b(?:just|recently)\s+had\s+(?:a\s+)?seizure\b",
    r"\bseizures?\s+(?:right\s+now|won't\s+stop|lasting|for\s+\w+\s+minutes)\b",
    r"\bhad\s+a\s+seizure\s+(?:just\s+now|today|tonight|this\s+morning|an?\s+(?:hour|few\s+minutes)\s+ago|\w+\s+minutes\s+ago)\b",
]

# The emergency reply always names 911 and the 988 Suicide & Crisis Lifeline.
_CALL_911 = "Call 911 now (US) or your local emergency number, or go to the nearest emergency room."
_CALL_988 = "If anyone may be thinking about suicide or self-harm, call or text 988 (Suicide & Crisis Lifeline, US)."

# Checked in this order; the first category with an acute match wins.
_CATEGORIES: Tuple[Tuple[str, str, Sequence[str], str], ...] = (
    ("acute_chest_pain", "acute chest pain/pressure", CHEST_PATTERNS,
     f"EMERGENCY WARNING: Possible heart emergency. {_CALL_911} {_CALL_988}"),
    ("anaphylaxis", "acute allergic airway reaction", ANAPHYLAXIS_PATTERNS,
     f"EMERGENCY WARNING: Possible severe allergic reaction. Use epinephrine (an EpiPen) if one is prescribed. {_CALL_911} {_CALL_988}"),
    ("stroke_fast", "FAST neurological symptoms", STROKE_PATTERNS,
     f"EMERGENCY WARNING: Possible stroke. Note the time symptoms started. {_CALL_911} {_CALL_988}"),
    ("respiratory_distress", "severe breathing difficulty", RESPIRATORY_PATTERNS,
     f"EMERGENCY WARNING: Severe breathing trouble. {_CALL_911} {_CALL_988}"),
    ("seizure", "active seizure", SEIZURE_PATTERNS,
     f"EMERGENCY WARNING: Possible seizure emergency. Keep the person safe from injury and do not put anything in their mouth. {_CALL_911} {_CALL_988}"),
    ("unconscious", "unresponsive person", UNCONSCIOUS_PATTERNS,
     f"EMERGENCY WARNING: Someone may be unconscious. {_CALL_911} {_CALL_988}"),
    ("overdose_poisoning", "overdose or poisoning", OVERDOSE_PATTERNS,
     f"EMERGENCY WARNING: Possible overdose or poisoning. {_CALL_911} You can also call Poison Control at 1-800-222-1222 (US). {_CALL_988}"),
    ("severe_bleeding", "severe bleeding", BLEEDING_PATTERNS,
     f"EMERGENCY WARNING: Severe bleeding. Press firmly on the wound. {_CALL_911} {_CALL_988}"),
    ("suicide_crisis", "suicide or self-harm crisis", SUICIDE_PATTERNS,
     "EMERGENCY WARNING: Acute crisis. If you or someone else may act on thoughts of suicide or self-harm, "
     "call or text 988 now (Suicide & Crisis Lifeline, US). If anyone is in immediate danger, call 911 now "
     "or go to the nearest emergency room."),
)

_COMPILED: Tuple[Tuple[str, str, Tuple[Pattern[str], ...], str], ...] = tuple(
    (cat, trig, tuple(re.compile(p) for p in pats), msg) for cat, trig, pats, msg in _CATEGORIES
)

EMERGENCY_REFERRAL_MESSAGE = (
    f"EMERGENCY WARNING: This may be an emergency. {_CALL_911} {_CALL_988}"
)
"""Fallback referral when a refusal is an emergency but carries no message."""


def _acute_match(clause: str, patterns: Iterable[Pattern[str]]) -> Optional[str]:
    if _non_acute_clause(clause):
        return None
    for pattern in patterns:
        for m in pattern.finditer(clause):
            if not _negated(clause, m.start()):
                return m.group(0)
    return None


def check_emergency_red_flags(prompt: str) -> Optional[EmergencyFlag]:
    """Returns an EmergencyFlag when ``prompt`` describes an acute emergency, else None."""
    if not prompt or not isinstance(prompt, str):
        return None
    clauses = _clauses(normalize(prompt))
    for category, trigger, patterns, message in _COMPILED:
        for clause in clauses:
            hit = _acute_match(clause, patterns)
            if hit is not None:
                return EmergencyFlag(
                    detected=True,
                    category=category,
                    trigger_phrase=f"{trigger}: {hit}",
                    referral_message=message,
                )
    return None


__all__ = [
    "ANAPHYLAXIS_PATTERNS",
    "BLEEDING_PATTERNS",
    "CHEST_PATTERNS",
    "EMERGENCY_REFERRAL_MESSAGE",
    "EmergencyFlag",
    "OVERDOSE_PATTERNS",
    "RESPIRATORY_PATTERNS",
    "SEIZURE_PATTERNS",
    "STROKE_PATTERNS",
    "SUICIDE_PATTERNS",
    "UNCONSCIOUS_PATTERNS",
    "check_emergency_red_flags",
    "normalize",
]
