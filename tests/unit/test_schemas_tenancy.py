"""Tests for tenancy Pydantic schemas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from smadp.schemas.tenancy import Member, Plan, Role, Workspace


def test_workspace_minimal_fields():
    ws = Workspace(
        id="ws_01HXAMPLE",
        name="Acme Corp",
        plan="public",
        created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
    )
    assert ws.id == "ws_01HXAMPLE"
    assert ws.plan == "public"


def test_workspace_rejects_extra_fields():
    with pytest.raises(ValidationError):
        Workspace(
            id="ws_01HXAMPLE",
            name="Acme Corp",
            plan="public",
            created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
            extra_field="boom",
        )


def test_workspace_id_pattern():
    with pytest.raises(ValidationError):
        Workspace(
            id="not-an-id",
            name="Acme",
            plan="public",
            created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        )


def test_plan_enum():
    assert Plan.PUBLIC.value == "public"
    assert Plan.PRIVATE.value == "private"
    with pytest.raises(ValidationError):
        Workspace(
            id="ws_01HXAMPLE",
            name="Acme",
            plan="enterprise",
            created_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
        )


def test_member_role_enum():
    m = Member(workspace_id="ws_01HXAMPLE", user_id="u_01HUSER01", role="viewer")
    assert m.role == Role.VIEWER
    with pytest.raises(ValidationError):
        Member(workspace_id="ws_01HXAMPLE", user_id="u_01HUSER01", role="god")


def test_role_ordering():
    """Ordering encodes privilege escalation; needed by require_role."""
    assert Role.VIEWER < Role.EDITOR < Role.ADMIN < Role.OWNER
