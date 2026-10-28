import os, re, json, time, hashlib, html, logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo
import feedparser, requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
TOKEN = os.environ['TELEGRAM_TOKEN'].strip()
CHAT_ID = os.environ['TELEGRAM_CHAT_ID'].strip()
MAX_ITEMS = 20
MAX_AGE_HOURS = 12  # covers schedule delays; state prevents duplicates
STATE = Path('seen.json')
TZ = ZoneInfo('Asia/Tehran')
NOW = datetime.now(timezone.utc)
SESSION = requests.Session()
SESSION.headers.update({'User-Agent':'LoLNewsHunter/4.0 (+RSS aggregator)'})

# Direct editorial RSS + Google News site-specific discovery. No Reddit discussion feeds.
DIRECT_FEEDS = [
    ('NERFPLZ', 'https://www.nerfplz.com/feeds/posts/default', 'report'),
    ('LoL News', 'https://lolnews.com/feed/', 'report'),
    ('League Feed', 'https://leaguefeed.net/feed/', 'report'),
]
SEARCHES = [
    ('Riot League', 'site:leagueoflegends.com/en-us/news/ League of Legends', 'official'),
    ('Riot Esports', 'site:lolesports.com League of Legends Worlds LCK LEC', 'official'),
    ('Sheep Esports', 'site:sheepesports.com League of Legends roster transfer', 'report'),
    ('Dot Esports', 'site:dotesports.com/league-of-legends League of Legends', 'report'),
    ('PCGamesN', 'site:pcgamesn.com/league-of-legends League of Legends', 'report'),
    ('JungleDiff', 'JungleDiff League of Legends PBE changes', 'report'),
    ('SkinSpotlights', 'SkinSpotlights League of Legends new skin preview', 'report'),
    ('Vandiril', 'Vandiril League of Legends bug interaction video', 'report'),
    ('Spideraxe', 'Spideraxe League of Legends PBE update', 'report'),
    ('Big Bad Bear', 'Big Bad Bear League of Legends leak', 'rumor'),
    ('Esports News', 'League of Legends esports roster transfer confirmed', 'report'),
]

BLOCKED = re.compile(r'\b(teamfight tactics|\btft\b|valorant|2xko|wild rift|legends of runeterra)\b', re.I)
DISCUSSION = re.compile(r'\b(how to|what do you think|anyone else|your opinion|my idea|suggestion|question|discussion|which champion|should riot|unpopular opinion|fan concept|tier list|guide to|tips for|i think|i wish)\b', re.I)
NEWS_SIGNALS = re.compile(r'\b(patch|update|announc|reveal|release|new skin|skinline|pbe|balance|buff|nerf|rework|champion|worlds|lck|lec|lpl|lcs|msi|transfer|roster|sign|join|leave|depart|leak|rumor|report|bug|exploit|trailer|cinematic|event|esports|tournament|final|results?|interview|riot)\b', re.I)

try:
    seen = set(json.loads(STATE.read_text(encoding='utf-8'))) if STATE.exists() else set()
except (ValueError, OSError):
    seen = set()

def google_feed(q):
    return 'https://news.google.com/rss/search?q=' + quote(q) + '&hl=en-US&gl=US&ceid=US:en'

def get_feed(url):
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    return feedparser.parse(r.content).entries

def entry_image(entry):
    for media in entry.get('media_content', []) + entry.get('media_thumbnail', []):
        if media.get('url', '').startswith('https://'):
            return media['url']
    for enc in entry.get('enclosures', []):
        if enc.get('type', '').startswith('image/') and enc.get('href','').startswith('https://'):
            return enc['href']
    raw = entry.get('summary', '') or entry.get('description', '')
    soup = BeautifulSoup(raw, 'html.parser')
    img = soup.find('img')
    return img.get('src', '') if img and img.get('src','').startswith('https://') else ''

def article_image(url):
    # Avoid fetching Google News redirect pages: not guaranteed to resolve to publisher.
    if 'news.google.com' in urlparse(url).netloc:
        return ''
    try:
        r = SESSION.get(url, timeout=8)
        r.raise_for_status()
        soup = BeautifulSoup(r.text[:250000], 'html.parser')
        for key in ('og:image', 'twitter:image'):
            tag = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
            if tag and tag.get('content', '').startswith('https://'):
                return tag['content']
    except requests.RequestException:
        pass
    return ''

