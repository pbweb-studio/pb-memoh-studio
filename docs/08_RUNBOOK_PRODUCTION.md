# Runbook: staging / первый production-запуск Studio (readiness)

Репозиторий **не выполняет** деплой автоматически; зафиксированный **staging** Studio: **jar.pb-web.ru** (см. раздел F). Memoh в этом процессе не меняется.

Связанные файлы:

- [`docker-compose.prod.yml`](../docker-compose.prod.yml)
- [`.env.prod.example`](../.env.prod.example) → скопировать в `.env.prod` (в `.gitignore`)
- [`deploy/scripts/validate_env_prod.py`](../deploy/scripts/validate_env_prod.py) — проверка обязательных и условных переменных (секреты не печатает)
- [`deploy/scripts/smoke-prod.sh`](../deploy/scripts/smoke-prod.sh) — smoke после старта API
- [`deploy/scripts/backup-postgres.sh`](../deploy/scripts/backup-postgres.sh), [`restore-postgres.sh`](../deploy/scripts/restore-postgres.sh), [`backup-kb-volume.sh`](../deploy/scripts/backup-kb-volume.sh)
- [`deploy/BACKUP_RESTORE.md`](../deploy/BACKUP_RESTORE.md)
- [`deploy/caddy/Caddyfile.example`](../deploy/caddy/Caddyfile.example)

Локальная разработка на Windows: [`docs/07_RUNBOOK_WINDOWS.md`](07_RUNBOOK_WINDOWS.md).

---

## A. Полный checklist (VPS → сервисы → smoke)

Отмечайте по шагам перед первым приёмом трафика.

### 1. Подготовка VPS

- [ ] ОС обновлена, SSH по ключу, firewall (минимум: 22 + при необходимости 80/443 для Caddy позже).
- [ ] Создан непривилегированный пользователь для деплоя (опционально; либо документированный `root` по политике).
- [ ] Достаточно RAM/диска под Postgres + Redis + образы (ориентир — см. нагрузку staging).

### 2. Docker и Compose

- [ ] Установлен **Docker Engine** и плагин **Compose V2** (`docker compose version`).
- [ ] Сервис Docker включён в автозагрузку: `systemctl enable --now docker` (systemd).

### 3. Код и переменные окружения

- [ ] Клонирован репозиторий, нужная ветка/тег.
- [ ] `cp .env.prod.example .env.prod`
- [ ] Заполнены **[REQUIRED]** поля в `.env.prod` (пароль Postgres, `DATABASE_URL`, `STUDIO_ADMIN_TOKEN`).
- [ ] `python3 deploy/scripts/validate_env_prod.py .env.prod` → **RESULT: OK** (на Windows без `python3` в PATH: `py -3 deploy/scripts/validate_env_prod.py .env.prod`).

### 4. Сборка образов и pull базовых образов

Из корня репозитория:

```bash
export COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"
$COMPOSE pull
$COMPOSE build studio-api studio-worker studio-beat studio-migrate
```

### 5. Миграции Alembic

```bash
$COMPOSE run --rm studio-migrate
# или сразу up -d: migrate выполнится до старта API по depends_on
$COMPOSE logs studio-migrate
```

Убедитесь, что контейнер `studio-migrate` завершился успешно (exit 0).

### 6. Запуск stack

```bash
$COMPOSE up -d
```

Сервисы: `studio-postgres`, `studio-redis`, `studio-api`, `studio-worker`, `studio-beat`.

### 7. Проверка `/health`

```bash
curl -fsS http://127.0.0.1:8000/health
```

(Порт/хост — как в `STUDIO_DOCKER_PUBLISH` в compose / `.env.prod`.)

### 8. Вход в `/admin`

- [ ] Открыть в браузере `http(s)://<хост>:<порт>/admin/login` (или через Caddy позже).
- [ ] Ввести **`STUDIO_ADMIN_TOKEN`** в форму логина (токен не передавать в чатах/скриншотах).

### 9. Control group (ручной smoke)

- [ ] В Telegram настроены управляющая группа и бот (Memoh / внешняя конфигурация — вне этого runbook).
- [ ] При `STUDIO_CONTROL_COMMANDS_ENABLED=true`: тестовая команда из CG (например `/summary_chats` или help по вашей матрице) и ответ в чате.

### 10. Тест `/kb_ask` (ручной, только если KB+RAG включены)

- [ ] `STUDIO_KB_ENABLED=true`, embeddings/search настроены, `STUDIO_KB_RAG_ENABLED=true`, заданы `STUDIO_KB_CHAT_*`.
- [ ] Из **control group**: `/kb_ask <короткий вопрос>` — ожидается ответ бота (или диагностируемая ошибка конфигурации в логах, без утечки ключей).

### 11. Тест бэкапа Postgres

```bash
mkdir -p backups
./deploy/scripts/backup-postgres.sh ./backups
ls -la ./backups/pb_studio_pg_*.sql.gz
```

