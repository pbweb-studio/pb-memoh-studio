package studio

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/memohai/memoh/internal/channel"
)

// nlGateHTTPDo is swapped in tests.
var nlGateHTTPDo = func(req *http.Request) (*http.Response, error) {
	return http.DefaultClient.Do(req)
}

// NLGateRequest mirrors Studio POST /integrations/memoh/nl-gate JSON body.
type NLGateRequest struct {
	TelegramChatID int64  `json:"telegram_chat_id"`
	MessageID      int    `json:"message_id"`
	UpdateID       *int   `json:"update_id,omitempty"`
	Text           string `json:"text"`
	RawText        string `json:"raw_text"`
	FromID         *int64 `json:"from_id,omitempty"`
	IsMentioned    bool   `json:"is_mentioned"`
	IsReplyToBot   bool   `json:"is_reply_to_bot"`
	IsBot          bool   `json:"is_bot"`
}

// NLGateResponse mirrors Studio JSON response.
type NLGateResponse struct {
	SuppressMemohAssistant bool   `json:"suppress_memoh_assistant"`
	Reason                 string `json:"reason"`
}

func nlGateTimeout() time.Duration {
	ms := 2500
	if s := strings.TrimSpace(os.Getenv("MEMOH_STUDIO_NL_GATE_TIMEOUT_MS")); s != "" {
		if v, err := strconv.Atoi(s); err == nil && v > 0 {
			ms = v
		}
	}
	return time.Duration(ms) * time.Millisecond
}

func nlGateBearer() string {
	if t := strings.TrimSpace(os.Getenv("MEMOH_STUDIO_NL_GATE_TOKEN")); t != "" {
		return t
	}
	return strings.TrimSpace(os.Getenv("MEMOH_STUDIO_EVENTS_TOKEN"))
}

// PostNLGate calls Studio nl-gate. Empty URL: (false, nil) fail-open.
// Configured URL: network/HTTP/decode errors return (false, err); HTTP non-2xx returns (false, err) so Memoh can suppress duplicate assistant replies.
func PostNLGate(ctx context.Context, body NLGateRequest) (bool, error) {
	url := strings.TrimSpace(os.Getenv("MEMOH_STUDIO_NL_GATE_URL"))
	if url == "" {
		return false, nil
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return false, err
	}
	timeout := nlGateTimeout()
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(cctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return false, err
	}
	req.Header.Set("Content-Type", "application/json")
	if tok := nlGateBearer(); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := nlGateHTTPDo(req)
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return false, fmt.Errorf("studio nl gate: HTTP %s", resp.Status)
	}
	var out NLGateResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return false, err
	}
	return out.SuppressMemohAssistant, nil
}

// ShouldAttemptNLGate is true for Telegram group/supergroup when assistant would trigger.
func ShouldAttemptNLGate(msg channel.InboundMessage) bool {
	if msg.Channel != channel.ChannelTypeTelegram {
		return false
	}
	ct := channel.NormalizeConversationType(msg.Conversation.Type)
	if ct != "group" && ct != "supergroup" {
		return false
	}
	return shouldTriggerAssistantResponse(msg)
}

func shouldTriggerAssistantResponse(msg channel.InboundMessage) bool {
	if isDirectConversationType(msg.Conversation.Type) {
		return true
	}
	if metadataBool(msg.Metadata, "is_mentioned") {
		return true
	}
	if metadataBool(msg.Metadata, "is_reply_to_bot") {
		return true
	}
	return false
}

func isDirectConversationType(convType string) bool {
	switch channel.NormalizeConversationType(convType) {
	case "private", "direct", "dm":
		return true
	default:
		return false
	}
}

func metadataBool(md map[string]any, key string) bool {
	if md == nil {
		return false
	}
	v, ok := md[key]
	if !ok {
		return false
	}
	b, ok := v.(bool)
	return ok && b
}
