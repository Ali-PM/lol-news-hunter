import os, re, json, time, hashlib, html, logging, warnings
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
import feedparser, requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger('lol-news')
TOKEN = os.environ['TELEGRAM_TOKEN'].strip()
CHAT_ID = os.environ['TELEGRAM_CHAT_ID'].strip()
MAX_ITEMS = 20
MAX_AGE_HOURS = 24
NOW = datetime.now(timezone.utc)
TZ = ZoneInfo('Asia/Tehran')
STATE = Path('seen.json')
TRANSLATE = os.getenv('TRANSLATE_TITLES', 'true').lower() == 'true'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; LoLNewsHunter/5.0)'})

# RSS direct feeds (a failed feed is logged and does not stop other sources).
DIRECT_FEEDS = [
    ('NERFPLZ', 'https://www.nerfplz.com/feeds/posts/default', 'report'),
    ('League Feed', 'https://leaguefeed.net/feed/', 'report'),
]
# Google News RSS is discovery, not direct monitoring of creators' posts.
SEARCHES = [
    ('Riot League', 'site:leagueoflegends.com/en-us/news/ League of Legends when:2d', 'official'),
    ('Riot Esports', 'site:lolesports.com League of Legends when:2d', 'official'),
    ('Sheep Esports', 'site:sheepesports.com League of Legends when:2d', 'report'),
    ('Dot Esports', 'site:dotesports.com/league-of-legends League of Legends when:2d', 'report'),
    ('PCGamesN', 'site:pcgamesn.com/league-of-legends League of Legends when:2d', 'report'),
    ('Esports Insider', 'site:esportsinsider.com League of Legends when:2d', 'report'),
    ('JungleDiff', 'JungleDiff League of Legends PBE when:2d', 'report'),
    ('SkinSpotlights', 'SkinSpotlights League of Legends skins when:2d', 'report'),
    ('Vandiril', 'Vandiril League of Legends bug when:2d', 'report'),
    ('Spideraxe', 'Spideraxe League of Legends PBE when:2d', 'report'),
    ('Big Bad Bear', 'Big Bad Bear League of Legends leak when:2d', 'rumor'),
    ('Esports Transfers', 'League of Legends esports roster transfer when:2d', 'report'),
    ('League PBE', 'League of Legends PBE patch skins update when:2d', 'report'),
]
BLOCKED = re.compile(r'\b(teamfight tactics|tft|valorant|2xko|wild rift|legends of runeterra)\b', re.I)
DISCUSSION = re.compile(r'\b(how to|what do you think|anyone else|your opinion|my idea|suggestion|question|discussion|which champion|should riot|unpopular opinion|fan concept|tier list|guide to|tips for|i think|i wish)\b', re.I)
NEWS_SIGNALS = re.compile(r'\b(patch|update|announc\w*|reveal\w*|releas\w*|skin\w*|pbe|balance|buff\w*|nerf\w*|rework\w*|champion\w*|worlds|lck|lec|lpl|lcs|msi|transfer\w*|roster|sign\w*|join\w*|depart\w*|leak\w*|rumou?r\w*|report\w*|bug\w*|exploit\w*|trailer|cinematic|event|esports|tournament|final\w*|result\w*|interview|riot|season|gameplay|ranked|hotfix|preview)\b', re.I)

try:
    seen = set(json.loads(STATE.read_text(encoding='utf-8'))) if STATE.exists() else set()
except (ValueError, OSError):
    seen = set()

def google_feed(q):
    return 'https://news.google.com/rss/search?q=' + quote(q) + '&hl=en-US&gl=US&ceid=US:en'

def clean_text(raw):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', MarkupResemblesLocatorWarning)
        return html.unescape(BeautifulSoup(str(raw or ''), 'html.parser').get_text(' ', strip=True))

def parse_date(entry):
    value = entry.get('published_parsed') or entry.get('updated_parsed')
    if value:
        return datetime(*value[:6], tzinfo=timezone.utc)
    for key in ('published', 'updated'):
        if entry.get(key):
            try:
                return parsedate_to_datetime(entry[key]).astimezone(timezone.utc)
            except (ValueError, TypeError, OverflowError):
                pass
    return None

def image_from_entry(entry):
    for media in entry.get('media_content', []) + entry.get('media_thumbnail', []):
        url = media.get('url', '')
        if url.startswith('https://'):
            return url
    for enc in entry.get('enclosures', []):
        url = enc.get('href', '') or enc.get('url', '')
        if url.startswith('https://') and enc.get('type', '').startswith('image/'):
            return url
    soup = BeautifulSoup(entry.get('summary', '') or entry.get('description', ''), 'html.parser')
    img = soup.find('img')
    url = img.get('src', '') if img else ''
    return url if url.startswith('https://') else ''

def image_from_article(url):
    if urlparse(url).hostname == 'news.google.com':
        return ''
    try:
        response = SESSION.get(url, timeout=7)
        response.raise_for_status()
        soup = BeautifulSoup(response.text[:200000], 'html.parser')
        for attrs in ({'property': 'og:image'}, {'name': 'twitter:image'}):
            tag = soup.find('meta', attrs=attrs)
            if tag and tag.get('content', '').startswith('https://'):
                return tag['content']
    except requests.RequestException:
        pass
    return ''

