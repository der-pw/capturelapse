from datetime import date, datetime, time as dtime
from typing import Optional, Tuple

from astral import LocationInfo
from astral.sun import sun

from app.logger_utils import log


def get_sun_times(cfg, target_date: Optional[date] = None) -> Tuple[Optional[dtime], Optional[dtime]]:
    """
    Compute sunrise/sunset for the location in cfg.
    Returns (sunrise_time, sunset_time) as naive time objects (HH:MM:SS).
    """
    if target_date is None:
        target_date = date.today()

    try:
        city = LocationInfo("", "", cfg.city_tz, cfg.city_lat, cfg.city_lon)
        s = sun(city.observer, date=target_date, tzinfo=city.timezone)
        sunrise = s.get("sunrise")
        sunset = s.get("sunset")
        if sunrise and sunset:
            return sunrise.time(), sunset.time()
        return None, None
    except Exception as e:
        log("warn", f"Astral calculation failed: {e}")
        return None, None


def is_within_time_range(start: dtime, end: dtime, now: Optional[dtime] = None) -> bool:
    """
    Check whether 'now' falls between start and end. Supports ranges across midnight.
    """
    if now is None:
        now = datetime.now().time()

    if start < end:
        return start <= now <= end
    else:
        # Across midnight (e.g., 22:00 - 06:00)
        return now >= start or now <= end
