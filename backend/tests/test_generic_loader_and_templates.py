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

"""Test suite verifying domain-agnostic loader architecture and Handlebars prompt templating.

Verifies:
1. Handlebars TemplateEngine rendering with helper functions (join, eq, upper, lower, etc.).
2. Dynamic prompt builder rendering system prompts via Handlebars (.hbs) templates.
3. Support for non-healthcare domains (retail, finance, operations, general) in AgentDomain.
4. Generic, data-driven follow-up suggestions for retail and finance agents without hardcoded domain checks in Python.
5. Inline suggestions declared directly on AgentManifest.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from carefold.engine.prompt_builder import build_system_prompt
from carefold.resources.loader import ResourceLoader, get_resource_loader
from carefold.schemas.manifest import AgentDomain, AgentManifest, RiskClass, SkillManifest
from carefold.templates.engine import TemplateEngine, get_template_engine, render_template


def test_handlebars_engine_helpers_and_blocks():
    """Verifies that Handlebars compiler processes conditionals, iterations, and helpers."""
    engine = get_template_engine()
    source = """
{{#if active}}
Status: ACTIVE
Agent: {{upper agent.name}}
{{#if (eq agent.domain "retail")}}
Domain: RETAIL STORE
{{/if}}
Tags: {{join tags ", "}}
{{#each items}}
- Item: {{name}} (Qty: {{qty}})
{{/each}}
{{/if}}
"""
    context = {
        "active": True,
        "agent": {"name": "store-clerk", "domain": "retail"},
        "tags": ["pos", "checkout", "inventory"],
        "items": [
            {"name": "Sneakers", "qty": 2},
            {"name": "Hoodie", "qty": 1},
        ],
    }

    result = engine.render(source, context)
    assert "Status: ACTIVE" in result
    assert "Agent: STORE-CLERK" in result
    assert "Domain: RETAIL STORE" in result
    assert "Tags: pos, checkout, inventory" in result
    assert "- Item: Sneakers (Qty: 2)" in result
    assert "- Item: Hoodie (Qty: 1)" in result


def test_build_system_prompt_via_handlebars_default():
    """Verifies that build_system_prompt compiles and renders system_prompt.hbs cleanly."""
    agent = AgentManifest(
        id="ecommerce-advisor",
        title="E-Commerce Advisor",
        domain=AgentDomain.RETAIL,
        category="retail.support",
        risk_class=RiskClass.WELLNESS,
        persona="You are a personal shopper helping users find products and track orders.",
        tools=["attach-read", "skill-docs"],
    )

    skill = SkillManifest(
        id="order-tracking",
        name="Order Tracking",
        description="Tracks shipment status.",
        instructions="Ask for order ID, then lookup tracking code.",
    )

    rendered = build_system_prompt(agent, skills=[skill], effective_tools=["attach-read", "skill-docs"])

    assert "# AGENT PERSONA & INSTRUCTIONS" in rendered
    assert "Agent ID: ecommerce-advisor" in rendered
    assert "Title: E-Commerce Advisor" in rendered
    assert "You are a personal shopper helping users find products and track orders." in rendered
    assert "Available Tools (Sandboxed): attach-read, skill-docs" in rendered
    assert "# SKILL INSTRUCTION PACKS" in rendered
    assert "### Skill: Order Tracking (order-tracking)" in rendered
    assert "Ask for order ID, then lookup tracking code." in rendered


def test_build_system_prompt_custom_handlebars_template():
    """Verifies that an agent can provide a custom Handlebars template."""
    custom_template = """
== DOMAIN IDENTITY: {{agent.title}} ({{agent.id}}) ==
Domain: {{agent.domain}}
Role: {{{persona_text}}}
{{#if has_skills}}
Active Capabilities:
{{#each skills}}
* {{name}}: {{{instructions}}}
{{/each}}
{{/if}}
"""
    agent = AgentManifest(
        id="wealth-planner",
        title="Wealth Planner",
        domain=AgentDomain.FINANCE,
        category="finance.advisory",
        risk_class=RiskClass.ADMIN,
        persona="Manage diversified portfolios and tax-advantaged retirement accounts.",
        prompt_template=custom_template,
    )

    skill = SkillManifest(
        id="asset-allocation",
        name="Asset Allocation",
        description="Model asset allocations.",
        instructions="Assess investor risk tolerance first.",
    )

    rendered = build_system_prompt(agent, skills=[skill])
    assert "== DOMAIN IDENTITY: Wealth Planner (wealth-planner) ==" in rendered
    assert "Domain: finance" in rendered
    assert "Manage diversified portfolios and tax-advantaged retirement accounts." in rendered
    assert "* Asset Allocation: Assess investor risk tolerance first." in rendered


def test_generic_suggestions_for_non_health_domains():
    """Verifies that loader.get_follow_up_suggestions dynamically resolves arbitrary domain keywords and tools."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        prompts_dir = tmp_path / "prompts" / "suggestions"
        prompts_dir.mkdir(parents=True)

        suggestions_yaml = prompts_dir / "suggestions.yaml"
        suggestions_yaml.write_text("""
tool_suggestions:
  order-search:
    - "Can you track my package status?"
    - "When is my estimated delivery date?"
    - "Can I change my delivery address?"

persona_suggestions:
  retail_advisor:
    return_keywords: ["return", "refund", "exchange", "receipt"]
    return_chips:
      - "What is the return window for this item?"
      - "How do I print a prepaid return shipping label?"
      - "Can I return an online order to a physical store?"
    coupon_keywords: ["discount", "coupon", "promo", "deal"]
    coupon_chips:
      - "Are there any active promo codes for my cart?"
      - "Can I stack store coupons with sale prices?"
      - "How do I earn rewards points on this purchase?"
    default_chips:
      - "Can you help me find similar products in my size?"
      - "What are your top-rated items in this category?"
      - "How do I check in-store stock availability?"

  crypto_analyst:
    yield_keywords: ["yield", "staking", "apy", "rewards"]
    yield_chips:
      - "What are the current staking APY rates?"
      - "What are the unbonding lockup periods?"
      - "How is staking yield taxed in my jurisdiction?"
    default_chips:
      - "Can you summarize the recent market volatility?"
      - "What are the gas fees on mainnet today?"
      - "How do hardware wallets secure private keys?"
""", encoding="utf-8")

        loader = ResourceLoader(resources_dir=tmp_path)

        # 1. Retail advisor with return query
        retail_return = loader.get_follow_up_suggestions(
            agent_id="retail-advisor",
            prompt="I want to return these shoes, where is my receipt?",
            tools_used=["order-search"],
        )
        assert any("return window" in c.lower() for c in retail_return)
        assert not any("doctor" in c.lower() for c in retail_return)

        # 2. Retail advisor general turn with tool used
        retail_order = loader.get_follow_up_suggestions(
            agent_id="retail-advisor",
            prompt="Hello there",
            tools_used=["order-search"],
        )
        assert any("package status" in c.lower() or "similar products" in c.lower() for c in retail_order)

        # 3. Crypto analyst with staking inquiry
        crypto_yield = loader.get_follow_up_suggestions(
            agent_id="crypto-analyst",
            prompt="What is the staking APY for this token?",
            tools_used=[],
        )
        assert any("staking apy" in c.lower() for c in crypto_yield)

        # 4. Crypto analyst default chips
        crypto_gen = loader.get_follow_up_suggestions(
            agent_id="crypto-analyst",
            prompt="Just checking in",
            tools_used=[],
        )
        assert any("market volatility" in c.lower() for c in crypto_gen)


def test_agent_manifest_inline_suggestions_override():
    """Verifies that an agent defining inline suggestions in manifest takes precedence."""
    agent = AgentManifest(
        id="devops-copilot",
        title="DevOps Copilot",
        domain=AgentDomain.OPERATIONS,
        category="operations.infra",
        risk_class=RiskClass.ADMIN,
        persona="Kubernetes cluster operator.",
        suggestions={
            "pod_keywords": ["pod", "crash", "oom", "restart"],
            "pod_chips": [
                "How do I check the pod logs for exit code 137?",
                "Can you describe the resource limits in the deployment spec?",
                "Should we scale up the replica count?",
            ],
            "default_chips": [
                "Can you summarize the cluster health?",
                "Are any nodes experiencing memory pressure?",
                "Show me recent ingress error rates.",
            ],
        },
    )

    # Mock registry returning our devops agent
    loader = get_resource_loader()
    loader._cache.clear()

    class FakeRegistry:
        def get(self, aid: str):
            if aid in ("devops-copilot", "devops_copilot"):
                return agent
            return None

    import carefold.agents.registry as reg_mod
    orig_registry = reg_mod._registry_instance
    reg_mod._registry_instance = FakeRegistry()  # type: ignore[assignment]

    try:
        # Keyword match
        chips_oom = loader.get_follow_up_suggestions(
            agent_id="devops-copilot",
            prompt="My pod crashed with OOMKilled",
        )
        assert any("exit code 137" in c.lower() for c in chips_oom)

        # Default match
        chips_default = loader.get_follow_up_suggestions(
            agent_id="devops-copilot",
            prompt="Hello cluster",
        )
        assert any("cluster health" in c.lower() for c in chips_default)
    finally:
        reg_mod._registry_instance = orig_registry


def test_pydantic_handlebars_model_rendering():
    """Verifies that TemplateEngine natively renders Pydantic models directly."""
    from pydantic import BaseModel, Field

    class InvoiceItem(BaseModel):
        description: str
        amount: float

    class Invoice(BaseModel):
        invoice_number: str
        customer: str
        status: str = "PENDING"
        items: list[InvoiceItem] = Field(default_factory=list)

    inv = Invoice(
        invoice_number="INV-2026-001",
        customer="Acme Corp",
        items=[
            InvoiceItem(description="Cloud GPU Cluster", amount=1200.50),
            InvoiceItem(description="Vector Storage", amount=150.00),
        ],
    )

    template = """
Invoice: {{invoice_number}} | Customer: {{customer}} | Status: {{status}}
{{#each items}}
- {{description}}: ${{amount}}
{{/each}}
"""
    engine = get_template_engine()
    rendered = engine.render(template, inv)

    assert "Invoice: INV-2026-001" in rendered
    assert "Customer: Acme Corp" in rendered
    assert "- Cloud GPU Cluster: $1200.5" in rendered
    assert "- Vector Storage: $150.0" in rendered

