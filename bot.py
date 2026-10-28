
import os
import json
import hashlib
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE = Path("seen.json")

SEARCHES = {
    "اخبار رسمی": "League of Legends Riot Games patch",
    "اسکین و چمپیون": "League of Legends new skins PBE",
    "لیک و شایعه": "League of Legends leaks rumors",
    "ایسپورت": "League of Legends esports roster transfer",
    "حاشیه": "League of Legends controversy drama",
}

if STATE.exists():
    seen = set(json.loads(STATE.read_text()))
    first_run = False
else:
    seen = set()
    first_run = False

candidates = []

for category, query in SEARCHES.items():
    url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )

    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        for entry in feed.entries[:15]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            if not link or not title:
                continue

            uid = hashlib.sha256(
                link.encode("utf-8")
            ).hexdigest()

            if uid not in seen:
                candidates.append((uid, category, title, link))
    except Exception as error:
        print(f"Feed error: {category}: {error}")

# در اولین اجرا، خبرهای قدیمی ارسال نمی‌شوند
if first_run:
    for uid, _, _, _ in candidates:
        seen.add(uid)
    print("Initial feed snapshot saved.")
else:
    sent = 0
    for uid, category, title, link in candidates:
        if uid in seen:
            continue

        if sent >= 5:
            break

        message = (
            f"🎮 {category}\n\n"
            f"📰 {title}\n\n"
            f"🔗 {link}\n\n"
            "#LeagueOfLegends"
        )

        try:
            result = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": message,
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
            result.raise_for_status()
            if not result.json().get("ok"):
                raise RuntimeError(result.text)

            seen.add(uid)
            sent += 1
        except Exception as error:
            print(f"Telegram error: {error}")

    print(f"Sent {sent} news items.")

STATE.write_text(
    json.dumps(sorted(seen), ensure_ascii=False)
)
