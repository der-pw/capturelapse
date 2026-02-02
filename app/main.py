from fastapi import FastAPI, Request, Form, HTTPException, Body
from typing import List, Optional
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import secrets
from time import monotonic, time
import hashlib
import bcrypt
import subprocess
import threading

from app.config_manager import load_config, save_config, resolve_save_dir
from app.models import ConfigModel
from app.scheduler import start_scheduler, stop_scheduler, cfg_lock, cfg, set_paused, is_active_time, get_next_snapshot_iso
from app import i18n
from app.broadcast_manager import add_client, remove_client, broadcast
from app.logger_utils import log
from app.downloader import take_snapshot, check_camera_health
from app.sunrise_utils import get_sun_times
from app.runtime_state import (
    set_camera_error,
    clear_camera_error,
    get_camera_error,
    set_camera_health,
    get_camera_health,
    set_image_stats,
    get_image_stats,
    get_image_stats_updated_at,
)
from starlette.middleware.sessions import SessionMiddleware

# === FastAPI App ===
app = FastAPI()

# === Static Mount (CSS, JS, images) ===
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static"
)

# === Templates ===
APP_VERSION = "0.9.0-beta"
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["app_version"] = APP_VERSION
IMAGE_STATS_TTL_SECONDS = 60
_timelapse_lock = threading.Lock()
_timelapse_status = {
    "state": "idle",  # idle | running | done | error
    "message": None,
    "output": None,
    "started_at": None,
    "finished_at": None,
    "frame": 0,
    "count": 0,
    "progress": 0,
}


def _now_in_cfg_tz(local_cfg) -> datetime:
    tz_name = getattr(local_cfg, "city_tz", "") or ""
    if tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def _get_cfg_tz(local_cfg) -> Optional[ZoneInfo]:
    tz_name = getattr(local_cfg, "city_tz", "") or ""
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return None
    return None


def _safe_instance_slug(name: Optional[str]) -> str:
    raw = (name or "").strip().lower()
    if not raw:
        return "capturelapse"
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    cleaned = cleaned.strip("_-") or "capturelapse"
    return cleaned[:64]


def _normalize_password(pwd: str) -> bytes:
    """Normalize password for bcrypt's 72-byte limit."""
    raw = (pwd or "").encode("utf-8")
    if len(raw) <= 72:
        return raw
    # For very long inputs, hash first to avoid bcrypt length errors.
    return hashlib.sha256(raw).hexdigest().encode("ascii")


def _hash_password(pwd: str) -> str:
    return bcrypt.hashpw(_normalize_password(pwd), bcrypt.gensalt()).decode("utf-8")


def _verify_password(pwd: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_normalize_password(pwd), (hashed or "").encode("utf-8"))
    except Exception:
        return False

# === Login throttling (simple in-memory protection) ===
LOGIN_WINDOW_SEC = 300
LOGIN_MAX_ATTEMPTS = 5
LOGIN_BLOCK_SEC = 60
_login_state: dict[str, dict[str, float | list[float]]] = {}


