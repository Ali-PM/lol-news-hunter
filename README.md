# LoL News Hunter

Replace your existing `bot.py`, `requirements.txt`, and `.github/workflows/news.yml` with these files. Keep GitHub Actions secrets `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`. GitHub Actions workflow permissions must allow writing repository contents. Use a **private** repository. The first run may send up to 12 items from the last 8 hours. The schedule is UTC and may be delayed. `seen.json` is committed automatically to remember successfully sent links; it is not a semantic duplicate detector.

Reddit feeds and Google News searches are best-effort, not guaranteed exhaustive. X, YouTube, and asset archives are not directly polled. Labels are conservative heuristics, not fact-checks. The publication timestamp is taken from each feed and may not be the original publication time.
