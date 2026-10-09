# Fantabot

Italian group chat bot with a shared, authenticated Modal `/chat` endpoint.
The first version uses GPT-4o-mini via OpenAI; no GPU is required. Existing
football scraping, news and voice scripts remain under `src/` and are not
connected to chat yet. The bot explicitly does **not** claim live football data.

## Python project (uv)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
uv sync --locked
uv run pytest
uv run ruff check src/fantabot tests
```

Python 3.11+ is required. `pyproject.toml` declares runtime dependencies and the
dev dependency group; `uv.lock` pins the resolution. Modal builds use the same
lockfile, without dev dependencies. Do not commit `.env` files or credentials.
Legacy news dependencies are optional: `uv sync --extra legacy-news`.
The old standalone `scraping.py` experiment (`crawl4ai`) and football/XTTS Modal
images remain independent and are not installed by the chat project's lockfile.
The old XTTS deployment keeps its separate, heavyweight Modal image.

## Credentials and configuration

**Revoke the old Telegram token through BotFather first.** It was committed in
legacy scripts. Removing it from current files does not remove it from Git history.
Create a new bot or rotate the token, then add the bot to the group.

Create a local `.env` (ignored by Git) with:

```dotenv
OPENAI_API_KEY=replace-me
TELEGRAM_BOT_TOKEN=replace-me
TELEGRAM_BOT_USERNAME=YourBotUsernameWithoutAt
TELEGRAM_GROUP_ID=-1001234567890
CHAT_API_KEY=replace-with-a-long-random-secret
TELEGRAM_WEBHOOK_SECRET=replace-with-a-different-random-secret
MONTHLY_BUDGET_EUR=15
EUR_PER_USD=1.10
INPUT_USD_PER_MILLION=0.15
OUTPUT_USD_PER_MILLION=0.60
MAX_OUTPUT_TOKENS=512
COOLDOWN_SECONDS=15
```

`TELEGRAM_GROUP_ID` is the numeric ID of the single allowed group/supergroup.
`TELEGRAM_BOT_USERNAME` must match BotFather. Generate independent secrets with
`uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Telegram's webhook secret permits only letters, digits, `_` and `-`.

```sh
uv run modal setup
uv run modal secret create fantabot-secrets --from-dotenv .env
uv run modal deploy --strategy recreate -m fantabot.modal_app
```

The deployment prints the base web URL. Register it as described below.

### Telegram webhook

For @mentions and replies to work reliably, turn **group privacy off** using
BotFather `/setprivacy`, then remove/re-add the bot if Telegram requires it.
Do not grant administrator privileges unless needed. The application ignores
ordinary group messages despite receiving them; it answers only `/ask`,
`/ask@YourBotUsername`, explicit @mentions and replies to its own messages.
Topic history is isolated; history within one topic is shared by group members.

Register without placing the token in shell arguments or command history:

```sh
uv run --env-file .env python -m fantabot.setup_webhook --url https://YOUR-MODAL-URL
```

`uv` loads the local `.env`; the helper verifies bot identity and registers `/telegram/webhook`
with the webhook secret and `allowed_updates=["message"]`. Existing pending
updates are dropped on registration to avoid replying to old conversations.

## Shared chat API

`POST /chat` accepts `Authorization: Bearer <CHAT_API_KEY>` and JSON:

```json
{
  "request_id": "unique-id-for-this-request",
  "conversation_id": "my-app-room",
  "user_id": "alice",
  "text": "Chi schiereresti tra questi due attaccanti?"
}
```

Responses contain `status` and `text`. Within a conversation, reusing an ID with
the same payload returns the stored response without another model call; changing
its user or text is a conflict. Use a new ID for a new question. `/health` is unauthenticated and returns
only liveness. API and Telegram conversation/user IDs occupy separate namespaces.
Treat the chat key as a trusted backend credential, not a browser/public client key.

## Budget, persistence and limitations

- A default **€15/month model allowance** leaves a target €5 for Modal. This is
  **not a guaranteed €20 combined bill cap**: hosting, taxes, exchange rates and
  provider price changes are outside application control. Set provider spend
  limits where available and Modal billing alerts/limits separately.
- Prices are configurable estimates, not live pricing. Verify current provider
  rates before deploying. `EUR_PER_USD=1.10` is a conservative conversion buffer,
  not a live exchange rate. When changing `CHAT_MODEL`, both token prices must
  be explicitly configured. Models must support OpenAI text chat completions
  and `max_completion_tokens`; test compatibility first.
- A reservation for the maximum estimated request cost is saved before inference.
  Success reconciles against reported token usage; failures/uncertain calls retain
  the reservation. No automatic provider retries. Budget resets by UTC calendar
  month, not by restarting/deploying containers.
- A single serial Modal worker owns SQLite on the `fantabot-state` volume. Requests
  queue; the web layer scales separately and Telegram work is spawned so webhook
  acknowledgement is quick. **Do not increase worker concurrency/containers** or
  run a second deployment against the same volume. Always deploy with
  `--strategy recreate` (as above), not the default rolling deployment, to avoid
  overlapping old/new writers. SQLite on Modal Volumes is not a distributed
  database. Higher throughput needs a transactional hosted database.
- Telegram updates are claimed durably before processing/sending, suppressing
  retries. Delivery is **at most once**, not guaranteed: a crash between claim and
  send can lose a reply; failed Telegram sends are not automatically retried.
- Per-user cooldown is 15 seconds; input limit 4000 characters; output limit 512
  tokens; history is at most 12 messages/16 KB and expires after seven days.
  At most roughly 1000 recently used conversations are retained. Request/update
  deduplication records expire after 35 days. Conversation text is stored on the
  volume, not intentionally logged; inform group members of this retention.
- Empty prompts get usage guidance without inference. Replies use plain text, not
  Markdown. Bot messages, edits, channel posts and other groups are ignored.
- Football tools, voice, streaming and per-user access controls beyond the allowed
  group are future work. Do not give the model credentials or private data.

## Layout

- `src/fantabot/modal_app.py`: Modal deployment and serial worker.
- `src/fantabot/web.py`: authenticated HTTP API and Telegram webhook.
- `src/fantabot/chat.py`: provider adapter, prompt and cost orchestration.
- `src/fantabot/state.py`: persistent history, cooldowns, deduplication and budget.
- `src/fantabot/telegram.py`: group routing and reply delivery.
- `tests/`: offline tests with fake provider/worker; no real credentials or API calls.
