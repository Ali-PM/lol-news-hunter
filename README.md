# LoL News Hunter v5

## Install
Replace `bot.py`, `requirements.txt`, and `.github/workflows/news.yml` in your GitHub repository (preserve directory structure). Commit to default branch. Keep existing repository secrets `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`. Enable **Settings > Actions > General > Workflow permissions > Read and write permissions**. Run **Actions > LoL News Hunter v5 > Run workflow** (not Re-run jobs on an older commit).

## Features
- Up to 20 new items every 6 hours (Iran time), with a 24-hour freshness window.
- Source-by-source diagnostics in GitHub Actions logs.
- Editorial RSS + Google News discovery; no Reddit discussion feed.
- Filters unrelated games, casual discussion posts, and irrelevant titles.
- Prefers articles with images and attempts article OG image for direct article URLs.
- Optional best-effort unofficial translation of titles via Google Translate endpoint (may fail; original English is retained).
- Conservative credibility labels; Google News links do not establish an official publisher domain.
- `seen.json` committed back to repository to prevent repeated URLs. GitHub Actions can be delayed and sources can be temporarily unavailable.

## Caveats
- No guarantee of 20 items or an image for every article.
- Not a full-article summarizer, and machine-translated headlines should be reviewed before publication.
- Google News indexes only a subset of posts; searches for X/YouTube personalities are indirect, not direct monitoring.
- News from the same event under different titles can still be duplicated.
- Some RSS sites may fail or block requests; source logs show failures.
- News URLs from Google News are redirect links, not necessarily original publisher links.
