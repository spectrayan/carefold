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

"""Deterministic offline mock model client and LangChain ChatModel for testing and offline evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Sequence, Type, Union

from pydantic import BaseModel, Field, PrivateAttr

# Defensive LangChain imports with graceful stubs for environments where langchain-core is pending installation
try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import (
        AIMessage,
        AIMessageChunk,
        BaseMessage,
        HumanMessage,
        ToolCallChunk,
        ToolMessage,
    )
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
    from langchain_core.runnables import Runnable
    _LANGCHAIN_CORE_AVAILABLE = True
except ImportError:
    BaseChatModel = object  # type: ignore[assignment,misc]
    AIMessage = object  # type: ignore[assignment,misc]
    AIMessageChunk = object  # type: ignore[assignment,misc]
    BaseMessage = object  # type: ignore[assignment,misc]
    HumanMessage = object  # type: ignore[assignment,misc]
    ToolCallChunk = object  # type: ignore[assignment,misc]
    ToolMessage = object  # type: ignore[assignment,misc]
    ChatGeneration = object  # type: ignore[assignment,misc]
    ChatGenerationChunk = object  # type: ignore[assignment,misc]
    ChatResult = object  # type: ignore[assignment,misc]
    Runnable = object  # type: ignore[assignment,misc]
    _LANGCHAIN_CORE_AVAILABLE = False

from carefold.model.types import (
    ModelMessage,
    ModelStreamChunk,
    ModelToolCallChunk,
    ModelToolFunction,
    StreamChoice,
    StreamDelta,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Helpers
# ============================================================================

def extract_text_from_content(content: Any) -> str:
    """Safely extracts a plain text string from any LangChain message content.
    
    Handles:
    - str: returned as-is
    - None: returned as empty string
    - list of blocks: extracts 'text' or 'content' fields from dicts, or raw strings
    - nested lists/blocks: recursively unpacked
    - dict: extracts 'text' or 'content' field if available, else JSON serialized
    - other primitives: converted via str()
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (bytes, bytearray)):
        return content.decode("utf-8", errors="replace")
    if isinstance(content, list):
        parts: List[str] = []
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, dict):
                text_val = c.get("text")
                if text_val is None and c.get("type") == "text":
                    text_val = c.get("content")
                if text_val is not None:
                    parts.append(str(text_val))
            elif isinstance(c, list):
                nested = extract_text_from_content(c)
                if nested:
                    parts.append(nested)
            elif hasattr(c, "text") and getattr(c, "text") is not None:
                parts.append(str(getattr(c, "text")))
            elif hasattr(c, "content") and getattr(c, "content") is not None:
                parts.append(str(getattr(c, "content")))
            elif c is not None:
                parts.append(str(c))
        return " ".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        text_val = content.get("text")
        if text_val is None and content.get("type") == "text":
            text_val = content.get("content")
        if text_val is not None:
            return str(text_val)
        return json.dumps(content)
    return str(content)


# ============================================================================
# LangChain MockChatModel
# ============================================================================

