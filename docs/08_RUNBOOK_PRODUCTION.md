# Runbook: первый production-запуск Studio (чеклист)

Репозиторий **не выполняет** деплой автоматически. Memoh, DNS, выпуск сертификатов и Caddy на реальном домене — **вне scope** этого шага (только после отдельного согласования).

Связанные файлы:

- [`docker-compose.prod.yml`](../docker-compose.prod.yml)
- [`.env.prod.example`](../.env.prod.example) → скопировать в `.env.prod` (файл в `.gitignore`)
- [`deploy/BACKUP_RESTORE.md`](../deploy/BACKUP_RESTORE.md)
- [`deploy/caddy/Caddyfile.example`](../deploy/caddy/Caddyfile.example)

Локальная разработка на Windows: см. также [`docs/07_RUNBOOK_WINDOWS.md`](07_RUNBOOK_WINDOWS.md).

---

## 1. Подготовка сервера

- [ ] Установлены Docker и Docker Compose plugin.
- [ ] Клонирован репозиторий (ветка с нужным релизом).
- [ ] Скопирован шаблон: `cp .env.prod.example .env.prod`.
- [ ] В `.env.prod` заданы **сильные** `POSTGRES_PASSWORD` и совпадающий пароль в `DATABASE_URL`.
- [ ] Задан **`STUDIO_ADMIN_TOKEN`** (длинная случайная строка).
- [ ] При необходимости исходящих сообщений Telegram / KB import: **`TELEGRAM_BOT_TOKEN`**.

---

## 2. Сборка и миграции

Из корня репозитория:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml build
docker compose --env-file .env.prod -f docker-compose.prod.yml run --rm studio-migrate
```

Или одним `up`: сервис `studio-migrate` выполнится как `condition: service_completed_successfully` перед API.

Убедиться, что миграции дошли до head:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs studio-migrate
```

---

## 3. Запуск stack

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

Сервисы: `studio-postgres`, `studio-redis`, `studio-api`, `studio-worker`, `studio-beat`.

---

## 4. Feature flags

Включайте по одному, после проверки (в `.env.prod` + `docker compose up -d` для пересоздания контейнеров с новым env):

| Флаг | Назначение |
|------|------------|
| `STUDIO_SYSTEM_NOTIFICATIONS_ENABLED` | Исходящие system notifications в control group |
| `STUDIO_SUMMARY_GENERATION_ENABLED` / `STUDIO_SUMMARY_DELIVERY_ENABLED` | Сводки |
| `STUDIO_CONTROL_COMMANDS_ENABLED` | Команды из control group |
| `STUDIO_SLA_ENABLED` | SLA |
| `STUDIO_KB_ENABLED` и далее embeddings/RAG | База знаний |
| `STUDIO_HISTORY_IMPORT_ENABLED` | Импорт Telegram Desktop JSON |

---

## 5. Проверки после старта

- [ ] **`GET /health`** (например `curl -fsS http://127.0.0.1:8000/health` с хоста, если так опубликован порт).
- [ ] **`/admin/login`** — веб-админка при заданном `STUDIO_ADMIN_TOKEN` (см. фазы 13a–13c).
- [ ] Логи API/worker без утечек секретов: `docker compose … logs studio-api --tail 200`.

---

## 6. Smoke: control group

- [ ] В Telegram задана управляющая группа и бот (Memoh / внешняя конфигурация — не этот runbook).
- [ ] При включённых командах: простая команда из CG (например help/summary list — по вашей постановке) и ответ в чате.

---

## 7. Бэкап

См. [`deploy/BACKUP_RESTORE.md`](../deploy/BACKUP_RESTORE.md). Регулярно: логический дамп Postgres; отдельно — volume KB при использовании загрузок.

---

## 8. Reverse proxy (позже)

Шаблон: [`deploy/caddy/Caddyfile.example`](../deploy/caddy/Caddyfile.example). Замените заглушки домена и upstream; включите TLS после настройки DNS.

---

## Проверка compose без секретов

Допустимые значения по умолчанию встроены в `docker-compose.prod.yml` для команды:

```bash
docker compose -f docker-compose.prod.yml config
```

Для реального окружения всегда используйте `--env-file .env.prod`.
