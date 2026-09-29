set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

mod backend
mod db

# List all recipes
default:
    @just --list --list-submodules

# Install Python and JavaScript dependencies
install:
    uv sync --directory backend
    pnpm install
