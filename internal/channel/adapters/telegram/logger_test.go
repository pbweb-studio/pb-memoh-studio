package telegram

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"
)

func TestSlogBotLogger_Println(t *testing.T) {
	t.Parallel()

	var buf bytes.Buffer
	log := slog.New(slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelDebug}))
	w := &slogBotLogger{log: log}

	w.Println("hello")
	if !bytes.Contains(buf.Bytes(), []byte("level=WARN")) {
		t.Fatalf("expected WARN level in output: %s", buf.String())
	}
	if !bytes.Contains(buf.Bytes(), []byte("hello")) {
		t.Fatalf("expected message in output: %s", buf.String())
	}

	buf.Reset()
	w.Println("err", 123)
	out := buf.String()
	if !bytes.Contains(buf.Bytes(), []byte("err")) || !bytes.Contains(buf.Bytes(), []byte("123")) {
		t.Fatalf("expected err and 123 in output: %s", out)
	}
}

func TestSlogBotLogger_Printf(t *testing.T) {
	t.Parallel()

	var buf bytes.Buffer
	log := slog.New(slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelDebug}))
	w := &slogBotLogger{log: log}

	w.Printf("retrying in %d seconds...", 3)
	if !bytes.Contains(buf.Bytes(), []byte("level=WARN")) {
		t.Fatalf("expected WARN level: %s", buf.String())
	}
	if !bytes.Contains(buf.Bytes(), []byte("retrying in 3 seconds")) {
		t.Fatalf("expected formatted message: %s", buf.String())
	}
}

func TestRedactTelegramBotAPIURLs_getUpdatesErrorDoesNotLeakToken(t *testing.T) {
	t.Parallel()

	secret := "AAHqTtestSecretReplaceMe"
	raw := `Post "https://api.telegram.org/bot123456789:` + secret + `/getUpdates": context deadline exceeded`
	got := redactTelegramBotAPIURLs(raw)
	if strings.Contains(got, secret) {
		t.Fatalf("token leaked in redacted string: %q", got)
	}
	if !strings.Contains(got, "/bot<redacted>/getUpdates") {
		t.Fatalf("expected masked path, got %q", got)
	}
}

func TestSlogBotLogger_Println_redactsGetUpdatesURL(t *testing.T) {
	t.Parallel()

	secret := "AAHqTtestSecretReplaceMe"
	var buf bytes.Buffer
	log := slog.New(slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelDebug}))
	w := &slogBotLogger{log: log}

	w.Println(`Post "https://api.telegram.org/bot123456789:` + secret + `/getUpdates": Client.Timeout exceeded`)
	out := buf.String()
	if strings.Contains(out, secret) {
		t.Fatalf("token leaked in slog output: %q", out)
	}
	if !strings.Contains(out, "bot<redacted>") {
		t.Fatalf("expected redacted bot path in output: %q", out)
	}
}
