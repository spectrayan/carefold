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

"""Carefold output guardrail node preserving Markdown formatting and multi-specialist fallbacks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.messages import AIMessage, ToolMessage

from yarvelle_core.engine.orchestration.runtime import MAIN_AGENT_ID
from yarvelle_core.engine.safety_policy import (
    SafetyPolicy,
    UnionSafetyPolicy,
    acheck_output,
    get_domain_safety_policy,
)
from carefold.resources.loader import get_resource_loader as get_carefold_resource_loader
from yarvelle_core.workflows.nodes.output_guardrail_node import OutputGuardrailNode, _guard_context

from carefold.engine.response_synthesizer import (
    CAREFOLD_CANONICAL_DISCLAIMER,
    CarefoldResponseSynthesizerNode,
    deduplicate_middle_disclaimers,
    rebrand_text,
    strip_safe_reference_preamble,
)


def extract_latest_turn_messages(messages: Sequence[Any]) -> List[Any]:
    """Returns messages belonging to the latest user turn (after the final HumanMessage)."""
    items = list(messages or [])
    last_human_idx = -1
    for idx, msg in enumerate(items):
        msg_type = getattr(msg, "type", "")
        role = msg.get("role") if isinstance(msg, dict) else None
        if msg_type in ("human", "user") or role in ("human", "user"):
            last_human_idx = idx
    return items[last_human_idx + 1 :] if last_human_idx >= 0 else items


def synthesize_uncomposed_subagent_turn(
    turn_messages: Sequence[Any],
    agent_titles: Optional[Dict[str, str]] = None,
) -> str:
    """Builds a deduplicated multi-specialist response when MainAgentNode returned an empty final AIMessage."""
    call_to_agent: Dict[str, str] = {}
    for msg in turn_messages:
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", None) or []:
                if isinstance(tc, dict) and tc.get("name") == "task":
                    tc_id = str(tc.get("id") or "")
                    args = tc.get("args") or {}
                    sub_id = str(args.get("subagent_type") or args.get("agent_id") or "specialist")
                    if tc_id:
                        call_to_agent[tc_id] = sub_id

    specialist_outputs: Dict[str, str] = {}
    for msg in turn_messages:
        if isinstance(msg, ToolMessage):
            tc_id = str(getattr(msg, "tool_call_id", "") or "")
            if tc_id not in call_to_agent:
                continue
            content = str(getattr(msg, "content", "") or "").strip()
            if not content or content.lower().startswith("error:"):
                continue
            aid = call_to_agent[tc_id]
            if aid in specialist_outputs:
                specialist_outputs[aid] = f"{specialist_outputs[aid]}\n\n{content}"
            else:
                specialist_outputs[aid] = content

    if not specialist_outputs:
        return ""

    synthesizer = CarefoldResponseSynthesizerNode(agent_titles=agent_titles or {})
    synth_state: Dict[str, Any] = {"specialist_outputs": specialist_outputs, "messages": []}
    return rebrand_text(synthesizer.synthesize_response(synth_state))


class CarefoldOutputGuardrailNode(OutputGuardrailNode):
    """Output guardrail using Carefold's pack disclaimer, safe preamble stripping, and subagent fallback."""

    def __init__(
        self,
        name: str = "output_guardrail",
        safety_policy: Optional[Union[SafetyPolicy, Sequence[SafetyPolicy]]] = None,
        agent_titles: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name=name, safety_policy=safety_policy)
        self.agent_titles = dict(agent_titles or {})

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        turn_messages = extract_latest_turn_messages(state.get("messages", []))
        output_text = str(state.get("output") or "")

        if not output_text:
            for msg in reversed(turn_messages):
                if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                    if isinstance(msg.content, str) and msg.content.strip():
                        output_text = msg.content
                        break
                elif isinstance(msg, dict) and msg.get("role") in ("assistant", "ai") and not msg.get("tool_calls"):
                    if str(msg.get("content") or "").strip():
                        output_text = str(msg.get("content"))
                        break

        # If MainAgentNode delegated to specialists via `task` but returned an empty final AIMessage,
        # synthesize the completed specialist outputs cleanly instead of emitting a bare disclaimer.
        if not output_text.strip() and state.get("current_agent") == MAIN_AGENT_ID:
            output_text = synthesize_uncomposed_subagent_turn(turn_messages, self.agent_titles)

        policies: List[SafetyPolicy] = [self.safety_policy]
        extra_policies = state.get("safety_policies") or []
        if isinstance(extra_policies, (list, tuple)):
            for p in extra_policies:
                if p not in policies:
                    policies.append(p)
        participating_domains = set(state.get("participating_domains") or [])
        if not participating_domains and state.get("deliberation_state"):
            d_state = state["deliberation_state"]
            for prop in (d_state.get("active_proposals") or {}).values():
                scope = prop.get("scope") if isinstance(prop, dict) else getattr(prop, "scope", None)
                if scope:
                    participating_domains.add(scope)
        for dom in participating_domains:
            dom_pol = get_domain_safety_policy(dom)
            if dom_pol and dom_pol not in policies:
                policies.append(dom_pol)

        effective_policy = UnionSafetyPolicy(policies) if len(policies) > 1 else policies[0]
        safety_check = await acheck_output(effective_policy, output_text, _guard_context(state))

        if safety_check.refused:
            reason = safety_check.reason or "forbidden_intent:policy_prohibited"
            is_hard = effective_policy.is_hard_refusal_reason(reason)
            return {
                "is_refusal": True,
                "refused": True,
                "refusal_reason": reason,
                "boundary_warning": not is_hard,
                "boundary_reason": reason if not is_hard else None,
                "next_step": "reflection",
                "is_compliant": False,
                "compliance_metadata": {
                    "compliant": False,
                    "reason": reason,
                    "boundary_warning": not is_hard,
                },
            }

        cleaned_output = deduplicate_middle_disclaimers(strip_safe_reference_preamble(output_text))
        header_text = get_carefold_resource_loader().get_disclaimer_header_text()
        final_output = cleaned_output
        if (
            header_text
            and header_text.lower() not in final_output.lower()
            and CAREFOLD_CANONICAL_DISCLAIMER.lower() not in final_output.lower()
            and "disclaimer:" not in final_output.lower()
        ):
            final_output = f"{cleaned_output}\n\n*Disclaimer: {header_text}*" if cleaned_output else f"*Disclaimer: {header_text}*"

        boundary_warning = bool(
            safety_check.refused and not effective_policy.is_hard_refusal_reason(safety_check.reason)
        )
        boundary_reason = safety_check.reason if boundary_warning else None
        return {
            "is_refusal": False,
            "refused": False,
            "boundary_warning": boundary_warning,
            "boundary_reason": boundary_reason,
            "is_compliant": True,
            "output": final_output,
            "compliance_disclaimer": header_text,
            "disclaimer": header_text,
            "compliance_metadata": {
                "compliant": True,
                "has_disclaimer": True,
                "boundary_warning": boundary_warning,
                "boundary_reason": boundary_reason,
            },
            "next_step": "suggestion",
        }


__all__ = [
    "CarefoldOutputGuardrailNode",
    "extract_latest_turn_messages",
    "synthesize_uncomposed_subagent_turn",
]
