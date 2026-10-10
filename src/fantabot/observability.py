"""Actionable error summaries without dumping requests or raw exception bodies."""

import hashlib
import json
import logging
import os
import re
import traceback
from pathlib import Path

LOGGER = logging.getLogger("fantabot.chat")
SECRET_VARIABLES = (
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_FANTABOT_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "CHAT_API_KEY",
    "TELEGRAM_WEBHOOK_SECRET",
)


def _safe_text(value, sensitive, limit=1000):
    text = str(value)
    # Redact before truncating, including JSON-escaped versions of prompt text.
    for secret in sorted(set(sensitive), key=len, reverse=True):
        if not secret:
            continue
        text = text.replace(secret, "[REDACTED]")
        text = text.replace(json.dumps(secret, ensure_ascii=True)[1:-1], "[REDACTED]")
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b", "[REDACTED]", text)
    return text[:limit]


def _error_fields(body):
    if not isinstance(body, dict):
        return {}
    error = body.get("error", body)
    return error if isinstance(error, dict) else {}


def log_chat_error(exc, *, model, request_id, prompt_contents):
    """Log a bounded JSON event to Modal stderr; never dump response/request bodies.

    Provider summaries may still contain sensitive fragments not matching a known
    secret or full prompt. Keep logs access-controlled; do not publish them.
    """
    sensitive = [*prompt_contents, *(os.getenv(key, "") for key in SECRET_VARIABLES)]
    body = getattr(exc, "body", None)
    error = _error_fields(body)
    message = error.get("message")
    if not isinstance(message, str):
        message = str(exc) if body is None else "No provider error message available"
    status = getattr(exc, "status_code", None)
    metadata = error.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    fields = {
        "event": "chat.request.failed",
        "request_ref": hashlib.sha256(request_id.encode()).hexdigest()[:12],
        "model": _safe_text(model, sensitive, 200),
        "error_type": type(exc).__name__,
        "http_status": status if isinstance(status, int) else None,
        "message": _safe_text(message, sensitive),
    }
    for name, value in (
        ("error_code", error.get("code")),
        ("provider", metadata.get("provider_name")),
        ("provider_request_id", getattr(exc, "request_id", None)),
    ):
        if isinstance(value, (str, int)):
            fields[name] = _safe_text(value, sensitive, 200)
    # OpenRouter can nest an upstream error in metadata.raw. Only extract its
    # message/code from JSON; never dump raw text, headers, prompts or other fields.
    raw = metadata.get("raw")
    if isinstance(raw, str) and len(raw) <= 16384:
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    upstream = _error_fields(raw)
    if isinstance(upstream.get("message"), str):
        fields["upstream_message"] = _safe_text(upstream["message"], sensitive)
    frames = traceback.extract_tb(exc.__traceback__)[-8:]
    fields["traceback_locations"] = [
        f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}" for frame in frames
    ]
    LOGGER.error(json.dumps(fields, ensure_ascii=False))