def _client_ip(request: Request) -> str:
    """Best-effort client IP, considering common reverse proxy headers."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # First hop is the originating client in most proxy setups.
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return (request.client.host if request.client else "unknown").strip()


def _prune_attempts(attempts: list[float], now: float) -> list[float]:
    cutoff = now - LOGIN_WINDOW_SEC
    return [ts for ts in attempts if ts >= cutoff]


def _is_blocked(ip: str) -> tuple[bool, int]:
    now = monotonic()
    state = _login_state.get(ip)
    if not state:
        return False, 0
    blocked_until = float(state.get("blocked_until", 0.0))
    if blocked_until > now:
        remaining = max(1, int(blocked_until - now))
        return True, remaining
    # Clear stale block markers.
    if blocked_until:
        state["blocked_until"] = 0.0
    attempts = _prune_attempts(list(state.get("attempts", [])), now)
    state["attempts"] = attempts
    return False, 0


def _register_failure(ip: str) -> None:
    now = monotonic()
    state = _login_state.setdefault(ip, {"attempts": [], "blocked_until": 0.0})
    attempts = _prune_attempts(list(state.get("attempts", [])), now)
    attempts.append(now)
    state["attempts"] = attempts
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        state["blocked_until"] = now + LOGIN_BLOCK_SEC


def _register_success(ip: str) -> None:
    if ip in _login_state:
        _login_state.pop(ip, None)


async def _get_access_password_state() -> tuple[str | None, str | None]:
    """Return (hash, plaintext) and migrate plaintext to hash when possible."""
    async with cfg_lock:
        local_cfg = cfg
        pwd_hash = getattr(local_cfg, "access_password_hash", None)
        pwd_plain = (getattr(local_cfg, "access_password", None) or "").strip() or None
        if pwd_plain and not pwd_hash:
            try:
                local_cfg.access_password_hash = _hash_password(pwd_plain)
                local_cfg.access_password = ""
                save_config(local_cfg)
                pwd_hash = local_cfg.access_password_hash
                pwd_plain = None
                log("info", "Migrated access password to hash.")
            except Exception as err:
                log("warn", f"Could not migrate access password to hash: {err}")
        return pwd_hash, pwd_plain


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Allow static assets without auth to avoid broken CSS/JS before login.
    if request.url.path.startswith("/static"):
        return await call_next(request)
    if request.url.path in ("/login", "/logout"):
        return await call_next(request)

    password_hash, password_plain = await _get_access_password_state()
    if not (password_hash or password_plain):
        return await call_next(request)

    if request.session.get("authenticated"):
        return await call_next(request)

    return RedirectResponse(url="/login", status_code=303)


_session_secret_env = os.getenv("CAPTURELAPSE_SESSION_SECRET")
_session_secret = _session_secret_env or secrets.token_urlsafe(32)
if not _session_secret_env:
    log("warn", "CAPTURELAPSE_SESSION_SECRET not set; using ephemeral secret.")
_session_https_only = os.getenv("CAPTURELAPSE_SESSION_HTTPS_ONLY", "").lower() in ("1", "true", "yes")
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    same_site="lax",
    https_only=_session_https_only,
    max_age=60 * 60 * 24 * 7,
)


def _compute_image_stats(save_path: Path) -> tuple[int, str | None, str | None, str | None]:
    """Compute image count and last snapshot timestamps from disk."""
    stats = get_image_stats() or {}
    stats_updated_at = get_image_stats_updated_at()
    now_ts = time()
    if (not stats) or (stats_updated_at is None) or (now_ts - stats_updated_at > IMAGE_STATS_TTL_SECONDS):
        count = 0
        last_snapshot_ts = None
        last_snapshot_full = None
        last_snapshot_iso = None
        latest_mtime = None
        allowed_suffixes = (".jpg", ".jpeg", ".png")
        if save_path.exists():
            for f in save_path.iterdir():
                if not f.is_file() or f.suffix.lower() not in allowed_suffixes:
                    continue
                count += 1
                try:
                    mtime = f.stat().st_mtime
                except Exception:
                    continue
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
            if latest_mtime:
                latest_dt = datetime.fromtimestamp(latest_mtime)
                last_snapshot_ts = latest_dt.strftime("%H:%M:%S")
                last_snapshot_full = latest_dt.strftime("%d.%m.%y %H:%M")
                last_snapshot_iso = latest_dt.isoformat(timespec="seconds")
        set_image_stats(count, last_snapshot_ts, last_snapshot_full, last_snapshot_iso)
    else:
        count = int(stats.get("count") or 0)
        last_snapshot_ts = stats.get("last_snapshot")
        last_snapshot_full = stats.get("last_snapshot_full")
        last_snapshot_iso = stats.get("last_snapshot_iso")
    return count, last_snapshot_ts, last_snapshot_full, last_snapshot_iso

# === SSE: server-sent events for live updates ===
@app.get("/events")
async def sse_events():
    """SSE endpoint for dashboard updates (snapshots, status, etc.)."""
    queue = asyncio.Queue()
    add_client(queue)

    async def event_generator():
        try:
            while True:
                msg = await queue.get()
                yield f"data: {json.dumps(msg)}\n\n"
        except asyncio.CancelledError:
            remove_client(queue)
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# === Auth: login/logout ===
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    password_hash, password_plain = await _get_access_password_state()
    if not (password_hash or password_plain):
        return RedirectResponse(url="/", status_code=303)
    ip = _client_ip(request)
    blocked, remaining = _is_blocked(ip)
    async with cfg_lock:
        local_cfg = cfg
    tr = i18n.load_translations(getattr(local_cfg, "language", "de"))
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": False,
            "error_message": None,
            "blocked": blocked,
            "blocked_seconds": remaining,
            "cfg": local_cfg,
            "tr": tr,
            "lang": getattr(local_cfg, "language", "de"),
        }
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, ACCESS_PASSWORD: str = Form("")):
    password_hash, password_plain = await _get_access_password_state()
    if not (password_hash or password_plain):
        return RedirectResponse(url="/", status_code=303)

    ip = _client_ip(request)
    blocked, remaining = _is_blocked(ip)
    async with cfg_lock:
        local_cfg = cfg
    tr = i18n.load_translations(getattr(local_cfg, "language", "de"))

    if blocked:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": True,
                "error_message": tr.get("login_blocked", "Too many attempts. Try again later."),
                "blocked": True,
                "blocked_seconds": remaining,
                "cfg": local_cfg,
                "tr": tr,
                "lang": getattr(local_cfg, "language", "de"),
            },
        )

    authenticated = False
    candidate = (ACCESS_PASSWORD or "").strip()
    try:
        if password_hash:
            authenticated = _verify_password(candidate, password_hash)
        elif password_plain:
            authenticated = secrets.compare_digest(candidate, password_plain)
    except Exception as err:
        log("warn", f"Password verification failed: {err}")
        authenticated = False

    if authenticated:
        request.session["authenticated"] = True
        _register_success(ip)
        return RedirectResponse(url="/", status_code=303)

    _register_failure(ip)
    blocked, remaining = _is_blocked(ip)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": True,
            "error_message": (
                tr.get("login_blocked", "Too many attempts. Try again later.")
                if blocked
                else tr.get("login_error", "Wrong password")
            ),
            "blocked": blocked,
            "blocked_seconds": remaining,
            "cfg": local_cfg,
            "tr": tr,
            "lang": getattr(local_cfg, "language", "de"),
        }
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# === Index page ===
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    async with cfg_lock:
        local_cfg = cfg

    # Cache buster for last.jpg to ensure immediate refresh
    cache_buster = int(datetime.now().timestamp())

    tr = i18n.load_translations(getattr(local_cfg, "language", "de"))
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "cfg": local_cfg,
            "cache_buster": cache_buster,
            "tr": tr,
            "lang": getattr(local_cfg, "language", "de"),
        }
    )


# === Settings page ===
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render the settings page (original layout)."""
    async with cfg_lock:
        local_cfg = cfg
    langs = i18n.available_languages()
    tr = i18n.load_translations(getattr(local_cfg, "language", "de"))
    message = None
    if request.query_params.get("saved"):
        message = tr.get("settings_saved", "Einstellungen gespeichert")
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "cfg": local_cfg,
            "message": message,
            "langs": langs,
            "tr": tr,
            "lang": getattr(local_cfg, "language", "de"),
        }
    )


