import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from datetime import datetime
from pathlib import Path
import shutil
from app.logger_utils import log
from app.config_manager import resolve_save_dir


def _build_auth(cfg):
    """Return requests auth based on config."""
    if cfg.auth_type == "basic" and cfg.username and cfg.password:
        return HTTPBasicAuth(cfg.username, cfg.password)
    if cfg.auth_type == "digest" and cfg.username and cfg.password:
        return HTTPDigestAuth(cfg.username, cfg.password)
    return None


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
        resp = requests.get(cfg.cam_url, auth=auth, timeout=10)

        if resp.status_code != 200:
            log("error", f"Camera responded with status {resp.status_code}")
            return None

        # Write file to disk
        with open(filepath, "wb") as f:
            f.write(resp.content)

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
        resp = requests.head(cfg.cam_url, auth=auth, timeout=5, allow_redirects=True)
        status = resp.status_code
        if status >= 400:
            # Some cameras reject HEAD (or auth on HEAD) but allow GET.
            resp = requests.get(
                cfg.cam_url,
                auth=auth,
                timeout=5,
                stream=True,
                allow_redirects=True,
                headers={"Range": "bytes=0-1023"},
            )
            status = resp.status_code
            # Read a single chunk to confirm reachability
            next(resp.iter_content(chunk_size=1024), None)
            resp.close()
        if status < 400:
            return {"ok": True, "code": str(status), "message": "Camera reachable"}
        return {"ok": False, "code": str(status), "message": f"HTTP {status}"}
    except Exception as e:
        return {"ok": False, "code": "exception", "message": str(e)}
