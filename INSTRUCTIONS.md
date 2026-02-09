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
- media storage under pictures root (`save_path`):
  - snapshots: `<save_path>/`
  - generated gallery thumbnails: `<save_path>/.thumbs/`
  - rendered timelapses: `<save_path>/timelapse/`

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

## Changelog + Commit Convention 
### Bitte inkl. Changelog/Versioning sauber mitziehen.
- If this trigger sentence is used, write changelog entries in English only.
- If this trigger sentence is used, always provide a ready-to-use commit note in English.
- Keep a top-level `CHANGELOG.md` with newest version first.
- For every user-visible change:
  - bump `APP_VERSION` in `app/main.py`
  - add one changelog section for that exact version
  - use the same version tag in the commit message/body
- Version heading format in changelog:
  - `## <APP_VERSION> - YYYY-MM-DD`
- Commit message convention:
  - subject: short summary
  - body first line: `APP_VERSION: <APP_VERSION>`
  - body bullets: same key points as in changelog entry

## Deployment
- Environments: Docker Compose possible
- Deploy steps: `docker compose up -d` (see README)

## Important Notes
- Access protection optional via `access_password` in `config.json`.
- Dashboard/settings run in the browser; status updates via Server-Sent Events.
- UI timelapse status reads from `/status` (single source of truth); `/timelapse/status` remains for API compatibility.
- Global status/alerts live in the navbar (`#global-status`); settings and timelapse messages are routed there.
- Gallery range selection uses “Pick first / Pick last” buttons with auto-normalized (chronological) ranges.
- “Select all” in Gallery selects the full filtered range across pagination.
- Gallery thumbnail images are served via `/thumbs/{filename}` with browser cache headers; thumbs are generated immediately on snapshot save and on-demand for existing files.
- Timelapse outputs are stored only in `<save_path>/timelapse/` (no legacy root fallback).
- This file can be automatically updated by the assistant when changes are confirmed to work.