# === Save settings ===
@app.post("/update", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    CAM_URL: str = Form(...),
    INSTANCE_NAME: str = Form(""),
    ACCESS_PASSWORD: str = Form(""),
    ACCESS_PASSWORD_ENABLE: str = Form(None),
    INTERVAL_SECONDS: int = Form(...),
    SAVE_PATH: str = Form(...),
    AUTH_TYPE: str = Form("none"),
    USERNAME: str = Form(""),
    PASSWORD: str = Form(""),
    ACTIVE_START: str = Form("06:00"),
    ACTIVE_END: str = Form("22:00"),
    ACTIVE_DAYS: List[str] = Form([]),
    DATE_FROM: str = Form(""),
    DATE_TO: str = Form(""),
    USE_ASTRAL: str = Form(None),
    CITY_LAT: float = Form(48.137),
    CITY_LON: float = Form(11.575),
    CITY_TZ: str = Form("Europe/Berlin"),
    LANGUAGE: str = Form("de"),
):
    """Persist settings and redirect back to /settings with a success flag."""
    async with cfg_lock:
        cfg.cam_url = CAM_URL
        cfg.instance_name = INSTANCE_NAME.strip() or None
        enable_access_password = ACCESS_PASSWORD_ENABLE is not None
        new_access_password = (ACCESS_PASSWORD or "").strip()
        if not enable_access_password:
            cfg.access_password_hash = None
            cfg.access_password = ""
        elif new_access_password:
            cfg.access_password_hash = _hash_password(new_access_password)
            cfg.access_password = ""
        cfg.interval_seconds = INTERVAL_SECONDS
        cfg.save_path = SAVE_PATH
        cfg.auth_type = AUTH_TYPE
        cfg.username = USERNAME
        if PASSWORD.strip():
            cfg.password = PASSWORD
        cfg.active_start = ACTIVE_START
        cfg.active_end = ACTIVE_END
        cfg.active_days = [d for d in ACTIVE_DAYS if d]
        cfg.schedule_start_date = (DATE_FROM or "").strip() or None
        cfg.schedule_end_date = (DATE_TO or "").strip() or None
        cfg.use_astral = USE_ASTRAL is not None
        cfg.city_lat = CITY_LAT
        cfg.city_lon = CITY_LON
        cfg.city_tz = CITY_TZ
        cfg.language = LANGUAGE or getattr(cfg, "language", "de")
        save_config(cfg)

    stop_scheduler()
    start_scheduler()
    # Run a quick healthcheck after saving to provide immediate feedback
    health = await asyncio.to_thread(check_camera_health, cfg)
    checked_at = _now_in_cfg_tz(cfg).strftime("%Y-%m-%d %H:%M:%S")
    if health.get("ok"):
        clear_camera_error()
        set_camera_health("ok", health.get("code"), health.get("message", "OK"), checked_at)
    else:
        set_camera_health("error", health.get("code"), health.get("message", "Error"), checked_at)
    await broadcast({
        "type": "camera_health",
        "status": "ok" if health.get("ok") else "error",
        "code": health.get("code"),
        "message": health.get("message"),
        "checked_at": checked_at,
    })
    next_snapshot_iso = get_next_snapshot_iso(cfg)
    await broadcast({
        "type": "next_snapshot",
        "next_snapshot_iso": next_snapshot_iso,
    })
    await broadcast({"type": "status", "status": "config_reloaded"})
    log("info", "Config saved and scheduler restarted")

    # Redirect back to /settings with success flag
    return RedirectResponse(url="/settings?saved=1", status_code=303)


