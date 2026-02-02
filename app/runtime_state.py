"""Holds runtime global state (e.g., last camera error)."""

from typing import Optional, Dict, Any
from time import time

_camera_error: Optional[Dict[str, Any]] = None
_camera_health: Optional[Dict[str, Any]] = None
_image_stats: Optional[Dict[str, Any]] = None
_image_stats_updated_at: Optional[float] = None


def set_camera_error(code: Optional[str], message: str) -> None:
    """Store the last camera error."""
    global _camera_error
    _camera_error = {
        "code": code,
        "message": message
    }


def clear_camera_error() -> None:
    """Clear the stored camera error."""
    global _camera_error
    _camera_error = None


def get_camera_error() -> Optional[Dict[str, Any]]:
    """Return the last camera error if present."""
    return _camera_error


def set_camera_health(status: str, code: Optional[str], message: str, checked_at: str) -> None:
    """Store the last camera healthcheck result."""
    global _camera_health
    _camera_health = {
        "status": status,
        "code": code,
        "message": message,
        "checked_at": checked_at,
    }


def get_camera_health() -> Optional[Dict[str, Any]]:
    """Return the last camera healthcheck info."""
    return _camera_health


def set_image_stats(
    count: int,
    last_snapshot: Optional[str],
    last_snapshot_full: Optional[str],
    last_snapshot_iso: Optional[str],
) -> None:
    """Store cached image stats for the status endpoint."""
    global _image_stats, _image_stats_updated_at
    _image_stats = {
        "count": count,
        "last_snapshot": last_snapshot,
        "last_snapshot_full": last_snapshot_full,
        "last_snapshot_iso": last_snapshot_iso,
    }
    _image_stats_updated_at = time()


def get_image_stats() -> Optional[Dict[str, Any]]:
    """Return cached image stats if present."""
    return _image_stats


def get_image_stats_updated_at() -> Optional[float]:
    """Return Unix timestamp of the last image stats refresh."""
    return _image_stats_updated_at
