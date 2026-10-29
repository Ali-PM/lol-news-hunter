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
MAX_ITEMS = 5
MAX_PER_CATEGORY = 1
MAX_PER_SOURCE = 5
MAX_AGE_HOURS = 24
NOW = datetime.now(timezone.utc)
TZ = ZoneInfo('Asia/Tehran')
STATE = Path('seen.json')
ARCHIVE_URL = os.environ.get('ARCHIVE_URL', '').strip().rstrip('/')
ARCHIVE_SECRET = os.environ.get('ARCHIVE_SECRET', '').strip()
TRANSLATE = False  # English titles only
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'LoLNewsHunter/6.1 (public League of Legends news aggregation; contact via GitHub)'})

# RSS direct feeds (a failed feed is logged and does not stop other sources).
DIRECT_FEEDS = [
    ('NERFPLZ', 'https://www.nerfplz.com/feeds/posts/default', 'report'),
    ('League Feed', 'https://leaguefeed.net/feed/', 'report'),
    ('LeagueOfMemes Reddit', 'https://www.reddit.com/r/LeagueOfMemes/new/.rss', 'community'),
    ('ARAM Reddit', 'https://www.reddit.com/r/ARAM/new/.rss', 'community'),
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
    ('Riot Patch Notes', 'site:leagueoflegends.com/en-us/news/game-updates/ patch notes when:2d', 'official'),
    ('Riot Dev Updates', 'site:leagueoflegends.com/en-us/news/dev/ League of Legends when:2d', 'official'),
    ('LoL Balance', 'League of Legends balance changes hotfix champion buffs nerfs when:2d', 'report'),
    ('LoL New Skins', 'League of Legends new skins splash art chromas reveal when:2d', 'report'),
    ('LoL PBE News', 'League of Legends PBE new skin changes preview when:2d', 'report'),
    ('LoL Leaks', 'League of Legends leaked upcoming skins champions rumors when:2d', 'rumor'),
    ('LoL Community', 'League of Legends funny moments memes community clips when:2d', 'report'),
    ('LoL Bugs', 'League of Legends funny bugs glitches clips when:2d', 'report'),
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
    if re.search(r'\b(rumou?r\w*|speculat\w*|might|could|possibly|unconfirmed)\b', title, re.I):
        return '🟣 RUMOR / SPECULATION', '#Rumor'
    if re.search(r'\b(leak\w*|reportedly|sources say)\b', title, re.I) or level == 'rumor':
        return '🟠 UNCONFIRMED REPORT', '#Unconfirmed'
    host = (urlparse(link).hostname or '').lower()
    if level == 'official' and any(host == domain or host.endswith('.' + domain)
                                   for domain in ('leagueoflegends.com', 'lolesports.com')):
        return '🟢 OFFICIAL', '#Official'
    if level == 'official':
        return '🔵 OFFICIAL SOURCE CLAIM — VERIFY LINK', '#VerifySource'
    return '🟠 MEDIA REPORT', '#Report'

# Every article belongs to exactly one category. Order matters: leaks first,
# then esports, skins/PBE, community, and finally general game updates.
CATEGORY_ORDER = [
    'Official & Game Updates',
    'Skins & PBE',
    'Esports & Transfers',
    'Leaks & Rumors',
    'Community, Bugs & Content',
]
CATEGORY_ICONS = {
    'Official & Game Updates': '🛡️',
    'Skins & PBE': '🎨',
    'Esports & Transfers': '🏆',
    'Leaks & Rumors': '🔍',
    'Community, Bugs & Content': '🎬',
}

def category_for(item):
    title = item['title']
    source = item['source'].lower()
    if item['level'] == 'community':
        return 'Community, Bugs & Content'
    if item['level'] == 'rumor' or re.search(r'\b(leak\w*|rumou?r\w*|speculat\w*|unconfirmed)\b', title, re.I):
        return 'Leaks & Rumors'
    if re.search(r'\b(worlds|lck|lec|lpl|lcs|msi|esport\w*|roster|transfer\w*|tournament|playoffs|finals?|team signs|player joins)\b', title, re.I) or 'esport' in source or source == 'sheep esports':
        return 'Esports & Transfers'
    if re.search(r'\b(skin\w*|chroma\w*|cosmetic\w*|pbe|test server)\b', title, re.I) or source in ('skinspotlights', 'junglediff', 'spideraxe', 'league pbe'):
        return 'Skins & PBE'
    if re.search(r'\b(bug\w*|exploit\w*|glitch\w*|cinematic|trailer|lore|interview|video|creator|community)\b', title, re.I) or source == 'vandiril':
        return 'Community, Bugs & Content'
    return 'Official & Game Updates'

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
            if BLOCKED.search(title) or (level != 'community' and (DISCUSSION.search(title) or not NEWS_SIGNALS.search(title))):
                stats['filtered'] += 1
                continue
            uid = hashlib.sha256(link.encode('utf-8')).hexdigest()
            if uid in seen:
                stats['seen'] += 1
                continue
            if level == 'community' and re.search(r'(?i)\b(nsfw|spoiler|advertis|commission|giveaway)\b', title):
                stats['filtered'] += 1
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

# Select a balanced batch before sending. Do not fill missing categories
# with extra esports or any other overrepresented category.
from collections import Counter
selected = []
category_counts = Counter()
source_counts = Counter()
for item in unique:
    category = category_for(item)
    if category_counts[category] >= MAX_PER_CATEGORY:
        continue
    if source_counts[item['source']] >= MAX_PER_SOURCE:
        continue
    item['category'] = category
    selected.append(item)
    category_counts[category] += 1
    source_counts[item['source']] += 1
    if len(selected) >= MAX_ITEMS:
        break

log.info('LoL News Hunter v6 | candidates=%d selected=%d | %s',
         len(unique), len(selected), ', '.join(f'{name}: {category_counts[name]}' for name in CATEGORY_ORDER))

sent = 0
for item in selected:
    label, status_tag = credibility(item['title'], item['level'], item['link'])
    published = item['date'].astimezone(TZ).strftime('%Y-%m-%d %H:%M')
    category = item['category']
    caption = (f'{CATEGORY_ICONS[category]} <b>{html.escape(category)}</b>\n'
               f'🎮 <b>{html.escape(item["title"])}</b>\n\n'
               f'{label}\n📍 {html.escape(item["source"])}\n'
               f'🕒 {published} (Iran)\n'
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
            if not resp.ok:
                logging.error("Telegram response: %s", resp.text[:500])
                
            resp.raise_for_status()
            if not resp.json().get('ok'):
                raise RuntimeError(resp.text[:200])
        seen.add(item['id'])
        sent += 1
        if ARCHIVE_URL and ARCHIVE_SECRET:
            try:
                archive_resp = SESSION.post(ARCHIVE_URL + '/ingest', json={
                    'id': item['id'], 'title': item['title'],
                    'description': item['title'], 'url': item['link'],
                    'source': item['source'], 'category': category,
                    'published': published + ' (Iran)'
                }, headers={'X-Ingest-Secret': ARCHIVE_SECRET}, timeout=15)
                archive_resp.raise_for_status()
            except requests.RequestException as archive_exc:
                log.error('Archive save failed for %s: %s', item['source'], archive_exc)
        time.sleep(0.4)
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        log.error('Telegram delivery failed for %s: %s', item['source'], exc)

STATE.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding='utf-8')
log.info('LoL News Hunter v6 | Sent %d / %d selected news items', sent, len(selected))
