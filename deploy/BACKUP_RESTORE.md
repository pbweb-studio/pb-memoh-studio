# Резервное копирование и восстановление Studio

Разделены **Postgres** (логический дамп) и **KB storage** (файлы на volume). Memoh в эти процедуры не входит.

## Postgres

### Дамп

Скрипт: [`deploy/scripts/backup-postgres.sh`](scripts/backup-postgres.sh).

```bash
export COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"
mkdir -p backups
./deploy/scripts/backup-postgres.sh ./backups
```

### Восстановление из `.sql.gz`

Скрипт (останавливает API/worker/beat, заливает дамп, поднимает сервисы): [`deploy/scripts/restore-postgres.sh`](scripts/restore-postgres.sh).

```bash
./deploy/scripts/restore-postgres.sh ./backups/pb_studio_pg_YYYYMMDDTHHMMSSZ.sql.gz
```

**Важно:** сделайте свежий бэкап текущей БД перед restore. Дамп с `pg_dump --clean` пересоздаёт объекты внутри БД; проверьте версию Postgres.

### Ручной restore (без скрипта)

1. Остановить `studio-api`, `studio-worker`, `studio-beat`.
2. `gunzip -c backups/….sql.gz | docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T studio-postgres psql -U pb_studio -d pb_studio`
3. Запустить сервисы обратно.

---

## KB storage (volume загрузок)

Данные в Docker volume **`pb_studio_prod_kb_uploads`** (полное имя с префиксом проекта: `pb-studio-prod_pb_studio_prod_kb_uploads` при `name: pb-studio-prod` в compose). Путь на хосте зависит от драйвера Docker.

### Бэкап (tar.gz)

```bash
./deploy/scripts/backup-kb-volume.sh ./backups
```

Переопределение имени volume: `KB_VOLUME_NAME=my_volume ./deploy/scripts/backup-kb-volume.sh ./backups`

### Восстановление KB (концепция)

1. Остановить запись в KB: как минимум `studio-api` и `studio-worker` (или весь stack).
2. Очистить или заменить содержимое volume: типичный вариант — временный контейнер с монтированием volume и распаковкой `tar xzf` из бэкапа в `/kb` (каталог внутри volume).
3. Запустить сервисы.

Postgres и файлы KB **независимы**: после restore БД файлы KB нужно восстанавливать отдельно, и наоборот.

---

## Redis

По умолчанию кэш/брокер; персистентные данные приложения — в Postgres. Снапшот Redis volume (`pb_studio_prod_redisdata`) опционален для «теплого» старта очередей; для чистого staging обычно достаточно не бэкапить.
