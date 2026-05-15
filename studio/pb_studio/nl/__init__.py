"""MCP report/memory utilities (legacy package name).

NL responder архивирован (single-brain Memoh + Studio MCP). В этом пакете
остались только:

- ``executor.py`` — read-only хелперы для текстовых отчётов, используемых
  MCP-инструментами и Studio Admin (digest, list chats/projects, KB search).
- ``models.py`` — ORM-модели ``StudioMemoryItem``, ``StudioPlaybook``,
  ``StudioNlInteraction`` (последнюю оставили как архив-таблицу).
"""
