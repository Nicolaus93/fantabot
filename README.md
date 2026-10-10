# Fantabot

Italian group chat bot with a shared, authenticated Modal `/chat` endpoint.
The default model is **Qwen3 30B A3B Instruct 2507** via OpenRouter
(`qwen/qwen3-30b-a3b-instruct-2507`); no GPU is required. It is a multilingual,
non-reasoning model, so the reply allowance is not consumed by hidden reasoning.
OpenRouter's catalog lists $0.10/million input tokens and $0.30/million output
tokens (checked 2026-10-09). Italian chat quality still needs a live trial.
The `openai` Python dependency is only the compatible client SDK; requests go to
OpenRouter, and no OpenAI account or API key is required. Existing
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
OPENROUTER_API_KEY=replace-me
CHAT_MODEL=qwen/qwen3-30b-a3b-instruct-2507
TELEGRAM_BOT_TOKEN=replace-me
TELEGRAM_BOT_USERNAME=YourBotUsernameWithoutAt
TELEGRAM_GROUP_ID=-1001234567890
CHAT_API_KEY=replace-with-a-long-random-secret
TELEGRAM_WEBHOOK_SECRET=replace-with-a-different-random-secret
MONTHLY_BUDGET_EUR=15
EUR_PER_USD=1.10
INPUT_USD_PER_MILLION=0.10
OUTPUT_USD_PER_MILLION=0.30
MAX_OUTPUT_TOKENS=512
COOLDOWN_SECONDS=15
```

`TELEGRAM_GROUP_ID` is the numeric ID of the single allowed group/supergroup.
Before registering a webhook, add the bot to your group, send
`/ask@YourBotUsername hello`, then find the ID with:

```sh
uv run --env-file .env python -m fantabot.get_group_id
```

Copy the printed negative ID (including its minus sign) into `.env`. The helper
reads pending updates only; it does not disable a webhook or consume updates.
If a webhook is already active, Telegram blocks this method.

`TELEGRAM_BOT_USERNAME` must match BotFather. Generate independent secrets with
`uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
Telegram's webhook secret permits only letters, digits, `_` and `-`.

```sh
uv run modal setup
uv run modal secret create fantabot-secrets --from-dotenv .env
uv run modal deploy --strategy recreate -m fantabot.modal_app
```

The deployment prints the base web URL. Register it as described below.

### Updating an existing OpenAI-based deployment

In your local `.env`, replace `OPENAI_API_KEY` with `OPENROUTER_API_KEY`, set
`CHAT_MODEL=qwen/qwen3-30b-a3b-instruct-2507`, and change the input/output prices
to `0.10` and `0.30`. Keep the Telegram token and both authentication secrets.
Use your funded OpenRouter account's API key, ideally with a dedicated key limit.
Then update the Modal secret and recreate the deployment:

```sh
uv run modal secret create fantabot-secrets --from-dotenv .env --force
uv run modal deploy --strategy recreate -m fantabot.modal_app
```

If the endpoint URL is unchanged, you do not need to register the webhook again.
The new chat deployment never reads an OpenAI key; old news/scraping scripts
remain separate and still use their own original provider configuration.

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
  provider price changes are outside application control. OpenRouter credit-purchase
  fees are also separate from token usage. Set an OpenRouter key spending limit
  and Modal billing alerts/limits separately.
- Prices are configurable estimates, not live pricing. Verify current provider
  rates before deploying. `EUR_PER_USD=1.10` is a conservative conversion buffer,
  not a live exchange rate. When changing `CHAT_MODEL`, both token prices must
  be explicitly configured. Models must support OpenRouter text chat completions
  and `max_tokens`; test compatibility and tokenizer bounds first. Requests cap
  provider input/output prices at the configured rates and require parameter
  support. If no provider fits, the call fails instead of exceeding the price cap.
  Routing sorts by price and allows backup providers within the same price caps
  when a provider is unavailable or throttled. Client-side automatic retries remain
  disabled. HTTP 429 produces a temporary-busy reply; structured worker logs record
  redacted provider summaries, error type, HTTP status and traceback locations.
- A reservation for the maximum estimated request cost is saved before inference.
  Success conservatively reconciles token usage at the configured price ceilings
  (a cheaper routed provider may actually cost less); failures/uncertain calls retain
  the reservation. No automatic client-side retries. Budget resets by UTC calendar
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

## Error logs

Modal captures the worker's stderr. In the dashboard, inspect the `ChatWorker`
function's logs (not just whether the call succeeded); handled chat errors still
return a friendly Telegram reply. You can also fetch or follow logs locally:

```sh
uv run modal app logs fantabot-chat --tail 100 --search chat.request.failed --timestamps
uv run modal app logs fantabot-chat --follow
```

Error events are JSON with `event=chat.request.failed`, a hashed `request_ref`,
model, exception type, HTTP status and the provider's error message. When supplied,
they include provider name, upstream JSON error message and provider request ID.
Traceback entries contain file/line/function locations, not local variables or
source lines. Raw response bodies and non-JSON upstream dumps are omitted.
Known environment secrets, token patterns, and full current/history prompt text
are redacted before truncation. This cannot guarantee removal of arbitrary private
fragments echoed by a provider: keep log access restricted and do not publish logs.
No Temporal deployment or external log service is required.

After changing the logging code, redeploy using `--strategy recreate`; existing
log entries cannot retroactively gain the details that were not recorded.

## Layout

- `src/fantabot/modal_app.py`: Modal deployment and serial worker.
- `src/fantabot/web.py`: authenticated HTTP API and Telegram webhook.
- `src/fantabot/chat.py`: provider adapter, prompt and cost orchestration.
- `src/fantabot/state.py`: persistent history, cooldowns, deduplication and budget.
- `src/fantabot/telegram.py`: group routing and reply delivery.
- `tests/`: offline tests with fake provider/worker; no real credentials or API calls.
