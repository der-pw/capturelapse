from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import time


class ConfigModel(BaseModel):
    """Global app configuration (replaces the former INI file)."""
    instance_name: Optional[str] = Field(None, description="Optional instance name override")
    cam_url: str = Field(
        "https://raw.githubusercontent.com/der-pw/capturelapse/main/app/static/img/capturelapse.jpg",
        description="Webcam snapshot URL",
    )
    access_password: Optional[str] = Field(
        None,
        description="Legacy plaintext password for UI/API access (migrated to hash when possible)",
    )
    access_password_hash: Optional[str] = Field(None, description="Hashed password for UI/API access")
    username: Optional[str] = Field(None, description="Camera username")
    password: Optional[str] = Field(None, description="Camera password")
    auth_type: str = Field("none", description="Auth type: none/basic/digest")
    save_path: str = Field("./pictures", description="Directory to store snapshots")

    interval_seconds: int = Field(300, description="Capture interval in seconds")
    active_start: str = Field("06:00", description="Start time (HH:MM)")
    active_end: str = Field("22:00", description="End time (HH:MM)")
    active_days: List[str] = Field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    schedule_start_date: Optional[str] = Field(None, description="Schedule start date (YYYY-MM-DD)")
    schedule_end_date: Optional[str] = Field(None, description="Schedule end date (YYYY-MM-DD)")

    paused: bool = Field(False, description="Scheduler state: paused yes/no")

    use_astral: bool = Field(False, description="Use sunrise/sunset")
    city_lat: float = Field(52.1676, description="Latitude")
    city_lon: float = Field(10.5479, description="Longitude")
    city_tz: str = Field("Europe/Berlin", description="Timezone")

    log_file: Optional[str] = Field(None, description="Log file (optional)")
    log_enabled: bool = Field(True, description="Write capturelapse.log file")
    language: str = Field("en", description="Language code (e.g., de, en)")


class StatusModel(BaseModel):
    """Status API response."""
    time: str
    active: bool
    paused: bool = False
    image_count: int = 0


class SnapshotEvent(BaseModel):
    """SSE event (e.g., new image or error)."""
    type: str
    message: Optional[str] = None
    filename: Optional[str] = None
    count: Optional[int] = None


