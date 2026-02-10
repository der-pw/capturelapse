import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from requests.exceptions import RequestException
from http.client import RemoteDisconnected
from datetime import datetime
from pathlib import Path
import shutil
import time
from app.logger_utils import log
from app.config_manager import resolve_save_dir
from app.thumbnails import ensure_thumbnail

SNAPSHOT_TIMEOUT_SECONDS = 10
HEALTH_TIMEOUT_SECONDS = 5
CAMERA_RETRIES = 3
CAMERA_RETRY_DELAY_SECONDS = 0.35
CAMERA_HEADERS = {
    "User-Agent": "CaptureLapse/0.9",
    "Accept": "image/*,*/*;q=0.8",
    # Disable keep-alive to avoid stale socket reuse with some IP cameras.
    "Connection": "close",
}


def _build_auth(cfg):
    """Return requests auth based on config."""
    if cfg.auth_type == "basic" and cfg.username and cfg.password:
        return HTTPBasicAuth(cfg.username, cfg.password)
    if cfg.auth_type == "digest" and cfg.username and cfg.password:
        return HTTPDigestAuth(cfg.username, cfg.password)
    return None


def _format_request_error(err: Exception) -> str:
    """Return a concise, user-facing message for transport errors."""
    if isinstance(err, RemoteDisconnected):
        return "Remote end closed connection without response"
    for arg in getattr(err, "args", ()):
        if isinstance(arg, RemoteDisconnected):
            return "Remote end closed connection without response"
        text = str(arg or "").strip()
        if text and "Remote end closed connection without response" in text:
            return "Remote end closed connection without response"
    text = str(err or "").strip()
    if text:
        return text
    return err.__class__.__name__


def _camera_get_with_retries(cfg, *, timeout_seconds: int, stream: bool = False):
    """Perform GET with retries for transient camera/network errors."""
    auth = _build_auth(cfg)
    last_error = None
    for attempt in range(CAMERA_RETRIES):
        try:
            resp = requests.get(
                cfg.cam_url,
                auth=auth,
                timeout=timeout_seconds,
                stream=stream,
                allow_redirects=True,
                headers=CAMERA_HEADERS,
            )
            return resp, auth, None
        except RequestException as err:
            last_error = err
        except Exception as err:
            last_error = err
        if attempt < CAMERA_RETRIES - 1:
            time.sleep(CAMERA_RETRY_DELAY_SECONDS)
    return None, auth, last_error


def take_snapshot(cfg):
    """Download a snapshot from the camera and store it locally."""
    if not cfg.cam_url:
        log("warn", "No camera URL configured - snapshot skipped.")
        return None

    try:
        # Resolve save_dir using configured base + relative path
        save_dir = resolve_save_dir(getattr(cfg, "save_path", None))
        save_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        filename = f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = save_dir / filename

        # Select auth method based on config
        auth = _build_auth(cfg)
        if auth:
            log("info", f"Using HTTP {cfg.auth_type.title()} Auth.")
        else:
            log("info", "No authentication used.")

        # Fetch snapshot
        log("info", f"Fetching snapshot from {cfg.cam_url} ...")
        resp, _auth, request_error = _camera_get_with_retries(
            cfg,
            timeout_seconds=SNAPSHOT_TIMEOUT_SECONDS,
            stream=True,
        )
        if request_error is not None:
            log("error", f"Snapshot request failed: {_format_request_error(request_error)}")
            return None
        if resp is None:
            log("error", "Snapshot request failed: no response")
            return None

        if resp.status_code != 200:
            log("error", f"Camera responded with status {resp.status_code}")
            resp.close()
            return None

        # Write file to disk
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
        resp.close()
        ensure_thumbnail(filepath)

        log("info", f"Snapshot saved: {filename}")

        # Copy to app/static/img/last.jpg for the dashboard preview
        try:
            preview_path = Path(__file__).resolve().parent / "static" / "img" / "last.jpg"
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(filepath, preview_path)
            log("info", f"last.jpg updated ({preview_path})")
        except Exception as e:
            log("error", f"Failed to copy last.jpg: {e}")

        return {
            "filename": filename,
            "filepath": str(filepath),
            "timestamp": now.strftime("%H:%M:%S"),
            "timestamp_full": now.strftime("%d.%m.%y %H:%M"),
            "timestamp_iso": now.isoformat(timespec="seconds")
        }

    except Exception as e:
        log("error", f"Snapshot failed: {e}")
        return None


def check_camera_health(cfg):
    """Lightweight healthcheck for the camera endpoint."""
    if not cfg.cam_url:
        return {"ok": False, "code": "no_url", "message": "No camera URL configured"}

    auth = _build_auth(cfg)

    try:
        # Prefer HEAD to avoid downloading the full snapshot; fall back to GET if needed.
        try:
            resp = requests.head(
                cfg.cam_url,
                auth=auth,
                timeout=HEALTH_TIMEOUT_SECONDS,
                allow_redirects=True,
                headers=CAMERA_HEADERS,
            )
            status = resp.status_code
        except Exception:
            status = 599

        if status >= 400:
            # Some cameras reject HEAD (or auth on HEAD) but allow GET.
            # Avoid Range headers because some cameras drop the connection on ranged requests.
            resp, _auth, last_error = _camera_get_with_retries(
                cfg,
                timeout_seconds=HEALTH_TIMEOUT_SECONDS,
                stream=True,
            )
            if resp is not None:
                status = resp.status_code
                if status < 400:
                    # Read a single chunk to confirm reachability.
                    next(resp.iter_content(chunk_size=1024), None)
                    resp.close()
                    return {"ok": True, "code": str(status), "message": "Camera reachable"}
                resp.close()
            if last_error is not None:
                return {
                    "ok": False,
                    "code": "connection_error",
                    "message": _format_request_error(last_error),
                }
        if status < 400:
            return {"ok": True, "code": str(status), "message": "Camera reachable"}
        return {"ok": False, "code": str(status), "message": f"HTTP {status}"}
    except Exception as e:
        return {"ok": False, "code": "exception", "message": _format_request_error(e)}
