# Vercel migration notes

This branch is preparation only; it is not deployable yet.

## Why the current bot cannot be deployed to Vercel as-is

- `bot.py` starts long polling with `dp.start_polling(bot)`. Vercel Functions are request-driven and do not keep that process running.
- The bot uses SQLite at `expenses.db`. Serverless filesystem storage is not durable, so expense records can disappear between deployments or instances.
- FSM state uses aiogram `MemoryStorage`, which is process-local and is not reliable across separate function invocations.

## Required implementation before deployment

1. Refactor handler registration so the dispatcher can be imported by a webhook endpoint without starting polling.
2. Add a Vercel Python Function (for example `api/webhook.py`) that validates Telegram's webhook secret header and feeds updates to aiogram.
3. Move expense/category storage to a managed PostgreSQL database and replace SQLite-specific calls with an async or safely managed PostgreSQL layer.
4. Replace `MemoryStorage` with durable FSM storage (Redis-compatible storage) or redesign the short category-selection flow so it can recover from stateless requests.
5. Add a health endpoint and tests for start, expense creation, category selection, report, and duplicate webhook delivery.
6. Configure secrets in Vercel Project Settings only: `BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and database connection settings. Never commit real values.
7. Deploy first to a preview environment, set Telegram's webhook to the preview URL, verify updates and persistent records, then switch to production.

## Security

If a bot token was ever pasted into a chat or committed to Git, revoke it with @BotFather and use a fresh token stored only in the hosting provider's environment variables.

## Current status

No Vercel deployment has been made. Do not import this branch as a working production deployment until the implementation steps above are complete.