На **чистом staging** допустимо сразу после бэкапа проверить распаковку дампа в отдельную БД или следовать [`deploy/BACKUP_RESTORE.md`](../deploy/BACKUP_RESTORE.md) (на проде — только в окно обслуживания).

### 12. Бэкап KB storage (если используете загрузки в KB)

```bash
./deploy/scripts/backup-kb-volume.sh ./backups
```

### 13. Автоматический smoke (curl)

```bash
export STUDIO_BASE_URL=http://127.0.0.1:8000
# опционально из секрет-хранилища, не в истории shell:
# export STUDIO_ADMIN_TOKEN='...'
./deploy/scripts/smoke-prod.sh
```

Скрипт **не печатает** токены. При незаданном `STUDIO_ADMIN_TOKEN` в окружении скрипта проверка Bearer к `/projects` пропускается.

**Правило (после инцидента 14c):** не запускать обёртки деплоя/smoke с **`bash -x`** / **`set -x`**, если в том же процессе выполняется **`export VAR=…`** для секретов (`STUDIO_ADMIN_TOKEN`, `TELEGRAM_BOT_TOKEN`, API keys) — иначе значение попадёт в stdout/stderr (CI, Cursor, `journalctl`). Использовать **`set -eu`** (без `x`) или явный редирект логов без трассировки export.

---

## B. Feature flags (включать по одному)

После изменения `.env.prod`: `docker compose … up -d` (пересоздать контейнеры при смене env).

| Флаг | Назначение |
|------|------------|
| `STUDIO_SYSTEM_NOTIFICATIONS_ENABLED` | Исходящие system notifications в control group |
| `STUDIO_SUMMARY_GENERATION_ENABLED` / `STUDIO_SUMMARY_DELIVERY_ENABLED` | Сводки (доставка → нужен `TELEGRAM_BOT_TOKEN`) |
| `STUDIO_CONTROL_COMMANDS_ENABLED` | Команды из control group |
| `STUDIO_SLA_ENABLED` | SLA |
| `STUDIO_KB_ENABLED` + embeddings + RAG | База знаний и `/kb_ask` |
| `STUDIO_HISTORY_IMPORT_ENABLED` | Импорт Telegram Desktop JSON |

---

## C. Логи и безопасность

- [ ] `docker compose … logs studio-api --tail 200` — без утечек секретов.
- [ ] `STUDIO_ADMIN_TOKEN` и `TELEGRAM_BOT_TOKEN` не в репозитории и не в публичных логах CI.
- [ ] **`.env.prod`** в `.gitignore`, на сервере только **`chmod 600`**, не копировать в чаты и не коммитить.
- [ ] Временный файл с одноразовым токеном на VPS (например **`/root/.studio_admin_token_once`**): после сохранения значения в менеджер секретов — **`rm`** на сервере.

### Инцидент 14c (раскрытие токена в логе)

При отладочном запуске вспомогательного shell с **`set -x`** в лог попала строка **`export STUDIO_ADMIN_TOKEN=…`**. **Меры:** токен на VPS **немедленно ротирован**; в репозитории и в **docs/** значения токенов **не** фиксировались. **Правило:** см. блок выше про `bash -x` и секреты; то же относится к любым deploy-обёрткам вокруг `smoke-prod.sh` и `docker compose`.

---

## D. Reverse proxy (позже)

Шаблон: [`deploy/caddy/Caddyfile.example`](../deploy/caddy/Caddyfile.example). Подставить домен, email для ACME, upstream `127.0.0.1:8000` после согласования DNS.

---

## E. Проверка compose без `.env.prod`

В `docker-compose.prod.yml` заданы безопасные значения по умолчанию для команды:

```bash
docker compose -f docker-compose.prod.yml config
```

Для реального окружения всегда используйте `--env-file .env.prod`.

---

## F. Зафиксированный staging: jar.pb-web.ru (фаза 14c)

| Параметр | Значение |
|-----------|----------|
| VPS (основной IP) | `148.253.209.54` |
| Публичный URL API / health | `https://jar.pb-web.ru` |
| Админка | `https://jar.pb-web.ru/admin/login` |
| Compose | `docker compose --env-file .env.prod -f docker-compose.prod.yml` из `/opt/pb-studio/pb-memoh-studio` |
| Секреты | только в `.env.prod` на сервере; **не** в git (см. `.gitignore`) |
| Якорь кода миграции в репо | `f8dbd06e09f7b081733061ca1c6aefcf9b727afb` |

Проверено на стенде: **health**, **admin**, **smoke-prod.sh**, **backup-postgres.sh**. **Memoh** репозитория и образы Memoh **не** затрагивались.

Одноразовый перенос токена админки на хост (если использовался): **`/root/.studio_admin_token_once`** — после копирования в менеджер секретов **удалить** (`rm` на сервере).

