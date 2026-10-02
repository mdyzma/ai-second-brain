set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

mod backend
mod web
mod db

# List all recipes
default:
    @just --list --list-submodules

# Install Python + JavaScript dependencies, the Playwright browser and git hooks
install:
    uv sync --directory backend
    pnpm install
    pnpm --dir web exec playwright install chromium
    git config core.hooksPath .githooks

# Enable the repo's git hooks (commit-msg guard)
hooks:
    git config core.hooksPath .githooks

# Unit tests for the TypeScript helper scripts
test-scripts:
    pnpm exec tsx --test scripts/lib/commit-msg.test.ts
    pnpm exec tsx --test scripts/lib/version.test.ts

# Preview the next release locally (needs GITHUB_TOKEN; see README)
release-dry-run:
    pnpm exec semantic-release --dry-run --no-ci

# First-time setup: dependencies, .env, database and migrations (Docker must be running)
setup: install
    pnpm exec tsx scripts/init-env.ts
    just db::up
    just db::migrate
    just db::test-prepare
    @echo "Setup complete. Next: run 'just hash-password', paste the line into .env, then 'just dev'."

# Run the ingestion worker alone
worker:
    just backend::worker

# Run API (reload), web dev server and ingestion worker together; open http://localhost:5173
dev:
    just db::up
    pnpm exec concurrently --names api,web,worker --prefix-colors blue,magenta,green --kill-others-on-fail "just backend::serve --reload" "just web::dev" "just backend::worker"

# All static checks (backend, web, API client, DB schema)
check:
    just backend::check
    just web::check
    just api-client-check
    just db::schema-check

# All tests (needs the database)
test:
    just backend::test
    just web::test
    just test-scripts

# Tests that need no database (macOS CI)
test-unit:
    just backend::test-unit
    just web::test
    just test-scripts

# End-to-end browser tests against the test database
e2e:
    just web::e2e

# Format and auto-fix everything
fmt:
    just backend::fmt
    just web::fmt

# Regenerate the TypeScript API client from the backend OpenAPI schema
api-client:
    uv run --directory backend ai-second-brain openapi --output ../web/src/api/openapi.json
    pnpm --dir web exec openapi-typescript src/api/openapi.json --output src/api/schema.d.ts

# Fail if the committed API client differs from the backend
api-client-check: api-client
    git diff --exit-code -- web/src/api

# Hash the owner password; paste the printed line into .env
hash-password:
    uv run --directory backend ai-second-brain hash-password

# Ask the configured local model one question (checks SB_OLLAMA_ENDPOINTS; nothing is saved)
chat-smoke:
    uv run --directory backend ai-second-brain chat-smoke

# One reconcile pass now (pass --allow-mass-delete via: just vault-scan --allow-mass-delete)
vault-scan *args:
    uv run --directory backend ai-second-brain vault reconcile {{ args }}

# Print ingestion status
vault-status:
    uv run --directory backend ai-second-brain vault status

# Create/migrate the scratch evaluation database (SB_EVAL_DATABASE_URL)
eval-prepare:
    uv run --directory backend ai-second-brain eval prepare

# Draft a starter query set: just eval-suggest --out ~/.second-brain/eval/queries.yaml
eval-suggest *args:
    uv run --directory backend ai-second-brain eval suggest {{ args }}

# Validate the query set against the current index
eval-check *args:
    uv run --directory backend ai-second-brain eval check {{ args }}

# Run the embedding bake-off and write a report to SB_EVAL_DIR
eval-run *args: eval-prepare
    uv run --directory backend ai-second-brain eval run {{ args }}
