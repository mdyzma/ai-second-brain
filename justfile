set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

mod db

# List all recipes
default:
    @just --list --list-submodules

# Install JavaScript tooling (Python and web are added in later tasks)
install:
    pnpm install
