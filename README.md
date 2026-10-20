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
uv run ty check
uv run prek install
```

Python 3.11+ is required. `pyproject.toml` declares runtime dependencies and the
dev dependency group; `uv.lock` pins the resolution. Modal builds use the same
lockfile, without dev dependencies. Do not commit `.env` files or credentials.
Legacy news dependencies are optional: `uv sync --extra legacy-news`.
The old standalone `scraping.py` experiment (`crawl4ai`) and football/XTTS Modal
images remain independent and are not installed by the chat project's lockfile.
The old XTTS deployment keeps its separate, heavyweight Modal image.

## Common commands (just)

Install [just](https://just.systems/man/en/packages.html) separately, then run
`just` to list the recipes. Python commands use the locked uv environment;
Telegram helpers load credentials from the local `.env` without passing tokens
as command-line arguments.

To find another group's ID while the bot already has an active webhook:

```sh
just webhook-remove
# Send /ask@YourBotUsername hello in the new group.
just group-id
just webhook-set https://YOUR-MODAL-URL
```

Removal preserves pending updates and temporarily stops Telegram delivery. Keep
your existing Modal base URL handy and always restore the webhook afterward.
Registration currently discards queued old updates. Finding a second group ID
alone does not enable it: this version still allows only one `TELEGRAM_GROUP_ID`.

Other recipes: `just sync`, `just hooks-install`, `just check`, `just test`,
`just typecheck`, `just secrets-upload`, `just deploy`, `just logs` and
`just logs-follow`. Deploying does not automatically update secrets or register
webhooks; these are explicit separate steps.

The removal script can also be run directly:

```sh
uv run --locked --env-file .env python -m fantabot.remove_webhook
```

## Pre-commit checks (prek)

`prek`, Ruff and `ty` are locked dev dependencies. After `uv sync --locked`, run
`uv run prek install` once per clone to enable checks on every commit. To check
the whole repository manually:

```sh
uv run prek run --all-files
```

`prek.toml` runs whitespace/end-of-file/line-ending fixes, YAML/TOML/JSON validation,
merge-marker, large-file, case-conflict, symlink and private-key checks. It also
blocks `.env` files (except `.env.example`). Ruff automatically fixes lint and
formats the active package/tests, then `ty` checks them, pytest runs the offline
suite, and `uv lock --check` verifies dependency changes have an up-to-date lockfile.
Python tooling is scoped to `src/fantabot/` and `tests/`; standalone legacy scripts
retain their independent dependencies and receive only the generic hygiene checks.
Hooks run in order, so formatters complete before type checking/tests.

If a hook changes files, review and re-stage them, then retry the commit. After
editing dependencies, run `uv lock` and commit both `pyproject.toml` and `uv.lock`.
The native `repo = "builtin"` hooks need no extra downloaded hook environments;
Python hooks use the project's locked environment through `uv`.

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

## League standings: `/classifica`

Send `/classifica` or `/classifica@YourBotUsername` in the configured Telegram
group. The bot returns team names (**Squadra**) and league points (**pt**), not
`pt totali`, for [Fantacalcio a casaccio, competition 867709](https://leghe.fantacalcio.it/fantacalcio-a-casaccio/view/competition/867709/standings).
The response preserves the site's ranking and replies in the same topic.
This command does not call the language model or consume the model budget.
Normal `/ask`, mentions and replies are unchanged.

Create a dedicated Fantacalcio account and have it join that league. Add these
values to your local ignored `.env`, retaining all existing bot configuration:

```dotenv
FANTACALCIO_USERNAME=your-dedicated-account-username
FANTACALCIO_PASSWORD=your-dedicated-account-password
```

Upload the **complete** `.env` using `just secrets-upload`, which replaces the
existing `fantabot-secrets` Modal Secret; do not upload a file containing only the
two new values. Then deploy with `just deploy`. Credentials belong in Modal secrets,
not GitHub, source code, chat, or command-line arguments. Never copy browser cookies.
No Telegram webhook change is needed; optionally add `classifica` in BotFather's
command menu (menu registration is not required for routing).

The adapter uses Fantacalcio's web login and read-only APIs, not a documented
public integration contract. The production web application's public `app_key`
is an application identifier, not an account credential. Login uses the dedicated
username/password; a league JWT accesses team names/calendar, while the login
cookie jar accesses the legacy standings endpoint. Sessions live only in memory
and are discarded after each fetch; no browser session or SQLite auth storage is
used. A fresh login on cache expiry avoids relying on undocumented refresh behavior.
Results are cached for 60 seconds per serial worker, failures for 30 seconds.
Timeouts, denied access, invalid responses and missing credentials produce a safe
unavailable message without affecting ordinary chat or logging session material.
Failures emit a JSON warning with `event=fantacalcio.standings.failed`, the
`stage` (`configuration`, `login`, `calendar`, `status`, `teams`, or `standings`),
`http_status`, `json_response` (whether the declared content type is JSON), and
`error_type`. A timeout before headers has a null status; an API rejection may have
HTTP 200 with `ValueError`. HTTP failures also include `error_codes`: up to five
allowlisted Fantacalcio identifiers (`ATH000`–`ATH099`, `AD00`–`AD99`, `S000`–`S099`)
from known error fields. An empty list means no recognized code was found, not
that authentication succeeded. Responses larger than 16 KB are not inspected.
No raw URLs, headers, exception messages, descriptions or response bodies are logged. After a failure, wait at least 30 seconds before retrying to
get a new diagnostic rather than the cached unavailable reply.

The latest calculated competition round is determined from its calendar and league
status, rather than hardcoding the current day. With no calculated rounds the bot
says standings are not available yet. The adapter intentionally supports this one
competition; other leagues are not selected via user input.

**Validation:** API schemas and the login request contract were inspected, but an
end-to-end login with the dedicated account still needs a deployment smoke test.
If Fantacalcio does not issue legacy cookies for that account, or introduces a
CAPTCHA/MFA challenge or changes its APIs, `/classifica` will report unavailable
rather than fabricate standings. Do not disable account security to work around it.

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
- Football tools beyond `/classifica`, voice, streaming and per-user access controls beyond the allowed
  group are future work. Do not give the model credentials or private data.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes, pull requests and manual dispatches
using GitHub-hosted Ubuntu runners with Python 3.12. It installs locked development
dependencies, runs the offline pytest suite, and runs all remaining prek hooks
(formatting, lint, types and file checks). The pytest hook is skipped in the prek
step because tests have their own step. CI uses read-only repository permissions
and no deployment credentials. Superseded runs on the same branch or PR are canceled.

## Deployment from GitHub

Run `just deploy` to dispatch the workflow for your current Git branch using
[GitHub CLI](https://cli.github.com/) (install it and run `gh auth login` first).
Push the branch and commits first: GitHub deploys the remote branch, not local
uncommitted or unpushed changes. Detached HEAD is not supported. This command
queues the run; follow its status in Actions or with `gh run list --workflow deploy.yml`.
Use `just deploy-local` only for a direct local Modal deployment, never concurrently
with a GitHub deployment.

Alternatively, in **Actions → deploy → Run workflow**, select the branch to deploy.
`.github/workflows/deploy.yml` deploys that branch's selected commit,
not necessarily `main`. Pushes and pull requests do not deploy automatically.
GitHub requires the workflow to exist on the default branch before manual dispatch
is available; the selected branch must also contain the workflow.
Only dispatch trusted branches: their code runs with deployment credentials.
Every branch updates the same existing app, not a separate preview app.

One-time setup:

1. Create a Modal API token for the same workspace as your existing bot, through
   Modal's token settings or `uv run modal token new --no-activate`.
2. In GitHub **Settings → Secrets and variables → Actions**, add repository secrets
   named `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` using that token's credentials.
   Do not commit these values or your `.modal.toml` credentials file.
3. The workflow targets the Modal environment `main`. If your bot lives in another
   environment, set the GitHub repository variable `MODAL_ENVIRONMENT` to its name.
4. Ensure the existing `fantabot-secrets` Modal Secret is present in that workspace
   and environment. It must contain the Telegram/OpenRouter configuration described
   above; the workflow does not create or overwrite it from GitHub.

Deployment does not run or wait for tests or prek checks. These run separately
in the CI workflow; verify CI succeeds before dispatching deployment. Actions are pinned
by commit SHA, dependencies are installed from `uv.lock`, and deployment runs across
all branches are serialized rather than canceled halfway through. GitHub may replace
an older pending run when another is queued; it does not guarantee a FIFO queue. The deploy command uses
`--strategy recreate` to avoid overlapping SQLite writers; expect a short restart.
Do not run a manual local deploy concurrently with a GitHub deployment.

The app name, persistent volume and existing Telegram webhook remain unchanged.
Secrets/configuration changes still require updating the Modal Secret separately;
a local `.env` is not uploaded by this workflow. Deployment logs are available in
GitHub Actions; running bot logs remain in Modal.

## Versioning

Use Semantic Versioning (`MAJOR.MINOR.PATCH`), starting at the existing `0.1.0`.
`pyproject.toml` is the source of truth; `uv.lock` must stay in sync.
Bump patch for fixes, minor for compatible features, and major for breaking changes.
During `0.x`, minor releases may introduce breaking changes.

Every change, including CI and documentation, needs a dedicated branch and version
bump (see `AGENTS.md`). On your change branch:

```sh
uv version --bump patch  # alternatively: minor or major
uv run --locked prek run --all-files
git add pyproject.toml uv.lock
git commit -m "Describe change and version bump"
git push origin HEAD
```

Open a PR to `main`. `.github/workflows/release.yml` publishes a GitHub Release
with generated notes and a `vMAJOR.MINOR.PATCH` tag on each push to `main`, covering
merge, squash and rebase merges (and direct pushes). The tag targets the exact
pushed commit. Version bumps happen in PRs, not in the release workflow; an existing
tag for a different commit fails instead of silently overwriting a release.
Re-running a successful job for the same commit does not create another release.
Keep branch protection on `main` to require CI before merging: release publishing
is independent of CI and does not wait for its post-merge run. If another PR lands
first, update your version before merging to avoid reusing its tag.
The workflow needs repository Actions enabled and `contents: write` permission.
It neither deploys the app nor updates secrets. Tags do not trigger deployment.

Dispatch **deploy** separately for the branch you want to deploy.
GitHub deployments and `just deploy-local` set Modal's deployment Tag to
`v<package-version>` (for example, `v0.2.2`). Modal's revision counter and client
version remain separate from the app version. Re-deploying the same package version
reuses that label; the GitHub summary's commit SHA distinguishes revisions.
Each deployment job summary records the package version,
branch and full commit SHA (`version+SHA`), distinguishing deployments even if
the package version has not changed. The summary identifies the attempted
revision; confirm the deploy step succeeds before treating it as deployed.
To roll back, create a branch at a known-good release tag and dispatch it.
Rolling back code does not roll back persistent data or Modal secrets.

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
