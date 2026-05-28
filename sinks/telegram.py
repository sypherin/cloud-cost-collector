"""Telegram sink — sends the digest/booking summary to a chat.

Secrets come from env, never config:
  CCC_TELEGRAM_TOKEN    bot token from @BotFather
  CCC_TELEGRAM_CHAT_ID  target chat id

Config (per sinks.telegram in config.yaml):
  enabled: true
  token_env: CCC_TELEGRAM_TOKEN      # override env var names if you like
  chat_id_env: CCC_TELEGRAM_CHAT_ID
"""
import os
import sys
import urllib.parse
import urllib.request


def send(cfg, text):
    token = os.environ.get(cfg.get("token_env", "CCC_TELEGRAM_TOKEN"), "")
    chat_id = os.environ.get(cfg.get("chat_id_env", "CCC_TELEGRAM_CHAT_ID"), "")
    if not token or not chat_id:
        print("Telegram sink: missing token/chat_id env vars — printing instead:", file=sys.stderr)
        print(text)
        return
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    urllib.request.urlopen(req, timeout=20).read()
