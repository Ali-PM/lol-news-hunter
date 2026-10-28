# LoL News Hunter v4

- Four runs daily (Iran local 00:00, 06:00, 12:00, 18:00), subject to GitHub schedule delays.
- Up to 20 individual news messages per run, not guaranteed 20 if fewer eligible stories exist.
- No Reddit feeds, TFT, Wild Rift, VALORANT, 2XKO; filters generic discussion headlines.
- Uses direct RSS plus Google News RSS search for third-party sources. Coverage of Google News search is not exhaustive.
- Tries RSS image, then article og:image on direct URLs; otherwise text with Telegram link preview.
- Keeps source headline in English. Persian credibility labels and hashtags, **not** translated headlines or article summaries. Automated free translation/summarization requires an additional service and may have cost/limits.
- Date shown is feed timestamp, which may differ from original publication time.
- Credibility tags are heuristic, not independent verification. A Google News result found via official-domain query is not independently domain-verified; manually verify important stories.
- `seen.json` persists to the repo via GitHub Actions with contents: write permission; Settings > Actions > General > Workflow permissions may need Read and write.
- Install `bot.py`, `requirements.txt`, `.github/workflows/news.yml` to repo root / matching path. Keep secrets TELEGRAM_TOKEN and TELEGRAM_CHAT_ID.
- First run may send older stories within 12h; later runs deduplicate by link. If GitHub cannot push seen.json, duplicates may recur.