# === Status endpoint ===
@app.get("/status")
async def status():
    """Status API for the dashboard."""
    async with cfg_lock:
        local_cfg = cfg

    # Resolve save path from config and env overrides
    save_path = resolve_save_dir(getattr(local_cfg, "save_path", None))

    count = 0
    last_snapshot_ts = None
    last_snapshot_full = None
    last_snapshot_iso = None
    latest_mtime = None
    allowed_suffixes = ('.jpg', '.jpeg', '.png')
    if save_path.exists():
        for f in save_path.iterdir():
            if f.is_file() and f.suffix.lower() in allowed_suffixes:
                count += 1
                mtime = f.stat().st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
        if latest_mtime:
            latest_dt = datetime.fromtimestamp(latest_mtime)
            last_snapshot_ts = latest_dt.strftime("%H:%M:%S")
            last_snapshot_full = latest_dt.strftime("%d.%m.%y %H:%M")
            last_snapshot_iso = latest_dt.isoformat(timespec="seconds")
    else:
        log("warn", f"Save path does not exist: {save_path}")

    if getattr(local_cfg, "use_astral", False):
        sunrise_time, sunset_time = get_sun_times(local_cfg)
        sunrise_str = sunrise_time.strftime("%H:%M") if sunrise_time else "--:--"
        sunset_str = sunset_time.strftime("%H:%M") if sunset_time else "--:--"
    else:
        sunrise_str = "--:--"
        sunset_str = "--:--"

    # Use the same logic as the scheduler, including active weekdays
    active = is_active_time(local_cfg)

    from app.scheduler import is_paused as scheduler_paused
    next_snapshot_iso = get_next_snapshot_iso(local_cfg)
    return {
        "time": _now_in_cfg_tz(local_cfg).strftime("%H:%M:%S"),
        "active": active,
        "paused": bool(scheduler_paused),
        "sunrise": sunrise_str,
        "sunset": sunset_str,
        "count": count,
        "last_snapshot": last_snapshot_ts,
        "last_snapshot_tooltip": last_snapshot_full,
        "last_snapshot_iso": last_snapshot_iso,
        "next_snapshot_iso": next_snapshot_iso,
        "camera_error": get_camera_error(),
        "camera_health": get_camera_health(),
    }


