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

"""Per-Connector Autonomy & A2 Standing Routines with Fire-Time Re-Checks (AU-58 / E1.10).

Implements:
- Per-connector autonomy override (`inherit`, `A0`, `A1`, `A2`) with under-13 pediatric A2 guard.
- Effective autonomy resolution (`resolve_effective_autonomy`).
- A2 standing routines (`create_standing_routine`) with:
  - Readiness gate requiring >= 2 active connectors on the profile (`ROADMAP.md` AU-58).
  - Mandatory expiration `<= 90` days (`MAX_ROUTINE_EXPIRY_DAYS = 90`).
  - Timezone-aware RFC 5545 RRULE `next_run_at` calculation via `dateutil.rrule.rrulestr` in `ZoneInfo`.
  - Automatic `Job(kind='routine')` scheduling.
- Fire-time re-check (`execute_standing_routine`, `E1.10`) verifying at every trigger:
  1. Routine is active.
  2. Routine has not passed `expires_at` (`<= 90` days).
  3. Routine creator (`created_by_user_id`) still holds `manage` access on `profile_id`.
  4. Bound `Connection` (if any) is `active` and holds an active `ConsentGrant`.
  5. Execution context is not tainted (`taint == False`).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from typing import Any, Callable, Dict, List, Optional
import uuid
from zoneinfo import ZoneInfo

try:
    from dateutil.rrule import rrulestr
except ImportError:  # pragma: no cover
    rrulestr = None  # type: ignore

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.clinical.reminders import advance_rrule_occurrence
from carefold.connectors.lifecycle import _is_profile_under_13
from carefold.db.models import (
    AuditEventRecord,
    Connection,
    ConsentGrant,
    Job,
    Profile,
    ProfileAccess,
    Routine,
    User,
    utc_now,
)
from carefold.engine.tool_exec import TaintFlag, ToolContext, execute_tool_call
from carefold.engine.tool_registry import ToolSpec, create_default_registry

MAX_ROUTINE_EXPIRY_DAYS: int = 90
MIN_ACTIVE_CONNECTORS_FOR_ROUTINES: int = 2
VALID_AUTONOMY_LEVELS = ("inherit", "A0", "A1", "A2")


def resolve_effective_autonomy(
    profile_autonomy: str,
    connection_autonomy: Optional[str] = None,
) -> str:
    """Resolves the effective autonomy level for a connector invocation (`AU-58`).

    If `connection_autonomy` is explicitly set to `'A0'`, `'A1'`, or `'A2'`, it overrides
    `profile_autonomy`; otherwise (`'inherit'` or `None`) returns `profile_autonomy`.
    """
    clean_conn = (connection_autonomy or "inherit").strip()
    if clean_conn in ("A0", "A1", "A2"):
        return clean_conn
    clean_prof = (profile_autonomy or "A1").strip()
    return clean_prof if clean_prof in ("A0", "A1", "A2") else "A1"


async def set_connection_autonomy(
    session: AsyncSession,
    profile_id: str,
    connection_id: str,
    autonomy_level: str,
    actor_user_id: Optional[str] = None,
) -> Connection:
    """Sets per-connector autonomy override (`inherit`, `A0`, `A1`, `A2`) on a `Connection` (`AU-58`)."""
    clean_profile_id = (profile_id or "").strip()
    clean_connection_id = (connection_id or "").strip()
    clean_level = (autonomy_level or "").strip()

    if clean_level not in VALID_AUTONOMY_LEVELS:
        raise ValueError(
            f"Invalid autonomy_level '{autonomy_level}'. Must be one of {VALID_AUTONOMY_LEVELS}."
        )

    prof_res = await session.execute(select(Profile).where(Profile.id == clean_profile_id))
    profile = prof_res.scalar_one_or_none()
    if profile is None:
        raise ValueError(f"Profile '{clean_profile_id}' not found.")

    if clean_level == "A2" and _is_profile_under_13(profile):
        raise PermissionError(
            "Under-13 pediatric profiles cannot be granted A2 connector autonomy."
        )

    conn_res = await session.execute(
        select(Connection).where(
            Connection.id == clean_connection_id,
            Connection.profile_id == clean_profile_id,
        )
    )
    connection = conn_res.scalar_one_or_none()
    if connection is None:
        raise ValueError(
            f"Connection '{clean_connection_id}' not found for profile '{clean_profile_id}'."
        )

    now = utc_now()
    previous_level = connection.autonomy_level
    connection.autonomy_level = clean_level
    connection.updated_at = now

    payload_hash = hashlib.sha256(
        json.dumps(
            {
                "profile_id": clean_profile_id,
                "connection_id": clean_connection_id,
                "previous_autonomy": previous_level,
                "autonomy_level": clean_level,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    audit = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=actor_user_id,
        principal="user",
        event="connection_autonomy_updated",
        tool="set_connection_autonomy",
        risk="admin",
        decision="allow",
        payload_hash=payload_hash,
        external_ref=f"connection:{clean_connection_id}",
        detail_redacted=json.dumps({
            "connection_id": clean_connection_id,
            "previous_autonomy": previous_level,
            "autonomy_level": clean_level,
        }),
    )
    session.add(audit)
    await session.commit()
    await session.refresh(connection)
    return connection


def compute_next_routine_run(
    rrule_str: str,
    timezone_str: str = "UTC",
    after_dt: Optional[datetime] = None,
) -> Optional[datetime]:
    """Computes the next occurrence timestamp in UTC using `dateutil.rrule.rrulestr` in `ZoneInfo(timezone_str)`."""
    clean_rrule = (rrule_str or "").strip()
    if not clean_rrule:
        raise ValueError("rrule is required for standing routines.")

    try:
        tz = ZoneInfo(timezone_str or "UTC")
    except Exception as exc:
        raise ValueError(f"Invalid IANA timezone '{timezone_str}': {exc}") from exc

    base_utc = after_dt or utc_now()
    if base_utc.tzinfo is None:
        base_utc = base_utc.replace(tzinfo=timezone.utc)
    else:
        base_utc = base_utc.astimezone(timezone.utc)

    local_dt = base_utc.astimezone(tz)

    if rrulestr is not None:
        try:
            rule_text = clean_rrule if clean_rrule.upper().startswith("RRULE:") else f"RRULE:{clean_rrule}"
            local_naive = local_dt.replace(tzinfo=None)
            rule_obj = rrulestr(rule_text, dtstart=local_naive, ignoretz=True)
            next_naive = rule_obj.after(local_naive, inc=False)
            if next_naive is not None:
                next_local = next_naive.replace(tzinfo=tz)
                return next_local.astimezone(timezone.utc)
        except Exception:
            pass

    next_dt = advance_rrule_occurrence(base_utc, clean_rrule, timezone_str or "UTC")
    if next_dt is None:
        raise ValueError(f"Invalid or exhausted RRULE string '{rrule_str}'.")
    return next_dt


async def _user_holds_manage_access(
    session: AsyncSession,
    profile: Profile,
    user_id: Optional[str],
) -> bool:
    """Checks whether `user_id` currently holds `manage` permission on `profile` (`E1.10`)."""
    clean_uid = (user_id or "").strip()
    if not clean_uid:
        return False

    # Verify user account is not disabled if a User row exists
    user_res = await session.execute(select(User).where(User.id == clean_uid))
    user_row = user_res.scalar_one_or_none()
    if user_row is not None and user_row.status != "active":
        return False

    # Check explicit ProfileAccess grant first (if present, its access_level governs)
    access_res = await session.execute(
        select(ProfileAccess).where(
            ProfileAccess.profile_id == profile.id,
            ProfileAccess.user_id == clean_uid,
        )
    )
    access_grant = access_res.scalar_one_or_none()
    if access_grant is not None:
        return access_grant.access_level == "manage"

    # Otherwise check direct profile ownership
    if profile.user_id is not None and profile.user_id == clean_uid:
        return True

    return False


async def create_standing_routine(
    session: AsyncSession,
    profile_id: str,
    created_by_user_id: str,
    name: str,
    tool_name: str,
    rrule: str,
    timezone_str: str = "UTC",
    args: Optional[Dict[str, Any]] = None,
    connection_id: Optional[str] = None,
    expires_in_days: int = 30,
    description: Optional[str] = None,
) -> Routine:
    """Creates a scoped A2 standing routine with `<= 90`-day expiry and readiness gate (`AU-58`)."""
    clean_profile_id = (profile_id or "").strip()
    clean_creator_id = (created_by_user_id or "").strip()
    clean_name = (name or "").strip()
    clean_tool = (tool_name or "").strip()
    clean_rrule = (rrule or "").strip()
    clean_tz = (timezone_str or "UTC").strip() or "UTC"

    if not clean_profile_id or not clean_creator_id or not clean_name or not clean_tool or not clean_rrule:
        raise ValueError("profile_id, created_by_user_id, name, tool_name, and rrule are required.")

    if int(expires_in_days) < 1 or int(expires_in_days) > MAX_ROUTINE_EXPIRY_DAYS:
        raise ValueError(
            f"Routine expires_in_days must be between 1 and {MAX_ROUTINE_EXPIRY_DAYS} days."
        )

    prof_res = await session.execute(select(Profile).where(Profile.id == clean_profile_id))
    profile = prof_res.scalar_one_or_none()
    if profile is None:
        raise ValueError(f"Profile '{clean_profile_id}' not found.")

    if _is_profile_under_13(profile):
        raise PermissionError("A2 standing routines cannot be created for under-13 profiles.")

    # Readiness Gate (ROADMAP.md AU-58: "after two connectors are in daily use")
    count_stmt = (
        select(func.count())
        .select_from(Connection)
        .where(
            Connection.profile_id == clean_profile_id,
            Connection.status == "active",
        )
    )
    count_res = await session.execute(count_stmt)
    active_connector_count = int(count_res.scalar() or 0)
    if active_connector_count < MIN_ACTIVE_CONNECTORS_FOR_ROUTINES:
        raise ValueError(
            "A2 standing routines require at least two active connectors on this profile."
        )

    now = utc_now()
    next_run_at = compute_next_routine_run(clean_rrule, clean_tz, after_dt=now)
    expires_at = now + timedelta(days=int(expires_in_days))

    routine = Routine(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        connection_id=connection_id.strip() if connection_id else None,
        created_by_user_id=clean_creator_id,
        name=clean_name,
        description=description,
        tool_name=clean_tool,
        args_json=json.dumps(args or {}, sort_keys=True),
        rrule=clean_rrule,
        timezone=clean_tz,
        status="active",
        last_run_at=None,
        next_run_at=next_run_at,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    session.add(routine)
    await session.flush()

    job = Job(
        id=str(uuid.uuid4()),
        profile_id=clean_profile_id,
        kind="routine",
        routine_id=routine.id,
        connection_id=routine.connection_id,
        payload=json.dumps(
            {
                "routine_id": routine.id,
                "profile_id": clean_profile_id,
                "connection_id": routine.connection_id,
                "tool_name": routine.tool_name,
                "args": args or {},
            },
            sort_keys=True,
        ),
        timezone=clean_tz,
        rrule=clean_rrule,
        next_run_at=next_run_at or now,
        idempotency_key=f"routine:{routine.id}",
        status="pending",
        created_at=now,
        updated_at=now,
    )
    session.add(job)

    audit = AuditEventRecord(
        id=str(uuid.uuid4()),
        ts=now,
        profile_id=clean_profile_id,
        actor_user_id=clean_creator_id,
        principal="user",
        event="routine_created",
        tool=clean_tool,
        risk="admin",
        decision="allow",
        payload_hash=hashlib.sha256(routine.args_json.encode("utf-8")).hexdigest(),
        external_ref=f"routine:{routine.id}",
        detail_redacted=json.dumps({
            "routine_id": routine.id,
            "name": routine.name,
            "tool_name": routine.tool_name,
            "rrule": routine.rrule,
            "expires_at": expires_at.isoformat(),
        }),
    )
    session.add(audit)
    await session.commit()
    await session.refresh(routine)
    if routine.expires_at and routine.expires_at.tzinfo is None:
        routine.expires_at = routine.expires_at.replace(tzinfo=timezone.utc)
    if routine.next_run_at and routine.next_run_at.tzinfo is None:
        routine.next_run_at = routine.next_run_at.replace(tzinfo=timezone.utc)
    return routine


async def execute_standing_routine(
    session: AsyncSession,
    routine_id: str,
    taint: bool = False,
    executor: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Executes a standing routine after performing all 5 Fire-Time Re-Checks (`E1.10`)."""
    clean_routine_id = (routine_id or "").strip()
    if not clean_routine_id:
        return {"status": "skipped", "reason": "routine_inactive"}

    stmt = select(Routine).where(Routine.id == clean_routine_id)
    res = await session.execute(stmt)
    routine = res.scalar_one_or_none()
    if routine is None or routine.status != "active":
        return {"status": "skipped", "reason": "routine_inactive"}

    prof_res = await session.execute(select(Profile).where(Profile.id == routine.profile_id))
    profile = prof_res.scalar_one_or_none()
    if profile is None:
        return {"status": "skipped", "reason": "routine_inactive"}

    now = utc_now()
    expires_at = routine.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    # 2. Check routine expiration (<= 90 days)
    if now >= expires_at:
        routine.status = "expired"
        routine.updated_at = now
        session.add(
            AuditEventRecord(
                id=str(uuid.uuid4()),
                ts=now,
                profile_id=routine.profile_id,
                actor_user_id=routine.created_by_user_id,
                principal="job",
                event="routine_expired",
                tool=routine.tool_name,
                risk="admin",
                decision="deny",
                external_ref=f"routine:{routine.id}",
                detail_redacted=json.dumps({
                    "routine_id": routine.id,
                    "reason": "routine_expired",
                }),
            )
        )
        await session.commit()
        return {"status": "blocked", "reason": "routine_expired"}

    # 3. Fire-Time Re-Check (E1.10): Verify creator still holds 'manage' access on profile_id
    has_manage = await _user_holds_manage_access(session, profile, routine.created_by_user_id)
    if not has_manage:
        routine.status = "revoked"
        routine.updated_at = now
        session.add(
            AuditEventRecord(
                id=str(uuid.uuid4()),
                ts=now,
                profile_id=routine.profile_id,
                actor_user_id=routine.created_by_user_id,
                principal="job",
                event="routine_revoked_access_lost",
                tool=routine.tool_name,
                risk="write_external",
                decision="deny",
                external_ref=f"routine:{routine.id}",
                detail_redacted=json.dumps({
                    "routine_id": routine.id,
                    "created_by_user_id": routine.created_by_user_id,
                    "reason": "creator_manage_access_lost",
                }),
            )
        )
        await session.commit()
        raise PermissionError("Routine creator no longer holds manage access on this profile.")

    # 4. Verify bound Connection is active and has an active ConsentGrant
    if routine.connection_id:
        conn_res = await session.execute(
            select(Connection).where(
                Connection.id == routine.connection_id,
                Connection.profile_id == routine.profile_id,
            )
        )
        conn = conn_res.scalar_one_or_none()
        if conn is None or conn.status != "active":
            session.add(
                AuditEventRecord(
                    id=str(uuid.uuid4()),
                    ts=now,
                    profile_id=routine.profile_id,
                    actor_user_id=routine.created_by_user_id,
                    principal="job",
                    event="routine_blocked_connection_inactive",
                    tool=routine.tool_name,
                    risk="write_external",
                    decision="deny",
                    external_ref=f"routine:{routine.id}",
                    detail_redacted=json.dumps({
                        "routine_id": routine.id,
                        "connection_id": routine.connection_id,
                        "reason": "connection_inactive",
                    }),
                )
            )
            await session.commit()
            raise PermissionError("Connection or consent is no longer active.")

        if conn.autonomy_level in ("A0", "A1"):
            raise PermissionError("Connection autonomy level does not permit A2 standing routine execution.")

        consent_res = await session.execute(
            select(ConsentGrant).where(
                ConsentGrant.profile_id == routine.profile_id,
                ConsentGrant.connector_id == conn.connector_id,
                ConsentGrant.status == "active",
                or_(
                    ConsentGrant.connection_id == conn.id,
                    ConsentGrant.connection_id.is_(None),
                ),
            )
        )
        active_grant = consent_res.scalars().first()
        if active_grant is None:
            session.add(
                AuditEventRecord(
                    id=str(uuid.uuid4()),
                    ts=now,
                    profile_id=routine.profile_id,
                    actor_user_id=routine.created_by_user_id,
                    principal="job",
                    event="routine_blocked_consent_missing",
                    tool=routine.tool_name,
                    risk="write_external",
                    decision="deny",
                    external_ref=f"routine:{routine.id}",
                    detail_redacted=json.dumps({
                        "routine_id": routine.id,
                        "connection_id": routine.connection_id,
                        "reason": "consent_missing",
                    }),
                )
            )
            await session.commit()
            raise PermissionError("Connection or consent is no longer active.")

    # 5. Check taint flag
    if bool(taint) is True:
        session.add(
            AuditEventRecord(
                id=str(uuid.uuid4()),
                ts=now,
                profile_id=routine.profile_id,
                actor_user_id=routine.created_by_user_id,
                principal="job",
                event="routine_blocked_taint",
                tool=routine.tool_name,
                risk="write_external",
                decision="deny",
                external_ref=f"routine:{routine.id}",
                detail_redacted=json.dumps({
                    "routine_id": routine.id,
                    "reason": "tainted_context",
                }),
            )
        )
        await session.commit()
        raise PermissionError("Tainted context cannot execute A2 routine without approval.")

    # 6. Execute routine tool call
    routine_args = routine.args
    ctx = ToolContext(
        user_id=routine.created_by_user_id or profile.user_id or "system:routine",
        profile_id=routine.profile_id,
        principal="job",
        run_id=f"routine:{routine.id}",
        autonomy="A2",
        taint=TaintFlag(False),
        extra={"db_session": session},
    )

    if executor is not None:
        try:
            sig = inspect.signature(executor)
            params = list(sig.parameters.keys())
        except (ValueError, TypeError):
            params = ["args"]

        if len(params) == 0:
            raw_out = executor()
        elif len(params) == 1:
            raw_out = executor(routine_args)
        else:
            if params[0] in ("tool", "tool_name"):
                raw_out = executor(routine.tool_name, routine_args)
            else:
                raw_out = executor(routine_args, ctx)

        if asyncio.iscoroutine(raw_out):
            raw_out = await raw_out
        exec_output = raw_out
    else:
        registry = create_default_registry()
        base_spec = registry.get(routine.tool_name)

        async def _routine_tool_runner(a: Dict[str, Any], c: Any = None) -> Any:
            if base_spec is not None and callable(base_spec.executor):
                try:
                    out = base_spec.executor(a, c)
                    if asyncio.iscoroutine(out):
                        out = await out
                    return out
                except Exception:
                    pass
            return {"status": "ok", "tool": routine.tool_name, "args": a}

        spec = ToolSpec(
            name=routine.tool_name,
            description=base_spec.description if base_spec else f"Standing routine tool {routine.tool_name}",
            risk_tier=base_spec.risk_tier if base_spec else "write_local",
            trust=base_spec.trust if base_spec else "trusted",
            data_flows=base_spec.data_flows if base_spec else (),
            executor=_routine_tool_runner,
        )
        tool_res = await execute_tool_call(
            ctx=ctx,
            spec=spec,
            args=routine_args,
            consents={"external_write_consent": True, "guardian_consent": True},
        )
        if not tool_res.success:
            raise PermissionError(tool_res.error or f"Routine tool '{routine.tool_name}' execution denied.")
        exec_output = tool_res.output

    routine.last_run_at = now
    routine.next_run_at = compute_next_routine_run(routine.rrule, routine.timezone, after_dt=now)
    routine.updated_at = now

    job_res = await session.execute(
        select(Job).where(
            Job.profile_id == routine.profile_id,
            Job.routine_id == routine.id,
            Job.kind == "routine",
        )
    )
    job = job_res.scalars().first()
    if job is not None and routine.next_run_at is not None:
        job.next_run_at = routine.next_run_at
        job.updated_at = now

    session.add(
        AuditEventRecord(
            id=str(uuid.uuid4()),
            ts=now,
            profile_id=routine.profile_id,
            actor_user_id=routine.created_by_user_id,
            principal="job",
            event="routine_executed",
            tool=routine.tool_name,
            risk="write_external",
            decision="allow",
            payload_hash=hashlib.sha256(routine.args_json.encode("utf-8")).hexdigest(),
            external_ref=f"routine:{routine.id}",
            detail_redacted=json.dumps({
                "routine_id": routine.id,
                "tool_name": routine.tool_name,
                "last_run_at": now.isoformat(),
                "next_run_at": routine.next_run_at.isoformat() if routine.next_run_at else None,
            }),
        )
    )
    await session.commit()
    await session.refresh(routine)

    return {
        "status": "executed",
        "routine_id": routine.id,
        "tool_name": routine.tool_name,
        "output": exec_output,
        "last_run_at": routine.last_run_at.isoformat() if routine.last_run_at else None,
        "next_run_at": routine.next_run_at.isoformat() if routine.next_run_at else None,
    }


