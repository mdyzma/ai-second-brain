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
    poetry install

# ===========================================
# QUALITY CONTROL
# ===========================================

# Run linters
lint:
    poetry run ruff check src/ tests/

# Auto-format code
fmt:
    poetry run ruff check --fix src/ tests/
    poetry run ruff format src/ tests/

# Run test suite
test *args:
    poetry run pytest {{ args }}

# Full quality check
check: lint test

# ===========================================
# APPLICATION
# ===========================================

# Start interactive chat
chat *args:
    poetry run second-brain chat {{ args }}

# Show memory statistics
stats:
    poetry run second-brain stats

# Run Obsidian vault sync watcher
sync-obsidian:
    poetry run python -m second_brain.tools.obsidian_sync

# ===========================================
# DATABASE (Docker)
# ===========================================

# Start local Postgres with pgvector
db-up:
    docker compose up -d

# Stop local Postgres
db-down:
    docker compose down