# === Gallery: list captured images ===
@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 200,
    page: int = 1,
    sort: str = "desc",
):
    async with cfg_lock:
        local_cfg = cfg

    tz = _get_cfg_tz(local_cfg)
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    allowed_suffixes = (".jpg", ".jpeg", ".png")

    parsed_from = None
    parsed_to = None
    try:
        if date_from:
            parsed_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        if date_to:
            parsed_to = datetime.strptime(date_to, "%Y-%m-%d").date()
    except Exception:
        parsed_from = None
        parsed_to = None

    items = []
    if save_dir.exists():
        for f in save_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in allowed_suffixes:
                continue
            try:
                mtime = f.stat().st_mtime
            except Exception:
                continue
            dt = datetime.fromtimestamp(mtime, tz=tz) if tz else datetime.fromtimestamp(mtime)
            file_date = dt.date()
            if parsed_from and file_date < parsed_from:
                continue
            if parsed_to and file_date > parsed_to:
                continue
            items.append({
                "name": f.name,
                "timestamp": dt.strftime("%Y-%m-%d %H:%M"),
                "dt": dt,
                "ts": int(dt.timestamp()),
            })

    all_items = list(items)
    sort_dir = (sort or "desc").lower()
    reverse = sort_dir != "asc"
    items.sort(key=lambda x: x["dt"], reverse=reverse)
    safe_limit = max(1, min(int(limit or 200), 2000))
    safe_page = max(1, int(page or 1))
    total = len(items)
    total_pages = max(1, (total + safe_limit - 1) // safe_limit)
    if safe_page > total_pages:
        safe_page = total_pages
    start_idx = (safe_page - 1) * safe_limit
    end_idx = start_idx + safe_limit
    items = items[start_idx:end_idx]

    range_all = None
    if all_items:
        all_items.sort(key=lambda x: x["dt"])
        range_all = {
            "start": all_items[0]["name"],
            "end": all_items[-1]["name"],
            "start_ts": all_items[0]["ts"],
            "end_ts": all_items[-1]["ts"],
        }

    tr = i18n.load_translations(getattr(local_cfg, "language", "de"))
    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "cfg": local_cfg,
            "tr": tr,
            "lang": getattr(local_cfg, "language", "de"),
            "items": items,
            "range_all": range_all,
            "filters": {
                "date_from": date_from or "",
                "date_to": date_to or "",
                "limit": safe_limit,
                "page": safe_page,
                "total_pages": total_pages,
                "total_items": total,
                "sort": sort_dir,
            },
        },
    )


@app.get("/pictures/{filename}")
async def serve_picture(filename: str):
    async with cfg_lock:
        local_cfg = cfg
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404)
    allowed_suffixes = (".jpg", ".jpeg", ".png")
    if not filename.lower().endswith(allowed_suffixes):
        raise HTTPException(status_code=404)
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    file_path = (save_dir / filename).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404)
    try:
        file_path.relative_to(save_dir.resolve())
    except Exception:
        raise HTTPException(status_code=404)
    return FileResponse(file_path)


