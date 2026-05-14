from __future__ import annotations


class AssistantRuleScope:
    GLOBAL = "global"
    PROJECT = "project"
    CHAT = "chat"


class AssistantRuleStatus:
    ACTIVE = "active"
    DISABLED = "disabled"


class AssistantRuleSource:
    MANUAL = "manual"
    CONTROL_GROUP = "control_group"


class AssistantRuleAuditAction:
    CREATED = "created"
    UPDATED = "updated"
    DISABLED = "disabled"


RULE_HELP_TEXT = """Правила поведения ассистента (Studio DB; фаза 11a — CRUD; фаза 11b — применение к KB RAG при /kb_ask и POST /knowledge/ask):

/rule_help — этот текст
/rule_list — активные и недавно отключённые правила (кратко)
/rule_add <текст> — правило глобального scope
/rule_add_project <project_slug> <текст> — правило для проекта
/rule_add_chat <studio_chat_uuid> <текст> — правило для чата
/rule_disable <rule_uuid> — отключить правило

Админ-API: GET/POST/PATCH /assistant-rules, POST …/disable, GET /assistant-rules/audit — под STUDIO_ADMIN_TOKEN.
Только из active control group; ACL — STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS.
"""
