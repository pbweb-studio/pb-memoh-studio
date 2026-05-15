# FEATURES_v1 — контракт продукта pb-memoh-studio (MVP)

Это финальный контракт первой живой версии. Источник правды по «что бот должен уметь и как».

Связанные документы:

- `docs/00_MASTER_GUIDE.md` — общий гид по репозиторию.
- `docs/06_DECISIONS.md` — архитектурные решения.
- `docs/15_OPERATOR_GUIDE.md` — что делает оператор в проде.
- `skills/pb-studio-manager/SKILL.md` — UX-правила для ассистента Memoh.

Старый план фаз 0–14 в `docs/03_IMPLEMENTATION_PLAN.md` сохраняется как **исторический**. Дальнейшее развитие следует этому документу.

---

## 1. Видение продукта

**pb-memoh-studio** — один Telegram-бот, который для команды веб-студии работает как «младший операционный менеджер»:

- Видит всё, что происходит в чатах студии.
- Отвечает в любых чатах, куда его добавили — но по-разному, в зависимости от типа чата.
- Понимает контекст: даёт умные отчёты «по смыслу» чата (задачи / лиды / согласования — сам решает формат).
- Помнит регламенты студии (база знаний с RAG).
- Учится правилам и фактам через обычный разговор, без правки кода.
- Контролирует SLA — клиенты не теряются.
- Защищает оператора от случайных опасных действий (inline-подтверждения).

**Архитектура:**

```
Telegram ──► Memoh (Go, один мозг бота)
              │
              ├── Event Mirror hook ──► Studio API (Python, FastAPI)
              │                              │
              └── MCP federation ──► Studio MCP (studio-mcp:8765)
                                          │
                                         ▼
                                    Postgres + pgvector + Redis + Celery
```

**Ключевые принципы:**

- Memoh — единственный «мозг», отвечает в Telegram.
- Studio — backend бизнес-данных + MCP-фасад инструментов.
- Никаких slash-команд как основного UX. Всё через естественный язык + mention.
- Никаких правок ядра Memoh (кроме одного существующего Event Mirror hook).
- Никаких параллельных «вторых мозгов» (Studio NL responder архивирован и удалён в MVP-чистке).

---

## 2. Поведение бота по типам чатов

В Studio у каждого чата есть `chat_role`. Поведение бота **зависит от роли**, через MCP-инструмент `studio_get_chat_context`, который ассистент вызывает перед каждым ответом.

| Роль | Поведение |
|---|---|
| `control_group` (одна активная управляющая) | Полный ассистент. Доступны все MCP-tools Studio. Системные уведомления, SLA, сводки приходят сюда. |
| `internal_chat` (команда студии) | Полный ассистент. Отвечает на mention/reply от любого участника. |
| `project_chat` (внутренний по проекту) | Полный ассистент, но с контекстом проекта (правила и память bound к проекту). |
| `client_chat` (чат с клиентом) | **Тихий наблюдатель.** Отвечает только на mention/reply **от участников из ACL** (менеджеры). Клиентов игнорирует — пока правила не разрешат иначе. |
| `service_chat` (сервис, не нужен бот) | Игнорирует всё. |
| `unknown` (новый, ещё не классифицирован) | По умолчанию ведёт себя как `internal_chat`. Оператор может назначить роль через auto-suggestion (см. U2) или через ассистента: «помечу чат X как клиентский». |

**Защита клиентов в `client_chat`:** даже когда менеджер обращается к боту с mention, ассистент учитывает активные правила scope=chat/project, чтобы не выдать клиенту внутреннюю информацию. Правила задаются через разговор: «запомни: в чате Ромашки не упоминай ценообразование без подтверждения».

---

## 3. MVP — что входит в первую живую версию

### 3.1. Базовый ассистент (Memoh upstream, не правим)

- Естественный диалог в Telegram (личка + любые группы, где есть бот).
- Memoh LLM-провайдеры: OpenAI, Anthropic, Google, OpenRouter, GitHub Copilot и т.д.
- Память агента в разговоре (Memoh memory) — внутри одной беседы.
- Голосовой ввод через Memoh speech provider (см. U5).
- Skills и federated MCP — единственное расширение бота, без правок ядра.
- Memoh Web UI: `https://memo.pb-web.ru`.

### 3.2. Студия — что добавляется через Studio MCP

