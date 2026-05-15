from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    studio_env: str = Field(default="local", description="STUDIO_ENV")
    database_url: str = Field(
        default="postgresql+asyncpg://pb_studio:pb_studio_dev@127.0.0.1:5433/pb_studio",
        description="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://127.0.0.1:6380/0",
        description="REDIS_URL",
    )
    celery_broker_url: str = Field(
        default="redis://127.0.0.1:6380/1",
        description="CELERY_BROKER_URL",
    )
    celery_result_backend: str | None = Field(
        default=None,
        description="CELERY_RESULT_BACKEND; если пусто — используется broker",
    )

    api_host: str = Field(default="0.0.0.0", description="STUDIO_API_HOST")
    api_port: int = Field(default=8000, description="STUDIO_API_PORT")

    studio_events_ingest_token: str | None = Field(
        default=None,
        description="STUDIO_EVENTS_INGEST_TOKEN — если задан, POST /events/telegram требует Authorization: Bearer …",
    )
    studio_mirror_enqueue_user_messages: bool = Field(
        default=False,
        description="STUDIO_MIRROR_ENQUEUE_USER_MESSAGES — enqueue в Response Queue только для user text/caption",
    )
    studio_admin_token: str | None = Field(
        default=None,
        description="STUDIO_ADMIN_TOKEN — если задан, админ-роуты требуют Authorization: Bearer …",
    )
    telegram_bot_token: str | None = Field(
        default=None,
        description="TELEGRAM_BOT_TOKEN — Bot API sendMessage (Studio worker/API); без polling/webhook из Studio",
    )
    studio_system_notifications_enabled: bool = Field(
        default=False,
        description="STUDIO_SYSTEM_NOTIFICATIONS_ENABLED — outbound доставка system notifications в control group",
    )
    studio_telegram_send_timeout_ms: int = Field(
        default=3000,
        description="STUDIO_TELEGRAM_SEND_TIMEOUT_MS",
    )
    studio_system_notification_max_retries: int = Field(
        default=3,
        description="STUDIO_SYSTEM_NOTIFICATION_MAX_RETRIES — после исчерпания помечается failed_permanent",
    )
    studio_summary_generation_enabled: bool = Field(
        default=False,
        description="STUDIO_SUMMARY_GENERATION_ENABLED — шаблонная генерация summary_text для pending jobs",
    )
    studio_summary_max_source_messages: int = Field(
        default=200,
        description="STUDIO_SUMMARY_MAX_SOURCE_MESSAGES — лимит строк сообщений/lifecycle для шаблона",
    )
    studio_summary_max_bullets: int = Field(
        default=20,
        description="STUDIO_SUMMARY_MAX_BULLETS — максимум пунктов со сниппетами текста",
    )
    studio_summary_delivery_enabled: bool = Field(
        default=False,
        description="STUDIO_SUMMARY_DELIVERY_ENABLED — отправка generated сводок в control group",
    )
    studio_summary_delivery_max_retries: int = Field(
        default=3,
        description="STUDIO_SUMMARY_DELIVERY_MAX_RETRIES — после исчерпания delivery → failed_permanent",
    )
    studio_control_commands_enabled: bool = Field(
        default=False,
        description="STUDIO_CONTROL_COMMANDS_ENABLED — скан Event Mirror + обработка /summary_* из control group",
    )
    studio_control_commands_max_batch: int = Field(
        default=50,
        description="STUDIO_CONTROL_COMMANDS_MAX_BATCH — лимит сообщений/команд за один цикл",
    )
    studio_control_commands_allowed_user_ids: str = Field(
        default="",
        description="STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS — CSV / пробелы: Telegram user id; пусто = все участники control group",
    )
    studio_control_commands_interval_seconds: int = Field(
        default=5,
        ge=3,
        le=300,
        description="STUDIO_CONTROL_COMMANDS_INTERVAL_SECONDS — интервал Celery beat для process_control_group_commands",
    )

    # NL responder архивирован (single-brain Memoh + Studio MCP).
    # Оставлен только debug-флаг digest (используется MCP studio_get_report).
    studio_nl_digest_debug: bool = Field(
        default=False,
        description="STUDIO_NL_DIGEST_DEBUG — в digest отчётах показывать UUID/status/ISO (отладка)",
    )

    studio_mcp_auth_token: str | None = Field(
        default=None,
        description="STUDIO_MCP_AUTH_TOKEN — Bearer для HTTP MCP (studio-mcp); пусто = без проверки (только доверенная сеть)",
    )
    studio_mcp_listen_host: str = Field(
        default="0.0.0.0",
        description="STUDIO_MCP_LISTEN_HOST — bind для процесса studio-mcp",
    )
    studio_mcp_listen_port: int = Field(
        default=8765,
        ge=1,
        le=65535,
        description="STUDIO_MCP_LISTEN_PORT — порт studio-mcp (streamable HTTP)",
    )

    studio_sla_enabled: bool = Field(
        default=False,
        description="STUDIO_SLA_ENABLED — детектор SLA по зеркалу studio_messages",
    )
    studio_sla_default_first_response_minutes: int = Field(
        default=60,
        description="STUDIO_SLA_DEFAULT_FIRST_RESPONSE_MINUTES — если нет активной policy для chat_role",
    )
    studio_sla_max_notifications_per_incident: int = Field(
        default=3,
        description="STUDIO_SLA_MAX_NOTIFICATIONS_PER_INCIDENT — лимит sendMessage в control group на инцидент",
    )
    studio_sla_default_timezone: str = Field(
        default="UTC",
        description="STUDIO_SLA_DEFAULT_TIMEZONE — IANA tz при отсутствии policy или для календаря без policy",
    )
    studio_sla_working_hours_enabled: bool = Field(
        default=False,
        description="STUDIO_SLA_WORKING_HOURS_ENABLED — учитывать рабочие часы/holidays при расчёте due_at",
    )
    studio_sla_notification_cooldown_minutes: int = Field(
        default=30,
        description="STUDIO_SLA_NOTIFICATION_COOLDOWN_MINUTES — минимальный интервал между повторными уведомлениями по инциденту",
    )
    studio_sla_notification_digest_max_items: int = Field(
        default=10,
        description="STUDIO_SLA_NOTIFICATION_DIGEST_MAX_ITEMS — макс. строк в одном digest за цикл",
    )
    studio_sla_notification_text_max_len: int = Field(
        default=3500,
        description="STUDIO_SLA_NOTIFICATION_TEXT_MAX_LEN — безопасная обрезка текста digest/single",
    )

    studio_history_import_enabled: bool = Field(
        default=False,
        description="STUDIO_HISTORY_IMPORT_ENABLED — POST /history-import/telegram-json (без Memoh/Bot API)",
    )
    studio_history_import_max_bytes: int = Field(
        default=52_428_800,
        ge=64,
        le=500_000_000,
        description="STUDIO_HISTORY_IMPORT_MAX_BYTES — макс. размер JSON импорта",
    )

    studio_kb_enabled: bool = Field(
        default=False,
        description="STUDIO_KB_ENABLED — API и команды /kb_* (без embeddings/LLM)",
    )
    studio_kb_chunk_max_chars: int = Field(
        default=2000,
        description="STUDIO_KB_CHUNK_MAX_CHARS — макс. длина чанка текста",
    )
    studio_kb_chunk_overlap_chars: int = Field(
        default=200,
        description="STUDIO_KB_CHUNK_OVERLAP_CHARS — перекрытие соседних чанков",
    )
    studio_kb_embeddings_enabled: bool = Field(
        default=False,
        description="STUDIO_KB_EMBEDDINGS_ENABLED — эмбеддинги и vector search (без LLM/chat)",
    )
    studio_kb_embedding_model: str = Field(
        default="deterministic",
        description="STUDIO_KB_EMBEDDING_MODEL — id модели для API (openai_compatible) или метка для deterministic",
    )
    studio_kb_embedding_dim: int = Field(
        default=384,
        ge=8,
        le=4096,
        description="STUDIO_KB_EMBEDDING_DIM — размерность вектора (должна совпадать с миграцией vector)",
    )
    studio_kb_search_top_k: int = Field(
        default=5,
        ge=1,
        le=100,
        description="STUDIO_KB_SEARCH_TOP_K — лимит результатов поиска по умолчанию",
    )
    studio_kb_embedding_provider: str = Field(
        default="deterministic",
        description="STUDIO_KB_EMBEDDING_PROVIDER — deterministic | openai_compatible",
    )
    studio_kb_embedding_api_base_url: str | None = Field(
        default=None,
        description="STUDIO_KB_EMBEDDING_API_BASE_URL — база OpenAI-compatible (…/v1), без /embeddings в конце",
    )
    studio_kb_embedding_api_key: str | None = Field(
        default=None,
        description="STUDIO_KB_EMBEDDING_API_KEY — Bearer для /embeddings (не логировать)",
    )
    studio_kb_embedding_timeout_ms: int = Field(
        default=10_000,
        ge=500,
        le=120_000,
        description="STUDIO_KB_EMBEDDING_TIMEOUT_MS — HTTP timeout для embeddings",
    )
    studio_kb_embedding_batch_size: int = Field(
        default=32,
        ge=1,
        le=128,
        description="STUDIO_KB_EMBEDDING_BATCH_SIZE — размер батча для openai_compatible",
    )
    studio_kb_rag_enabled: bool = Field(
        default=False,
        description="STUDIO_KB_RAG_ENABLED — RAG-ответы по KB (chat completion + vector search)",
    )
    studio_kb_chat_provider: str = Field(
        default="openai_compatible",
        description="STUDIO_KB_CHAT_PROVIDER — openai_compatible (MVP)",
    )
    studio_kb_chat_api_base_url: str | None = Field(
        default=None,
        description="STUDIO_KB_CHAT_API_BASE_URL — база OpenAI-compatible (…/v1)",
    )
    studio_kb_chat_api_key: str | None = Field(
        default=None,
        description="STUDIO_KB_CHAT_API_KEY — Bearer для /chat/completions (не логировать)",
    )
    studio_kb_chat_model: str | None = Field(
        default=None,
        description="STUDIO_KB_CHAT_MODEL — id модели для chat completion",
    )
    studio_kb_chat_timeout_ms: int = Field(
        default=20_000,
        ge=3_000,
        le=180_000,
        description="STUDIO_KB_CHAT_TIMEOUT_MS — HTTP timeout для chat completion",
    )
    studio_kb_rag_top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="STUDIO_KB_RAG_TOP_K — сколько чанков в контекст RAG",
    )
    studio_kb_rag_max_context_chars: int = Field(
        default=8000,
        ge=500,
        le=100_000,
        description="STUDIO_KB_RAG_MAX_CONTEXT_CHARS — лимит символов контекста из чанков",
    )
    studio_kb_docling_enabled: bool = Field(
        default=False,
        description="STUDIO_KB_DOCLING_ENABLED — парсинг PDF/DOCX через Docling (если пакет установлен)",
    )
    studio_kb_upload_max_bytes: int = Field(
        default=10_485_760,
        ge=64,
        le=200_000_000,
        description="STUDIO_KB_UPLOAD_MAX_BYTES — макс. размер multipart upload",
    )
    studio_kb_allowed_extensions: str = Field(
        default="txt,md,pdf,docx",
        description="STUDIO_KB_ALLOWED_EXTENSIONS — CSV расширений без точки (нижний регистр)",
    )
    studio_kb_storage_dir: str | None = Field(
        default=None,
        description="STUDIO_KB_STORAGE_DIR — корень для сохранения загруженных бинарников (pdf/docx); пусто = storage/kb от cwd",
    )
    studio_kb_telegram_import_enabled: bool = Field(
        default=False,
        description="STUDIO_KB_TELEGRAM_IMPORT_ENABLED — импорт файлов в KB из control group (/kb_import_last, /kb_import_file)",
    )
    studio_kb_telegram_download_timeout_ms: int = Field(
        default=10_000,
        ge=500,
        le=120_000,
        description="STUDIO_KB_TELEGRAM_DOWNLOAD_TIMEOUT_MS — HTTP timeout getFile+download",
    )
    studio_kb_telegram_max_file_bytes: int = Field(
        default=0,
        ge=0,
        le=200_000_000,
        description="STUDIO_KB_TELEGRAM_MAX_FILE_BYTES — лимит скачивания из Telegram; 0 = как STUDIO_KB_UPLOAD_MAX_BYTES",
    )

    @property
    def studio_control_commands_allowed_user_ids_set(self) -> frozenset[int]:
        raw = (self.studio_control_commands_allowed_user_ids or "").strip()
        if not raw:
            return frozenset()
        ids: list[int] = []
        for part in re.split(r"[\s,;]+", raw):
            p = part.strip()
            if not p or not p.isdigit():
                continue
            try:
                ids.append(int(p))
            except ValueError:
                continue
        return frozenset(ids)

    @property
    def studio_kb_allowed_extensions_set(self) -> frozenset[str]:
        raw = (self.studio_kb_allowed_extensions or "").strip().lower()
        out: set[str] = set()
        for part in re.split(r"[\s,;]+", raw):
            p = part.strip().lstrip(".")
            if p:
                out.add(p)
        return frozenset(out)

    @property
    def studio_kb_storage_path(self):
        from pathlib import Path

        raw = (self.studio_kb_storage_dir or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return (Path.cwd() / "storage" / "kb").resolve()

    @property
    def studio_kb_telegram_effective_max_bytes(self) -> int:
        """Лимит байт для скачивания из Telegram; не больше STUDIO_KB_UPLOAD_MAX_BYTES."""
        up = int(self.studio_kb_upload_max_bytes)
        t = int(self.studio_kb_telegram_max_file_bytes or 0)
        if t > 0:
            return min(t, up)
        return up

    @property
    def celery_backend_effective(self) -> str:
        return self.celery_result_backend or self.celery_broker_url

    @property
    def database_url_sync_for_alembic(self) -> str:
        u = self.database_url
        if "+asyncpg" in u:
            return u.replace("+asyncpg", "+psycopg2", 1)
        return u


@lru_cache
def get_settings() -> Settings:
    return Settings()
