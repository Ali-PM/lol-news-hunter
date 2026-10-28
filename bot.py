import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests

TOKEN = os.environ['TELEGRAM_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
STATE = Path('seen.json')
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=8)
TZ = ZoneInfo('Asia/Tehran')
MAX_ITEMS = 12

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
TAGS = {'Official': '#Official', 'General': '#LoLNews', 'PBE': '#PBE',
        'Esports': '#Esports', 'Memes': '#Memes', 'Guides': '#Guides',
        'Skins': '#Skins', 'Bugs': '#Bugs', 'Lore': '#Lore', 'Leaks': '#Leaks'}
TOPICS_FA = {'Official': 'خبر رسمی', 'General': 'اخبار و بحث جامعه بازیکنان',
             'PBE': 'تغییرات آزمایشی PBE', 'Esports': 'رقابت‌ها و نقل‌وانتقالات',
             'Memes': 'میم و سرگرمی', 'Guides': 'آموزش و متا',
             'Skins': 'اسکین‌ها', 'Bugs': 'باگ و مکانیک',
             'Lore': 'داستان بازی', 'Leaks': 'لیک و اطلاعات احتمالی'}

session = requests.Session()
session.headers.update({'User-Agent': 'LoLNewsHunter/3.0 (admin news digest)'})


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
    host = (urlparse(link).hostname or '').lower()
    official = (host == 'leagueoflegends.com' or host.endswith('.leagueoflegends.com')
                or host == 'lolesports.com' or host.endswith('.lolesports.com'))
    if official:
        return '✅ رسمی و تأییدشده', '#Official'
    if re.search(r'\b(rumou?r|speculat\w*|theory|prediction|possibly|might|alleged)\b', title, re.I):
        return '❔ شایعه و گمانه‌زنی', '#Rumor'
    if re.search(r'\b(leak\w*|datamin\w*|unconfirmed)\b', title, re.I) or source == 'Big Bad Bear':
        return '🟠 لیک یا گزارش غیررسمی', '#Unconfirmed'
    return '🔎 گزارش یا محتوای غیررسمی؛ نیازمند بررسی', '#Community'


def translate_headline(title, translator):
    # Translation is optional and uses an unofficial free endpoint. No guarantee of availability.
    if translator is None:
        return None
    try:
        result = translator.translate(title[:450])
        return result if result and result.strip() else None
    except Exception as exc:
        print('Translation unavailable:', type(exc).__name__)
        return None


def send_message(text):
    response = session.post(
        f'https://api.telegram.org/bot{TOKEN}/sendMessage',
        json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML',
              'disable_web_page_preview': True}, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError(str(data))


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
            dt, link = published(e), e.get('link', '')
            if dt and CUTOFF <= dt <= NOW and link:
                uid = hashlib.sha256(link.encode()).hexdigest()
                items[uid] = (dt, uid, source, topic, e.get('title', ''), link)
    except Exception as exc:
        print(f'Feed failed: {source}: {exc}')

for source, (query, topic) in SEARCHES.items():
    url = 'https://news.google.com/rss/search?q=' + quote(query) + '&hl=en-US&gl=US&ceid=US:en'
    try:
        entries = get_feed(url)
        feeds_ok += 1
        for e in entries:
            dt, link = published(e), e.get('link', '')
            if dt and CUTOFF <= dt <= NOW and link:
                uid = hashlib.sha256(link.encode()).hexdigest()
                items.setdefault(uid, (dt, uid, source, topic, e.get('title', ''), link))
    except Exception as exc:
        print(f'Feed failed: {source}: {exc}')

if not feeds_ok:
    raise RuntimeError('All feeds failed. Retry next run.')

candidates = sorted((item for uid, item in items.items() if uid not in seen),
                    key=lambda x: x[0], reverse=True)
selected, per_source = [], {}
for item in candidates:
    source = item[2]
    if per_source.get(source, 0) >= 3:
        continue
    selected.append(item)
    per_source[source] = per_source.get(source, 0) + 1
    if len(selected) == MAX_ITEMS:
        break

translator = None
if selected:
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target='fa')
    except Exception as exc:
        print('Translator unavailable:', type(exc).__name__)

# A single digest (split into parts only if Telegram's 4096-character limit requires it).
header = ('🎮 <b>گزارش ۶ ساعته League of Legends</b>\n'
          f'🕒 زمان تهیه: {NOW.astimezone(TZ):%Y-%m-%d %H:%M} (ایران)\n'
          '📌 تاریخ‌ها مربوط به زمان ثبت در فید هستند، نه لزوماً انتشار اولیه.\n'
          '⚠️ برچسب اعتبار خودکار است؛ قبل از انتشار عمومی بررسی کنید.\n')
if not selected:
    print(f'Feeds OK: {feeds_ok}; no new items. No digest sent.')
else:
    blocks = []
    for index, (dt, uid, source, topic, title, link) in enumerate(selected, 1):
        label, trust_tag = credibility(source, title, link)
        translated = translate_headline(title, translator)
        fa_headline = translated or f'موضوع: {TOPICS_FA[topic]} (ترجمه در دسترس نیست)'
        local = dt.astimezone(TZ).strftime('%Y-%m-%d %H:%M')
        block = (f'\n<b>{index}. {html.escape(fa_headline)}</b>\n'
                 f'📰 {html.escape(title[:240])}\n'
                 f'🏷 {label} | {html.escape(TOPICS_FA[topic])}\n'
                 f'📍 {html.escape(source)} | 🕒 {local}\n'
                 f'<a href="{html.escape(link, quote=True)}">مشاهده منبع</a>\n'
                 f'{TAGS[topic]} {trust_tag}')
        blocks.append((uid, block))

    # Chunk at safe boundaries; mark IDs as seen only after their message is delivered.
    batches = []
    current_text, current_ids = header, []
    for uid, block in blocks:
        if len(current_text) + len(block) > 3800 and current_ids:
            batches.append((current_text, current_ids))
            current_text, current_ids = header + '📄 ادامه گزارش\n', []
        current_text += block + '\n'
        current_ids.append(uid)
    if current_ids:
        batches.append((current_text, current_ids))

    sent = 0
    for message, ids in batches:
        try:
            send_message(message)
            seen.update(ids)
            sent += len(ids)
            time.sleep(0.5)
        except Exception as exc:
            print('Telegram digest failed:', exc)
            break

    STATE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding='utf-8')
    print(f'Feeds OK: {feeds_ok}; candidates: {len(candidates)}; sent items: {sent}')
    if sent == 0:
        raise RuntimeError('Telegram digest was not sent.')
