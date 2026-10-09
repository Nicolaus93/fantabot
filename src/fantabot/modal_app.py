"""Deploy with: uv run modal deploy --strategy recreate -m fantabot.modal_app."""

import logging
import os
from pathlib import Path

import modal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_sync(str(PROJECT_ROOT), extra_options="--no-dev", uv_version="0.11.14")
    .add_local_python_source("fantabot")
)
app = modal.App("fantabot-chat", image=image)
secrets = [modal.Secret.from_name("fantabot-secrets")]
volume = modal.Volume.from_name("fantabot-state", create_if_missing=True)


@app.cls(
    secrets=secrets,
    volumes={"/state": volume},
    max_containers=1,
    min_containers=0,
    buffer_containers=0,
    scaledown_window=60,
    timeout=120,
    retries=0,
    cpu=0.25,
    memory=512,
)
class ChatWorker:
    """Exactly one serial input: SQLite and budget need a single writer.

    Do not add @modal.concurrent, container replicas, or another app sharing this
    volume. Web endpoints can scale independently without scaling this writer.
    """

    @modal.enter()
    def setup(self):
        from fantabot.chat import ChatService, OpenAIProvider
        from fantabot.config import Settings
        from fantabot.state import State

        # HTTPX INFO request logs include Telegram's token-bearing URL.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        settings = Settings.from_env()
        self.state = State("/state/chat.sqlite3", persist=volume.commit)
        self.service = ChatService(
            self.state, OpenAIProvider(os.environ["OPENAI_API_KEY"], settings), settings
        )

    @modal.method()
    def chat(self, request_id: str, conversation: str, user: str, text: str):
        return self.service.chat(request_id, conversation, user, text)

    @modal.method()
    def telegram(self, update: dict):
        import httpx

        from fantabot.telegram import addressed_message, send_reply

        token = os.environ["TELEGRAM_BOT_TOKEN"]
        message = addressed_message(
            update,
            int(os.environ["TELEGRAM_GROUP_ID"]),
            os.environ["TELEGRAM_BOT_USERNAME"],
            int(token.split(":", 1)[0]),
        )
        if message is None or not self.state.claim_delivery(message.update_id):
            return
        result = self.service.chat(
            f"telegram:{message.update_id}",
            message.conversation_id,
            f"telegram:{message.user_id}",
            message.text,
        )
        try:
            with httpx.Client(timeout=15) as client:
                send_reply(client, token, message, result["text"])
        except Exception as exc:
            logging.warning("Telegram delivery failed (%s)", type(exc).__name__)


@app.function(
    secrets=secrets,
    min_containers=0,
    max_containers=2,
    scaledown_window=60,
    cpu=0.25,
    memory=256,
)
@modal.asgi_app()
def web():
    from fantabot.web import create_web_app

    worker = ChatWorker()
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return create_web_app(
        worker.chat.remote.aio,
        worker.telegram.spawn.aio,
        api_key=os.environ["CHAT_API_KEY"],
        webhook_secret=os.environ["TELEGRAM_WEBHOOK_SECRET"],
        group_id=int(os.environ["TELEGRAM_GROUP_ID"]),
        bot_username=os.environ["TELEGRAM_BOT_USERNAME"],
        bot_id=int(token.split(":", 1)[0]),
    )
