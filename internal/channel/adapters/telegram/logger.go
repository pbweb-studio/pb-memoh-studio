package telegram

import (
	"fmt"
	"log/slog"
	"regexp"
	"sync"
)

var (
	telegramFileBotPathURL = regexp.MustCompile(`(?i)/file/bot\d+:[a-z0-9_-]+/`)
	telegramBotPathURL     = regexp.MustCompile(`(?i)/bot\d+:[a-z0-9_-]+/`)
)

// redactTelegramBotAPIURLs masks bot tokens in Telegram Bot API URLs (e.g. .../bot<token>/getUpdates).
func redactTelegramBotAPIURLs(msg string) string {
	msg = telegramFileBotPathURL.ReplaceAllString(msg, "/file/bot<redacted>/")
	msg = telegramBotPathURL.ReplaceAllString(msg, "/bot<redacted>/")
	return msg
}

// slogBotLogger adapts slog.Logger to tgbotapi.BotLogger so library logs go through slog.
type slogBotLogger struct {
	mu  sync.RWMutex
	log *slog.Logger
}

func newSlogBotLogger(log *slog.Logger) *slogBotLogger {
	logger := &slogBotLogger{}
	logger.SetLogger(log)
	return logger
}

func (s *slogBotLogger) SetLogger(log *slog.Logger) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if log == nil {
		log = slog.Default()
	}
	s.log = log
}

func (s *slogBotLogger) current() *slog.Logger {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.log == nil {
		return slog.Default()
	}
	return s.log
}

func (s *slogBotLogger) Println(v ...interface{}) {
	s.current().Warn("telegram bot sdk log", slog.String("message", redactTelegramBotAPIURLs(fmt.Sprint(v...))))
}

func (s *slogBotLogger) Printf(format string, v ...interface{}) {
	s.current().Warn(
		"telegram bot sdk log",
		slog.String("message", redactTelegramBotAPIURLs(fmt.Sprintf(format, v...))),
	)
}