| Группа | Возможность | Реализация |
|---|---|---|
| **Архив** | Все сообщения всех чатов, где есть бот, попадают в Studio DB | Event Mirror hook + `studio_messages` |
| **Архив** | Просмотр чатов и сообщений в Studio Admin | `/admin/chats`, `/admin/messages` |
| **Чаты** | Назначить чату роль (`client_chat` / `project_chat` / `internal_chat` / `service_chat`) | MCP `studio_assign_chat_role` |
| **Чаты** | Активная управляющая группа | MCP `studio_set_control_group` |
| **Проекты** | Создать проект, привязать к нему чаты | MCP `studio_create_project`, `studio_bind_chat_to_project` |
| **Проекты** | Список проектов и чатов проекта | MCP `studio_list_projects` |
| **Сводки** | Сводка по чату за период | MCP `studio_get_report` (общий) |
| **Сводки** | Сводка по проекту | MCP `studio_get_project_digest` |
| **Сводки** | **Умный LLM-отчёт «по смыслу чата»** — задачи, лиды, согласования, бот сам решает формат | MCP `studio_smart_chat_report` |
| **SLA** | Политика SLA по роли чата (минуты до первого ответа) | MCP `studio_set_sla_policy` |
| **SLA** | Уведомления о просрочках в control group (антиспам, digest) | существующий Celery worker |
| **SLA** | Список открытых SLA-инцидентов | MCP `studio_list_open_sla` |
| **KB** | Загрузка документа (HTTP, или в личке боту командой «сохрани в базу знаний») | MCP `studio_import_kb_text` (текст), HTTP upload (бинарники) |
| **KB** | Поиск по KB | MCP `studio_search_kb` |
| **KB** | Q&A по KB через LLM (RAG) | существующий `/knowledge/ask` + MCP wrapper |
| **Правила** | Сохранение правила («запомни, что …») | MCP `studio_save_behavior_rule` |
| **Правила** | Скоуп: global / project / chat | через параметры MCP |
| **Правила** | **Применение правил во всех ответах ассистента** | MCP `studio_get_active_rules` + инструкция в skill |
| **Правила** | Отключение правила + аудит | MCP `studio_disable_rule` |
| **Память бизнеса** | Бизнес-факт студии («запомни, что менеджер по дизайну — Аня») | MCP `studio_save_memory_item` |
| **Память бизнеса** | Подтягивание фактов в ответ | через `studio_get_chat_context` |
| **Уведомления** | Системные в control group: бот добавлен/удалён, сбои | Event Mirror + Studio Celery |
| **Уведомления** | SLA-уведомления | существующий Celery |
| **Безопасность** | ACL менеджеров (только определённые TG user id могут давать команды управления) | `STUDIO_CONTROL_COMMANDS_ALLOWED_USER_IDS` + `studio_get_chat_context` |
| **Безопасность** | Аудит изменений (правила, проекты, роли) | `studio_audit_log`, `studio_assistant_rule_audit` |
| **Безопасность** | Studio Admin под токеном | `STUDIO_ADMIN_TOKEN` Bearer / cookie |

### 3.3. UX-фичи (U1–U8) — то, что делает продукт «удобным»

| Код | Фича | Описание |
|---|---|---|
| **U1** | **Self-introduction** | Бот добавлен в чат → одно короткое приветствие + объяснение, как с ним работать. Для клиентских — лаконично, для управляющей — с inline-кнопкой «назначить меня управляющей». |
| **U2** | **Auto-suggestion ролей** | Новый чат → бот шлёт владельцу в личку «Я добавлен в чат X. Какой это чат?» + inline-кнопки [Клиентский] [Проектный] [Внутренний] [Игнорировать]. Один клик — роль назначена. |
| **U3** | **Morning briefing** | Первое утреннее сообщение оператора в личку → single-page обзор: «6 чатов с активностью / 2 SLA-просрочки / новые лиды в Ромашке / 1 правило ждёт подтверждения». |
| **U4** | **Inline-confirmations** | Рискованные действия («отправить клиенту», «удалить правило», «изменить SLA») → inline-кнопки [Да] [Только мне] [Изменить]. |
| **U5** | **Голосовой ввод** | Voice messages оператора → speech-to-text Memoh → ассистент. Из машины/в дороге. |
| **U6** | **Mute by phrase** | «Помолчи здесь 2 часа» → бот молчит N времени в этом чате, потом возвращается. Сохраняется как chat-rule с TTL. |
| **U7** | **Onboarding wizard** | Первый вход в Studio Admin → 4-шаговая страница: «Подключи бота → добавь в управляющую → назначь → добавь в тестовый чат». |
| **U8** | **Единая навигация** | В Memoh Web ссылка на Studio Admin и обратно, единая стартовая страница. |

