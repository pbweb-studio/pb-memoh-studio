# Active context

**Сейчас:** **VPS 148.253.209.54** — **`/opt/pb-studio/pb-memoh-studio`**, **`origin/pb-studio/main`** (актуальный **HEAD** — по **`git rev-parse HEAD`** на сервере после **`git pull`/`reset`**). Функциональный фикс Studio — **`8af1537d`**. Пересобраны только **studio-api / studio-worker / studio-beat**; Memoh без пересборки.

**Ссылки:** Studio Admin **https://jar.pb-web.ru/admin/** · Memoh Web **https://memo.pb-web.ru**

**Проверено:** **getMe** → **jarvispbweb_bot** / **ИИ Purple Bear**; **webhook пустой**; **pending_update_count=0**; **`GET /control-group`** — active, **Управление Jarvis**, **telegram_chat_id=-1003903704506**; **`vps-e2e-smoke.sh`** — **PASS** (**`/admin/assistant-rules`** **200**). **SKIP:** history import, live Telegram (блок 12), pytest в prod-образе.

**Telegram (2026-05-14, скрины):** личка **`mvp-private-001`**, **`/kb_help`** и **`/kb_help@jarvispbweb_bot`** в control group — ок.

**Зеркало:** в **`studio_messages`** есть текст с **`mvp-group-mention-001`** (как минимум одна строка). Визуально в группе: один нормальный ответ Memoh, без дублей / «……» / зависшего typing — **USER_CONFIRM_REQUIRED**, если нужна свежая проверка после выката.

**Security:** ротация **`TELEGRAM_BOT_TOKEN`** не выполняется по решению оператора (**остаточный риск принят**); при новой утечке — ротировать.

**Следующий шаг:** только отдельные задачи (**6+**, расширение админки и т.д.); MVP по smoke и админ-маршрутам правил — **закрыт**.
