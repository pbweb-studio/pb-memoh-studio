# Текущая задача

## После фазы 10c (KB embeddings + vector search)

**Статус:** pgvector + deterministic embeddings; `POST /knowledge/embed-pending`, `POST /knowledge/search`; Celery `embed_pending_knowledge_chunks`; `/kb_search`. Memoh не менялся.

**Следующий шаг:** по постановке — **6+** (LLM), **10+** (Docling, внешние embeddings, полный RAG), или иной эпик.
