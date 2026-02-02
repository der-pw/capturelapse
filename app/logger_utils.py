import logging
import os
import inspect
from pathlib import Path
from datetime import datetime

# === Standard logger ===
logger = logging.getLogger("capturelapse")
_level_name = os.getenv("CAPTURELAPSE_LOG_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, _level_name, logging.INFO))

# Console handler (no file output)
console_handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# In-memory buffer (for live view)
LOG_BUFFER = []


_CATEGORY_MAP = {
    "scheduler": "SCHEDULER",
    "main": "APP",
    "downloader": "CAMERA",
    "sunrise_utils": "ASTRAL",
    "broadcast_manager": "SSE",
    "config_manager": "CONFIG",
}


def _infer_category() -> str:
    frame = inspect.currentframe()
    if not frame or not frame.f_back:
        return "APP"
    caller = frame.f_back
    module = Path(caller.f_code.co_filename).stem
    return _CATEGORY_MAP.get(module, module.upper())


def log(level: str, msg: str, category: str | None = None):
    """Write to both console and in-memory buffer."""
    cat = category or _infer_category()
    formatted = f"[{cat}] {msg}"
    entry = f"{datetime.now():%H:%M:%S} [{level.upper()}] {formatted}"
    LOG_BUFFER.append(entry)
    if len(LOG_BUFFER) > 200:
        LOG_BUFFER.pop(0)

    level = level.lower()
    if level == "error":
        logger.error(formatted)
    elif level in ("warn", "warning"):
        logger.warning(formatted)
    else:
        logger.info(formatted)


def get_recent_logs(n: int = 100):
    """Return the last n log entries from the in-memory buffer."""
    return LOG_BUFFER[-n:]



