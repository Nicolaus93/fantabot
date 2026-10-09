"""Telegram routing independent of HTTP and model inference."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GroupMessage:
    update_id: int
    chat_id: int
    user_id: int
    message_id: int
    thread_id: int | None
    text: str

    @property
    def conversation_id(self):
        return f"telegram:{self.chat_id}:{self.thread_id or 0}"


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _addressed_text(message, bot_username, bot_id):
    text = message["text"].strip()
    command = re.match(r"^/ask(?:@([A-Za-z0-9_]+))?(?:\s|$)", text, re.IGNORECASE)
    if command:
        if command[1] and command[1].lower() != bot_username.lower():
            return None
        return text[command.end() :].strip()
    if text.startswith("/"):
        return None  # Other slash commands are not ordinary @mentions.
    mention = re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)
    reply = message.get("reply_to_message", {})
    reply_sender = reply.get("from", {}) if isinstance(reply, dict) else {}
    replying = isinstance(reply_sender, dict) and reply_sender.get("id") == bot_id
    if not mention.search(text) and not replying:
        return None
    return mention.sub("", text).strip()


def addressed_message(update, allowed_chat_id, bot_username, bot_id):
    """Only /ask, explicit mentions and replies to this bot in the allowed group."""
    if not isinstance(update, dict) or not is_int(update.get("update_id")):
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None  # Ignore edited messages, channel posts and service events.
    chat = message.get("chat", {})
    sender = message.get("from", {})
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return None
    if chat.get("id") != allowed_chat_id or chat.get("type") not in ("group", "supergroup"):
        return None
    if sender.get("is_bot") or not is_int(sender.get("id")):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not is_int(message.get("message_id")):
        return None
    thread = message.get("message_thread_id")
    if thread is not None and not is_int(thread):
        return None
    text = _addressed_text(message, bot_username, bot_id)
    if text is None:
        return None
    return GroupMessage(
        update["update_id"], chat["id"], sender["id"], message["message_id"], thread, text
    )


def send_reply(client, token, message, text):
    """Plain text avoids Telegram Markdown escaping problems; cap at its text limit."""
    payload = {
        "chat_id": message.chat_id,
        "text": text[:4000],
        "reply_parameters": {"message_id": message.message_id, "allow_sending_without_reply": True},
    }
    if message.thread_id is not None:
        payload["message_thread_id"] = message.thread_id
    response = client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected the reply")
