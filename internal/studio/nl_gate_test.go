package studio

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"testing"

	"github.com/memohai/memoh/internal/channel"
)

func TestPostNLGate_EmptyURL(t *testing.T) {
	t.Setenv("MEMOH_STUDIO_NL_GATE_URL", "")
	sup, err := PostNLGate(context.Background(), NLGateRequest{TelegramChatID: 1, MessageID: 1})
	if err != nil {
		t.Fatal(err)
	}
	if sup {
		t.Fatalf("expected false when URL empty")
	}
}

func TestPostNLGate_DecodeSuppress(t *testing.T) {
	prevDo := nlGateHTTPDo
	defer func() { nlGateHTTPDo = prevDo }()

	nlGateHTTPDo = func(req *http.Request) (*http.Response, error) {
		body := `{"suppress_memoh_assistant":true,"reason":"nl_enqueued"}`
		return &http.Response{
			StatusCode: http.StatusOK,
			Body:       io.NopCloser(bytes.NewBufferString(body)),
			Header:     make(http.Header),
		}, nil
	}

	t.Setenv("MEMOH_STUDIO_NL_GATE_URL", "http://stub/nl-gate")
	t.Setenv("MEMOH_STUDIO_NL_GATE_TOKEN", "tok-test")

	sup, err := PostNLGate(
		context.Background(),
		NLGateRequest{
			TelegramChatID: -100,
			MessageID:      42,
			Text:           "hi",
			RawText:        "hi",
			IsMentioned:    true,
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	if !sup {
		t.Fatalf("expected suppress true")
	}
}

func TestShouldAttemptNLGate_GroupMention(t *testing.T) {
	msg := channel.InboundMessage{
		Channel: channel.ChannelTypeTelegram,
		Conversation: channel.Conversation{
			Type: "supergroup",
		},
		Metadata: map[string]any{"is_mentioned": true},
	}
	if !ShouldAttemptNLGate(msg) {
		t.Fatalf("expected true for supergroup + mention")
	}
}

func TestShouldAttemptNLGate_PrivateSkipped(t *testing.T) {
	msg := channel.InboundMessage{
		Channel: channel.ChannelTypeTelegram,
		Conversation: channel.Conversation{
			Type: "private",
		},
		Metadata: map[string]any{"is_mentioned": true},
	}
	if ShouldAttemptNLGate(msg) {
		t.Fatalf("expected false for private (direct triggers assistant but gate is groups only)")
	}
}
