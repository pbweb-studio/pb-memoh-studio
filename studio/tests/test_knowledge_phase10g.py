"""Фаза 10g: импорт KB из Telegram document (Event Mirror + control group)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pb_studio.control_commands.models  # noqa: F401
import pb_studio.control_group.models  # noqa: F401
import pb_studio.event_mirror.models  # noqa: F401
import pb_studio.knowledge.models  # noqa: F401
import pb_studio.project_digests.models  # noqa: F401
import pb_studio.projects.models  # noqa: F401
import pb_studio.summaries.models  # noqa: F401
from pb_studio.api.deps import get_db
from pb_studio.api.main import app
from pb_studio.control_commands.constants import ControlCommandName, ControlCommandStatus
from pb_studio.control_commands.models import StudioControlCommand
from pb_studio.control_commands.parser import parse_control_group_command_line
from pb_studio.control_commands import service as control_cmd_service
from pb_studio.control_commands.service import run_control_commands_cycle
from pb_studio.core.config import get_settings
from pb_studio.knowledge.constants import KnowledgeVersionStatus
from pb_studio.knowledge.models import StudioKnowledgeChunk, StudioKnowledgeDocumentVersion
from pb_studio.response_queue.models import Base


@pytest_asyncio.fixture
async def g10_engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def g10_client(g10_engine):
    factory = async_sessionmaker(g10_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:

        async def db_override():
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        app.dependency_overrides[get_db] = db_override
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session
        app.dependency_overrides.clear()


def _msg_text(update_id: int, chat_id: int, *, text: str, message_id: int, from_user_id: int = 42) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "T"},
            "from": {"id": from_user_id, "is_bot": False, "first_name": "U"},
            "text": text,
        },
    }


def _msg_document(
    update_id: int,
    chat_id: int,
    *,
    message_id: int,
    from_user_id: int = 42,
    file_name: str = "n.txt",
    file_id: str = "AgACAgIAAxkBAAIB",
    file_size: int = 50,
) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "T"},
            "from": {"id": from_user_id, "is_bot": False, "first_name": "U"},
            "document": {
                "file_name": file_name,
                "file_id": file_id,
                "file_unique_id": "uq",
                "file_size": file_size,
                "mime_type": "text/plain",
            },
        },
    }


def _env10g(monkeypatch: pytest.MonkeyPatch, tmp_path, *, telegram_import: bool = True, allowed: str = "") -> None:
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10g")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "200")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
    monkeypatch.setenv("STUDIO_KB_UPLOAD_MAX_BYTES", "50000")
    monkeypatch.setenv("STUDIO_KB_TELEGRAM_MAX_FILE_BYTES", "0")
    monkeypatch.setenv("STUDIO_KB_ALLOWED_EXTENSIONS", "txt,md,pdf,docx")
    monkeypatch.setenv("STUDIO_KB_STORAGE_DIR", str(tmp_path / "kb10g"))
    monkeypatch.setenv("STUDIO_KB_DOCLING_ENABLED", "false")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "FAKEBOTTOKEN10G")
    monkeypatch.setenv("STUDIO_KB_TELEGRAM_IMPORT_ENABLED", "true" if telegram_import else "false")
    monkeypatch.setenv("STUDIO_KB_TELEGRAM_DOWNLOAD_TIMEOUT_MS", "5000")
    if allowed:
        monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS", allowed)
    (tmp_path / "kb10g").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_kb_import_last_txt_creates_chunks(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001001
    await client.post("/events/telegram", json=_msg_text(100001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post("/events/telegram", json=_msg_document(100002, cg, message_id=2, file_name="mirror.txt"))
    await client.post(
        "/events/telegram",
        json=_msg_text(100003, cg, text="/kb_import_last My Telegram Doc", message_id=3),
    )

    async def fake_fetch(_settings, *, file_id: str):
        assert file_id == "AgACAgIAAxkBAAIB"
        return True, b"unique10g mirror content for chunking test", "", "mirror.txt"

    monkeypatch.setattr(
        "pb_studio.knowledge.telegram_kb_import.fetch_document_bytes_for_kb",
        fake_fetch,
    )

    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd is not None
    assert cmd.command_name == ControlCommandName.KB_IMPORT_LAST
    assert cmd.status == ControlCommandStatus.PROCESSED
    ver = await session.scalar(select(StudioKnowledgeDocumentVersion).order_by(StudioKnowledgeDocumentVersion.created_at.desc()))
    assert ver is not None
    assert ver.status == KnowledgeVersionStatus.PARSED
    n = await session.scalar(
        select(func.count()).select_from(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == ver.id)
    )
    assert int(n or 0) >= 1


@pytest.mark.asyncio
async def test_kb_import_last_md_chunks(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001002
    await client.post("/events/telegram", json=_msg_text(101001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post("/events/telegram", json=_msg_document(101002, cg, message_id=2, file_name="x.md", file_id="fidmd"))
    await client.post("/events/telegram", json=_msg_text(101003, cg, text="/kb_import_last MD Title", message_id=3))

    async def fake_fetch(_settings, *, file_id: str):
        return True, b"# H1\n\nmd10g line\n", "", "x.md"

    monkeypatch.setattr("pb_studio.knowledge.telegram_kb_import.fetch_document_bytes_for_kb", fake_fetch)
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    ver = await session.scalar(select(StudioKnowledgeDocumentVersion).order_by(StudioKnowledgeDocumentVersion.created_at.desc()))
    assert ver.status == KnowledgeVersionStatus.PARSED
    n = await session.scalar(
        select(func.count()).select_from(StudioKnowledgeChunk).where(StudioKnowledgeChunk.document_version_id == ver.id)
    )
    assert int(n or 0) >= 1


@pytest.mark.asyncio
async def test_kb_import_last_pdf_docling_off_failed_unsupported(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001003
    await client.post("/events/telegram", json=_msg_text(102001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post(
        "/events/telegram",
        json=_msg_document(102002, cg, message_id=2, file_name="z.pdf", file_id="fidpdf"),
    )
    await client.post("/events/telegram", json=_msg_text(102003, cg, text="/kb_import_last PDF doc", message_id=3))
    pdf = b"%PDF-1.1\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

    async def fake_fetch(_settings, *, file_id: str):
        return True, pdf, "", "z.pdf"

    monkeypatch.setattr("pb_studio.knowledge.telegram_kb_import.fetch_document_bytes_for_kb", fake_fetch)
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    ver = await session.scalar(select(StudioKnowledgeDocumentVersion).order_by(StudioKnowledgeDocumentVersion.created_at.desc()))
    assert ver.status == KnowledgeVersionStatus.FAILED_UNSUPPORTED


@pytest.mark.asyncio
async def test_kb_import_ignored_outside_control_group(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    await client.post("/events/telegram", json=_msg_text(103001, -10001004, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": -10001004})
    await client.post("/events/telegram", json=_msg_document(103002, -10001005, message_id=2))
    await client.post(
        "/events/telegram",
        json=_msg_text(103003, -10001005, text="/kb_import_last T", message_id=3),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    n = await session.scalar(select(func.count()).select_from(StudioControlCommand))
    assert int(n or 0) == 0


@pytest.mark.asyncio
async def test_kb_import_acl_denied(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path, allowed="7")
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001006
    await client.post("/events/telegram", json=_msg_text(104001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post("/events/telegram", json=_msg_document(104002, cg, message_id=2, from_user_id=99))
    await client.post(
        "/events/telegram",
        json=_msg_text(104003, cg, text="/kb_import_last X", message_id=3, from_user_id=99),
    )
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.status == ControlCommandStatus.FAILED_ACCESS_DENIED


@pytest.mark.asyncio
async def test_kb_import_rejects_oversize_declared(g10_client, monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", "adm10g")
    monkeypatch.setenv("STUDIO_KB_ENABLED", "true")
    monkeypatch.setenv("STUDIO_KB_CHUNK_MAX_CHARS", "200")
    monkeypatch.setenv("STUDIO_KB_CHUNK_OVERLAP_CHARS", "10")
    monkeypatch.setenv("STUDIO_KB_UPLOAD_MAX_BYTES", "100")
    monkeypatch.setenv("STUDIO_KB_TELEGRAM_MAX_FILE_BYTES", "0")
    monkeypatch.setenv("STUDIO_KB_ALLOWED_EXTENSIONS", "txt")
    monkeypatch.setenv("STUDIO_KB_STORAGE_DIR", str(tmp_path / "kbo"))
    monkeypatch.setenv("STUDIO_KB_DOCLING_ENABLED", "false")
    monkeypatch.setenv("STUDIO_CONTROL_COMMANDS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "FAKEBOTTOKEN10G")
    monkeypatch.setenv("STUDIO_KB_TELEGRAM_IMPORT_ENABLED", "true")
    (tmp_path / "kbo").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()

    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001007
    await client.post("/events/telegram", json=_msg_text(105001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post(
        "/events/telegram",
        json=_msg_document(105002, cg, message_id=2, file_name="huge.txt", file_id="x", file_size=999999),
    )
    await client.post("/events/telegram", json=_msg_text(105003, cg, text="/kb_import_last Big", message_id=3))
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.status == ControlCommandStatus.PROCESSED
    assert "лимит" in (send.call_args.kwargs.get("text") or "")


@pytest.mark.asyncio
async def test_kb_import_rejects_bad_extension_after_download(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001008
    await client.post("/events/telegram", json=_msg_text(106001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post("/events/telegram", json=_msg_text(106002, cg, text="/kb_import_file fid99 Bad ext", message_id=2))

    async def fake_fetch(_settings, *, file_id: str):
        return True, b"MZ", "", "bad.exe"

    monkeypatch.setattr("pb_studio.knowledge.telegram_kb_import.fetch_document_bytes_for_kb", fake_fetch)
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    assert "отклон" in (send.call_args.kwargs.get("text") or "").lower() or "extension" in (send.call_args.kwargs.get("text") or "")


@pytest.mark.asyncio
async def test_kb_import_download_timeout_does_not_fail_batch(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001009
    await client.post("/events/telegram", json=_msg_text(107001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post("/events/telegram", json=_msg_text(107002, cg, text="/kb_import_file fid1 T1", message_id=2))
    await client.post("/events/telegram", json=_msg_document(107003, cg, message_id=3, file_name="ok.txt", file_id="fidok"))
    await client.post("/events/telegram", json=_msg_text(107004, cg, text="/kb_import_last T2", message_id=4))

    calls = {"n": 0}

    async def fake_fetch(_settings, *, file_id: str):
        calls["n"] += 1
        if file_id == "fid1":
            return False, None, "download_timeout", "x.txt"
        return True, b"batch10g ok content here", "", "ok.txt"

    monkeypatch.setattr("pb_studio.knowledge.telegram_kb_import.fetch_document_bytes_for_kb", fake_fetch)
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    cmds = list((await session.scalars(select(StudioControlCommand).order_by(StudioControlCommand.source_message_id.asc()))).all())
    assert len(cmds) == 2
    assert cmds[0].status == ControlCommandStatus.PROCESSED
    assert cmds[1].status == ControlCommandStatus.PROCESSED
    assert calls["n"] == 2
    ver = await session.scalar(select(StudioKnowledgeDocumentVersion).order_by(StudioKnowledgeDocumentVersion.created_at.desc()))
    assert ver.status == KnowledgeVersionStatus.PARSED


@pytest.mark.asyncio
async def test_kb_ingest_exception_last_error_redacts(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001010
    await client.post("/events/telegram", json=_msg_text(108001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post("/events/telegram", json=_msg_document(108002, cg, message_id=2))
    await client.post("/events/telegram", json=_msg_text(108003, cg, text="/kb_import_last Boom", message_id=3))

    async def fake_fetch(_settings, *, file_id: str):
        return True, b"txt", "", "z.txt"

    monkeypatch.setattr("pb_studio.knowledge.telegram_kb_import.fetch_document_bytes_for_kb", fake_fetch)

    async def boom(*_a, **_k):
        raise RuntimeError("fail sk-abcdefghijklmnopqrstuv FAKEBOTTOKEN10G")

    monkeypatch.setattr(control_cmd_service.studio_kb_service, "ingest_new_document_from_upload", boom)
    await run_control_commands_cycle(session, get_settings(), send_message=AsyncMock(return_value=(True, 200, "", 1)))
    cmd = await session.scalar(select(StudioControlCommand).order_by(StudioControlCommand.created_at.desc()))
    assert cmd.status == ControlCommandStatus.FAILED
    assert cmd.last_error is not None
    assert "FAKEBOTTOKEN10G" not in cmd.last_error
    assert "sk-" not in cmd.last_error


def test_kb_search_parse_still_works():
    p = parse_control_group_command_line("/kb_search hello world")
    assert p is not None
    assert p.name == ControlCommandName.KB_SEARCH


@pytest.mark.asyncio
async def test_kb_import_disabled_short_circuit(g10_client, monkeypatch, tmp_path):
    _env10g(monkeypatch, tmp_path, telegram_import=False)
    client, session = g10_client
    h = {"Authorization": "Bearer adm10g"}
    cg = -10001011
    await client.post("/events/telegram", json=_msg_text(109001, cg, text="/x", message_id=1))
    await client.post("/control-group/set", headers=h, json={"telegram_chat_id": cg})
    await client.post("/events/telegram", json=_msg_document(109002, cg, message_id=2))
    await client.post("/events/telegram", json=_msg_text(109003, cg, text="/kb_import_last X", message_id=3))
    send = AsyncMock(return_value=(True, 200, "", 1))
    await run_control_commands_cycle(session, get_settings(), send_message=send)
    assert "STUDIO_KB_TELEGRAM_IMPORT_ENABLED" in (send.call_args.kwargs.get("text") or "")