def credibility(title, level, link):
    if re.search(r'\b(rumou?r|speculat\w*|might|could|possibly|unconfirmed)\b', title, re.I):
        return '🟣 شایعه و گمانه‌زنی', '#Rumor'
    if re.search(r'\b(leak\w*|reportedly|sources say)\b', title, re.I) or level == 'rumor':
        return '🟠 لیک یا گزارش غیررسمی', '#Unconfirmed'
    host = (urlparse(link).hostname or '').lower()
    # Google News redirect links do not prove the publisher's identity.
    if level == 'official' and (host == 'leagueoflegends.com' or host.endswith('.leagueoflegends.com') or host == 'lolesports.com' or host.endswith('.lolesports.com')):
        return '🟢 رسمی و تأییدشده (منبع رسمی)', '#Official'
    if level == 'official':
        return '🔵 منتسب به منبع رسمی؛ لینک را بررسی کنید', '#VerifySource'
    return '🟠 گزارش رسانه‌ای؛ نیازمند بررسی', '#Report'

def topic(title):
    for pattern, tag in [
        (r'\b(skin\w*|cosmetic|chroma)\b', '#Skins'),
        (r'\b(pbe|test server)\b', '#PBE'),
        (r'\b(patch|buff\w*|nerf\w*|balance|item\w*|rework)\b', '#Patch'),
        (r'\b(worlds|lck|lec|lpl|lcs|msi|esport\w*|roster|transfer|tournament|final)\b', '#Esports'),
        (r'\b(bug|exploit|glitch)\b', '#Bugs'),
        (r'\b(leak|rumou?r)\b', '#Leaks'),
        (r'\b(trailer|cinematic|lore)\b', '#Lore'),
    ]:
        if re.search(pattern, title, re.I):
            return tag
    return '#LoLNews'

def translate_title(title):
    if not TRANSLATE:
        return ''
    try:
        response = SESSION.get('https://translate.googleapis.com/translate_a/single', params={
            'client': 'gtx', 'sl': 'auto', 'tl': 'fa', 'dt': 't', 'q': title
        }, timeout=6)
        response.raise_for_status()
        translated = ''.join(part[0] for part in response.json()[0] if part and part[0])
        return translated if translated and translated.casefold() != title.casefold() else ''
    except (requests.RequestException, ValueError, IndexError, TypeError):
        return ''

items = []
for source, url, level in DIRECT_FEEDS + [(name, google_feed(query), level) for name, query, level in SEARCHES]:
    stats = {'fetched': 0, 'old_or_undated': 0, 'filtered': 0, 'seen': 0, 'accepted': 0}
    try:
        response = SESSION.get(url, timeout=20)
        response.raise_for_status()
        entries = feedparser.parse(response.content).entries[:40]
        stats['fetched'] = len(entries)
        for entry in entries:
            title = clean_text(entry.get('title', ''))
            link = entry.get('link', '')
            dt = parse_date(entry)
            if not link or not title or not dt or dt > NOW + timedelta(minutes=5) or dt < NOW - timedelta(hours=MAX_AGE_HOURS):
                stats['old_or_undated'] += 1
                continue
            if BLOCKED.search(title) or DISCUSSION.search(title) or not NEWS_SIGNALS.search(title):
                stats['filtered'] += 1
                continue
            uid = hashlib.sha256(link.encode('utf-8')).hexdigest()
            if uid in seen:
                stats['seen'] += 1
                continue
            items.append({'id': uid, 'source': source, 'title': title, 'link': link, 'date': dt, 'level': level, 'image': image_from_entry(entry)})
            stats['accepted'] += 1
        log.info('%s | fetched=%d old/undated=%d filtered=%d seen=%d accepted=%d', source, *stats.values())
    except (requests.RequestException, Exception) as exc:
        log.warning('%s | feed failed: %s', source, exc)

# Prioritize official discoveries, images and recency. Different links to the same title are collapsed.
items.sort(key=lambda x: (x['level'] == 'official', bool(x['image']), x['date']), reverse=True)
unique, headlines = [], set()
for item in items:
    normalized = re.sub(r'[^a-z0-9 ]', '', item['title'].lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()[:110]
    if normalized in headlines:
        continue
    headlines.add(normalized)
    unique.append(item)

sent = 0
for item in unique:
    if sent >= MAX_ITEMS:
        break
    label, status_tag = credibility(item['title'], item['level'], item['link'])
    published = item['date'].astimezone(TZ).strftime('%Y-%m-%d %H:%M')
    translated = translate_title(item['title'])
    heading = (f'🇮🇷 <b>{html.escape(translated)}</b>\n' if translated else '')
    caption = (f'{heading}🎮 <b>{html.escape(item["title"])}</b>\n\n'
               f'{label}\n📍 {html.escape(item["source"])}\n'
               f'🕒 {published} (ایران)\n'
               f'🔗 {html.escape(item["link"])}\n\n'
               f'#LeagueOfLegends {topic(item["title"])} {status_tag}')
    image_url = item['image'] or image_from_article(item['link'])
    try:
        delivered = False
        if image_url and len(caption.encode('utf-8')) < 950:
            resp = SESSION.post(f'https://api.telegram.org/bot{TOKEN}/sendPhoto', data={
                'chat_id': CHAT_ID, 'photo': image_url, 'caption': caption, 'parse_mode': 'HTML'
            }, timeout=25)
            if resp.ok and resp.json().get('ok'):
                delivered = True
            else:
                log.warning('Photo rejected for %s; falling back to text', item['source'])
        if not delivered:
            resp = SESSION.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage', json={
                'chat_id': CHAT_ID, 'text': caption, 'parse_mode': 'HTML', 'disable_web_page_preview': False
            }, timeout=25)
            resp.raise_for_status()
            if not resp.json().get('ok'):
                raise RuntimeError(resp.text[:200])
        seen.add(item['id'])
        sent += 1
        time.sleep(0.4)
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        log.error('Telegram delivery failed for %s: %s', item['source'], exc)

STATE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding='utf-8')
log.info('LoL News Hunter v5 | Sent %d / %d candidate news items', sent, len(unique))
