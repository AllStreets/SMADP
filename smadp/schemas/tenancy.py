"""Tenancy schemas: workspaces, members, roles, plans (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from functools import total_ordering

from pydantic import BaseModel, ConfigDict, field_validator

WORKSPACE_ID_RE = re.compile(r"^ws_[A-Z0-9]{8,}$")
USER_ID_RE = re.compile(r"^u_[A-Z0-9]{8,}$")


class Plan(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


@total_ordering
class Role(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    OWNER = "owner"

    @property
    def _rank(self) -> int:
        return {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}[self.value]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self._rank < other._rank


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    plan: Plan
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    user_id: str
    role: Role

    @field_validator("workspace_id")
    @classmethod
    def _workspace_id(cls, v: str) -> str:
        if not WORKSPACE_ID_RE.match(v):
            raise ValueError(f"Invalid workspace id: {v!r}")
        return v

    @field_validator("user_id")
    @classmethod
    def _user_id(cls, v: str) -> str:
        if not USER_ID_RE.match(v):
            raise ValueError(f"Invalid user id: {v!r}")
        return v


__all__ = ["Member", "Plan", "Role", "Workspace"]
