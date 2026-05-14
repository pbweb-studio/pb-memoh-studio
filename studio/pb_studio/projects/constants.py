from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class RoleInProject(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    CLIENT = "client"
    INTERNAL = "internal"