def credibility(title, level):
    if re.search(r'\b(rumou?r|speculat|might|could|possibly|unconfirmed)\b', title, re.I):
        return '🟣 شایعه و گمانه‌زنی', '#Rumor'
    if re.search(r'\b(leak|reportedly|sources say)\b', title, re.I) or level == 'rumor':
        return '🟠 لیک یا گزارش غیررسمی', '#Unconfirmed'
    if level == 'official':
        return '🟢 رسمی و تأییدشده (منبع رسمی)', '#Official'
    return '🟠 گزارش رسانه‌ای؛ نیازمند بررسی', '#Report'

def topic(title):
    rules = [
        (r'\b(skin|cosmetic|chroma)\b', '#Skins'),
        (r'\b(pbe|test server)\b', '#PBE'),
        (r'\b(patch|buff|nerf|balance|item|rework)\b', '#Patch'),
        (r'\b(worlds|lck|lec|lpl|lcs|msi|esport|roster|transfer|tournament|final)\b', '#Esports'),
        (r'\b(bug|exploit|glitch)\b', '#Bugs'),
        (r'\b(leak|rumor)\b', '#Leaks'),
        (r'\b(trailer|cinematic|lore)\b', '#Lore'),
    ]
    return next((tag for pattern, tag in rules if re.search(pattern, title, re.I)), '#LoLNews')

def parse_date(entry):
    value = entry.get('published_parsed') or entry.get('updated_parsed')
    if not value:
        return None
    return datetime(*value[:6], tzinfo=timezone.utc)

def eligible(title, dt):
    if not dt or dt > NOW + timedelta(minutes=5) or dt < NOW - timedelta(hours=MAX_AGE_HOURS):
        return False
    if BLOCKED.search(title) or DISCUSSION.search(title):
        return False
    return bool(NEWS_SIGNALS.search(title))

items = []
for source, url, level in DIRECT_FEEDS + [(name, google_feed(query), level) for name, query, level in SEARCHES]:
    try:
        for entry in get_feed(url)[:25]:
            title = html.unescape(BeautifulSoup(entry.get('title',''), 'html.parser').get_text(' ', strip=True))
            link = entry.get('link', '')
            dt = parse_date(entry)
            if not link or not eligible(title, dt):
                continue
            uid = hashlib.sha256(link.encode()).hexdigest()
            if uid in seen:
                continue
            items.append({'id':uid,'source':source,'title':title,'link':link,'date':dt,'level':level,'image':entry_image(entry)})
    except Exception as exc:
        logging.warning('Feed failed %s: %s', source, exc)

# Deduplicate same headline across publishers; prefer official and articles with RSS images.
items.sort(key=lambda x: (x['level']=='official', bool(x['image']), x['date']), reverse=True)
unique = []
headlines = set()
for item in items:
    normalized = re.sub(r'[^a-z0-9 ]','', item['title'].lower())
    normalized = re.sub(r'\s+',' ', normalized).strip()[:105]
    if normalized in headlines:
        continue
    headlines.add(normalized)
    unique.append(item)

sent = 0
for item in unique:
    if sent >= MAX_ITEMS:
        break
    label, status_tag = credibility(item['title'], item['level'])
    published = item['date'].astimezone(TZ).strftime('%Y-%m-%d %H:%M')
    caption = (f'🎮 <b>{html.escape(item["title"])}</b>\n\n'
               f'{label}\n📍 {html.escape(item["source"])}\n'
               f'🕒 {published} (ایران)\n'
               f'🔗 {html.escape(item["link"])}\n\n'
               f'#LeagueOfLegends {topic(item["title"])} {status_tag}')
    # A news source does not always expose an image; fall back to text, never invent one.
    image_url = item['image'] or article_image(item['link'])
    try:
        if image_url and len(caption) <= 1024:
            resp = SESSION.post(f'https://api.telegram.org/bot{TOKEN}/sendPhoto',
                                data={'chat_id':CHAT_ID,'photo':image_url,'caption':caption,'parse_mode':'HTML'}, timeout=25)
            if not resp.ok or not resp.json().get('ok'):
                logging.warning('Photo unavailable; sending text: %s', resp.text[:160])
                image_url = ''
        if not image_url:
            resp = SESSION.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',
                                json={'chat_id':CHAT_ID,'text':caption,'parse_mode':'HTML', 'disable_web_page_preview':False}, timeout=25)
        resp.raise_for_status()
        if not resp.json().get('ok'):
            raise RuntimeError(resp.text)
        seen.add(item['id'])
        sent += 1
        time.sleep(0.5)
    except Exception as exc:
        logging.error('Telegram delivery failed: %s', exc)

STATE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding='utf-8')
logging.info('LoL News Hunter v4 | Sent %s / %s candidate news items', sent, len(unique))
