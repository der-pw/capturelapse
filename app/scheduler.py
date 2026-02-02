import asyncio
import shutil
from datetime import datetime, timedelta, time as dt_time
import math
from zoneinfo import ZoneInfo
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.downloader import take_snapshot, check_camera_health
from app.logger_utils import log
from app.broadcast_manager import broadcast
from app.sunrise_utils import is_within_time_range, get_sun_times
from app.config_manager import load_config, save_config, resolve_save_dir
from app.runtime_state import (
    set_camera_error,
    clear_camera_error,
    set_camera_health,
    set_image_stats,
    get_image_stats,
)

# Global state
scheduler = None
cfg = load_config()
cfg_lock = asyncio.Lock()
is_paused = getattr(cfg, "paused", False)
STATUS_HEARTBEAT_SECONDS = 10
CAMERA_HEALTHCHECK_SECONDS = 60


def _get_tz(cfg):
    tz_name = getattr(cfg, "city_tz", "") or ""
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def _now(cfg) -> datetime:
    tz = _get_tz(cfg)
    return datetime.now(tz) if tz else datetime.now()


def _in_schedule_date_range(cfg, now_dt: datetime) -> bool:
    start_raw = (getattr(cfg, "schedule_start_date", None) or "").strip()
    end_raw = (getattr(cfg, "schedule_end_date", None) or "").strip()
    if not start_raw and not end_raw:
        return True
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except Exception:
        return True
    today = now_dt.date()
    if start_date and today < start_date:
        return False
    if end_date and today > end_date:
        return False
    return True


# === Check whether we are inside the capture window ===
def get_schedule_decision(cfg, now_dt: datetime | None = None) -> tuple[bool, dict]:
    """Return (active, details) for the current schedule decision."""
    now_dt = now_dt or _now(cfg)
    details: dict = {
        "now": now_dt.isoformat(timespec="seconds"),
        "reason": "active",
        "active_days": getattr(cfg, "active_days", []) or [],
        "date_from": (getattr(cfg, "schedule_start_date", None) or "").strip() or None,
        "date_to": (getattr(cfg, "schedule_end_date", None) or "").strip() or None,
        "use_astral": bool(getattr(cfg, "use_astral", False)),
    }

    try:
        start_time = datetime.strptime(cfg.active_start, "%H:%M").time()
        end_time = datetime.strptime(cfg.active_end, "%H:%M").time()
        details["window_start"] = start_time.strftime("%H:%M")
        details["window_end"] = end_time.strftime("%H:%M")
    except Exception:
        details["reason"] = "invalid_time_window"
        return True, details  # Fallback: always active

    if not _in_schedule_date_range(cfg, now_dt):
        details["reason"] = "outside_date_range"
        return False, details

    # Optional: honor active weekdays if configured
    try:
        days = getattr(cfg, "active_days", []) or []
        if days:
            day_abbr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            today = day_abbr[now_dt.weekday()]
            details["weekday"] = today
            if today not in days:
                details["reason"] = "weekday_disabled"
                return False, details
    except Exception:
        pass

    now_time = now_dt.time()
    active = is_within_time_range(start_time, end_time, now=now_time)
    if not active:
        details["reason"] = "outside_time_window"
        return False, details

    if getattr(cfg, "use_astral", False):
        sunrise, sunset = get_sun_times(cfg, target_date=now_dt.date())
        if not sunrise or not sunset:
            details["reason"] = "astral_unavailable"
            return False, details
        details["sunrise"] = sunrise.strftime("%H:%M")
        details["sunset"] = sunset.strftime("%H:%M")
        if not is_within_time_range(sunrise, sunset, now=now_time):
            details["reason"] = "outside_astral_window"
            return False, details

    return True, details


def is_active_time(cfg, now_dt: datetime | None = None):
    """True if the current time is within the capture window."""
    active, _details = get_schedule_decision(cfg, now_dt=now_dt)
    return active


