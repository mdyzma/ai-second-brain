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
