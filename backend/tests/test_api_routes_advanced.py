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

"""API Routes and Edge Cases Test Suite.
Target Endpoints:
- GET /api/agents/categories
- GET /api/agents
- GET /api/agents/{agent_id}
- GET /api/skills
- GET /api/skills/{skill_id}

Scope of Tests:
1. Route Shadowing & Path Routing:
   - GET /api/agents/categories returns category tree with 200 OK (not shadowed by /{agent_id}).
   - GET /api/agents/benefits-guide returns 200 OK detail.
   - GET /api/agents/visit-steward and habit-companion return 200 OK detail.
   - GET /api/agents/categories_test returns 404 Not Found (nonexistent agent).
   - GET /api/agents/categories-fake returns 404 Not Found.
   - Sub-paths under categories (GET /api/agents/categories/sub) return 404 Not Found.
2. Pagination Boundary & Validation Edge Cases:
   - page=0, page=-1, page=-5 -> HTTP 422 Unprocessable Entity (FastAPI Query ge=1 constraint).
   - per_page=0, per_page=-1, per_page=-5 -> HTTP 422 Unprocessable Entity.
   - Non-integer page/per_page (e.g. page="abc", per_page="xyz") -> HTTP 422.
   - High page offset (page=1000) -> HTTP 200 OK, empty list [].
   - page=1&per_page=1 -> HTTP 200 OK, exact length 1.
   - page=2&per_page=1 -> HTTP 200 OK, exact length 1, disjoint from page 1.
   - page omitted (None) -> returns full unpaginated list regardless of per_page (backward compatibility).
   - Large per_page (e.g. per_page=1000000) -> returns all items without failure.
   - Applied symmetrically to both /api/agents and /api/skills.
3. Domain Filtering:
   - Case insensitivity: domain="NAVIGATION", domain="navigation", domain="Navigation".
   - Whitespace stripping: domain="  navigation  ".
   - Nonexistent domain: domain="nonexistent_domain" -> HTTP 200 OK, empty list [].
   - Domain filtering on /api/skills: domain="WELLNESS", domain="wellness", domain="nonexistent".
4. Category Prefix Filtering:
   - Prefix match: category="navigation" matches both navigation.insurance and navigation.appointments.
   - Exact category: category="navigation.insurance" matches only benefits-guide.
   - Exact category: category="navigation.appointments" matches only visit-steward.
   - Dot-segment boundary check: category="nav" does NOT match navigation.insurance (boundary safe).
   - Case insensitivity: category="NAVIGATION".
5. Combined Filters & Adversarial Inputs:
   - Combined query: domain=navigation&risk_class=administrative&page=1&per_page=10
     Verifies that because valid risk_class is "admin" (not "administrative"), returns 200 OK with [].
   - Combined query: domain=navigation&risk_class=admin&page=1&per_page=10 -> returns benefits-guide.
   - Combined query: domain=navigation&risk_class=wellness&page=1&per_page=10 -> returns visit-steward.
   - Combined query with search: domain=navigation&search=benefits&page=1&per_page=5 -> returns benefits-guide.
   - Combined with include_hidden=true: domain=wellness&risk_class=admin&include_hidden=true -> returns system agents.
6. Category Tree Accuracy & Integrity:
   - Root keys and count rollups.
   - System agents from _system/ are excluded from category tree totals.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set
import pytest
from fastapi.testclient import TestClient


# ============================================================================
# 1. Route Shadowing & Path Routing Challenges
# ============================================================================

class TestRouteShadowing:
    """Verifies that fixed static routes like /categories are not shadowed by path params."""

    def test_categories_endpoint_returns_200_and_tree(self, client: TestClient):
        """GET /api/agents/categories must return 200 OK with the category hierarchy tree."""
        res = client.get("/api/agents/categories")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict)

        # Must have domain keys or 'domains' key
        domains = data.get("domains", data)
        assert "navigation" in domains
        assert "wellness" in domains

        # Total count should match user-facing agents (6 navigation, 1 wellness, 13 clinical)
        assert domains["navigation"]["count"] == 6
        assert domains["wellness"]["count"] == 1

        # Check subcategories
        nav_cats = domains["navigation"].get("categories", {})
        assert "insurance" in nav_cats
        assert "appointments" in nav_cats
        assert nav_cats["insurance"]["count"] == 1
        assert nav_cats["appointments"]["count"] == 1

    def test_agent_detail_benefits_guide_returns_200(self, client: TestClient):
        """GET /api/agents/benefits-guide must resolve to the detail endpoint with 200 OK."""
        res = client.get("/api/agents/benefits-guide")
        assert res.status_code == 200
        detail = res.json()
        assert detail["id"] == "benefits-guide"
        assert detail["domain"] == "navigation"
        assert detail["category"] == "navigation.insurance"
        assert detail["risk_class"] == "admin"
        assert "attach-read" in detail["effectiveTools"]

    def test_agent_detail_visit_steward_returns_200(self, client: TestClient):
        """GET /api/agents/visit-steward must resolve to detail endpoint with 200 OK."""
        res = client.get("/api/agents/visit-steward?allow_clinical=true")
        assert res.status_code == 200
        detail = res.json()
        assert detail["id"] == "visit-steward"
        assert detail["domain"] == "navigation"
        assert detail["category"] == "navigation.appointments"

    def test_agent_detail_habit_companion_returns_200(self, client: TestClient):
        """GET /api/agents/habit-companion must resolve to detail endpoint with 200 OK."""
        res = client.get("/api/agents/habit-companion")
        assert res.status_code == 200
        detail = res.json()
        assert detail["id"] == "habit-companion"
        assert detail["domain"] == "wellness"
        assert detail["category"] == "wellness.habits"

    def test_nonexistent_agent_categories_test_returns_404(self, client: TestClient):
        """GET /api/agents/categories_test should not confuse router and must return 404."""
        res = client.get("/api/agents/categories_test")
        assert res.status_code == 404
        assert "categories_test" in res.json().get("detail", "")

    def test_nonexistent_agent_categories_fake_returns_404(self, client: TestClient):
        """GET /api/agents/categories-fake must return 404."""
        res = client.get("/api/agents/categories-fake")
        assert res.status_code == 404
        assert "categories-fake" in res.json().get("detail", "")

    def test_subpath_under_categories_returns_404(self, client: TestClient):
        """GET /api/agents/categories/unknown-subpath must return 404."""
        res = client.get("/api/agents/categories/unknown-subpath")
        assert res.status_code == 404


# ============================================================================
# 2. Pagination Boundary & Validation Edge Cases
# ============================================================================

class TestPaginationBoundaries:
    """Stress-tests query parameter validation (ge=1) and slicing boundaries."""

    @pytest.mark.parametrize("invalid_page", [0, -1, -5, -99999])
    def test_agents_invalid_page_raises_422(self, client: TestClient, invalid_page: int):
        """Verify page < 1 triggers FastAPI 422 Unprocessable Entity."""
        res = client.get(f"/api/agents?page={invalid_page}")
        assert res.status_code == 422

    @pytest.mark.parametrize("invalid_per_page", [0, -1, -5, -99999])
    def test_agents_invalid_per_page_raises_422(self, client: TestClient, invalid_per_page: int):
        """Verify per_page < 1 triggers FastAPI 422 Unprocessable Entity."""
        res = client.get(f"/api/agents?per_page={invalid_per_page}")
        assert res.status_code == 422

    @pytest.mark.parametrize("bad_val", ["abc", "null", "1.5", "undefined"])
    def test_agents_non_integer_pagination_raises_422(self, client: TestClient, bad_val: str):
        """Verify non-integer page or per_page triggers 422."""
        res_page = client.get(f"/api/agents?page={bad_val}")
        assert res_page.status_code == 422
        res_per_page = client.get(f"/api/agents?per_page={bad_val}")
        assert res_per_page.status_code == 422

    def test_agents_high_page_returns_empty_list(self, client: TestClient):
        """Verify page beyond total dataset (e.g. page=1000) returns HTTP 200 with empty list []."""
        res = client.get("/api/agents?page=1000")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert data == []

    def test_agents_page_1_per_page_1_returns_exact_length_1(self, client: TestClient):
        """Verify page=1&per_page=1 returns exactly 1 item."""
        res = client.get("/api/agents?page=1&per_page=1")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_agents_pagination_disjoint_pages(self, client: TestClient):
        """Verify page 1 and page 2 with per_page=1 return different agents."""
        res1 = client.get("/api/agents?page=1&per_page=1")
        res2 = client.get("/api/agents?page=2&per_page=1")
        assert res1.status_code == 200
        assert res2.status_code == 200
        item1 = res1.json()[0]
        item2 = res2.json()[0]
        assert item1["id"] != item2["id"]

    def test_agents_omitted_page_returns_full_list(self, client: TestClient):
        """When page is omitted, returns unpaginated list for backward compatibility."""
        res_all = client.get("/api/agents")
        assert res_all.status_code == 200
        all_agents = res_all.json()
        assert len(all_agents) >= 3

        # Even if per_page is specified, if page is None, all agents are returned
        res_with_per_page_only = client.get("/api/agents?per_page=1")
        assert res_with_per_page_only.status_code == 200
        assert len(res_with_per_page_only.json()) == len(all_agents)

    def test_agents_very_large_per_page(self, client: TestClient):
        """Verify page=1&per_page=1000000 returns all agents safely."""
        res = client.get("/api/agents?page=1&per_page=1000000")
        assert res.status_code == 200
        assert len(res.json()) >= 3

    # Symmetric tests for /api/skills
    @pytest.mark.parametrize("invalid_page", [0, -1, -5])
    def test_skills_invalid_page_raises_422(self, client: TestClient, invalid_page: int):
        res = client.get(f"/api/skills?page={invalid_page}")
        assert res.status_code == 422

    @pytest.mark.parametrize("invalid_per_page", [0, -1, -5])
    def test_skills_invalid_per_page_raises_422(self, client: TestClient, invalid_per_page: int):
        res = client.get(f"/api/skills?per_page={invalid_per_page}")
        assert res.status_code == 422

    def test_skills_high_page_returns_empty_list(self, client: TestClient):
        res = client.get("/api/skills?page=1000")
        assert res.status_code == 200
        assert res.json() == []

    def test_skills_page_1_per_page_1_returns_exact_length_1(self, client: TestClient):
        res = client.get("/api/skills?page=1&per_page=1")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1


# ============================================================================
# 3. Domain Filtering Challenges
# ============================================================================

class TestDomainFiltering:
    """Verifies case-insensitive domain filtering and whitespace handling."""

    @pytest.mark.parametrize("domain_param", ["navigation", "NAVIGATION", "Navigation", "  navigation  "])
    def test_agents_filter_domain_case_insensitive(self, client: TestClient, domain_param: str):
        """Verify domain matching handles UPPERCASE, lowercase, titlecase, and whitespace."""
        res = client.get(f"/api/agents?domain={domain_param}")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) == 6
        returned_ids = {a["id"] for a in agents}
        assert returned_ids == {
            "benefits-guide",
            "visit-steward",
            "prior-auth-navigator",
            "claims-appeals-guide",
            "records-coordinator",
            "formulary-guide",
        }
        for a in agents:
            assert a["domain"].lower() == "navigation"

    def test_agents_filter_domain_wellness(self, client: TestClient):
        res = client.get("/api/agents?domain=wellness")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) == 1
        assert agents[0]["id"] == "habit-companion"
        assert agents[0]["domain"].lower() == "wellness"

    def test_agents_filter_domain_nonexistent_returns_empty(self, client: TestClient):
        """Verify querying a nonexistent domain returns 200 OK with empty list."""
        res = client.get("/api/agents?domain=nonexistent_domain")
        assert res.status_code == 200
        assert res.json() == []

    def test_agents_filter_domain_clinical(self, client: TestClient):
        """Verify clinical domain returns public clinical organ navigators."""
        res = client.get("/api/agents?domain=clinical")
        assert res.status_code == 200
        assert len(res.json()) >= 8

    def test_agents_filter_domain_therapy_empty(self, client: TestClient):
        """Verify therapy domain returns empty list since no public therapy agents exist."""
        res = client.get("/api/agents?domain=therapy")
        assert res.status_code == 200
        assert res.json() == []

    @pytest.mark.parametrize("domain_param", ["wellness", "WELLNESS", "Wellness", "  wellness  "])
    def test_skills_filter_domain_case_insensitive(self, client: TestClient, domain_param: str):
        """Verify skills domain filtering is case-insensitive."""
        res = client.get(f"/api/skills?domain={domain_param}")
        assert res.status_code == 200
        skills = res.json()
        assert len(skills) >= 1
        for s in skills:
            assert s["domain"].lower() == "wellness"

    def test_skills_filter_domain_nonexistent_returns_empty(self, client: TestClient):
        res = client.get("/api/skills?domain=nonexistent_domain")
        assert res.status_code == 200
        assert res.json() == []


# ============================================================================
# 4. Category Prefix Filtering Challenges
# ============================================================================

class TestCategoryPrefixFiltering:
    """Verifies hierarchical category prefix matching (e.g. 'navigation' matches 'navigation.*')."""

    def test_category_prefix_navigation_matches_both_agents(self, client: TestClient):
        """Category 'navigation' should match both 'navigation.insurance' and 'navigation.appointments'."""
        res = client.get("/api/agents?category=navigation")
        assert res.status_code == 200
        agents = res.json()
        returned_ids = {a["id"] for a in agents}
        assert returned_ids == {
            "benefits-guide",
            "visit-steward",
            "prior-auth-navigator",
            "claims-appeals-guide",
            "records-coordinator",
            "formulary-guide",
        }

    def test_category_prefix_case_insensitive(self, client: TestClient):
        """Category matching must be case-insensitive ('NAVIGATION' or 'Navigation')."""
        for param in ["NAVIGATION", "Navigation", " navigation "]:
            res = client.get(f"/api/agents?category={param}")
            assert res.status_code == 200
            agents = res.json()
            returned_ids = {a["id"] for a in agents}
            assert returned_ids == {
                "benefits-guide",
                "visit-steward",
                "prior-auth-navigator",
                "claims-appeals-guide",
                "records-coordinator",
                "formulary-guide",
            }

    def test_category_exact_navigation_insurance(self, client: TestClient):
        """Exact category 'navigation.insurance' should only return benefits-guide."""
        res = client.get("/api/agents?category=navigation.insurance")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) == 1
        assert agents[0]["id"] == "benefits-guide"

    def test_category_exact_navigation_appointments(self, client: TestClient):
        """Exact category 'navigation.appointments' should only return visit-steward."""
        res = client.get("/api/agents?category=navigation.appointments")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) == 1
        assert agents[0]["id"] == "visit-steward"

    def test_category_segment_boundary_safety(self, client: TestClient):
        """'nav' is a substring of 'navigation', but NOT a category prefix segment.
        The matching logic is `cat == c or cat.startswith(f"{c}.")`.
        Therefore category='nav' MUST NOT match 'navigation.insurance'.
        """
        res = client.get("/api/agents?category=nav")
        assert res.status_code == 200
        assert res.json() == []

    def test_category_nonexistent_returns_empty(self, client: TestClient):
        res = client.get("/api/agents?category=navigation.nonexistent")
        assert res.status_code == 200
        assert res.json() == []


# ============================================================================
# 5. Combined Filters & Adversarial Inputs
# ============================================================================

class TestCombinedFilters:
    """Tests combinations of domain, risk_class, category, search, and pagination."""

    def test_combined_domain_navigation_risk_class_administrative(self, client: TestClient):
        """Resilience Challenge:
        The prompt tests: `domain=navigation&risk_class=administrative&page=1&per_page=10`.
        In the Carefold taxonomy, the risk class is 'admin', NOT 'administrative'.
        Verify that passing risk_class='administrative' returns 200 OK with empty list []
        because no agent has risk_class == 'administrative'.
        """
        res = client.get("/api/agents?domain=navigation&risk_class=administrative&page=1&per_page=10")
        assert res.status_code == 200
        assert res.json() == []

    def test_combined_domain_navigation_risk_class_admin(self, client: TestClient):
        """When risk_class='admin' is used with domain='navigation', admin navigation agents match."""
        res = client.get("/api/agents?domain=navigation&risk_class=admin&page=1&per_page=10")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) >= 1
        agent_ids = {a["id"] for a in agents}
        assert "benefits-guide" in agent_ids

    def test_combined_domain_navigation_risk_class_clinical_assist(self, client: TestClient):
        """When risk_class='clinical_assist' is used with domain='navigation', exactly visit-steward matches."""
        res = client.get("/api/agents?domain=navigation&risk_class=clinical_assist&page=1&per_page=10")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) == 1
        assert agents[0]["id"] == "visit-steward"

    def test_combined_filters_with_search_and_pagination(self, client: TestClient):
        """Combined: domain=navigation & search=benefits & page=1 & per_page=5."""
        res = client.get("/api/agents?domain=navigation&search=benefits&page=1&per_page=5")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) >= 1
        agent_ids = {a["id"] for a in agents}
        assert "benefits-guide" in agent_ids

    def test_combined_filters_conflicting_search_returns_empty(self, client: TestClient):
        """Combined: domain=wellness & search=insurance -> empty list []."""
        res = client.get("/api/agents?domain=wellness&search=insurance")
        assert res.status_code == 200
        assert res.json() == []

    def test_combined_filters_with_hidden_system_agents(self, client: TestClient):
        """Combined: domain=wellness & risk_class=admin & include_hidden=true.
        Should return system agents (orchestrator, document-extractor, skill-generator, suggestion-generator)
        which are domain=wellness and risk_class=admin.
        """
        res = client.get("/api/agents?domain=wellness&risk_class=admin&include_hidden=true")
        assert res.status_code == 200
        agents = res.json()
        agent_ids = {a["id"] for a in agents}
        assert "orchestrator" in agent_ids
        assert "document-extractor" in agent_ids
        assert "skill-generator" in agent_ids
        assert "suggestion-generator" in agent_ids
        assert "_template" not in agent_ids


# ============================================================================
# 6. Category Tree Accuracy & Fallback Verification
# ============================================================================

class TestCategoryTreeIntegrity:
    """Verifies category tree generation, accuracy, and fallback behavior."""

    def test_category_tree_excludes_system_agents(self, client: TestClient):
        """Hidden system agents must NOT be counted in category tree totals."""
        res = client.get("/api/agents/categories")
        assert res.status_code == 200
        data = res.json()
        domains = data.get("domains", data)

        # Wellness should only have 1 (habit-companion), not 5 (orchestrator, extractor, etc. excluded)
        assert domains["wellness"]["count"] == 1
        # Navigation has 6 navigation agents
        assert domains["navigation"]["count"] == 6
        total_count = sum(domains[d]["count"] for d in domains if isinstance(domains[d], dict) and "count" in domains[d])
        assert total_count >= 3
        assert domains.get("clinical", {}).get("count", 0) >= 8

    def test_category_tree_fallback_when_catalog_fails(self, client: TestClient, monkeypatch):
        """When get_catalog_port fails or raises, category endpoint gracefully falls back to manifest scan."""
        import carefold.api.agents as agents_api

        def broken_catalog_port():
            raise RuntimeError("Database unavailable")

        # Mock catalog retrieval failure in the endpoint
        monkeypatch.setattr("carefold.memory.factory.get_catalog_port", broken_catalog_port)

        res = client.get("/api/agents/categories")
        assert res.status_code == 200
        data = res.json()
        domains = data.get("domains", data)
        assert "navigation" in domains
        assert domains["navigation"]["count"] == 6
        assert "wellness" in domains
        assert domains["wellness"]["count"] == 1


# ============================================================================
# 7. Adversarial Strings & Injection Attempts
# ============================================================================

class TestAdversarialInputs:
    """Stress tests malicious inputs, SQL injection patterns, and whitespace strings."""

    @pytest.mark.parametrize(
        "malicious_payload",
        [
            "' OR '1'='1",
            "admin'--",
            "'; DROP TABLE agents;--",
            "<script>alert(1)</script>",
            "../../etc/passwd",
            "%00",
            "\\x00",
            "!@#$%^&*()_+",
        ],
    )
    def test_domain_and_category_params(self, client: TestClient, malicious_payload: str):
        """Adversarial query parameters should not cause 500 error; return 200 with [] safe list."""
        res_agents = client.get(f"/api/agents?domain={malicious_payload}")
        assert res_agents.status_code == 200
        assert res_agents.json() == []

        res_cat = client.get(f"/api/agents?category={malicious_payload}")
        assert res_cat.status_code == 200
        assert res_cat.json() == []

        res_skills = client.get(f"/api/skills?domain={malicious_payload}")
        assert res_skills.status_code == 200
        assert res_skills.json() == []

    def test_empty_string_parameters_do_not_crash(self, client: TestClient):
        """Passing empty query params (e.g. ?domain= or ?category=) returns unfiltered list safely."""
        res = client.get("/api/agents?domain=&category=")
        assert res.status_code == 200
        agents = res.json()
        assert len(agents) >= 3

    def test_whitespace_only_domain_returns_empty(self, client: TestClient):
        """Passing whitespace-only domain returns empty list because stripped string does not match any valid domain."""
        res = client.get("/api/agents?domain=%20%20%20")
        assert res.status_code == 200
        assert res.json() == []


# ============================================================================
# 8. Skills Pagination Multi-Page Invariance
# ============================================================================

class TestSkillsMultiPagePagination:
    """Verifies multi-page slicing invariance and exhaustiveness across skills."""

    def test_skills_multi_page_coverage(self, client: TestClient):
        """Paginating across all installed skills with per_page=3 partitions the entire skill set."""
        res_all = client.get("/api/skills")
        assert res_all.status_code == 200
        all_skills = res_all.json()
        total_skills = len(all_skills)
        assert total_skills >= 5

        page = 1
        per_page = 3
        collected_ids: List[str] = []

        while True:
            res_page = client.get(f"/api/skills?page={page}&per_page={per_page}")
            assert res_page.status_code == 200
            skills_chunk = res_page.json()
            if not skills_chunk:
                break
            assert len(skills_chunk) <= per_page
            collected_ids.extend([s["id"] for s in skills_chunk])
            page += 1

        # All skills collected without duplicates or omissions
        assert len(collected_ids) == total_skills
        assert len(collected_ids) == len(set(collected_ids))
        assert collected_ids == [s["id"] for s in all_skills]

