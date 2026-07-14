from datetime import datetime, timedelta, timezone
import re
from typing import Optional


BEIJING_TZ = timezone(timedelta(hours=8))
LEGACY_UTC_FORMAT = "%Y-%m-%d %H:%M:%S"
CANONICAL_BEIJING_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
LEGACY_UTC_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
CANONICAL_BEIJING_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00")


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


def is_canonical_beijing_iso(value: Optional[str]) -> bool:
    if not value or not CANONICAL_BEIJING_PATTERN.fullmatch(value):
        return False
    try:
        datetime.strptime(value, CANONICAL_BEIJING_FORMAT)
    except ValueError:
        return False
    return True


def legacy_utc_to_beijing_iso(value: Optional[str]) -> Optional[str]:
    if not value or is_canonical_beijing_iso(value):
        return value
    if not LEGACY_UTC_PATTERN.fullmatch(value):
        return value
    try:
        parsed = datetime.strptime(value, LEGACY_UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return parsed.astimezone(BEIJING_TZ).replace(microsecond=0).isoformat()
