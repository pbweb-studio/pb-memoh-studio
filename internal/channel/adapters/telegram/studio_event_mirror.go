package telegram

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// studioMirrorHTTPDo is swapped in tests to avoid real network and to assert requests.
var studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
	return http.DefaultClient.Do(req)
}

func telegramStudioEventMirrorEnabled() bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED")))
	return v == "1" || v == "true" || v == "yes"
}

func studioTelegramMirrorTimeout() time.Duration {
	ms := 1000
	if s := strings.TrimSpace(os.Getenv("MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS")); s != "" {
		if v, err := strconv.Atoi(s); err == nil && v > 0 {
			ms = v
		}
	}
	return time.Duration(ms) * time.Millisecond
}

func studioTelegramMirrorBearerToken() string {
	if t := strings.TrimSpace(os.Getenv("MEMOH_STUDIO_EVENTS_TOKEN")); t != "" {
		return t
	}
	return strings.TrimSpace(os.Getenv("STUDIO_EVENTS_INGEST_TOKEN"))
}

// postStudioTelegramMirror sends the raw Telegram update JSON to Studio Event Mirror.
// It must never panic and must not block the polling loop (call from a goroutine only).
func (a *TelegramAdapter) postStudioTelegramMirror(configID string, update tgbotapi.Update) {
	if !telegramStudioEventMirrorEnabled() {
		return
	}
	url := strings.TrimSpace(os.Getenv("STUDIO_EVENTS_URL"))
	if url == "" {
		return
	}
	body, err := json.Marshal(update)
	if err != nil {
		if a.logger != nil {
			a.logger.Warn("studio event mirror: marshal update failed",
				slog.String("config_id", configID),
				slog.Any("error", err),
			)
		}
		return
	}
	timeout := studioTelegramMirrorTimeout()
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		if a.logger != nil {
			a.logger.Warn("studio event mirror: build request failed",
				slog.String("config_id", configID),
				slog.Any("error", err),
			)
		}
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if tok := studioTelegramMirrorBearerToken(); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := studioMirrorHTTPDo(req)
	if err != nil {
		if a.logger != nil {
			a.logger.Warn("studio event mirror: request failed",
				slog.String("config_id", configID),
				slog.Any("error", err),
			)
		}
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		if a.logger != nil {
			a.logger.Warn("studio event mirror: non-success status",
				slog.String("config_id", configID),
				slog.Int("status", resp.StatusCode),
			)
		}
	}
}

func (a *TelegramAdapter) mirrorTelegramUpdateToStudioAsync(configID string, update tgbotapi.Update) {
	go func() {
		defer func() {
			if r := recover(); r != nil && a.logger != nil {
				a.logger.Error("studio event mirror: panic recovered",
					slog.String("config_id", configID),
					slog.Any("recover", r),
				)
			}
		}()
		a.postStudioTelegramMirror(configID, update)
	}()
}
