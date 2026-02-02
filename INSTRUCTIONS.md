# INSTRUCTIONS.md

Quick agent overview — keep this up to date when workflows change.

## Goal / Product
- CaptureLapse: Browser-based app that captures webcam snapshots at fixed intervals.
- Core value/features: Timelapse documentation with time windows, weekdays, and optional sunrise/sunset limits; status/control in the dashboard.

## Tech Stack
- Language/Runtime: Python 3.10+
- Frameworks/Libraries: FastAPI, Jinja2, Uvicorn (per README)
- Frontend/Backend: Server-rendered templates + JS (dashboard/settings), API endpoints
- Data: `app/data/config.json` (or `/data/config.json` via Docker)
- Infra/Container: Docker/Docker Compose optional

## Project Structure (Short)
- `app/`: application code (FastAPI + templates + static)
- `app/static/js/`: frontend scripts (app.js, dashboard.js, settings.js)
- `app/templates/`: Jinja2 templates
- `app/data/config.json`: runtime configuration (local)

## Local Setup
- Prereqs: Python 3.10+
- Install: `python -m pip install -r requirements.txt`
- Config: `app/data/config.json`; optional `CAPTURELAPSE_DATA_DIR`, `CAPTURELAPSE_PICTURES_DIR`

## Build / Run
- Local run (dev): `uvicorn app.main:app --reload --port 8000`
- Local run (prod example): `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Docker: via Docker Compose (see README)

## Tests
- Test runner: not documented (fill in if present)
- Command: -

## Code Style / Conventions
- Formatter/Linter: not documented
- Naming conventions: not documented

## Deployment
- Environments: Docker Compose possible
- Deploy steps: `docker compose up -d` (see README)

## Important Notes
- Access protection optional via `access_password` in `config.json`.
- Dashboard/settings run in the browser; status updates via Server-Sent Events.
- Global status/alerts live in the navbar (`#global-status`); settings and timelapse messages are routed there.
- Gallery range selection uses “Pick first / Pick last” buttons with auto-normalized (chronological) ranges.
- “Select all” in Gallery selects the full filtered range across pagination.
- This file can be automatically updated by the assistant when changes are confirmed to work.




