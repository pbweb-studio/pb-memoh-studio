package telegram

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

func TestPostStudioTelegramMirror_DisabledNoHTTP(t *testing.T) {
	orig := studioMirrorHTTPDo
	var calls atomic.Int32
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		calls.Add(1)
		return orig(req)
	}
	t.Cleanup(func() { studioMirrorHTTPDo = orig })
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "false")
	t.Setenv("STUDIO_EVENTS_URL", "http://127.0.0.1:9/should-not-run")
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS", "200")

	a := NewTelegramAdapter(slog.Default())
	a.postStudioTelegramMirror("cfg-1", tgbotapi.Update{UpdateID: 1})
	if calls.Load() != 0 {
		t.Fatalf("expected no HTTP when mirror disabled, got %d calls", calls.Load())
	}
}

func TestPostStudioTelegramMirror_EnabledNoURLNoHTTP(t *testing.T) {
	orig := studioMirrorHTTPDo
	var calls atomic.Int32
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		calls.Add(1)
		return orig(req)
	}
	t.Cleanup(func() { studioMirrorHTTPDo = orig })
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", "")
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS", "200")

	a := NewTelegramAdapter(slog.Default())
	a.postStudioTelegramMirror("cfg-1", tgbotapi.Update{UpdateID: 2})
	if calls.Load() != 0 {
		t.Fatalf("expected no HTTP without STUDIO_EVENTS_URL, got %d calls", calls.Load())
	}
}

func TestPostStudioTelegramMirror_EnabledPostsJSON(t *testing.T) {
	orig := studioMirrorHTTPDo
	t.Cleanup(func() { studioMirrorHTTPDo = orig })

	var gotMethod, gotCT, gotAuth string
	var body []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotCT = r.Header.Get("Content-Type")
		gotAuth = r.Header.Get("Authorization")
		var err error
		body, err = io.ReadAll(r.Body)
		if err != nil {
			t.Fatalf("read body: %v", err)
		}
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)

	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		return srv.Client().Do(req)
	}

	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", srv.URL+"/events/telegram")
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS", "500")
	t.Setenv("MEMOH_STUDIO_EVENTS_TOKEN", "secret-memoh")

	a := NewTelegramAdapter(slog.Default())
	u := tgbotapi.Update{UpdateID: 99, Message: &tgbotapi.Message{MessageID: 5, Text: "hi"}}
	a.postStudioTelegramMirror("cfg-x", u)

	if gotMethod != http.MethodPost {
		t.Fatalf("method = %q, want POST", gotMethod)
	}
	if gotCT != "application/json" {
		t.Fatalf("content-type = %q", gotCT)
	}
	if gotAuth != "Bearer secret-memoh" {
		t.Fatalf("authorization = %q", gotAuth)
	}
	var decoded tgbotapi.Update
	if err := json.Unmarshal(body, &decoded); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if decoded.UpdateID != 99 {
		t.Fatalf("update_id = %d", decoded.UpdateID)
	}
}

func TestPostStudioTelegramMirror_FallsBackToStudioIngestToken(t *testing.T) {
	orig := studioMirrorHTTPDo
	t.Cleanup(func() { studioMirrorHTTPDo = orig })

	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		return srv.Client().Do(req)
	}

	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", srv.URL+"/events/telegram")
	t.Setenv("MEMOH_STUDIO_EVENTS_TOKEN", "")
	t.Setenv("STUDIO_EVENTS_INGEST_TOKEN", "from-studio-env")

	a := NewTelegramAdapter(slog.Default())
	a.postStudioTelegramMirror("cfg", tgbotapi.Update{UpdateID: 3})
	if gotAuth != "Bearer from-studio-env" {
		t.Fatalf("authorization = %q", gotAuth)
	}
}

func TestPostStudioTelegramMirror_NoAuthWhenNoToken(t *testing.T) {
	orig := studioMirrorHTTPDo
	t.Cleanup(func() { studioMirrorHTTPDo = orig })

	var gotAuth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth = r.Header.Get("Authorization")
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		return srv.Client().Do(req)
	}

	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", srv.URL+"/events/telegram")
	t.Setenv("MEMOH_STUDIO_EVENTS_TOKEN", "")
	t.Setenv("STUDIO_EVENTS_INGEST_TOKEN", "")

	a := NewTelegramAdapter(slog.Default())
	a.postStudioTelegramMirror("cfg", tgbotapi.Update{UpdateID: 4})
	if gotAuth != "" {
		t.Fatalf("expected no Authorization header, got %q", gotAuth)
	}
}

func TestPostStudioTelegramMirror_Status500DoesNotPanic(t *testing.T) {
	orig := studioMirrorHTTPDo
	t.Cleanup(func() { studioMirrorHTTPDo = orig })

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	t.Cleanup(srv.Close)
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		return srv.Client().Do(req)
	}

	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", srv.URL+"/events/telegram")
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS", "200")

	a := NewTelegramAdapter(slog.Default())
	a.postStudioTelegramMirror("cfg", tgbotapi.Update{UpdateID: 5})
}

func TestPostStudioTelegramMirror_TimeoutDoesNotPanic(t *testing.T) {
	orig := studioMirrorHTTPDo
	t.Cleanup(func() { studioMirrorHTTPDo = orig })

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		time.Sleep(500 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		return srv.Client().Do(req)
	}

	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", srv.URL+"/events/telegram")
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS", "30")

	a := NewTelegramAdapter(slog.Default())
	a.postStudioTelegramMirror("cfg", tgbotapi.Update{UpdateID: 6})
}

func TestPostStudioTelegramMirror_UpdateBodyUnchanged(t *testing.T) {
	orig := studioMirrorHTTPDo
	t.Cleanup(func() { studioMirrorHTTPDo = orig })

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(srv.Close)
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		return srv.Client().Do(req)
	}

	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", srv.URL+"/events/telegram")

	u := tgbotapi.Update{UpdateID: 42, Message: &tgbotapi.Message{MessageID: 1, Text: "x"}}
	before, err := json.Marshal(u)
	if err != nil {
		t.Fatal(err)
	}
	a := NewTelegramAdapter(slog.Default())
	a.postStudioTelegramMirror("cfg", u)
	after, err := json.Marshal(u)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatalf("update mutated: before %s after %s", before, after)
	}
}

func TestMirrorTelegramUpdateToStudioAsync_DoesNotBlock(t *testing.T) {
	orig := studioMirrorHTTPDo
	t.Cleanup(func() { studioMirrorHTTPDo = orig })

	block := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		<-block
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(func() { close(block); srv.Close() })
	studioMirrorHTTPDo = func(req *http.Request) (*http.Response, error) {
		return srv.Client().Do(req)
	}

	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_ENABLED", "true")
	t.Setenv("STUDIO_EVENTS_URL", srv.URL+"/events/telegram")
	t.Setenv("MEMOH_TELEGRAM_EVENT_MIRROR_TIMEOUT_MS", "5000")

	a := NewTelegramAdapter(slog.Default())
	start := time.Now()
	a.mirrorTelegramUpdateToStudioAsync("cfg", tgbotapi.Update{UpdateID: 8})
	if time.Since(start) > 50*time.Millisecond {
		t.Fatalf("async mirror should return quickly, took %v", time.Since(start))
	}
}
