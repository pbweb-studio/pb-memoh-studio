from __future__ import annotations


class KnowledgeDocumentSourceType:
    MANUAL = "manual"
    FILE = "file"
    URL = "url"
    TELEGRAM = "telegram"
    GOOGLE_DRIVE = "google_drive"


class KnowledgeDocumentStatus:
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    FAILED = "failed"


class KnowledgeVersionStatus:
    PENDING = "pending"
    PARSED = "parsed"
    FAILED = "failed"
