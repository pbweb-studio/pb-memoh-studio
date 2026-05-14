# Публичные сайты pb-web.ru на одном VPS (Caddy → локальные порты Docker).
# Установка: скопировать на сервер как /etc/caddy/Caddyfile (или import из основного файла),
# затем: caddy validate --config /etc/caddy/Caddyfile && caddy reload --config /etc/caddy/Caddyfile
#
# Требования DNS: A/AAAA записи jar.pb-web.ru и memo.pb-web.ru на IP сервера.
# Memoh web (memohai/web) слушает 127.0.0.1:8082; статика дергает API по пути /api (nginx внутри web).

jar.pb-web.ru {
	encode gzip zstd
	reverse_proxy 127.0.0.1:8000
}

memo.pb-web.ru {
	encode gzip zstd
	reverse_proxy 127.0.0.1:8082
}
