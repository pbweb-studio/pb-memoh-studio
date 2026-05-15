"""NL layer string constants (no business logic)."""


class NlInteractionStatus:
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    PENDING_CONFIRMATION = "pending_confirmation"
    IGNORED = "ignored"


class NlTriggerType:
    MENTION = "mention"
    REPLY = "reply"
    ALIAS = "alias"
    MANUAL = "manual"


class RouterMode:
    ROUTER_PENDING = "router_pending"
    BUSINESS_ACTION = "business_action"
    LEARNING = "learning"
    CLARIFY = "clarify"
    CASUAL = "casual"
    REFUSAL = "refusal"
    ERROR = "error"


class NlIntent:
    STUDIO_DIGEST = "studio_digest"
    PROJECT_DIGEST = "project_digest"
    OPEN_RISKS_OR_SLA = "open_risks_or_sla"
    LIST_CHATS = "list_chats"
    LIST_PROJECTS = "list_projects"
    KB_SEARCH = "kb_search"
    KB_ASK = "kb_ask"
    DIAGNOSTICS_STATUS = "diagnostics_status"
    HELP_CAPABILITIES = "help_capabilities"
    LEARNING_REQUEST = "learning_request"
    CASUAL_OR_ASSISTANT = "casual_or_assistant"
    UNCLEAR = "unclear"
    CONFIRMATION_REPLY = "confirmation_reply"


class LearningType:
    BEHAVIOR_RULE = "behavior_rule"
    KNOWLEDGE_DOCUMENT = "knowledge_document"
    KNOWLEDGE_NOTE = "knowledge_note"
    PROJECT_FACT = "project_fact"
    CLIENT_PREFERENCE = "client_preference"
    WORKFLOW_PLAYBOOK = "workflow_playbook"
    TASK_TEMPLATE = "task_template"
    BOT_CONFIG_REQUEST = "bot_config_request"
    DANGEROUS_CHANGE = "dangerous_change"
    CLARIFY = "clarify"