def get_next_snapshot_iso(local_cfg) -> str | None:
    """Return the next snapshot time that is actually allowed by the schedule."""
    if is_paused or not scheduler:
        return None
    job = scheduler.get_job("job_snapshot")
    if not job:
        return None
    candidate = job.next_run_time or _now(local_cfg)
    tz = _get_tz(local_cfg)
    if candidate.tzinfo is None:
        if tz:
            candidate = candidate.replace(tzinfo=tz)
    elif tz:
        # Normalize to config timezone for consistent comparisons.
        candidate = candidate.astimezone(tz)
    now_dt = _now(local_cfg)
    if candidate < now_dt:
        candidate = now_dt
    interval = int(getattr(local_cfg, "interval_seconds", 60) or 60)
    if interval <= 0:
        interval = 60

    # Determine scan window: default 30 days, extend to scheduled start if needed.
    scan_days = 30
    try:
        start_raw = (getattr(local_cfg, "schedule_start_date", None) or "").strip()
        end_raw = (getattr(local_cfg, "schedule_end_date", None) or "").strip()
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except Exception:
        start_date = None
        end_date = None

    if start_date:
        days_until_start = (start_date - now_dt.date()).days
        if days_until_start > scan_days:
            scan_days = days_until_start + 2
    if end_date:
        days_until_end = (end_date - now_dt.date()).days
        if days_until_end < scan_days:
            scan_days = max(0, days_until_end + 1)

    try:
        start_time = datetime.strptime(local_cfg.active_start, "%H:%M").time()
        end_time = datetime.strptime(local_cfg.active_end, "%H:%M").time()
    except Exception:
        return candidate.isoformat()

    def _is_day_allowed(day):
        check_dt = datetime.combine(day, dt_time.min)
        if tz:
            check_dt = check_dt.replace(tzinfo=tz)
        if not _in_schedule_date_range(local_cfg, check_dt):
            return False
        try:
            days = getattr(local_cfg, "active_days", []) or []
            if days:
                day_abbr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                return day_abbr[day.weekday()] in days
        except Exception:
            return True
        return True

    base_time = candidate
    currently_active = is_active_time(local_cfg, now_dt=now_dt)

    for offset in range(scan_days + 1):
        day = now_dt.date() + timedelta(days=offset)
        if not _is_day_allowed(day):
            continue

        if getattr(local_cfg, "use_astral", False):
            sunrise, sunset = get_sun_times(local_cfg, target_date=day)
            if not sunrise or not sunset:
                continue
            window_start = datetime.combine(day, sunrise)
            window_end = datetime.combine(day, sunset)
        else:
            window_start = datetime.combine(day, start_time)
            if start_time == end_time:
                # Treat 00:00-00:00 (or any equal times) as full-day capture.
                window_end = datetime.combine(day + timedelta(days=1), end_time)
            elif start_time < end_time:
                window_end = datetime.combine(day, end_time)
            else:
                window_end = datetime.combine(day + timedelta(days=1), end_time)

        if tz:
            window_start = window_start.replace(tzinfo=tz)
            window_end = window_end.replace(tzinfo=tz)

        # Skip windows entirely in the past.
        if window_end < now_dt:
            continue

        candidate_time = max(window_start, now_dt)
        if candidate_time > window_end:
            continue

        if not currently_active and window_start >= now_dt:
            return window_start.isoformat()

        if candidate_time <= base_time:
            aligned = base_time
        else:
            delta = (candidate_time - base_time).total_seconds()
            steps = math.ceil(delta / interval)
            aligned = base_time + timedelta(seconds=steps * interval)

        if aligned <= window_end and aligned >= now_dt:
            return aligned.isoformat()

    return None