---

## 4. MCP-инструменты Studio (полный финальный набор)

Все инструменты доступны через сервис `studio-mcp` (streamable HTTP, порт 8765, Bearer `STUDIO_MCP_AUTH_TOKEN`).

### Read-only (используются перед любым ответом или явно по запросу)

| Tool | Что делает |
|---|---|
| `studio_get_chat_context(tg_chat_id, from_user_id)` | **Ключевой.** Возвращает `{role, project, can_respond_to_user, active_rules, recent_summary}`. Ассистент вызывает перед каждым ответом для определения поведения. |
| `studio_list_chats(include_debug?)` | Список всех чатов с ролями, проектами, краткой статистикой. |
| `studio_get_recent_messages(chat_id, limit?)` | Последние N сообщений конкретного чата. Используется для умного отчёта и контекста. |
| `studio_list_projects(include_debug?)` | Активные проекты. |
| `studio_list_open_sla(include_debug?)` | Открытые SLA-инциденты. |
| `studio_search_kb(query, include_debug?)` | Поиск чанков в базе знаний. |
| `studio_get_kb_sources(limit?, include_debug?)` | Список документов в KB. |
| `studio_get_active_rules(scope, scope_id?)` | Активные правила в скоупе global/project/chat. |
| `studio_get_report(period?, include_debug?)` | Общий отчёт по всем активным чатам за период. |
| `studio_get_project_digest(project_name_guess, period?)` | Дайджест проекта. |
| `studio_smart_chat_report(chat_id_or_name, period?)` | **Главная фича.** LLM-отчёт, формат выбирается по содержимому чата (задачи / лиды / согласования / хронология). |
| `studio_runtime_status(include_debug?)` | Флаги Studio (без секретов). |

### Write (изменяют состояние Studio)

| Tool | Что делает |
|---|---|
| `studio_assign_chat_role(tg_chat_id, role)` | Установить роль чата. |
| `studio_set_control_group(tg_chat_id)` | Назначить активную управляющую группу. |
| `studio_create_project(name, slug)` | Создать проект. |
| `studio_bind_chat_to_project(tg_chat_id, project_slug)` | Привязать чат к проекту. |
| `studio_set_sla_policy(chat_role, first_response_minutes)` | Установить политику SLA для роли. |
| `studio_save_behavior_rule(rule_text, scope, project_slug?, chat_id?)` | Сохранить правило поведения. |
| `studio_save_memory_item(text, scope_type, project_slug?)` | Сохранить бизнес-факт. |
| `studio_disable_rule(rule_id)` | Отключить правило. |
| `studio_import_kb_text(title, content, project_slug?)` | Загрузить документ в KB как текст. |

**Итого:** 12 read + 9 write = **21 MCP-инструмент**.

`studio_create_playbook_draft` остаётся в коде, но скрыт из skill до LATER-итерации.

---

## 5. LATER — после MVP (следующие итерации)

Не входит в первый PR, делается отдельно после успешной приёмки MVP.

| Код | Что | Условия для запуска |
|---|---|---|
| A2 | Импорт истории Telegram Desktop JSON | После того как MVP стабилизирован |
| C4 | Авто-сводки по расписанию (cron) | Когда понятна желаемая частота |
| D2 | Рабочие часы / выходные / праздники SLA | После реального опыта с D1 |
| D3 | Mute политики SLA | По мере роста числа политик |
| E4 | Привязка KB-документа к проекту | Когда наберётся ≥10 документов в KB |
| E5 | Импорт KB через пересылку файла в Telegram | После UX-проверки текстового пути |
| H1–H3 | Playbooks | Когда оператор накопит реальные процессы |
| I3 | Авто-доставка готовых сводок в control group | После проверки полезности сводок вручную |
| SSO Memoh + Studio | Единый логин | Когда станет реально мешать |

---

## 6. WON'T — что не делаем

| Код | Что | Почему |
|---|---|---|
| W2 | Полноценный таск-трекер (как Asana) | Дублирование внешних инструментов; в Telegram это плохо ложится. |
| W3 | Биллинг / счета | Не задача ассистента. |
| W4 | TTS / голосовые ответы от бота | Не нужно для b2b-сценария. |
| W5 | Генерация картинок | Не нужно для студии. |
| W6 | Календарь / звонки | Дублирование Google Calendar и т.п. |

