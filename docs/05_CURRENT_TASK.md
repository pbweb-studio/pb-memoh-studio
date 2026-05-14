# Текущая задача

## После фазы 5a (управляющая группа в Studio)

**Статус:** таблицы, API, system notifications из `my_chat_member`, политика «только control group»; **без** реальной отправки в Telegram и **без** правок Memoh.

**Следующий шаг (не начинать без задачи):** фаза **6** (сводки) **или** подфаза доставки `pending_for_control_group_delivery` в Telegram (возможен ADR на Memoh hook).

**Ограничение:** не слать системные уведомления в client/project чаты; не включать второй бот.
