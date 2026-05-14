from __future__ import annotations

from enum import StrEnum


class SlaIncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class SlaSeverity(StrEnum):
    WARNING = "warning"
    BREACHED = "breached"
