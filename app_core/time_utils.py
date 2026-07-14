from datetime import datetime, timedelta, timezone
from typing import Optional


BEIJING_TZ = timezone(timedelta(hours=8))
LEGACY_UTC_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_beijing_iso(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(BEIJING_TZ).replace(microsecond=0).isoformat()


def beijing_today(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(BEIJING_TZ).date().isoformat()


def legacy_utc_to_beijing_iso(value: Optional[str]) -> Optional[str]:
    if not value or "T" in value:
        return value
    try:
        parsed = datetime.strptime(value, LEGACY_UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return parsed.astimezone(BEIJING_TZ).replace(microsecond=0).isoformat()