# === On startup: copy latest snapshot for dashboard preview ===
def copy_latest_image_on_startup(cfg):
    """Copy the newest image to static/img/last.jpg on startup."""
    app_dir = Path(__file__).resolve().parent
    data_dir = resolve_save_dir(getattr(cfg, "save_path", None))
    target_path = app_dir / "static" / "img" / "last.jpg"

    if not data_dir.exists():
        print(f"[INIT] Data directory not found: {data_dir}")
        return

    # List all images and sort by modification time
    images = sorted(
        [f for f in data_dir.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    if images:
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(images[0], target_path)
            print(f"[INIT] last.jpg updated -> {images[0].name}")
        except Exception as e:
            print(f"[INIT] Failed to copy last.jpg: {e}")
    else:
        print("[INIT] No existing image found to copy.")


def _refresh_image_stats(cfg) -> None:
    """Initialize cached image stats from disk."""
    data_dir = resolve_save_dir(getattr(cfg, "save_path", None))
    if not data_dir.exists():
        set_image_stats(0, None, None, None)
        return
    allowed_suffixes = (".jpg", ".jpeg", ".png")
    count = 0
    latest_mtime = None
    for f in data_dir.iterdir():
        if f.is_file() and f.suffix.lower() in allowed_suffixes:
            count += 1
            mtime = f.stat().st_mtime
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime
    if latest_mtime:
        latest_dt = datetime.fromtimestamp(latest_mtime)
        last_snapshot = latest_dt.strftime("%H:%M:%S")
        last_snapshot_full = latest_dt.strftime("%d.%m.%y %H:%M")
    else:
        last_snapshot = None
        last_snapshot_full = None
    last_snapshot_iso = latest_dt.isoformat(timespec="seconds") if latest_mtime else None
    set_image_stats(count, last_snapshot, last_snapshot_full, last_snapshot_iso)


# === Scheduler job ===
def job_snapshot():
    """Run a snapshot capture if allowed."""
    global cfg, is_paused

    if is_paused:
        log("info", "Scheduler paused - no snapshot.")
        return

    local_cfg = cfg

    active, decision = get_schedule_decision(local_cfg)
    if not active:
        reason = decision.get("reason", "inactive")
        now_val = decision.get("now", "")
        window = f"{decision.get('window_start', '--')}–{decision.get('window_end', '--')}"
        date_range = f"{decision.get('date_from') or '--'}..{decision.get('date_to') or '--'}"
        days = ",".join(decision.get("active_days") or []) or "--"
        astral = "on" if decision.get("use_astral") else "off"
        sunrise = decision.get("sunrise", "--")
        sunset = decision.get("sunset", "--")
        log(
            "info",
            "Snapshot skipped "
            f"(reason={reason}, now={now_val}, window={window}, "
            f"days={days}, date_range={date_range}, astral={astral}, "
            f"sunrise={sunrise}, sunset={sunset}).",
        )
        return

    result = take_snapshot(local_cfg)
    if result:
        # After each snapshot, update last.jpg
        try:
            app_dir = Path(__file__).resolve().parent
            src = Path(result["filepath"])
            dest = app_dir / "static" / "img" / "last.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest)
        except Exception as e:
            log("error", f"Failed to copy last.jpg: {e}")

        asyncio.run(broadcast({
            "type": "snapshot",
            "filename": result["filename"],
            "timestamp": result["timestamp"],
            "timestamp_full": result.get("timestamp_full"),
            "timestamp_iso": result.get("timestamp_iso"),
        }))
        try:
            next_snapshot_iso = get_next_snapshot_iso(local_cfg)
        except Exception:
            next_snapshot_iso = None
        try:
            asyncio.run(broadcast({
                "type": "next_snapshot",
                "next_snapshot_iso": next_snapshot_iso,
            }))
        except RuntimeError as err:
            log("error", f"Failed to send next snapshot update: {err}")
        log("info", f"Snapshot saved: {result['filename']}")
        clear_camera_error()
        stats = get_image_stats() or {}
        count = int(stats.get("count") or 0) + 1
        set_image_stats(
            count,
            result["timestamp"],
            result.get("timestamp_full"),
            result.get("timestamp_iso"),
        )
    else:
        log("error", "Snapshot failed")
        set_camera_error("snapshot_failed", "Snapshot failed")
        try:
            asyncio.run(broadcast({
                "type": "camera_error",
                "code": "snapshot_failed",
                "message": "Snapshot failed"
            }))
        except RuntimeError as err:
            log("error", f"Failed to send camera error: {err}")


def job_status_heartbeat():
    """Send periodic status events via SSE."""
    global cfg, is_paused

    if is_paused:
        status = "paused"
    else:
        status = "running" if is_active_time(cfg) else "waiting_window"

    try:
        asyncio.run(broadcast({
            "type": "status",
            "status": status
        }))
    except RuntimeError as err:
        log("error", f"Failed to send status heartbeat: {err}")


def job_camera_healthcheck():
    """Periodically check camera reachability without taking a snapshot."""
    local_cfg = cfg
    result = check_camera_health(local_cfg)
    checked_at = _now(cfg).strftime("%Y-%m-%d %H:%M:%S")
    if result["ok"]:
        clear_camera_error()
        set_camera_health("ok", result.get("code"), result.get("message", "OK"), checked_at)
    else:
        set_camera_health("error", result.get("code"), result.get("message", "Error"), checked_at)
    try:
        asyncio.run(broadcast({
            "type": "camera_health",
            "status": "ok" if result["ok"] else "error",
            "code": result.get("code"),
            "message": result.get("message"),
            "checked_at": checked_at,
        }))
    except RuntimeError as err:
        log("error", f"Failed to send camera health update: {err}")


# === Start scheduler ===
def start_scheduler():
    """Initialize and start the scheduler."""
    global scheduler, cfg

    if scheduler:
        scheduler.shutdown(wait=False)

    # Copy last snapshot immediately on startup
    copy_latest_image_on_startup(cfg)
    _refresh_image_stats(cfg)

    scheduler = BackgroundScheduler(timezone=_get_tz(cfg))

    scheduler.add_job(
        job_snapshot,
        trigger=IntervalTrigger(seconds=cfg.interval_seconds),
        id="job_snapshot",
        replace_existing=True
    )
    scheduler.add_job(
        job_status_heartbeat,
        trigger=IntervalTrigger(seconds=STATUS_HEARTBEAT_SECONDS),
        id="job_status_heartbeat",
        replace_existing=True
    )
    scheduler.add_job(
        job_camera_healthcheck,
        trigger=IntervalTrigger(seconds=CAMERA_HEALTHCHECK_SECONDS),
        id="job_camera_healthcheck",
        replace_existing=True
    )

    scheduler.start()
    log("info", f"Scheduler started (interval: {cfg.interval_seconds}s)")


# === Stop scheduler ===
def stop_scheduler():
    """Stop the scheduler."""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        log("info", "Scheduler stopped")
        scheduler = None


# === Pause/resume control ===
async def set_paused(value: bool, *, persist: bool = True) -> None:
    """Set the scheduler paused state and optionally persist config."""
    global cfg, is_paused

    async with cfg_lock:
        is_paused = bool(value)
        if hasattr(cfg, "paused"):
            cfg.paused = is_paused
        if persist:
            try:
                save_config(cfg)
            except Exception as exc:  # pragma: no cover - logging is sufficient here
                log("warn", f"Failed to persist pause state: {exc}")

    state = "paused" if is_paused else "resumed"
    log("info", f"Scheduler {state}")
