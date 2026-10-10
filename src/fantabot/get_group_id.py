"""Find Telegram group IDs from pending updates without changing the webhook."""

import logging
import os
import sys

import httpx


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env and run with uv run --env-file .env.")
    # HTTPX INFO logs include Telegram's token-bearing URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        with httpx.Client(timeout=20) as client:
            data = client.get(f"https://api.telegram.org/bot{token}/getUpdates").json()
    except Exception as exc:
        # Do not print HTTP exceptions: their request URLs contain the token.
        sys.exit(f"Telegram request failed ({type(exc).__name__}); check network and credentials.")
    if not data.get("ok"):
        if data.get("error_code") == 409:
            sys.exit(
                "getUpdates conflicts with an active webhook or another polling client. "
                "Stop polling, or remove the webhook temporarily and register it again afterward. "
                "This script does not change your webhook."
            )
        sys.exit("Telegram rejected the request; check your bot token.")
    groups = {}
    for update in data.get("result", []):
        chat = update.get("message", {}).get("chat", {})
        if chat.get("type") in ("group", "supergroup"):
            groups[chat["id"]] = chat.get("title", "Untitled group")
    if not groups:
        print("No groups found. Add the bot and send /ask@YourBotUsername hello in your group.")
        return
    for group_id, title in groups.items():
        print(f"{title}: TELEGRAM_GROUP_ID={group_id}")


if __name__ == "__main__":
    main()
