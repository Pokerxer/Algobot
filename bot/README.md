# Algobot — MT5 Agentic Trading Bot

See `docs/superpowers/specs/2026-05-27-algobot-mt5-agentic-design.md` for design.

## Setup

cd bot
uv venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv pip install -e ".[dev]"
cp .env.example .env  # fill in secrets

## Run tests

pytest