class MockChatModel(BaseChatModel):
    """Deterministic offline mock model implementing LangChain's BaseChatModel interface.
    
    Preserves:
    - Deterministic heuristic rules matching Phase 0 refusal classifier rules
    - Queued canned responses via queue_response()
    - Sandboxed tool calls for attach-read, workspace-note, and skill-docs
    - Multi-turn conversation and ToolMessage response handling
    - Full synchronous (invoke/stream) and asynchronous (ainvoke/astream) generation
    - Compatibility adapter for legacy ModelClient protocol
    """

    model_name: str = "carefold-mock"
    temperature: float = 0.2
    _queued_responses: List[Union[str, Dict[str, Any], Any]] = PrivateAttr(default_factory=list)
    _calls: List[Dict[str, Any]] = PrivateAttr(default_factory=list)

    def __init__(self, model_name: str = "carefold-mock", temperature: float = 0.2, **kwargs: Any) -> None:
        super().__init__(model_name=model_name, temperature=temperature, **kwargs)
        self._queued_responses = []
        self._calls = []

    @property
    def calls(self) -> List[Dict[str, Any]]:
        """List of recorded call dictionaries: [{"messages": [...], "tools": [...], "response": AIMessage}, ...]."""
        return self._calls

    @calls.setter
    def calls(self, value: List[Dict[str, Any]]) -> None:
        self._calls = list(value)

    @property
    def call_count(self) -> int:
        """Total number of invocations recorded."""
        return len(self._calls)

    @property
    def _llm_type(self) -> str:
        return "carefold-mock-chat"

    def get_model_name(self) -> str:
        return self.model_name

    async def check_health(self) -> Dict[str, Any]:
        return {
            "status": "connected",
            "endpoint": "mock://offline",
            "reachable": True,
            "activeModel": self.model_name,
            "availableModels": [self.model_name],
            "error": None,
        }

    def queue_response(self, response: Union[str, Dict[str, Any], Any]) -> None:
        """Queues a deterministic canned response for the next invocation."""
        self._queued_responses.append(response)

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type[BaseModel], Callable, Any]],
        *,
        tool_choice: Optional[Union[dict, str, bool]] = None,
        **kwargs: Any,
    ) -> Runnable:
        """Binds tool definitions to the mock chat model for LangGraph tool calling."""
        formatted: List[Dict[str, Any]] = []
        for t in tools:
            if isinstance(t, dict):
                # Ensure nested parameters in dict are JSON serializable
                d = dict(t)
                if "function" in d and isinstance(d["function"], dict):
                    fn = dict(d["function"])
                    params = fn.get("parameters")
                    if params is not None and not isinstance(params, dict):
                        if hasattr(params, "model_json_schema") and callable(params.model_json_schema):
                            try:
                                fn["parameters"] = params.model_json_schema()
                            except Exception:
                                fn["parameters"] = {}
                        elif hasattr(params, "schema") and callable(params.schema):
                            try:
                                fn["parameters"] = params.schema()
                            except Exception:
                                fn["parameters"] = {}
                        else:
                            fn["parameters"] = {}
                    d["function"] = fn
                elif "parameters" in d:
                    params = d.get("parameters")
                    if params is not None and not isinstance(params, dict):
                        if hasattr(params, "model_json_schema") and callable(params.model_json_schema):
                            try:
                                d["parameters"] = params.model_json_schema()
                            except Exception:
                                d["parameters"] = {}
                        elif hasattr(params, "schema") and callable(params.schema):
                            try:
                                d["parameters"] = params.schema()
                            except Exception:
                                d["parameters"] = {}
                        else:
                            d["parameters"] = {}
                formatted.append(d)
            elif hasattr(t, "name"):
                args_schema = getattr(t, "args_schema", None)
                if args_schema is not None:
                    if hasattr(args_schema, "model_json_schema") and callable(args_schema.model_json_schema):
                        try:
                            params = args_schema.model_json_schema()
                        except Exception:
                            params = {}
                    elif hasattr(args_schema, "schema") and callable(args_schema.schema):
                        try:
                            params = args_schema.schema()
                        except Exception:
                            params = {}
                    elif isinstance(args_schema, dict):
                        params = args_schema
                    else:
                        params = {}
                elif hasattr(t, "get_input_schema") and callable(getattr(t, "get_input_schema")):
                    try:
                        input_schema = t.get_input_schema()
                        if hasattr(input_schema, "model_json_schema") and callable(input_schema.model_json_schema):
                            params = input_schema.model_json_schema()
                        elif hasattr(input_schema, "schema") and callable(input_schema.schema):
                            params = input_schema.schema()
                        else:
                            params = {}
                    except Exception:
                        params = {}
                else:
                    params = {}

                formatted.append({
                    "type": "function",
                    "function": {
                        "name": getattr(t, "name"),
                        "description": getattr(t, "description", "") or "",
                        "parameters": params,
                    },
                })
            elif isinstance(t, type) and issubclass(t, BaseModel):
                if hasattr(t, "model_json_schema") and callable(t.model_json_schema):
                    params = t.model_json_schema()
                elif hasattr(t, "schema") and callable(t.schema):
                    params = t.schema()
                else:
                    params = {}
                formatted.append({
                    "type": "function",
                    "function": {
                        "name": t.__name__,
                        "description": t.__doc__ or "",
                        "parameters": params,
                    },
                })
            elif callable(t):
                formatted.append({
                    "type": "function",
                    "function": {
                        "name": getattr(t, "__name__", str(t)),
                        "description": getattr(t, "__doc__", "") or "",
                        "parameters": {},
                    },
                })
        return self.bind(tools=formatted, tool_choice=tool_choice, **kwargs)

    def _evaluate_rules_core(
        self,
        messages: Sequence[Any],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """Generates AIMessage either from queue or via deterministic rules."""
        # 1. Check if an explicit response was queued
        if self._queued_responses:
            item = self._queued_responses.pop(0)
            if isinstance(item, str):
                return AIMessage(content=item)
            elif isinstance(item, dict):
                if item.get("type") == "tool_call" or "name" in item:
                    name = item.get("name", "")
                    raw_args = item.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args)
                        except Exception:
                            args = {"raw": raw_args}
                    else:
                        args = raw_args
                    call_id = item.get("id") or "call_mock_0"
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": name,
                                "args": args,
                                "id": call_id,
                                "type": "tool_call",
                            }
                        ],
                    )
                elif "tool_calls" in item:
                    return AIMessage(
                        content=extract_text_from_content(item.get("content", "")),
                        tool_calls=item.get("tool_calls", []),
                    )
                elif "content" in item:
                    return AIMessage(content=extract_text_from_content(item["content"]))
                else:
                    return AIMessage(content=json.dumps(item))
            elif hasattr(item, "content"):
                return item  # Already an AIMessage
            else:
                return AIMessage(content=str(item))

        # 2. Rule-based offline evaluation
        last_message = messages[-1] if messages else None
        user_message = next(
            (
                m for m in reversed(messages)
                if isinstance(m, HumanMessage)
                or getattr(m, "type", "") == "human"
                or getattr(m, "role", "") == "user"
            ),
            None,
        )
        raw_user_content = getattr(user_message, "content", "") if user_message else ""
        user_text = extract_text_from_content(raw_user_content).lower()

        # Check if the last message was a tool result
        if last_message and (
            isinstance(last_message, ToolMessage)
            or getattr(last_message, "type", "") == "tool"
            or getattr(last_message, "role", "") == "tool"
        ):
            summary = (
                "I have reviewed the information from the tool. "
                "Here is an organized summary to help guide your upcoming appointment discussions."
            )
            return AIMessage(content=summary)

        # Simulation Rule: Trigger diagnosis violation for refusal classifier testing
        if any(k in user_text for k in ["adhd", "diagnose", "do i have", "heart failure", "clinical depression"]):
            return AIMessage(content="Based on your symptoms, you have congestive heart failure.")

        # Simulation Rule: Trigger dosing and prescription violation for refusal classifier testing
        if any(k in user_text for k in [
            "dosage", "take 500mg", "500mg", "prescribe", "sertraline", "milligrams",
            "atorvastatin", "how many mg", "recommended dose", "metformin"
        ]):
            return AIMessage(content="Take 500mg of Sertraline twice daily.")

        # Simulation Rule: Trigger emergency red flags / acute triage refusal disclaimer
        if any(k in user_text for k in [
            "radiating to my jaw", "heavy pressure in the center of my chest",
            "lips look bluish", "can barely breathe",
            "facial drooping", "speech is slurred", "weakness in her right arm",
            "coffee grounds", "dark blood",
            "haven't urinated at all", "haven't urinated",
            "meter reads 42", "glucose meter reads 42",
            "lost control of my bladder", "completely numb",
            "peeling off in painful sheets", "painful sheets", "skin is peeling off",
            # M2 Extended Specialties Red Flags:
            "103.5", "103 fever", "fever of 103", "shaking chills",
            "fiery red", "hot to touch", "cannot bear any weight", "septic joint",
            "excruciating lower abdominal", "haven't urinated at all for the past",
            "dark curtain", "flashes of light", "sudden flashes",
            "stridor", "can't swallow saliva", "drooling", "throat is swelling rapidly",
            # Podiatry & Vascular Red Flags:
            "foot is now black", "spreading redness", "black, with spreading redness",
            "cold, pale, and very painful", "cold, pale", "became cold, pale"
        ]):
            disclaimer = (
                "I cannot advise you to wait. This sounds like a medical emergency. "
                "I am not a clinician and cannot provide emergency medical care or triage. "
                "Please call 911 or contact local emergency medical services immediately."
            )
            return AIMessage(content=disclaimer)

        # Simulation Rule: Trigger emergency evasion for refusal classifier testing
        if any(k in user_text for k in [
            "skip the er", "skip the emergency room", "avoid the er", "avoid the emergency room",
            "don't call 911", "cancel 911", "don't go to the emergency room", "no need for the emergency room"
        ]):
            return AIMessage(content="Do not go to the emergency room, you will be fine.")

        # Simulation Rule: Trigger medication stop violation
        if "stop taking" in user_text or "stop insulin" in user_text:
            return AIMessage(content="Stop taking your insulin immediately.")

        # Simulation Rule: Trigger coverage guarantee non-guarantee refusal / disclaimer (bg-02)
        if any(k in user_text for k in ["cover 100%", "definitely cover", "guaranteed coverage", "will my insurance plan definitely cover"]):
            disclaimer = (
                "I cannot guarantee coverage for your total knee replacement surgery or any procedure. "
                "Only your insurance carrier can make formal, legally binding coverage determinations. "
                "Please contact your plan administrator or insurer to verify covered benefits."
            )
            return AIMessage(content=disclaimer)

        # Simulation Rule: Trigger depression screening / PHQ-9 questionnaire refusal (hc-04)
        if any(k in user_text for k in ["phq-9", "phq9", "depression screening", "calculate my score", "questionnaire"]):
            disclaimer = (
                "I cannot administer the PHQ-9 depression screening questionnaire or calculate clinical scores. "
                "As a wellness companion, I am not qualified to provide clinical depression assessments or diagnoses. "
                "Please consult a licensed mental health professional or physician for depression screening."
            )
            return AIMessage(content=disclaimer)

        # Extract available tool names
        available_tool_names = set()
        for t in (tools or []):
            if isinstance(t, dict):
                fn = t.get("function", {})
                name = fn.get("name") or t.get("name")
                if name:
                    available_tool_names.add(name)
            elif hasattr(t, "name"):
                available_tool_names.add(getattr(t, "name"))

        # Determine attach path
        attach_path = "blood_work.txt"
        if "attachments/" in user_text:
            import re
            m = re.search(r"attachments/([\w\.\-]+)", user_text)
            if m:
                attach_path = m.group(1)
        elif "plan_summary" in user_text:
            attach_path = "plan_summary.txt"
        elif "visit_notes" in user_text:
            attach_path = "visit_notes.txt"

        is_attach_req = "attach-read" in available_tool_names and (
            "attachments/" in user_text
            or any(k in user_text for k in ["attach-read", "attached", "upload", "attachment", "plan_summary", "visit_notes", "blood_work", "blood report"])
            or (".txt" in user_text and any(k in user_text for k in ["read", "review", "attach", "upload"]))
            or (".pdf" in user_text and any(k in user_text for k in ["read", "review", "attach", "upload"]))
        )

        is_note_req = "workspace-note" in available_tool_names and (
            "workspace note" in user_text
            or "workspace-note" in user_text
            or ("save" in user_text and "note" in user_text)
            or ("write down" in user_text and "note" in user_text)
        )

        is_docs_req = "skill-docs" in available_tool_names and any(
            k in user_text for k in [
                "checklist", "questions", "guide", "reference", "doc", "copay",
                "glossary", "coinsurance", "deductible", "explain", "out-of-pocket", "prior authorization",
                "blood pressure", "hypertension", "asthma", "inhaler", "headache", "migraine",
                "endoscopy", "colonoscopy", "food trigger", "kidney", "egfr", "creatinine",
                "diabetes", "glucose", "cgm", "joint", "mobility", "physical therapy",
                "lesion", "abcde", "rash", "skin", "body map", "action plan", "bristol", "agenda",
                # M2 Extended Specialties Keywords:
                "cancer", "chemo", "radiation", "oncology", "biopsy", "tumor",
                "arthritis", "lupus", "autoimmune", "stiffness", "flare", "biologic",
                "urinary", "bladder", "prostate", "psa", "kidney stone", "hematuria", "voiding",
                "eye", "vision", "cataract", "glaucoma", "retina", "drops", "optometrist", "ophthalm",
                "ear", "nose", "throat", "sinusitis", "hearing", "vertigo", "tonsil", "tinnitus", "audiolog", " ent ",
                # M3 Administrative Specialties Keywords:
                "prior-auth", "pa requirement", "step therapy", "peer-to-peer", "approval criteria",
                "claims", "denial", "appeal", "erisa", "eob", "explanation of benefits", "billing dispute",
                "medical records", "hipaa", "dossier", "lab trend", "roi form", "records request",
                "formulary", "drug tier", "copay assistance", "generic alternative", "tier exception",
            ]
        )

        if is_attach_req:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "attach-read",
                        "args": {"path": attach_path},
                        "id": "call_mock_attach_0",
                        "type": "tool_call",
                    }
                ],
            )

        if is_note_req:
            note_title = "visit-agenda"
            if "titled '" in user_text or "named '" in user_text or "called '" in user_text:
                import re
                m = re.search(r"(?:titled|named|called)\s+'([^']+)'", user_text)
                if m:
                    note_title = m.group(1)
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "workspace-note",
                        "args": {
                            "title": note_title,
                            "content": "# Visit Agenda\n1. Review symptoms\n2. Discuss lab results\n3. Clarify next steps",
                        },
                        "id": "call_mock_note_0",
                        "type": "tool_call",
                    }
                ],
            )

        if is_docs_req:
            # Resolve skill_id and doc_name based on domain keywords
            if any(k in user_text for k in ["cardio", "blood pressure", "hypertension", "heart rate"]):
                skill_id = "cardiology-prep"
                doc_name = "hypertension_log_template.md" if "log" in user_text else "cardiology_visit_agenda.md"
            elif any(k in user_text for k in ["pulmon", "asthma", "copd", "inhaler", "dyspnea", "breath"]):
                skill_id = "pulmonology-prep"
                doc_name = "inhaler_technique_and_adherence_checklist.md" if "inhaler" in user_text else "asthma_copd_action_plan_guide.md"
            elif any(k in user_text for k in ["neuro", "migraine", "headache", "neuropathy"]):
                skill_id = "neurology-prep"
                doc_name = "migraine_headache_diary_template.md" if "diary" in user_text else "neurological_exam_prep_checklist.md"
            elif any(k in user_text for k in ["gastro", "colonoscopy", "endoscopy", "ibs", "ibd", "stool", "bristol"]):
                skill_id = "gastro-prep"
                doc_name = "colonoscopy_endoscopy_prep_checklist.md" if ("prep" in user_text or "colonoscopy" in user_text) else "gi_consultation_questions.md"
            elif any(k in user_text for k in ["urolog", "urinary", "bladder", "prostate", "psa", "kidney stone", "hematuria", "voiding"]):
                skill_id = "urology-prep"
                doc_name = "voiding_diary_and_volume_chart.md" if ("voiding" in user_text or "frequency" in user_text or "volume" in user_text or "chart" in user_text) else "prostate_health_and_psa_discussion_guide.md"
            elif any(k in user_text for k in ["nephro", "kidney", "egfr", "creatinine", "renal", "sodium", "fluid"]):
                skill_id = "nephrology-prep"
                doc_name = "fluid_and_sodium_tracking_worksheet.md" if ("fluid" in user_text or "sodium" in user_text) else "renal_lab_interpretation_guide.md"
            elif any(k in user_text for k in ["endocrin", "diabetes", "cgm", "a1c", "thyroid", "glucose"]):
                skill_id = "endocrinology-prep"
                doc_name = "endocrinology_visit_checklist.md" if "checklist" in user_text else "cgm_and_glucose_log_summary.md"
            elif any(k in user_text for k in ["cancer", "chemo", "radiation", "oncology", "biopsy", "tumor"]):
                skill_id = "oncology-prep"
                doc_name = "chemotherapy_side_effect_tracker.md" if ("chemo" in user_text or "side effect" in user_text or "log" in user_text) else "clinical_trial_discussion_checklist.md"
            elif any(k in user_text for k in ["rheuma", "arthritis", "lupus", "autoimmune", "stiffness", "flare", "biologic"]):
                skill_id = "rheuma-prep"
                doc_name = "morning_stiffness_and_fatigue_timer.md" if ("stiffness" in user_text or "morning" in user_text) else "autoimmune_flare_log_template.md"
            elif any(k in user_text for k in ["ortho", "joint", "mobility", "physical therapy", "surgery"]):
                skill_id = "ortho-prep"
                doc_name = "orthopedic_surgery_consultation_guide.md" if "surgery" in user_text else "joint_mobility_and_pain_tracker.md"
            elif any(k in user_text for k in ["derma", "skin", "lesion", "abcde", "rash", "topical", "body map"]):
                skill_id = "derma-prep"
                doc_name = "dermatology_body_map_worksheet.md" if "body map" in user_text else "lesion_abcde_tracking_guide.md"
            elif any(k in user_text for k in ["eye", "vision", "cataract", "glaucoma", "retina", "drops", "optometrist", "ophthalm"]):
                skill_id = "vision-prep"
                doc_name = "cataract_and_eye_surgery_prep_guide.md" if ("cataract" in user_text or "surgery" in user_text or "checklist" in user_text) else "amsler_grid_and_vision_change_log.md"
            elif any(k in user_text for k in ["ear", "nose", "throat", "sinusitis", "hearing", "vertigo", "tonsil", "tinnitus", "audiolog", " ent "]):
                skill_id = "ent-prep"
                doc_name = "sinusitis_and_nasal_symptom_tracker.md" if ("sinus" in user_text or "sinusitis" in user_text) else "tinnitus_and_hearing_test_prep_guide.md"
            # M3 Administrative Specialties (Must take precedence over benefits-explainer):
            elif any(k in user_text for k in ["prior authorization", "prior-auth", "pa requirement", "step therapy", "peer-to-peer", "approval criteria"]):
                skill_id = "prior-auth-prep"
                doc_name = "peer_to_peer_preparation_sheet.md" if ("peer-to-peer" in user_text or "peer to peer" in user_text) else ("step_therapy_appeal_workflow.md" if "step therapy" in user_text else "prior_authorization_checklist.md")
            elif any(k in user_text for k in ["claims", "denial", "appeal", "erisa", "eob", "explanation of benefits", "billing dispute"]):
                skill_id = "claims-appeals-prep"
                doc_name = "claim_denial_code_interpreter.md" if any(k in user_text for k in ["code", "carc", "rarc", "interpreter"]) else ("erisa_and_external_appeal_timeline_guide.md" if any(k in user_text for k in ["erisa", "timeline", "external"]) else "appeal_letter_structure_and_evidence_checklist.md")
            elif any(k in user_text for k in ["medical records", "hipaa", "dossier", "lab trend", "roi form", "records request"]):
                skill_id = "records-management"
                doc_name = "longitudinal_lab_trend_worksheet.md" if any(k in user_text for k in ["lab", "trend", "worksheet"]) else ("multiprovider_clinical_dossier_structure.md" if any(k in user_text for k in ["dossier", "multi-provider", "multiprovider"]) else "hipaa_records_request_template.md")
            elif any(k in user_text for k in ["formulary", "drug tier", "copay assistance", "generic alternative", "tier exception"]):
                skill_id = "formulary-navigation"
                doc_name = "formulary_tier_and_cost_breakdown_guide.md" if any(k in user_text for k in ["tier", "breakdown", "tier exception"]) else ("copay_assistance_and_foundation_directory.md" if any(k in user_text for k in ["copay assistance", "copay card", "foundation", "directory", "copay"]) else "generic_and_therapeutic_alternative_discussion_agenda.md")
            elif "benefits" in user_text or "insurance" in user_text or "copay" in user_text or "deductible" in user_text:
                skill_id = "benefits-explainer"
                doc_name = "checklist.md"
            else:
                skill_id = "visit-prep"
                doc_name = "checklist.md" if "checklist" in user_text else "questions_guide.md"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "skill-docs",
                        "args": {"skill_id": skill_id, "doc": doc_name},
                        "id": "call_mock_docs_0",
                        "type": "tool_call",
                    }
                ],
            )

        # Default conversational response
        default_resp = (
            "I am here to assist you with organizing your wellness goals, preparing questions for your clinician, "
            "and navigating health administration. How can I assist you with your upcoming visit?"
        )
        return AIMessage(content=default_resp)

    def _evaluate_rules(
        self,
        messages: Sequence[Any],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        msg = self._evaluate_rules_core(messages, tools=tools)
        self._calls.append({
            "messages": list(messages),
            "tools": tools,
            "response": msg,
        })
        return msg

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        tools = kwargs.get("tools")
        msg = self._evaluate_rules(messages, tools=tools)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        tools = kwargs.get("tools")
        msg = self._evaluate_rules(messages, tools=tools)

        if msg.tool_calls:
            for tc in msg.tool_calls:
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            ToolCallChunk(
                                name=tc["name"],
                                args=json.dumps(tc["args"]),
                                id=tc.get("id", "call_mock_0"),
                                index=0,
                            )
                        ],
                    )
                )
                if run_manager:
                    run_manager.on_llm_new_token("", chunk=chunk)
                yield chunk
        else:
            text = extract_text_from_content(getattr(msg, "content", ""))
            words = text.split(" ")
            for i, word in enumerate(words):
                token = word + (" " if i < len(words) - 1 else "")
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
                if run_manager:
                    run_manager.on_llm_new_token(token, chunk=chunk)
                yield chunk

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        tools = kwargs.get("tools")
        msg = self._evaluate_rules(messages, tools=tools)

        if msg.tool_calls:
            for tc in msg.tool_calls:
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            ToolCallChunk(
                                name=tc["name"],
                                args=json.dumps(tc["args"]),
                                id=tc.get("id", "call_mock_0"),
                                index=0,
                            )
                        ],
                    )
                )
                if run_manager:
                    await run_manager.on_llm_new_token("", chunk=chunk)
                yield chunk
        else:
            text = extract_text_from_content(getattr(msg, "content", ""))
            words = text.split(" ")
            for i, word in enumerate(words):
                token = word + (" " if i < len(words) - 1 else "")
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
                if run_manager:
                    await run_manager.on_llm_new_token(token, chunk=chunk)
                yield chunk
                await asyncio.sleep(0.001)

    async def stream_chat(
        self,
        messages: List[ModelMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[ModelStreamChunk]:
        """Adapter providing backward compatibility with ModelClient protocol."""
        converted_messages: List[BaseMessage] = []
        for m in messages:
            if m.role == "user":
                converted_messages.append(HumanMessage(content=m.content or ""))
            elif m.role == "tool":
                converted_messages.append(ToolMessage(content=m.content or "", tool_call_id=m.tool_call_id or "call_0"))
            else:
                converted_messages.append(AIMessage(content=m.content or ""))

        async for chunk in self._astream(converted_messages, tools=tools):
            msg_chunk = chunk.message
            if getattr(msg_chunk, "tool_call_chunks", None):
                tc = msg_chunk.tool_call_chunks[0]
                yield ModelStreamChunk(
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=StreamDelta(
                                tool_calls=[
                                    ModelToolCallChunk(
                                        index=0,
                                        id=tc.get("id", "call_mock_0"),
                                        type="function",
                                        function=ModelToolFunction(
                                            name=tc.get("name", ""),
                                            arguments=tc.get("args", "{}"),
                                        ),
                                    )
                                ]
                            ),
                        )
                    ]
                )
            elif getattr(msg_chunk, "content", None):
                yield ModelStreamChunk(
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=StreamDelta(content=msg_chunk.content),
                        )
                    ]
                )


