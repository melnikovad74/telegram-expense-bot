"""Register Telegram webhook for the deployed Vercel project."""
import json
import os
import urllib.parse
import urllib.request

token = os.environ["BOT_TOKEN"]
secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]
base_url = os.environ["PUBLIC_BASE_URL"].rstrip("/")
if not base_url.startswith("https://"):
    raise SystemExit("PUBLIC_BASE_URL must be an https:// URL")
if not (32 <= len(secret) <= 256) or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in secret):
    raise SystemExit("TELEGRAM_WEBHOOK_SECRET must be 32-256 chars using A-Z, a-z, 0-9, _ or -")

url = f"https://api.telegram.org/bot{token}/setWebhook"
body = urllib.parse.urlencode({
    "url": f"{base_url}/api/webhook",
    "secret_token": secret,
    "allowed_updates": json.dumps(["message", "callback_query"]),
    "drop_pending_updates": "false",
}).encode()
request = urllib.request.Request(url, data=body, method="POST")
with urllib.request.urlopen(request, timeout=20) as response:
    result = json.loads(response.read().decode())
if not result.get("ok"):
    raise SystemExit(f"Telegram rejected webhook registration: {result}")
print("Webhook registered successfully.")
