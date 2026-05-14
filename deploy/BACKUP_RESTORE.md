# Резервное копирование и восстановление Studio (Postgres + KB storage)

## Postgres

### Дамп

Скрипт: [`deploy/scripts/backup-postgres.sh`](scripts/backup-postgres.sh) (bash, на сервере с Docker).

### Восстановление (логический дамп `.sql.gz`)

1. Остановите сервисы, которые пишут в БД (как минимум `studio-api`, `studio-worker`, `studio-beat`):

   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml stop studio-api studio-worker studio-beat
   ```

2. Распакуйте и восстановите в **пустую** БД (или после `DROP` согласно политике; `--clean` в дампе помогает пересоздать объекты):

   ```bash
   gunzip -c backups/pb_studio_pg_YYYYMMDD.sql.gz | docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T studio-postgres \
     psql -U pb_studio -d pb_studio
   ```

3. Запустите сервисы обратно:

   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml start studio-api studio-worker studio-beat
   ```

**Важно:** перед восстановлением на проде сделайте свежий бэкап текущего состояния. Проверьте совместимость версии Postgres с дампом.

## KB storage (файлы загрузок)

Данные лежат в Docker volume **`pb_studio_prod_kb_uploads`** (путь на хосте зависит от драйвера Docker).

Варианты бэкапа:

- **Остановить запись**, смонтировать volume во временный контейнер и скопировать содержимое (`docker run --rm -v pb_studio_prod_kb_uploads:/kb -v "$PWD/kb-backup":/out alpine tar czf /out/kb.tgz -C /kb .`).
- Или снимайте снапшоты диска ВМ, если volume на локальном диске.

После восстановления Postgres файлы в KB не восстанавливаются автоматически — восстанавливайте volume отдельно.
