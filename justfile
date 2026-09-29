set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

mod backend
mod db
mod web

# List all recipes
default:
    @just --list --list-submodules

# Install Python and JavaScript dependencies
install:
    uv sync --directory backend
    pnpm install

# Hash the owner password; paste the printed line into .env
hash-password:
    uv run --directory backend ai-second-brain hash-password

# Regenerate the TypeScript API client from the backend OpenAPI schema
api-client:
    uv run --directory backend ai-second-brain openapi --output ../web/src/api/openapi.json
    pnpm --dir web exec openapi-typescript src/api/openapi.json --output src/api/schema.d.ts

# Fail if the committed API client differs from the backend
api-client-check: api-client
    git diff --exit-code -- web/src/api