**Раньше был W1 (бот не отвечает клиентам) и W7 (Sales-бот) — пересмотрены:**

- **Клиенты в client_chat** по умолчанию игнорируются ботом (тихий наблюдатель), но это поведение **управляется правилами**, а не жёстким запретом в коде. При желании оператор может правилом разрешить ответы.
- **Sales-функции** в текущем релизе не делаются, но контракт не запрещает добавить их позже как новые правила/playbooks.

---

## 7. Приёмка MVP (6 сценариев в Telegram)

После деплоя оператор проходит в управляющей группе:

1. `@bot какие чаты ты видишь?` → ответ через `studio_list_chats`.
2. `@bot дай умный отчёт по чату Ромашки за неделю` → `studio_smart_chat_report` с LLM-разбором по смыслу.
3. `@bot создай проект Лендинг и привяжи к нему чат Ромашки` → две tool calls подряд, осмысленный отчёт о результате.
4. `@bot запомни правило для клиентских чатов: не упоминай ценообразование без подтверждения менеджера` → `save_behavior_rule` scope=global или client_chat, видно в `/admin/assistant-rules`.
5. В клиентском чате клиент пишет «привет» → бот молчит (role-aware K1 + правило).
6. Менеджер в том же клиентском чате `@bot дай резюме переписки за сегодня` → бот отвечает с учётом правила (без ценообразования).

**Дополнительно после PR2:**

7. Добавили бота в новый чат → self-intro (U1) + оператору пришёл auto-suggestion с кнопками (U2).
8. Утром написали боту «доброе утро» → morning briefing (U3).
9. Записали голосовое «дай отчёт за сегодня» → ответ как на текст (U5).
10. В чате сказали боту «помолчи 30 минут» → бот молчит, через 30 минут возвращается (U6).

---

## 8. Конфигурация (упрощённая)

Дефолтные значения и логика — в `.env.prod.example`. После чистки конфиг разбит на три секции:

**MVP-минимум (обязательно):**

```
POSTGRES_PASSWORD, DATABASE_URL, STUDIO_ADMIN_TOKEN,
TELEGRAM_BOT_TOKEN, STUDIO_EVENTS_INGEST_TOKEN,
STUDIO_MCP_AUTH_TOKEN
```

**Опциональные фичи (включаются по одной):**

```
STUDIO_KB_ENABLED, STUDIO_KB_EMBEDDINGS_ENABLED, STUDIO_KB_RAG_ENABLED,
STUDIO_KB_CHAT_API_BASE_URL, STUDIO_KB_CHAT_API_KEY, STUDIO_KB_CHAT_MODEL,
STUDIO_SLA_ENABLED, STUDIO_SLA_DEFAULT_FIRST_RESPONSE_MINUTES,
STUDIO_SYSTEM_NOTIFICATIONS_ENABLED,
STUDIO_SUMMARY_GENERATION_ENABLED, STUDIO_SUMMARY_DELIVERY_ENABLED,
STUDIO_HISTORY_IMPORT_ENABLED
```

**Legacy / archived (выключено, не нужно трогать):**

```
STUDIO_NL_* — NL responder архивирован, переменные удалены из compose
STUDIO_CONTROL_COMMANDS_* — slash-команды как opt-in для emergency
```

---

## 9. Что считается «живой бот» (definition of done MVP)

- [ ] Деплой Studio + Memoh на VPS прошёл без ошибок.
- [ ] `studio-mcp` healthy, доступен из Memoh-контейнера.
- [ ] В Memoh Admin: подключён MCP-источник + установлен skill `pb-studio-manager` + включён для бота.
- [ ] Все 6 сценариев приёмки MVP в Telegram дают ожидаемый результат.
- [ ] В Studio Admin видны новые `studio_assistant_rules` / `studio_projects` / `studio_chats` с правильными ролями, созданные через диалог.
- [ ] Логи Memoh показывают tool calls к `studio_*` для каждого живого сценария.
- [ ] Нет дублей ответов от Studio NL responder (он удалён).
- [ ] `STUDIO_NL_COMMANDS_ENABLED=false`, `STUDIO_CONTROL_COMMANDS_ENABLED=false` по умолчанию.
- [ ] `vps-e2e-smoke.sh` → PASS с ожидаемыми SKIP.
- [ ] Бэкап Postgres выполнен после rollout.