@app.delete("/pictures/{filename}")
async def delete_picture(filename: str):
    async with cfg_lock:
        local_cfg = cfg
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404)
    allowed_suffixes = (".jpg", ".jpeg", ".png")
    if not filename.lower().endswith(allowed_suffixes):
        raise HTTPException(status_code=404)
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    file_path = (save_dir / filename).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404)
    try:
        file_path.relative_to(save_dir.resolve())
    except Exception:
        raise HTTPException(status_code=404)
    try:
        file_path.unlink()
    except Exception:
        raise HTTPException(status_code=500, detail="delete_failed")
    return {"ok": True}


def _resolve_gallery_file(save_dir: Path, filename: str) -> Path:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404)
    allowed_suffixes = (".jpg", ".jpeg", ".png")
    if not filename.lower().endswith(allowed_suffixes):
        raise HTTPException(status_code=404)
    file_path = (save_dir / filename).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404)
    try:
        file_path.relative_to(save_dir.resolve())
    except Exception:
        raise HTTPException(status_code=404)
    return file_path


def _gallery_range_items(save_dir: Path, start_name: str, end_name: str) -> list[Path]:
    start_path = _resolve_gallery_file(save_dir, start_name)
    end_path = _resolve_gallery_file(save_dir, end_name)
    start_ts = start_path.stat().st_mtime
    end_ts = end_path.stat().st_mtime
    low_ts = min(start_ts, end_ts)
    high_ts = max(start_ts, end_ts)
    allowed_suffixes = (".jpg", ".jpeg", ".png")
    items: list[Path] = []
    if save_dir.exists():
        for f in save_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in allowed_suffixes:
                continue
            try:
                mtime = f.stat().st_mtime
            except Exception:
                continue
            if mtime < low_ts or mtime > high_ts:
                continue
            items.append(f)
    return items


@app.post("/gallery/range-count")
async def gallery_range_count(payload: dict = Body(...)):
    start_name = (payload.get("start") or "").strip()
    end_name = (payload.get("end") or "").strip()
    if not start_name or not end_name:
        raise HTTPException(status_code=400, detail="start_end_required")
    async with cfg_lock:
        local_cfg = cfg
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    items = _gallery_range_items(save_dir, start_name, end_name)
    return {"count": len(items)}


@app.post("/gallery/delete-range")
async def delete_gallery_range(payload: dict = Body(...)):
    start_name = (payload.get("start") or "").strip()
    end_name = (payload.get("end") or "").strip()
    if not start_name or not end_name:
        raise HTTPException(status_code=400, detail="start_end_required")
    async with cfg_lock:
        local_cfg = cfg
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    items = _gallery_range_items(save_dir, start_name, end_name)
    deleted = 0
    failed = 0
    for path in items:
        try:
            path.unlink()
            deleted += 1
        except Exception:
            failed += 1
    return {"ok": failed == 0, "deleted": deleted, "failed": failed}


