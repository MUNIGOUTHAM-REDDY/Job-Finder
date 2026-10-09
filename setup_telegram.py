#!/usr/bin/env python3
"""One-time Telegram setup: saves your bot token + chat id to .env and sends a test message."""
import getpass
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENV = Path(__file__).resolve().parent / ".env"


def call(token, method):
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", timeout=15) as r:
        return json.load(r)


token = getpass.getpass("Paste your bot token from @BotFather (input is hidden): ").strip()
try:
    bot = call(token, "getMe")["result"]
except Exception:
    sys.exit("That token didn't work. Copy it again from @BotFather and retry.")
print(f"Bot found: @{bot['username']}")

updates = call(token, "getUpdates").get("result", [])
chats = [u["message"]["chat"] for u in updates if "message" in u]
if not chats:
    sys.exit(f"No messages yet. Open https://t.me/{bot['username']}, press Start, send 'hi', then run this again.")
chat = chats[-1]
print(f"Chat found: {chat.get('first_name', '')} {chat.get('last_name', '')} (id {chat['id']})")

ENV.write_text(f"TG_BOT_TOKEN={token}\nTG_CHAT_ID={chat['id']}\n")
ENV.chmod(0o600)
body = urllib.parse.urlencode({"chat_id": chat["id"], "text": "✅ Job Finder connected. Alerts will arrive here."}).encode()
urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=15)
print("Saved to .env and sent a test message. Check Telegram!")
