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

"""Adversarial security boundary tests for the yarvelle-core SQL AST sandbox.

Adversarially stress-tests:
1. DDL rejection (DROP, ALTER, CREATE, TRUNCATE, RENAME, etc.) across whitespace,
   comments, stacked queries, and subqueries.
2. System table protection (users, audit_events, credentials, profile_keys, etc.)
   across quotes, schema qualification, subqueries, JOINs, UNIONs, and CTEs.
3. Tenant & scope isolation against injections (WHERE 1=1, comments, stacked queries)
   and live database execution across multiple profiles and scopes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yarvelle_core.db.base import Base
import yarvelle_core.db.models  # noqa: F401
from yarvelle_core.db.schema_catalog import SYSTEM_DENYLIST_TABLES
from yarvelle_core.db.session import create_db_engine
from yarvelle_core.scope.context import ScopeContext
from yarvelle_core.tools.mcp_db_toolbox import McpDatabaseToolbox
from yarvelle_core.tools.sql_ast_sandbox import (
    SqlSecurityError,
    SqlValidationError,
    validate_and_rewrite_sql,
)

AUTH_PROFILE_ID = "da08ab02-df24-4a9f-96d8-e1f2cac369c9"
VICTIM_PROFILE_ID = "victim-profile-uuid-9999-000000000000"
HEALTH_SCOPE = "health"
FINANCIAL_SCOPE = "financial"


@pytest.fixture
def auth_scope_ctx() -> ScopeContext:
    return ScopeContext(
        profile_id=AUTH_PROFILE_ID,
        scope=HEALTH_SCOPE,
        granted_scopes=(HEALTH_SCOPE, f"{HEALTH_SCOPE}.*"),
    )


class TestDdlRejectionAdversarial:
    """Challenge 1: Adversarial DDL and Administrative Statement Rejection."""

    @pytest.mark.parametrize(
        "ddl_statement",
        [
            # Direct DDL
            "DROP TABLE notes",
            "DROP TABLE notes;",
            "drop table notes",
            "DrOp TaBlE notes",
            "ALTER TABLE notes ADD COLUMN leaked TEXT",
            "CREATE TABLE evil (id INT PRIMARY KEY)",
            "TRUNCATE TABLE notes",
            "TRUNCATE notes",
            "RENAME TABLE notes TO old_notes",
            "DROP INDEX ix_notes_slug",
            "CREATE INDEX evil_idx ON notes(slug)",
            "CREATE VIEW evil_view AS SELECT * FROM notes",
            # Database control commands
            "ATTACH DATABASE '/tmp/pwn.db' AS pwn",
            "DETACH DATABASE pwn",
            "PRAGMA table_info(notes)",
            "VACUUM",
            "ANALYZE",
            "REINDEX",
            # Comment and whitespace obfuscation
            "/* harmless comment */ DROP TABLE notes",
            "-- line comment\nDROP TABLE notes",
            "   \n\t  DROP TABLE notes;",
            "/* multi\nline\ncomment */ CREATE TABLE evil (x INT)",
            # Stacked DDL
            "SELECT * FROM notes; DROP TABLE notes;",
            "SELECT * FROM notes; ALTER TABLE notes DROP COLUMN title;",
            "SELECT * FROM notes; TRUNCATE TABLE notes;",
            "SELECT * FROM notes; RENAME TABLE notes TO leaked;",
            "SELECT * FROM notes; CREATE TABLE evil (id INT);",
        ],
    )
    def test_blocks_all_ddl_variations(
        self, ddl_statement: str, auth_scope_ctx: ScopeContext
    ) -> None:
        with pytest.raises((SqlSecurityError, SqlValidationError)):
            validate_and_rewrite_sql(ddl_statement, scope_ctx=auth_scope_ctx)


class TestSystemTableProtectionAdversarial:
    """Challenge 2: System and Vault Table Protection."""

    @pytest.mark.parametrize(
        "system_table",
        sorted(SYSTEM_DENYLIST_TABLES) + [
            "sqlite_master",
            "sqlite_schema",
            "sqlite_temp_master",
            "sqlite_temp_schema",
            "sqlite_sequence",
            "information_schema.tables",
        ],
    )
    def test_blocks_direct_select_on_denylisted_system_tables(
        self, system_table: str, auth_scope_ctx: ScopeContext
    ) -> None:
        query = f"SELECT * FROM {system_table}"
        with pytest.raises((SqlSecurityError, SqlValidationError)):
            validate_and_rewrite_sql(query, scope_ctx=auth_scope_ctx)

    @pytest.mark.parametrize(
        "quoted_table",
        [
            '"users"',
            "`users`",
            "[users]",
            "main.users",
            "public.users",
        ],
    )
    def test_blocks_quoted_and_schema_qualified_system_tables(
        self, quoted_table: str, auth_scope_ctx: ScopeContext
    ) -> None:
        query = f"SELECT * FROM {quoted_table}"
        with pytest.raises((SqlSecurityError, SqlValidationError)):
            validate_and_rewrite_sql(query, scope_ctx=auth_scope_ctx)

    @pytest.mark.parametrize(
        "subquery_or_join",
        [
            # Scalar subquery
            "SELECT (SELECT email FROM users LIMIT 1) FROM notes",
            # FROM subquery
            "SELECT * FROM (SELECT * FROM users) u",
            # WHERE IN subquery
            "SELECT * FROM notes WHERE id IN (SELECT id FROM users)",
            # WHERE EXISTS subqueries
            "SELECT * FROM notes WHERE EXISTS (SELECT 1 FROM credentials)",
            "SELECT * FROM notes WHERE EXISTS (SELECT 1 FROM profile_keys)",
            "SELECT * FROM notes WHERE EXISTS (SELECT 1 FROM audit_events)",
            "SELECT * FROM notes WHERE EXISTS (SELECT 1 FROM sessions)",
            "SELECT * FROM notes WHERE EXISTS (SELECT 1 FROM password_resets)",
            "SELECT * FROM notes WHERE EXISTS (SELECT 1 FROM sqlite_master)",
            # JOINs
            "SELECT * FROM notes JOIN users ON 1=1",
            "SELECT * FROM notes LEFT JOIN credentials ON 1=1",
            "SELECT * FROM notes INNER JOIN profile_keys ON 1=1",
            "SELECT * FROM notes CROSS JOIN audit_events",
            # CTEs
            "WITH u AS (SELECT * FROM users) SELECT * FROM u",
            "WITH secret AS (SELECT * FROM credentials) SELECT * FROM notes JOIN secret ON 1=1",
            "WITH sm AS (SELECT * FROM sqlite_master) SELECT * FROM sm",
            # UNION in subquery
            "SELECT * FROM (SELECT id FROM notes UNION SELECT id FROM users) u",
        ],
    )
    def test_blocks_system_tables_in_subqueries_joins_and_ctes(
        self, subquery_or_join: str, auth_scope_ctx: ScopeContext
    ) -> None:
        with pytest.raises((SqlSecurityError, SqlValidationError)):
            validate_and_rewrite_sql(subquery_or_join, scope_ctx=auth_scope_ctx)


class TestTenantAndScopeIsolationAdversarial:
    """Challenge 3: Tenant & Scope Isolation Against Injections."""

    @pytest.mark.parametrize(
        ("injection_sql", "params"),
        [
            ("SELECT id, title FROM notes WHERE 1=1", {}),
            ("SELECT id, title FROM notes WHERE TRUE", {}),
            ("SELECT id, title FROM notes WHERE profile_id IS NOT NULL", {}),
            (
                f"SELECT id, title FROM notes WHERE notes.profile_id != '{AUTH_PROFILE_ID}'",
                {},
            ),
            ("SELECT id, title FROM notes WHERE profile_id = 'other-profile' OR 1=1", {}),
            ("SELECT id, title FROM notes WHERE 1=0 OR 1=1", {}),
            ("SELECT id, title FROM notes WHERE 'a' = 'a'", {}),
            ("SELECT id, title FROM notes WHERE (profile_id = 'other' OR 1=1)", {}),
            ("SELECT id, title FROM notes WHERE /* evil comment */ 1=1", {}),
            ("SELECT id, title FROM notes -- comment\nWHERE 1=1", {}),
            ("SELECT id, title FROM notes WHERE title = :title /* comment */", {"title": "cardio"}),
            (
                "SELECT id, title FROM notes WHERE profile_id = :other_prof OR 1=1",
                {"other_prof": "victim-id"},
            ),
        ],
    )
    def test_tenant_and_scope_predicates_injected_into_where(
        self, injection_sql: str, params: dict, auth_scope_ctx: ScopeContext
    ) -> None:
        plan = validate_and_rewrite_sql(injection_sql, params, scope_ctx=auth_scope_ctx)
        assert ":__ctx_profile_id" in plan.rewritten_sql
        assert ":__ctx_scope" in plan.rewritten_sql
        assert plan.bound_params["__ctx_profile_id"] == AUTH_PROFILE_ID
        assert plan.bound_params["__ctx_scope"] == HEALTH_SCOPE
        assert "LIMIT" in plan.rewritten_sql

    def test_blocks_stacked_select_statements(
        self, auth_scope_ctx: ScopeContext
    ) -> None:
        with pytest.raises(SqlSecurityError):
            validate_and_rewrite_sql(
                "SELECT id FROM notes; SELECT id FROM notes;",
                scope_ctx=auth_scope_ctx,
            )

    def test_blocks_top_level_union_statement(
        self, auth_scope_ctx: ScopeContext
    ) -> None:
        with pytest.raises(SqlSecurityError):
            validate_and_rewrite_sql(
                "SELECT id, title FROM notes UNION SELECT id, title FROM notes",
                scope_ctx=auth_scope_ctx,
            )

    def test_subquery_union_rewrites_both_branches(
        self, auth_scope_ctx: ScopeContext
    ) -> None:
        plan = validate_and_rewrite_sql(
            "SELECT * FROM (SELECT id FROM notes UNION SELECT id FROM notes) u",
            scope_ctx=auth_scope_ctx,
        )
        assert plan.rewritten_sql.count(":__ctx_profile_id") == 2
        assert plan.rewritten_sql.count(":__ctx_scope") == 2

    def test_multi_table_join_injects_predicates_on_both_tables(
        self, auth_scope_ctx: ScopeContext
    ) -> None:
        plan = validate_and_rewrite_sql(
            "SELECT n.id, n.title, r.id FROM notes n JOIN reminders r ON n.profile_id = r.profile_id",
            scope_ctx=auth_scope_ctx,
        )
        assert "n.profile_id = :__ctx_profile_id" in plan.rewritten_sql
        assert "n.scope = :__ctx_scope" in plan.rewritten_sql
        assert "r.profile_id = :__ctx_profile_id" in plan.rewritten_sql
        assert "r.scope = :__ctx_scope" in plan.rewritten_sql

    def test_subquery_in_where_injects_predicates_on_both_levels(
        self, auth_scope_ctx: ScopeContext
    ) -> None:
        plan = validate_and_rewrite_sql(
            "SELECT id, title FROM notes WHERE id IN (SELECT id FROM notes WHERE title = :title)",
            {"title": "cardio"},
            scope_ctx=auth_scope_ctx,
        )
        assert plan.rewritten_sql.count(":__ctx_profile_id") == 2
        assert plan.rewritten_sql.count(":__ctx_scope") == 2

    @pytest.mark.parametrize("immutable_col", ["profile_id", "scope", "id", "user_id", "created_at"])
    def test_blocks_update_to_immutable_columns(
        self, immutable_col: str, auth_scope_ctx: ScopeContext
    ) -> None:
        with pytest.raises(SqlSecurityError):
            validate_and_rewrite_sql(
                f"UPDATE notes SET {immutable_col} = :val WHERE slug = :slug",
                {"val": "attacker", "slug": "test"},
                scope_ctx=auth_scope_ctx,
            )

    @pytest.mark.parametrize(
        "tautology_stmt",
        [
            "UPDATE notes SET title = :val",
            "UPDATE notes SET title = :val WHERE 1=1",
            "UPDATE notes SET title = :val WHERE 'a' = 'a'",
            "DELETE FROM notes",
            "DELETE FROM notes WHERE 1=1",
            "DELETE FROM notes WHERE 'a' = 'a'",
        ],
    )
    def test_blocks_tautological_and_unfiltered_mutations(
        self, tautology_stmt: str, auth_scope_ctx: ScopeContext
    ) -> None:
        with pytest.raises(SqlSecurityError):
            validate_and_rewrite_sql(
                tautology_stmt,
                {"val": "pwned"},
                scope_ctx=auth_scope_ctx,
            )


class TestLiveDatabaseIsolationEmpirical:
    """Challenge 4: Empirical SQLite Database Execution & Zero Row Leakage."""

    async def test_live_sqlite_tenant_and_scope_isolation_under_attack(
        self, tmp_path
    ) -> None:
        db_file = tmp_path / "test_challenge_ast.db"
        engine = create_db_engine(f"sqlite+aiosqlite:///{db_file}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        toolbox = McpDatabaseToolbox()

        ctx_auth = ScopeContext(
            profile_id=AUTH_PROFILE_ID,
            scope=HEALTH_SCOPE,
            granted_scopes=(HEALTH_SCOPE, f"{HEALTH_SCOPE}.*"),
        )
        ctx_victim = ScopeContext(
            profile_id=VICTIM_PROFILE_ID,
            scope=HEALTH_SCOPE,
            granted_scopes=(HEALTH_SCOPE, f"{HEALTH_SCOPE}.*"),
        )
        ctx_financial = ScopeContext(
            profile_id=AUTH_PROFILE_ID,
            scope=FINANCIAL_SCOPE,
            granted_scopes=(FINANCIAL_SCOPE, f"{FINANCIAL_SCOPE}.*"),
        )

        async with maker() as session:
            # Seed 3 notes across different profile/scope combinations
            await toolbox.execute(
                "upsert_workspace_note",
                {
                    "slug": "auth-health-note",
                    "title": "Auth User Health Note",
                    "content": "Secret health data for auth user",
                    "type": "prep",
                },
                profile_id=AUTH_PROFILE_ID,
                scope=HEALTH_SCOPE,
                session=session,
            )
            await toolbox.execute(
                "upsert_workspace_note",
                {
                    "slug": "victim-health-note",
                    "title": "Victim User Health Note",
                    "content": "Confidential medical history for victim",
                    "type": "prep",
                },
                profile_id=VICTIM_PROFILE_ID,
                scope=HEALTH_SCOPE,
                session=session,
            )
            await toolbox.execute(
                "upsert_workspace_note",
                {
                    "slug": "auth-financial-note",
                    "title": "Auth User Financial Note",
                    "content": "Bank accounts and invoices",
                    "type": "prep",
                },
                profile_id=AUTH_PROFILE_ID,
                scope=FINANCIAL_SCOPE,
                session=session,
            )

            # Attack 1: Injected OR 1=1 query from Auth user must return ONLY Auth user's health note
            res_attack1 = await toolbox.execute_dynamic_query(
                statement=f"SELECT title, content, profile_id, scope FROM notes WHERE profile_id = '{VICTIM_PROFILE_ID}' OR 1=1",
                profile_id=AUTH_PROFILE_ID,
                scope_ctx=ctx_auth,
                session=session,
            )
            assert res_attack1["status"] == "ok"
            assert res_attack1["count"] == 1
            assert res_attack1["records"][0]["profile_id"] == AUTH_PROFILE_ID
            assert res_attack1["records"][0]["scope"] == HEALTH_SCOPE
            assert res_attack1["records"][0]["title"] == "Auth User Health Note"

            # Attack 2: Querying as victim profile must see ONLY victim's note
            res_victim = await toolbox.execute_dynamic_query(
                statement="SELECT title, content, profile_id, scope FROM notes WHERE 1=1",
                profile_id=VICTIM_PROFILE_ID,
                scope_ctx=ctx_victim,
                session=session,
            )
            assert res_victim["status"] == "ok"
            assert res_victim["count"] == 1
            assert res_victim["records"][0]["profile_id"] == VICTIM_PROFILE_ID
            assert res_victim["records"][0]["title"] == "Victim User Health Note"

            # Attack 3: Querying under financial scope must see ONLY financial note
            res_scope = await toolbox.execute_dynamic_query(
                statement="SELECT title, content, profile_id, scope FROM notes WHERE 1=1",
                profile_id=AUTH_PROFILE_ID,
                scope_ctx=ctx_financial,
                session=session,
            )
            assert res_scope["status"] == "ok"
            assert res_scope["count"] == 1
            assert res_scope["records"][0]["scope"] == FINANCIAL_SCOPE
            assert res_scope["records"][0]["title"] == "Auth User Financial Note"

            # Attack 4: DDL attempt through toolbox must fail closed and leave tables intact
            with pytest.raises(SqlSecurityError):
                await toolbox.execute_dynamic_query(
                    statement="DROP TABLE notes",
                    profile_id=AUTH_PROFILE_ID,
                    scope_ctx=ctx_auth,
                    session=session,
                )

            # Check that table still exists and still has 3 records
            raw_check = await session.execute(text("SELECT count(*) FROM notes"))
            assert raw_check.scalar() == 3

            # Attack 5: System table query through toolbox must fail closed
            with pytest.raises(SqlSecurityError):
                await toolbox.execute_dynamic_query(
                    statement="SELECT * FROM users",
                    profile_id=AUTH_PROFILE_ID,
                    scope_ctx=ctx_auth,
                    session=session,
                )

        await engine.dispose()