@app.post("/timelapse")
async def create_timelapse(payload: dict = Body(...)):
    with _timelapse_lock:
        if _timelapse_status["state"] == "running":
            raise HTTPException(status_code=409, detail="timelapse_running")

    start_name = (payload.get("start") or "").strip()
    end_name = (payload.get("end") or "").strip()
    fps = int(payload.get("fps") or 25)
    crf = int(payload.get("crf") or 23)
    preset = (payload.get("preset") or "medium").strip().lower()
    width = payload.get("width")
    height = payload.get("height")
    if not start_name or not end_name:
        raise HTTPException(status_code=400, detail="start_end_required")
    if fps < 1 or fps > 120:
        raise HTTPException(status_code=400, detail="invalid_fps")
    if crf < 0 or crf > 51:
        raise HTTPException(status_code=400, detail="invalid_crf")
    allowed_presets = {
        "ultrafast", "superfast", "veryfast", "faster",
        "fast", "medium", "slow", "slower", "veryslow",
    }
    if preset not in allowed_presets:
        preset = "medium"
    scale_filter = None
    try:
        if width or height:
            w = int(width) if width else -1
            h = int(height) if height else -1
            if (w != -1 and w < 1) or (h != -1 and h < 1):
                raise ValueError("invalid_scale")
            scale_filter = f"scale={w}:{h}"
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_scale")

    async with cfg_lock:
        local_cfg = cfg
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    allowed_suffixes = (".jpg", ".jpeg", ".png")

    def _resolve_file(name: str) -> Path:
        if "/" in name or "\\" in name:
            raise HTTPException(status_code=404)
        if not name.lower().endswith(allowed_suffixes):
            raise HTTPException(status_code=404)
        file_path = (save_dir / name).resolve()
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404)
        try:
            file_path.relative_to(save_dir.resolve())
        except Exception:
            raise HTTPException(status_code=404)
        return file_path

    start_path = _resolve_file(start_name)
    end_path = _resolve_file(end_name)
    start_ts = start_path.stat().st_mtime
    end_ts = end_path.stat().st_mtime
    if start_ts > end_ts:
        raise HTTPException(status_code=400, detail="start_after_end")

    items = []
    if save_dir.exists():
        for f in save_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in allowed_suffixes:
                continue
            try:
                mtime = f.stat().st_mtime
            except Exception:
                continue
            if mtime < start_ts or mtime > end_ts:
                continue
            items.append((mtime, f.name))
    items.sort(key=lambda x: x[0])
    if not items:
        raise HTTPException(status_code=400, detail="no_items")

    list_path = save_dir / "timelapse.txt"
    def _escape(name: str) -> str:
        return name.replace("'", "'\\''")
    list_lines = [f"file '{_escape(name)}'" for _, name in items]
    list_path.write_text("\n".join(list_lines) + "\n", encoding="utf-8")

    timestamp = _now_in_cfg_tz(local_cfg).strftime("%Y%m%d_%H%M")
    instance_slug = _safe_instance_slug(getattr(local_cfg, "instance_name", None))
    output_path = save_dir / f"timelapse_{instance_slug}.mp4"

    cmd = [
        "nice", "-n", "10",
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_path),
        "-r", str(fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", str(crf),
        "-preset", preset,
        "-progress", "pipe:1",
        "-nostats",
        str(output_path),
    ]
    if scale_filter:
        # Insert filter options right before the output file.
        cmd.insert(-1, "-vf")
        cmd.insert(-1, scale_filter)

    def _run():
        try:
            count = len(items)
            with _timelapse_lock:
                _timelapse_status.update({
                    "state": "running",
                    "message": "running",
                    "output": output_path.name,
                    "started_at": _now_in_cfg_tz(local_cfg).strftime("%Y-%m-%d %H:%M:%S"),
                    "finished_at": None,
                    "frame": 0,
                    "count": count,
                    "progress": 0,
                })
            proc = subprocess.Popen(
                cmd,
                cwd=str(save_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            def _drain_stderr():
                if not proc.stderr:
                    return
                for line in proc.stderr:
                    line = line.strip()
                    if line:
                        log("info", f"ffmpeg: {line}")
            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            stderr_thread.start()
            if proc.stdout:
                for line in proc.stdout:
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key == "frame":
                        try:
                            frame = int(value)
                        except Exception:
                            continue
                        if count > 0:
                            percent = min(100, int((frame / count) * 100))
                        else:
                            percent = 0
                        with _timelapse_lock:
                            _timelapse_status.update({
                                "frame": frame,
                                "progress": percent,
                            })
            ret = proc.wait()
            stderr_thread.join(timeout=1)
            if ret != 0:
                raise RuntimeError(f"ffmpeg_failed_{ret}")
            log("info", f"Timelapse created: {output_path.name}")
            with _timelapse_lock:
                _timelapse_status.update({
                    "state": "done",
                    "message": "done",
                    "finished_at": _now_in_cfg_tz(local_cfg).strftime("%Y-%m-%d %H:%M:%S"),
                    "progress": 100,
                })
        except Exception as exc:
            log("error", f"Timelapse failed: {exc}")
            with _timelapse_lock:
                _timelapse_status.update({
                    "state": "error",
                    "message": str(exc),
                    "finished_at": _now_in_cfg_tz(local_cfg).strftime("%Y-%m-%d %H:%M:%S"),
                })

    asyncio.create_task(asyncio.to_thread(_run))

    return {"ok": True, "output": output_path.name, "count": len(items)}


@app.get("/timelapse/status")
async def timelapse_status():
    async with cfg_lock:
        local_cfg = cfg
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    has_output = False
    output_name = None
    candidates = []
    try:
        for f in save_dir.glob("timelapse_*.mp4"):
            if f.is_file():
                candidates.append(f)
    except Exception:
        candidates = []
    if candidates:
        has_output = True
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        output_name = latest.name
    with _timelapse_lock:
        payload = dict(_timelapse_status)
    if output_name:
        payload["output"] = output_name
    payload["has_output"] = has_output
    return payload


@app.delete("/timelapse/delete/{filename}")
async def delete_timelapse(filename: str):
    async with cfg_lock:
        local_cfg = cfg
    if not (filename.startswith("timelapse_") and filename.lower().endswith(".mp4")):
        raise HTTPException(status_code=404)
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    deleted_any = False
    try:
        for f in save_dir.glob("timelapse_*.mp4"):
            if not f.is_file():
                continue
            try:
                f.resolve().relative_to(save_dir.resolve())
            except Exception:
                continue
            try:
                f.unlink()
                deleted_any = True
            except Exception:
                raise HTTPException(status_code=500, detail="delete_failed")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="delete_failed")
    if not deleted_any:
        raise HTTPException(status_code=404)
    with _timelapse_lock:
        _timelapse_status.update({
            "output": None,
            "progress": 0,
            "frame": 0,
            "count": 0,
        })
    return {"ok": True}


@app.get("/timelapse/download/{filename}")
async def download_timelapse(filename: str):
    async with cfg_lock:
        local_cfg = cfg
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404)
    if not (filename.startswith("timelapse_") and filename.lower().endswith(".mp4")):
        raise HTTPException(status_code=404)
    save_dir = resolve_save_dir(getattr(local_cfg, "save_path", None))
    file_path = (save_dir / filename).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404)
    try:
        file_path.relative_to(save_dir.resolve())
    except Exception:
        raise HTTPException(status_code=404)
    media_type = "video/mp4" if filename.lower().endswith(".mp4") else "video/x-msvideo"
    return FileResponse(file_path, media_type=media_type, filename=filename)


