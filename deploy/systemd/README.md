# systemd units для PB Memoh Studio

## memoh-orphan-cleanup.{service,timer}

Watchdog против повисших user-turn в `bot_history_messages` (Memoh Postgres).

**ВАЖНО — область применения:** скрипт работает **только** в DM-сессиях
(`bot_channel_routes.conversation_type = 'private'`). В групповых чатах
бот легитимно молчит на сообщениях, на которые не должен отвечать
(ACL / роль `client_chat` / `service_chat` / отсутствие mention), и
трактовать такие user-row как orphan нельзя — это сотрёт историю
активного чата. Watchdog в текущем виде group-чаты **игнорирует**.

### Установка на VPS

Юниты лежат в репозитории. Чтобы systemd их подхватил, нужно симлинкнуть
их в `/etc/systemd/system/` (или скопировать).

```bash
cd /opt/pb-studio/pb-memoh-studio
sudo ln -sf "$(pwd)/deploy/systemd/memoh-orphan-cleanup.service" /etc/systemd/system/memoh-orphan-cleanup.service
sudo ln -sf "$(pwd)/deploy/systemd/memoh-orphan-cleanup.timer"   /etc/systemd/system/memoh-orphan-cleanup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now memoh-orphan-cleanup.timer
```

### Проверка

```bash
systemctl list-timers memoh-orphan-cleanup.timer
journalctl -u memoh-orphan-cleanup.service --since "10 min ago"
tail -n 50 /var/log/memoh-orphan-cleanup.log
```

### Откат

```bash
sudo systemctl disable --now memoh-orphan-cleanup.timer
sudo rm /etc/systemd/system/memoh-orphan-cleanup.timer /etc/systemd/system/memoh-orphan-cleanup.service
sudo systemctl daemon-reload
```

### Параметры (через env в .service или вручную)

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `GRACE_SECONDS` | `120` | Возраст user-row, после которого считается orphan |
| `MEMOH_PG_CONTAINER` | `memoh-jar-postgres-1` | Имя контейнера Memoh-Postgres |
| `MEMOH_PG_USER` | `memoh` | Пользователь БД |
| `MEMOH_PG_DB` | `memoh` | Имя БД |
| `DRY_RUN` | `0` | `1` — только показать orphan-ы, не удалять |
| `LOG_FILE` | `/var/log/memoh-orphan-cleanup.log` | Лог скрипта |

### Что и почему делает скрипт

См. шапку `deploy/scripts/memoh-orphan-cleanup.sh` и ADR в `docs/06_DECISIONS.md` секция «Memoh DM history hygiene (orphan watchdog)».
