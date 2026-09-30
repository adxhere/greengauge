#!/usr/bin/env python3
"""
Find the Telegram chat id to send GreenGauge alerts to.

1. Create a bot with @BotFather on Telegram and copy its token.
2. From the supervisor's phone, open the bot and send it any message (e.g. "hi").
3. Run:  python tools/telegram_chat_id.py YOUR_BOT_TOKEN
"""
import json
import sys
import urllib.request

if len(sys.argv) != 2:
    sys.exit("Usage: python tools/telegram_chat_id.py YOUR_BOT_TOKEN")
with urllib.request.urlopen(f"https://api.telegram.org/bot{sys.argv[1]}/getUpdates", timeout=20) as r:
    updates = json.loads(r.read()).get("result", [])
chats = {}
for u in updates:
    msg = u.get("message") or u.get("channel_post") or {}
    c = msg.get("chat")
    if c:
        chats[c["id"]] = c.get("title") or " ".join(filter(None, [c.get("first_name"), c.get("last_name")])) or c.get("username")
if not chats:
    print("No messages found. Send your bot a message from Telegram first, then run this again.")
for cid, who in chats.items():
    print(f"TELEGRAM_CHAT_ID={cid}    ({who})")
