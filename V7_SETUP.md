# LoL News Hunter v7 — phase 1

Branch: `v7-development`. Main is unchanged. AI is not enabled yet.

## Cloudflare
1. Create a free Cloudflare account and D1 database named `lol-news-hunter`.
2. In `worker/`, copy `wrangler.toml.example` to `wrangler.toml` and fill in the D1 database ID. Do not commit credentials.
3. Run `npx wrangler d1 execute lol-news-hunter --remote --file=schema.sql`.
4. Configure Worker secrets with `npx wrangler secret put NAME`: `TELEGRAM_TOKEN`, `ALLOWED_CHAT_ID`, `WEBHOOK_SECRET`, `INGEST_SECRET`.
5. Set ALLOWED_CHAT_ID to the verified group ID, including the minus sign. Generate separate random secrets with `python -c "import secrets;print(secrets.token_urlsafe(32))"`.
6. Deploy: `npx wrangler deploy`.

## Telegram
Set the webhook from a terminal with environment variables (never paste tokens in chat):
```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" --data-urlencode "url=${WORKER_URL}/telegram" --data-urlencode "secret_token=${WEBHOOK_SECRET}" --data-urlencode 'allowed_updates=["message","callback_query"]'
```
The bot should be a group administrator for reliable membership checks. Commands work only **inside** the configured group.

## GitHub
Add repository Actions secrets `ARCHIVE_URL` (Worker URL without /ingest) and `ARCHIVE_SECRET` (same as Worker INGEST_SECRET). Existing Telegram secrets remain unchanged.
Only after testing on the development branch should the changes be merged to main. The collector archives only successfully sent new articles. Existing seen.json does not contain historical descriptions.

## BotFather
```
start - Bot introduction
help - Available commands
latest - Latest news
history - Browse news archive
skins - Skins and PBE updates
esports - Esports and transfers
leaks - Leaks and rumors
```
No AI /ask in phase 1.
