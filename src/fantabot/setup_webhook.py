"""Register Telegram webhook without exposing the bot token on command lines."""

import argparse
import os
from urllib.parse import urlparse

import httpx


def register_webhook(client, token, username, base_url, secret):
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Use the HTTPS base URL printed by Modal (no query or fragment)")
    root = f"https://api.telegram.org/bot{token}"
    identity = client.get(f"{root}/getMe")
    identity.raise_for_status()
    account = identity.json()
    if not account.get("ok") or account["result"].get("username", "").lower() != username.lower():
        raise ValueError("TELEGRAM_BOT_USERNAME does not match the token")
    response = client.post(
        f"{root}/setWebhook",
        json={
            "url": base_url.rstrip("/") + "/telegram/webhook",
            "secret_token": secret,
            "allowed_updates": ["message"],
            "drop_pending_updates": True,
            "max_connections": 2,
        },
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected webhook registration")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Base HTTPS URL printed by Modal")
    args = parser.parse_args()
    try:
        with httpx.Client(timeout=20) as client:
            register_webhook(
                client,
                os.environ["TELEGRAM_BOT_TOKEN"],
                os.environ["TELEGRAM_BOT_USERNAME"],
                args.url,
                os.environ["TELEGRAM_WEBHOOK_SECRET"],
            )
    except Exception as exc:
        # HTTP exceptions can contain the token-bearing request URL. Never print it.
        parser.exit(1, f"Registration failed ({type(exc).__name__}); check URL and credentials.\n")
    print("Telegram webhook registered; old pending updates were dropped.")


if __name__ == "__main__":
    main()