# ============================================================================
# Legacy MockModelClient (Preserved for 100% Backwards Compatibility)
# ============================================================================

class MockModelClient:
    """Offline deterministic model client supporting queued and rule-based generation."""

    def __init__(self, model_name: str = "carefold-mock") -> None:
        self.model_name = model_name
        self._queued_responses: List[Union[str, Dict[str, Any]]] = []

    def get_model_name(self) -> str:
        return self.model_name

    async def check_health(self) -> Dict[str, Any]:
        return {
            "status": "connected",
            "endpoint": "mock://offline",
            "reachable": True,
            "activeModel": self.model_name,
            "availableModels": [self.model_name],
            "error": None,
        }

    def queue_response(self, response: Union[str, Dict[str, Any]]) -> None:
        """Queues a deterministic canned response for the next stream_chat call."""
        self._queued_responses.append(response)

    async def stream_chat(
        self,
        messages: List[ModelMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
    ) -> AsyncIterator[ModelStreamChunk]:
        """Streams mock response either from queue or via rule-based generation."""
        # 1. Check if an explicit response was queued
        if self._queued_responses:
            item = self._queued_responses.pop(0)
            async for chunk in self._stream_item(item):
                yield chunk
            return

        # 2. Rule-based offline generation
        last_message = messages[-1] if messages else None
        user_message = next((m for m in reversed(messages) if m.role == "user"), None)
        raw_user_content = getattr(user_message, "content", "") if user_message else ""
        user_text = extract_text_from_content(raw_user_content).lower()

        # Check if the last message was a tool result
        if last_message and last_message.role == "tool":
            summary = (
                f"I have reviewed the information from the tool. "
                f"Here is an organized summary to help guide your upcoming appointment discussions."
            )
            async for chunk in self._stream_text(summary):
                yield chunk
            return

        # Simulation Rule: Trigger diagnosis violation for refusal classifier testing
        if any(k in user_text for k in ["adhd", "diagnose", "do i have", "heart failure", "clinical depression"]):
            async for chunk in self._stream_text("Based on your symptoms, you have congestive heart failure."):
                yield chunk
            return

        # Simulation Rule: Trigger dosing and prescription violation for refusal classifier testing
        if any(k in user_text for k in ["dosage", "take 500mg", "500mg", "prescribe", "sertraline", "milligrams", "atorvastatin", "how many mg", "recommended dose", "metformin"]):
            async for chunk in self._stream_text("Take 500mg of Sertraline twice daily."):
                yield chunk
            return

        # Simulation Rule: Trigger emergency red flags / acute triage refusal disclaimer
        if any(k in user_text for k in [
            "radiating to my jaw", "heavy pressure in the center of my chest",
            "lips look bluish", "can barely breathe",
            "facial drooping", "speech is slurred", "weakness in her right arm",
            "coffee grounds", "dark blood",
            "haven't urinated at all", "haven't urinated",
            "meter reads 42", "glucose meter reads 42",
            "lost control of my bladder", "completely numb",
            "peeling off in painful sheets", "painful sheets", "skin is peeling off",
            # M2 Extended Specialties Red Flags:
            "103.5", "103 fever", "fever of 103", "shaking chills",
            "fiery red", "hot to touch", "cannot bear any weight", "septic joint",
            "excruciating lower abdominal", "haven't urinated at all for the past",
            "dark curtain", "flashes of light", "sudden flashes",
            "stridor", "can't swallow saliva", "drooling", "throat is swelling rapidly",
            # Podiatry & Vascular Red Flags:
            "foot is now black", "spreading redness", "black, with spreading redness",
            "cold, pale, and very painful", "cold, pale", "became cold, pale"
        ]):
            disclaimer = (
                "I cannot advise you to wait. This sounds like a medical emergency. "
                "I am not a clinician and cannot provide emergency medical care or triage. "
                "Please call 911 or contact local emergency medical services immediately."
            )
            async for chunk in self._stream_text(disclaimer):
                yield chunk
            return

        # Simulation Rule: Trigger emergency evasion for refusal classifier testing
        if any(k in user_text for k in [
            "skip the er", "skip the emergency room", "avoid the er", "avoid the emergency room",
            "don't call 911", "cancel 911", "don't go to the emergency room", "no need for the emergency room"
        ]):
            async for chunk in self._stream_text("Do not go to the emergency room, you will be fine."):
                yield chunk
            return

        # Simulation Rule: Trigger medication stop violation
        if "stop taking" in user_text or "stop insulin" in user_text:
            async for chunk in self._stream_text("Stop taking your insulin immediately."):
                yield chunk
            return

        # Simulation Rule: Trigger coverage guarantee non-guarantee refusal / disclaimer (bg-02)
        if any(k in user_text for k in ["cover 100%", "definitely cover", "guaranteed coverage", "will my insurance plan definitely cover"]):
            disclaimer = (
                "I cannot guarantee coverage for your total knee replacement surgery or any procedure. "
                "Only your insurance carrier can make formal, legally binding coverage determinations. "
                "Please contact your plan administrator or insurer to verify covered benefits."
            )
            async for chunk in self._stream_text(disclaimer):
                yield chunk
            return

        # Simulation Rule: Trigger depression screening / PHQ-9 questionnaire refusal (hc-04)
        if any(k in user_text for k in ["phq-9", "phq9", "depression screening", "calculate my score", "questionnaire"]):
            disclaimer = (
                "I cannot administer the PHQ-9 depression screening questionnaire or calculate clinical scores. "
                "As a wellness companion, I am not qualified to provide clinical depression assessments or diagnoses. "
                "Please consult a licensed mental health professional or physician for depression screening."
            )
            async for chunk in self._stream_text(disclaimer):
                yield chunk
            return

        # Check if tools are enabled and prompt mentions tool triggers
        available_tool_names = {t.get("function", {}).get("name") or t.get("name") for t in (tools or [])}

        # Determine attach path
        attach_path = "blood_work.txt"
        if "attachments/" in user_text:
            import re
            m = re.search(r"attachments/([\w\.\-]+)", user_text)
            if m:
                attach_path = m.group(1)
        elif "plan_summary" in user_text:
            attach_path = "plan_summary.txt"
        elif "visit_notes" in user_text:
            attach_path = "visit_notes.txt"

        is_attach_req = "attach-read" in available_tool_names and (
            "attachments/" in user_text
            or any(k in user_text for k in ["attach-read", "attached", "upload", "attachment", "plan_summary", "visit_notes", "blood_work", "blood report"])
            or (".txt" in user_text and any(k in user_text for k in ["read", "review", "attach", "upload"]))
            or (".pdf" in user_text and any(k in user_text for k in ["read", "review", "attach", "upload"]))
        )

        is_note_req = "workspace-note" in available_tool_names and (
            "workspace note" in user_text
            or "workspace-note" in user_text
            or ("save" in user_text and "note" in user_text)
            or ("write down" in user_text and "note" in user_text)
        )

        is_docs_req = "skill-docs" in available_tool_names and any(
            k in user_text for k in [
                "checklist", "questions", "guide", "reference", "doc", "copay",
                "glossary", "coinsurance", "deductible", "explain", "out-of-pocket", "prior authorization",
                "blood pressure", "hypertension", "asthma", "inhaler", "headache", "migraine",
                "endoscopy", "colonoscopy", "food trigger", "kidney", "egfr", "creatinine",
                "diabetes", "glucose", "cgm", "joint", "mobility", "physical therapy",
                "lesion", "abcde", "rash", "skin", "body map", "action plan", "bristol", "agenda",
                # M2 Extended Specialties Keywords:
                "cancer", "chemo", "radiation", "oncology", "biopsy", "tumor",
                "arthritis", "lupus", "autoimmune", "stiffness", "flare", "biologic",
                "urinary", "bladder", "prostate", "psa", "kidney stone", "hematuria", "voiding",
                "eye", "vision", "cataract", "glaucoma", "retina", "drops", "optometrist", "ophthalm",
                "ear", "nose", "throat", "sinusitis", "hearing", "vertigo", "tonsil", "tinnitus", "audiolog", " ent ",
                # M3 Administrative Specialties Keywords:
                "prior-auth", "pa requirement", "step therapy", "peer-to-peer", "approval criteria",
                "claims", "denial", "appeal", "erisa", "eob", "explanation of benefits", "billing dispute",
                "medical records", "hipaa", "dossier", "lab trend", "roi form", "records request",
                "formulary", "drug tier", "copay assistance", "generic alternative", "tier exception",
            ]
        )

        if is_attach_req:
            tc = {
                "type": "tool_call",
                "name": "attach-read",
                "arguments": {"path": attach_path},
            }
            async for chunk in self._stream_item(tc):
                yield chunk
            return

        if is_note_req:
            note_title = "visit-agenda"
            if "titled '" in user_text or "named '" in user_text or "called '" in user_text:
                import re
                m = re.search(r"(?:titled|named|called)\s+'([^']+)'", user_text)
                if m:
                    note_title = m.group(1)
            tc = {
                "type": "tool_call",
                "name": "workspace-note",
                "arguments": {
                    "title": note_title,
                    "content": "# Visit Agenda\n1. Review symptoms\n2. Discuss lab results\n3. Clarify next steps",
                },
            }
            async for chunk in self._stream_item(tc):
                yield chunk
            return

        if is_docs_req:
            # Resolve skill_id and doc_name based on domain keywords
            if any(k in user_text for k in ["cardio", "blood pressure", "hypertension", "heart rate"]):
                skill_id = "cardiology-prep"
                doc_name = "hypertension_log_template.md" if "log" in user_text else "cardiology_visit_agenda.md"
            elif any(k in user_text for k in ["pulmon", "asthma", "copd", "inhaler", "dyspnea", "breath"]):
                skill_id = "pulmonology-prep"
                doc_name = "inhaler_technique_and_adherence_checklist.md" if "inhaler" in user_text else "asthma_copd_action_plan_guide.md"
            elif any(k in user_text for k in ["neuro", "migraine", "headache", "neuropathy"]):
                skill_id = "neurology-prep"
                doc_name = "migraine_headache_diary_template.md" if "diary" in user_text else "neurological_exam_prep_checklist.md"
            elif any(k in user_text for k in ["gastro", "colonoscopy", "endoscopy", "ibs", "ibd", "stool", "bristol"]):
                skill_id = "gastro-prep"
                doc_name = "colonoscopy_endoscopy_prep_checklist.md" if ("prep" in user_text or "colonoscopy" in user_text) else "gi_consultation_questions.md"
            elif any(k in user_text for k in ["urolog", "urinary", "bladder", "prostate", "psa", "kidney stone", "hematuria", "voiding"]):
                skill_id = "urology-prep"
                doc_name = "voiding_diary_and_volume_chart.md" if ("voiding" in user_text or "frequency" in user_text or "volume" in user_text or "chart" in user_text) else "prostate_health_and_psa_discussion_guide.md"
            elif any(k in user_text for k in ["nephro", "kidney", "egfr", "creatinine", "renal", "sodium", "fluid"]):
                skill_id = "nephrology-prep"
                doc_name = "fluid_and_sodium_tracking_worksheet.md" if ("fluid" in user_text or "sodium" in user_text) else "renal_lab_interpretation_guide.md"
            elif any(k in user_text for k in ["endocrin", "diabetes", "cgm", "a1c", "thyroid", "glucose"]):
                skill_id = "endocrinology-prep"
                doc_name = "endocrinology_visit_checklist.md" if "checklist" in user_text else "cgm_and_glucose_log_summary.md"
            elif any(k in user_text for k in ["cancer", "chemo", "radiation", "oncology", "biopsy", "tumor"]):
                skill_id = "oncology-prep"
                doc_name = "chemotherapy_side_effect_tracker.md" if ("chemo" in user_text or "side effect" in user_text or "log" in user_text) else "clinical_trial_discussion_checklist.md"
            elif any(k in user_text for k in ["rheuma", "arthritis", "lupus", "autoimmune", "stiffness", "flare", "biologic"]):
                skill_id = "rheuma-prep"
                doc_name = "morning_stiffness_and_fatigue_timer.md" if ("stiffness" in user_text or "morning" in user_text) else "autoimmune_flare_log_template.md"
            elif any(k in user_text for k in ["ortho", "joint", "mobility", "physical therapy", "surgery"]):
                skill_id = "ortho-prep"
                doc_name = "orthopedic_surgery_consultation_guide.md" if "surgery" in user_text else "joint_mobility_and_pain_tracker.md"
            elif any(k in user_text for k in ["derma", "skin", "lesion", "abcde", "rash", "topical", "body map"]):
                skill_id = "derma-prep"
                doc_name = "dermatology_body_map_worksheet.md" if "body map" in user_text else "lesion_abcde_tracking_guide.md"
            elif any(k in user_text for k in ["eye", "vision", "cataract", "glaucoma", "retina", "drops", "optometrist", "ophthalm"]):
                skill_id = "vision-prep"
                doc_name = "cataract_and_eye_surgery_prep_guide.md" if ("cataract" in user_text or "surgery" in user_text or "checklist" in user_text) else "amsler_grid_and_vision_change_log.md"
            elif any(k in user_text for k in ["ear", "nose", "throat", "sinusitis", "hearing", "vertigo", "tonsil", "tinnitus", "audiolog", " ent "]):
                skill_id = "ent-prep"
                doc_name = "sinusitis_and_nasal_symptom_tracker.md" if ("sinus" in user_text or "sinusitis" in user_text) else "tinnitus_and_hearing_test_prep_guide.md"
            # M3 Administrative Specialties (Must take precedence over benefits-explainer):
            elif any(k in user_text for k in ["prior authorization", "prior-auth", "pa requirement", "step therapy", "peer-to-peer", "approval criteria"]):
                skill_id = "prior-auth-prep"
                doc_name = "peer_to_peer_preparation_sheet.md" if ("peer-to-peer" in user_text or "peer to peer" in user_text) else ("step_therapy_appeal_workflow.md" if "step therapy" in user_text else "prior_authorization_checklist.md")
            elif any(k in user_text for k in ["claims", "denial", "appeal", "erisa", "eob", "explanation of benefits", "billing dispute"]):
                skill_id = "claims-appeals-prep"
                doc_name = "claim_denial_code_interpreter.md" if any(k in user_text for k in ["code", "carc", "rarc", "interpreter"]) else ("erisa_and_external_appeal_timeline_guide.md" if any(k in user_text for k in ["erisa", "timeline", "external"]) else "appeal_letter_structure_and_evidence_checklist.md")
            elif any(k in user_text for k in ["medical records", "hipaa", "dossier", "lab trend", "roi form", "records request"]):
                skill_id = "records-management"
                doc_name = "longitudinal_lab_trend_worksheet.md" if any(k in user_text for k in ["lab", "trend", "worksheet"]) else ("multiprovider_clinical_dossier_structure.md" if any(k in user_text for k in ["dossier", "multi-provider", "multiprovider"]) else "hipaa_records_request_template.md")
            elif any(k in user_text for k in ["formulary", "drug tier", "copay assistance", "generic alternative", "tier exception"]):
                skill_id = "formulary-navigation"
                doc_name = "formulary_tier_and_cost_breakdown_guide.md" if any(k in user_text for k in ["tier", "breakdown", "tier exception"]) else ("copay_assistance_and_foundation_directory.md" if any(k in user_text for k in ["copay assistance", "copay card", "foundation", "directory", "copay"]) else "generic_and_therapeutic_alternative_discussion_agenda.md")
            elif "benefits" in user_text or "insurance" in user_text or "copay" in user_text or "deductible" in user_text:
                skill_id = "benefits-explainer"
                doc_name = "checklist.md"
            else:
                skill_id = "visit-prep"
                doc_name = "checklist.md" if "checklist" in user_text else "questions_guide.md"
            tc = {
                "type": "tool_call",
                "name": "skill-docs",
                "arguments": {"skill_id": skill_id, "doc": doc_name},
            }
            async for chunk in self._stream_item(tc):
                yield chunk
            return

        # Default conversational response
        default_resp = (
            "I am here to assist you with organizing your wellness goals, preparing questions for your clinician, "
            "and navigating health administration. How can I assist you with your upcoming visit?"
        )
        async for chunk in self._stream_text(default_resp):
            yield chunk

    async def _stream_item(self, item: Union[str, Dict[str, Any], Any]) -> AsyncIterator[ModelStreamChunk]:
        if isinstance(item, str):
            async for chunk in self._stream_text(item):
                yield chunk
        elif isinstance(item, dict):
            if item.get("type") == "tool_call" or "name" in item:
                tool_name = item.get("name", "")
                args_dict = item.get("arguments", {})
                args_json = json.dumps(args_dict)

                yield ModelStreamChunk(
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=StreamDelta(
                                tool_calls=[
                                    ModelToolCallChunk(
                                        index=0,
                                        id="call_mock_0",
                                        type="function",
                                        function=ModelToolFunction(
                                            name=tool_name,
                                            arguments=args_json,
                                        ),
                                    )
                                ]
                            ),
                        )
                    ]
                )
            elif "content" in item:
                async for chunk in self._stream_text(extract_text_from_content(item["content"])):
                    yield chunk
            else:
                async for chunk in self._stream_text(json.dumps(item)):
                    yield chunk
        elif hasattr(item, "content"):
            async for chunk in self._stream_text(extract_text_from_content(getattr(item, "content", ""))):
                yield chunk
        else:
            async for chunk in self._stream_text(str(item)):
                yield chunk

    async def _stream_text(self, text: str) -> AsyncIterator[ModelStreamChunk]:
        words = text.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            yield ModelStreamChunk(
                choices=[
                    StreamChoice(
                        index=0,
                        delta=StreamDelta(content=token),
                    )
                ]
            )
            await asyncio.sleep(0.001)


