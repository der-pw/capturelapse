import json
import os
from pathlib import Path
from typing import Optional
from app.models import ConfigModel

APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.default.json"


def _resolve_data_dir() -> Path:
    env_dir = os.getenv("CAPTURELAPSE_DATA_DIR")
    if env_dir:
        candidate = Path(env_dir)
        if not candidate.is_absolute():
            candidate = (APP_DIR / candidate).resolve()
        return candidate
    # Prefer /data inside Docker for mounted persistence; fall back to app-local data.
    if Path("/.dockerenv").exists():
        return Path("/data")
    return APP_DIR / "data"


def _resolve_pictures_dir() -> Path:
    env_dir = os.getenv("CAPTURELAPSE_PICTURES_DIR")
    if env_dir:
        candidate = Path(env_dir)
        if not candidate.is_absolute():
            candidate = (APP_DIR / candidate).resolve()
        return candidate
    # Prefer /pictures inside Docker for mounted persistence; fall back to app-local pictures.
    if Path("/.dockerenv").exists():
        return Path("/pictures")
    return APP_DIR / "pictures"


DATA_DIR = _resolve_data_dir()  # Central location for config storage
CONFIG_PATH = DATA_DIR / "config.json"
PICTURES_DIR = _resolve_pictures_dir()  # Default root for snapshots


def _harmonize_default_config(default_data: dict) -> dict:
    data = dict(default_data)
    save_path = data.get("save_path")
    env_pictures = os.getenv("CAPTURELAPSE_PICTURES_DIR")
    if env_pictures:
        # If an explicit pictures dir is provided, persist it to avoid confusion.
        data["save_path"] = str(PICTURES_DIR)
        return data
    if isinstance(save_path, str) and save_path == "/pictures" and DATA_DIR != Path("/data"):
        data["save_path"] = "./pictures"
    return data


def _harmonize_existing_config(data: dict) -> tuple[dict, bool]:
    """Adjust config values that should reflect environment overrides."""
    updated = False
    env_pictures = os.getenv("CAPTURELAPSE_PICTURES_DIR")
    if env_pictures:
        save_path = data.get("save_path")
        if isinstance(save_path, str) and save_path.strip() in ("./pictures", "pictures", "/pictures"):
            data["save_path"] = str(PICTURES_DIR)
            updated = True
    return data, updated


def resolve_save_dir(save_path: Optional[str]) -> Path:
    """Resolve the configured save path to an absolute directory."""
    if not save_path:
        return PICTURES_DIR
    candidate = Path(save_path)
    if candidate.is_absolute():
        if candidate == Path("/pictures") and PICTURES_DIR != Path("/pictures"):
            return PICTURES_DIR
        return candidate
    normalized = save_path.replace("\\", "/").strip()
    if normalized in ("./pictures", "pictures"):
        return PICTURES_DIR
    return (PICTURES_DIR / candidate).resolve()


def load_config() -> ConfigModel:
    """Load config.json; initialize from config.default.json on first start.

    Order:
    1) If config.json exists -> load and return
    2) If not, but config.default.json exists -> copy to config.json and return
    3) Fallback: use Pydantic defaults and write config.json
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 1) Normal load if present
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            data, updated = _harmonize_existing_config(data)
            if updated:
                CONFIG_PATH.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                print("[INFO] Config updated to reflect ENV overrides:", CONFIG_PATH)
            return ConfigModel(**data)
        except Exception as e:
            print(f"[WARN] Failed to load config: {e}")

    # 2) First start: copy default file to config.json if possible
    if DEFAULT_CONFIG_PATH.exists():
        try:
            default_data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
            default_data = _harmonize_default_config(default_data)
            CONFIG_PATH.write_text(
                json.dumps(default_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print("[INFO] Copied config.default.json to config.json")
            return ConfigModel(**default_data)
        except Exception as e:
            print(f"[WARN] Could not apply default config: {e}")

    # 3) Last fallback: use model defaults
    cfg = ConfigModel()
    save_config(cfg)
    return cfg


def save_config(cfg: ConfigModel | dict) -> None:
    """Persist configuration to config.json."""
    if isinstance(cfg, ConfigModel):
        data = cfg.model_dump()
    else:
        data = dict(cfg)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[INFO] Config saved:", CONFIG_PATH)


