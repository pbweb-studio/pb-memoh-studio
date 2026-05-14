# Runbook: Windows / локальная разработка

## Предпосылки

- Windows 10/11.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) с WSL2 backend (рекомендуется).
- Git, Cursor.

## Секреты

1. Скопируйте `.env.example` → `.env.local` (если файла ещё нет — его создаст агент при необходимости).
2. Заполните ключи (OpenAI, Telegram и т.д.) по мере готовности фич; без секретов можно поднимать только инфраструктуру.

## Инфраструктура Studio (Postgres + Redis)

Из корня репозитория (агент выполняет сам):

```powershell
docker compose -f docker-compose.local.yml up -d
```

Локальный Redis студии по умолчанию слушает **6380** на хосте (см. `STUDIO_REDIS_PORT` в `docker-compose.local.yml`), чтобы не конфликтовать с другим Redis. Пример `REDIS_URL`: `redis://127.0.0.1:6380/0`.

## Memoh

Штатный запуск Memoh — по документации upstream (`docker-compose.yml` в корне или `docker/`). На Фазе 0 слой студии не подключается к Memoh автоматически.

## Полезные пути

- Документация: `docs/`.
- Контекст для ИИ: `docs/AI_CONTEXT.md`.
- Память проекта: `memory-bank/`.
