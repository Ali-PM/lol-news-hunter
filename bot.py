import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests

TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
STATE = Path('seen.json')
NOW = datetime.now(timezone.utc)
WINDOW_HOURS = 8
MAX_MESSAGES = 12
CUTOFF = NOW - timedelta(hours=WINDOW_HOURS)
TZ = ZoneInfo('Asia/Tehran')

REDDIT = {
    'LoL Reddit': ('leagueoflegends', 'General'),
    'LeaguePBE': ('LeaguePBE', 'PBE'),
    'PedroPeepos': ('PedroPeepos', 'Esports'),
    'LeagueOfMemes': ('LeagueOfMemes', 'Memes'),
    'SummonerSchool': ('summonerschool', 'Guides'),
}
SEARCHES = {
    'Riot Games': ('site:leagueoflegends.com/en-us/news/ League of Legends', 'Official'),
    'LoL Esports': ('site:lolesports.com League of Legends', 'Esports'),
    'Sheep Esports': ('site:sheepesports.com League of Legends', 'Esports'),
    'JungleDiff': ('site:junglediff.net League of Legends PBE', 'PBE'),
    'SkinSpotlights': ('SkinSpotlights League of Legends new skins', 'Skins'),
    'Vandiril': ('Vandiril League of Legends bug', 'Bugs'),
    'Necrit': ('Necrit League of Legends lore', 'Lore'),
    'Spideraxe': ('Spideraxe League of Legends PBE changes', 'PBE'),
    'Big Bad Bear': ('Big Bad Bear League of Legends leaks', 'Leaks'),
    'LoL transfers': ('League of Legends esports roster transfer', 'Esports'),
}
TAGS = {'Official':'#Official', 'General':'#LoLNews', 'PBE':'#PBE',
        'Esports':'#Esports', 'Memes':'#Memes', 'Guides':'#Guides',
        'Skins':'#Skins', 'Bugs':'#Bugs', 'Lore':'#Lore', 'Leaks':'#Leaks'}

session = requests.Session()
session.headers.update({'User-Agent': 'LoLNewsHunter/1.0 (RSS aggregator; admin review)'})

def get_feed(url):
    response = session.get(url, timeout=25)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise ValueError(str(feed.bozo_exception))
    return feed.entries

def published(entry):
    for key in ('published_parsed', 'updated_parsed'):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None

def credibility(source, title, link):
    # Only a direct official Riot page is labeled official.
    host = urlparse(link).hostname or ''
    official = host == 'leagueoflegends.com' or host.endswith('.leagueoflegends.com') or host == 'lolesports.com' or host.endswith('.lolesports.com')
    if official:
        return '✅ رسمی و تأییدشده', '#Official'
    if re.search(r'\b(rumou?r|speculat|theory|prediction|possibly|might|alleged)\b', title, re.I):
        return '❔ شایعه و گمانه‌زنی', '#Rumor'
    if re.search(r'\b(leak|datamin|unconfirmed)\b', title, re.I) or source in ('Big Bad Bear', 'LoL transfers'):
        return '🟠 لیک یا گزارش غیررسمی', '#Unconfirmed'
    return '🔎 گزارش یا محتوای غیررسمی؛ نیازمند بررسی', '#Community'

def key_for(link):
    return hashlib.sha256(link.encode('utf-8')).hexdigest()

try:
    seen = set(json.loads(STATE.read_text(encoding='utf-8')))
except (OSError, ValueError, TypeError):
    seen = set()

items = {}
feeds_ok = 0
for source, (sub, topic) in REDDIT.items():
    url = f'https://www.reddit.com/r/{sub}/new/.rss?limit=50'
    try:
        entries = get_feed(url)
        feeds_ok += 1
        for e in entries:
            dt = published(e)
            link = e.get('link', '')
            if dt and CUTOFF <= dt <= NOW and link:
                uid = key_for(link)
                items[uid] = (dt, uid, source, topic, e.get('title', ''), link)
    except Exception as exc:
        print(f'Feed failed: {source}: {exc}')

for source, (query, topic) in SEARCHES.items():
    url = 'https://news.google.com/rss/search?q=' + quote(query) + '&hl=en-US&gl=US&ceid=US:en'
    try:
        entries = get_feed(url)
        feeds_ok += 1
        for e in entries:
            dt = published(e)
            link = e.get('link', '')
            if dt and CUTOFF <= dt <= NOW and link:
                uid = key_for(link)
                items.setdefault(uid, (dt, uid, source, topic, e.get('title', ''), link))
    except Exception as exc:
        print(f'Feed failed: {source}: {exc}')

if not feeds_ok:
    raise RuntimeError('All feeds failed. Nothing sent; retry on next run.')

candidates = [item for uid, item in items.items() if uid not in seen]
candidates.sort(key=lambda x: x[0], reverse=True)

# Prefer a balanced mix, so one busy source cannot monopolize the digest.
selected = []
per_source = {}
for item in candidates:
    source = item[2]
    if per_source.get(source, 0) >= 3:
        continue
    selected.append(item)
    per_source[source] = per_source.get(source, 0) + 1
    if len(selected) >= MAX_MESSAGES:
        break

sent = 0
for dt, uid, source, topic, title, link in selected:
    label, trust_tag = credibility(source, title, link)
    local_time = dt.astimezone(TZ).strftime('%Y-%m-%d %H:%M')
    text = (f'🎮 {topic} | {source}\n{label}\n\n'
            f'📰 {title}\n\n'
            f'🕒 {local_time} (ایران، زمان ثبت در فید)\n'
            f'🔗 {link}\n\n#LeagueOfLegends {TAGS[topic]} {trust_tag}')
    try:
        r = session.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',
                         json={'chat_id': CHAT_ID, 'text': text,
                               'disable_web_page_preview': True}, timeout=25)
        r.raise_for_status()
        if not r.json().get('ok'):
            raise RuntimeError(r.text)
        seen.add(uid)
        sent += 1
        time.sleep(0.4)
    except Exception as exc:
        print(f'Telegram failed for {source}: {exc}')

STATE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding='utf-8')
print(f'Feeds OK: {feeds_ok}; candidates: {len(candidates)}; sent: {sent}')
if selected and sent == 0:
    raise RuntimeError('All Telegram sends failed. Check credentials and chat permissions.')
