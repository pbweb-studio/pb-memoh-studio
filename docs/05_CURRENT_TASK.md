# Текущая задача

## После фазы 5b (outbound system notifications)

**Статус:** доставка записей `studio_system_notifications` в активную control group через Bot API `sendMessage` (при `STUDIO_SYSTEM_NOTIFICATIONS_ENABLED=true` и валидном `TELEGRAM_BOT_TOKEN`); Celery-задача и админ-эндпоинты; Memoh не менялся.

**Следующий шаг (не начинать без задачи):** фаза **6** (сводки).

**Ограничение:** не слать системные уведомления в client/project/internal/service чаты; не включать второй бот; не запускать polling/webhook из Studio.
