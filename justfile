# Second Brain - Command Runner
set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

# ===========================================
# SETUP
# ===========================================

# Install all dependencies
setup:
    uv sync

# ===========================================
# QUALITY CONTROL
# ===========================================

# Run linters
lint:
    uv run ruff check src/ tests/

# Auto-format code
fmt:
    uv run ruff check --fix src/ tests/
    uv run ruff format src/ tests/

# Run test suite
test *args:
    uv run pytest {{ args }}

# Full quality check
check: lint test

# ===========================================
# APPLICATION
# ===========================================

# Start interactive chat
chat *args:
    uv run second-brain chat {{ args }}

# Show memory statistics
stats:
    uv run second-brain stats

# Run Obsidian vault sync watcher
sync-obsidian:
    uv run python -m second_brain.tools.obsidian_sync

# ===========================================
# DATABASE (Docker)
# ===========================================

# Start local Postgres with pgvector
db-up:
    docker compose up -d

# Stop local Postgres
db-down:
    docker compose down
