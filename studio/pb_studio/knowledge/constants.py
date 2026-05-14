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
    FAILED_UNSUPPORTED = "failed_unsupported"


class KnowledgeParserName:
    PLAIN = "plain_text"
    MARKDOWN = "markdown"
    PLACEHOLDER = "placeholder"


# Размерность колонки vector в миграции 014 (должна совпадать с STUDIO_KB_EMBEDDING_DIM по умолчанию).
KNOWLEDGE_EMBEDDING_VECTOR_DIM = 384


class KnowledgeChunkEmbeddingStatus:
    PENDING = "pending"
    EMBEDDED = "embedded"
    FAILED = "failed"


class KnowledgeEmbeddingProviderKind:
    DETERMINISTIC = "deterministic"
    OPENAI_COMPATIBLE = "openai_compatible"


class KnowledgeChatProviderKind:
    OPENAI_COMPATIBLE = "openai_compatible"


# Ответ при отсутствии релевантных чанков в RAG (фаза 10e).
KNOWLEDGE_RAG_NOT_FOUND_ANSWER = "не найдено в базе знаний"
