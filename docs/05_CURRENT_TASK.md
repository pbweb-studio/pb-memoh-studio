# Текущая задача

## После фазы 11a (assistant rules — storage / API / команды)

**Статус:** активные `assistant_rules` подмешиваются в **user**-prompt KB RAG (`ask_knowledge_base`): глобальные; + **project** при `project_id` в запросе; + **chat** при `chat_id` (API `POST /knowledge/ask`) или для `/kb_ask` — `studio_chats.id` активной control group. Ответ содержит `applied_rule_ids`. **Без** Memoh, без изменения system prompt Memoh, без сводок/SLA/digest, без Studio Admin UI.

**Следующий шаг:** по постановке — **6+**, **12–14**, расширение RAG, или иной эпик.
