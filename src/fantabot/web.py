"""HTTP boundary: authenticate before reading bodies or scheduling work."""

import hmac
import json
import logging
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fantabot.telegram import addressed_message


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    conversation_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    user_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    text: str = Field(min_length=1, max_length=4000)


def authenticate(supplied, expected):
    if not isinstance(supplied, str) or not hmac.compare_digest(
        supplied.encode(), expected.encode()
    ):
        raise HTTPException(401, "Unauthorized")


async def bounded_json(request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            raise HTTPException(413, "Body too large")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid JSON") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "Expected a JSON object")
    return data


def create_web_app(
    chat_call, telegram_enqueue, *, api_key, webhook_secret, group_id, bot_username, bot_id
):
    if len(api_key) < 24 or len(webhook_secret) < 24:
        raise ValueError("Use independent API/webhook secrets of at least 24 characters")
    if api_key == webhook_secret:
        raise ValueError("API and webhook secrets must be different")
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,256}", webhook_secret):
        raise ValueError("Invalid Telegram webhook secret")
    if group_id >= 0 or bot_id <= 0 or not re.fullmatch(r"[A-Za-z0-9_]+", bot_username):
        raise ValueError("Invalid group or bot configuration")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/chat")
    async def chat(request: Request):
        authenticate(request.headers.get("authorization"), f"Bearer {api_key}")
        data = await bounded_json(request)
        try:
            payload = ChatRequest.model_validate(data)
        except ValidationError:
            raise HTTPException(422, "Invalid chat request") from None
        try:
            result = await chat_call(
                f"api:{len(payload.conversation_id)}:{payload.conversation_id}:{payload.request_id}",
                f"api:{payload.conversation_id}",
                f"api:{payload.user_id}",
                payload.text,
            )
        except Exception as exc:
            logging.warning("Chat worker unavailable (%s)", type(exc).__name__)
            raise HTTPException(503, "Chat worker unavailable") from None
        status_code = {
            "ok": 200,
            "invalid": 400,
            "conflict": 409,
            "pending": 409,
            "cooldown": 429,
            "budget": 503,
            "error": 502,
        }[result["status"]]
        return JSONResponse(result, status_code=status_code)

    @app.post("/telegram/webhook")
    async def webhook(request: Request):
        authenticate(request.headers.get("x-telegram-bot-api-secret-token"), webhook_secret)
        update = await bounded_json(request)
        message = addressed_message(update, group_id, bot_username, bot_id)
        if message is not None:
            try:
                await telegram_enqueue(update)
            except Exception as exc:
                logging.warning("Telegram enqueue failed (%s)", type(exc).__name__)
                # Let Telegram retry if durable dispatch itself fails.
                raise HTTPException(503, "Worker unavailable") from None
        return {"ok": True}

    return app