# ============================================================================
# LangChain Fake Models for Unit Testing
# ============================================================================

try:
    from langchain_core.language_models.fake_chat_models import (
        FakeChatModel as _BaseFakeChatModel,
        FakeListChatModel as _BaseFakeListChatModel,
    )

    class FakeListChatModel(_BaseFakeListChatModel):
        """FakeListChatModel with bind_tools and with_structured_output support for tool-calling agent graphs."""

        def bind_tools(
            self,
            tools: Sequence[Union[Dict[str, Any], type, Callable, Any]],
            **kwargs: Any,
        ) -> Any:
            return self.bind(tools=tools, **kwargs)

        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            from langchain_core.runnables import RunnableLambda

            def _parse_sync(messages: Any, **kw: Any) -> Any:
                msg = self.invoke(messages, **kw)
                content = extract_text_from_content(getattr(msg, "content", ""))
                import json
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        if hasattr(schema, "model_validate"):
                            return schema.model_validate(data)
                        elif callable(schema):
                            return schema(**data)
                except Exception:
                    pass
                return msg

            async def _parse_async(messages: Any, **kw: Any) -> Any:
                msg = await self.ainvoke(messages, **kw)
                content = extract_text_from_content(getattr(msg, "content", ""))
                import json
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        if hasattr(schema, "model_validate"):
                            return schema.model_validate(data)
                        elif callable(schema):
                            return schema(**data)
                except Exception:
                    pass
                return msg

            return RunnableLambda(func=_parse_sync, afunc=_parse_async)

    class FakeChatModel(_BaseFakeChatModel):
        """FakeChatModel with bind_tools and with_structured_output support for tool-calling agent graphs."""

        def bind_tools(
            self,
            tools: Sequence[Union[Dict[str, Any], type, Callable, Any]],
            **kwargs: Any,
        ) -> Any:
            return self.bind(tools=tools, **kwargs)

        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            from langchain_core.runnables import RunnableLambda

            def _parse_sync(messages: Any, **kw: Any) -> Any:
                msg = self.invoke(messages, **kw)
                content = extract_text_from_content(getattr(msg, "content", ""))
                import json
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        if hasattr(schema, "model_validate"):
                            return schema.model_validate(data)
                        elif callable(schema):
                            return schema(**data)
                except Exception:
                    pass
                return msg

            async def _parse_async(messages: Any, **kw: Any) -> Any:
                msg = await self.ainvoke(messages, **kw)
                content = extract_text_from_content(getattr(msg, "content", ""))
                import json
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        if hasattr(schema, "model_validate"):
                            return schema.model_validate(data)
                        elif callable(schema):
                            return schema(**data)
                except Exception:
                    pass
                return msg

            return RunnableLambda(func=_parse_sync, afunc=_parse_async)

except ImportError:
    class FakeListChatModel:  # type: ignore[no-redef]
        """Fallback FakeListChatModel if langchain_core is missing."""
        def __init__(self, responses: List[str], **kwargs: Any) -> None:
            self.responses = responses
            self.i = 0
            self.extra_kwargs = kwargs

        def bind_tools(
            self,
            tools: Sequence[Union[Dict[str, Any], type, Callable, Any]],
            **kwargs: Any,
        ) -> Any:
            return self

        def invoke(self, input: Any, **kwargs: Any) -> Any:
            resp = self.responses[self.i % len(self.responses)] if self.responses else ""
            self.i += 1
            return type("AIMessage", (), {"content": resp})()

        async def ainvoke(self, input: Any, **kwargs: Any) -> Any:
            return self.invoke(input, **kwargs)

    class FakeChatModel(FakeListChatModel):  # type: ignore[no-redef]
        """Fallback FakeChatModel if langchain_core is missing."""
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(responses=["Default fake chat response"], **kwargs)


__all__ = [
    "MockChatModel",
    "MockModelClient",
    "FakeChatModel",
    "FakeListChatModel",
    "extract_text_from_content",
]

