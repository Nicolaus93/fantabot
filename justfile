# Install just separately: https://just.systems/man/en/packages.html
# Parameters are passed as shell arguments, not interpolated into shell commands.
set positional-arguments

# Show available recipes.
default:
    @just --list

# Install locked Python dependencies, including development tools.
sync:
    uv sync --locked

# Enable pre-commit checks in this clone.
hooks-install:
    uv run --locked prek install

# Format, lint, type-check, test, and run standard file checks.
check:
    uv run --locked prek run --all-files

# Run the offline tests.
test:
    uv run --locked pytest -q

# Type-check the active package and tests.
typecheck:
    uv run --locked ty check --error-on-warning

# Temporarily disable Telegram delivery; retain pending updates.
webhook-remove:
    uv run --locked --env-file .env python -m fantabot.remove_webhook

# Discover group IDs after sending /ask@YourBotUsername in the group (webhook must be off).
group-id:
    uv run --locked --env-file .env python -m fantabot.get_group_id

# Register/restore the webhook using the Modal base URL. Discards queued old updates.
webhook-set url:
    uv run --locked --env-file .env python -m fantabot.setup_webhook --url "$1"

# Upload local .env values to the named Modal Secret, replacing its current contents.
secrets-upload:
    uv run --locked modal secret create fantabot-secrets --from-dotenv .env --force

# Dispatch GitHub deployment for the current branch (push commits first; requires gh auth login).
deploy:
    branch=$(git symbolic-ref --quiet --short HEAD) && gh workflow run deploy.yml --ref "$branch"

# Deploy locally without overlapping SQLite writers. Never run alongside a GitHub deploy.
deploy-local:
    uv run --locked modal deploy --strategy recreate -m fantabot.modal_app

# Show the last 100 handled chat errors.
logs:
    uv run --locked modal app logs fantabot-chat --tail 100 --search chat.request.failed --timestamps

# Stream all Modal application logs until interrupted.
logs-follow:
    uv run --locked modal app logs fantabot-chat --follow
