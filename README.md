# LoL News Hunter v6

Balanced English-language League of Legends news collector.

- Every 6 hours (GitHub Actions cron; runs can be delayed).
- Maximum 20 items per run, at most 4 from each of 5 categories.
- Maximum 3 items from any single named source per run.
- Categories: Official & Game Updates; Skins & PBE; Esports & Transfers; Leaks & Rumors; Community, Bugs & Content.
- English titles and English credibility labels; no translation requests.
- 24-hour publication window; avoids previously sent URLs using `seen.json`.
- Images where available; text fallback; no general Reddit discussion feeds.
- Reports per-source filter stats and selected-category counts in Actions logs.

## Install
Replace `bot.py`, `requirements.txt`, `.github/workflows/news.yml` in your GitHub repo and commit. Keep your existing `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` Actions secrets. In repository Settings > Actions > General, allow Read and write permissions so workflow can commit `seen.json`. Run a NEW workflow execution from main (not Re-run jobs).

Notes: categories are inferred from title/source using rules, not AI verification. A story may be miscategorized. Google News searches do not guarantee discovery of every publisher post. 20 is a ceiling, not a target. Telegram captions use original English titles. Existing seen.json is preserved in the repo.