# === Action routes ===
@app.post("/action/pause")
async def action_pause():
    await set_paused(True)
    await broadcast({"type": "status", "status": "paused"})
    return {"ok": True}


@app.post("/action/resume")
async def action_resume():
    await set_paused(False)
    await broadcast({"type": "status", "status": "running"})
    return {"ok": True}


@app.post("/action/snapshot")
async def action_snapshot():
    async with cfg_lock:
        local_cfg = cfg
    result = await asyncio.to_thread(take_snapshot, local_cfg)
    if result:
        clear_camera_error()
        stats = get_image_stats() or {}
        count = int(stats.get("count") or 0) + 1
        set_image_stats(
            count,
            result["timestamp"],
            result.get("timestamp_full"),
            result.get("timestamp_iso"),
        )
        await broadcast({
            "type": "snapshot",
            "filename": result["filename"],
            "timestamp": result["timestamp"],
            "timestamp_full": result.get("timestamp_full"),
            "timestamp_iso": result.get("timestamp_iso"),
        })
        return {"ok": True}
    else:
        set_camera_error("snapshot_failed", "Snapshot failed")
        await broadcast({
            "type": "camera_error",
            "code": "snapshot_failed",
            "message": "Snapshot failed"
        })
        return {"ok": False}


# === App lifecycle ===
@app.on_event("startup")
def startup_event():
    log("info", "Starting CaptureLapse ...")
    start_scheduler()


@app.on_event("shutdown")
def shutdown_event():
    log("info", "Stopping CaptureLapse ...")
    stop_scheduler()