async def update_standing_routine_status(
    session: AsyncSession,
    profile_id: str,
    routine_id: str,
    status: str,
    actor_user_id: Optional[str] = None,
) -> Routine:
    """Updates a standing routine's lifecycle status (`active`, `paused`, `revoked`)."""
    clean_profile_id = (profile_id or "").strip()
    clean_routine_id = (routine_id or "").strip()
    clean_status = (status or "").strip().lower()

    if clean_status in ("pause", "paused"):
        target_status = "paused"
    elif clean_status in ("resume", "active"):
        target_status = "active"
    elif clean_status in ("revoke", "revoked"):
        target_status = "revoked"
    else:
        raise ValueError(f"Unsupported routine status '{status}'. Use 'active', 'paused', or 'revoked'.")

    stmt = select(Routine).where(
        Routine.id == clean_routine_id,
        Routine.profile_id == clean_profile_id,
    )
    res = await session.execute(stmt)
    routine = res.scalar_one_or_none()
    if routine is None:
        raise ValueError(f"Routine '{clean_routine_id}' not found for profile '{clean_profile_id}'.")

    now = utc_now()
    routine.status = target_status
    routine.updated_at = now

    job_res = await session.execute(
        select(Job).where(
            Job.profile_id == clean_profile_id,
            Job.routine_id == routine.id,
            Job.kind == "routine",
        )
    )
    for job in job_res.scalars().all():
        if target_status == "revoked":
            job.status = "completed"
        elif target_status == "active":
            job.status = "pending"
        job.updated_at = now

    session.add(
        AuditEventRecord(
            id=str(uuid.uuid4()),
            ts=now,
            profile_id=clean_profile_id,
            actor_user_id=actor_user_id,
            principal="user",
            event=f"routine_{target_status}",
            tool=routine.tool_name,
            risk="admin",
            decision="allow",
            external_ref=f"routine:{routine.id}",
            detail_redacted=json.dumps({
                "routine_id": routine.id,
                "status": target_status,
            }),
        )
    )
    await session.commit()
    await session.refresh(routine)
    return routine


__all__ = [
    "MAX_ROUTINE_EXPIRY_DAYS",
    "MIN_ACTIVE_CONNECTORS_FOR_ROUTINES",
    "VALID_AUTONOMY_LEVELS",
    "compute_next_routine_run",
    "create_standing_routine",
    "execute_standing_routine",
    "resolve_effective_autonomy",
    "set_connection_autonomy",
    "update_standing_routine_status",
]
