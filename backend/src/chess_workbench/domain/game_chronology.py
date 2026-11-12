"""Read game start times without mistaking the end of a correspondence game for its start."""

import re
from datetime import UTC, datetime, time, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class GameChronology(NamedTuple):
    order_at: datetime
    started_at: datetime | None
    time_control: str | None


def _date(raw: str) -> tuple[datetime, int] | None:
    match = re.fullmatch(r"(\d{4})(?:[.-](\d{2}|\?\?)(?:[.-](\d{2}|\?\?))?)?", raw)
    if not match:
        return None
    year, month, day = match.groups()
    if month in {None, "??"} and day not in {None, "??"}:
        return None
    parts = [int(value) for value in (year, month, day) if value not in {None, "??"}]
    try:
        first = datetime(
            parts[0],
            parts[1] if len(parts) > 1 else 1,
            parts[2] if len(parts) > 2 else 1,
            tzinfo=UTC,
        )
    except ValueError:
        return None
    return first, len(parts)


def _most_precise(
    utc_day: tuple[datetime, int] | None,
    local_day: tuple[datetime, int] | None,
) -> tuple[datetime, int] | None:
    return max((day for day in (utc_day, local_day) if day), key=lambda pair: pair[1], default=None)


def catalog_date(tags: dict[str, str]) -> str:
    """Spell a partial PGN date without inventing the machine's local day or time."""
    day = _most_precise(_date(tags.get("utcdate", "")), _date(tags.get("date", "")))
    if day is None:
        return "????.??.??"
    moment, precision = day
    month = f"{moment.month:02d}" if precision >= 2 else "??"
    date = f"{moment.day:02d}" if precision >= 3 else "??"
    return f"{moment.year:04d}.{month}.{date}"


def _zone(raw: str) -> timezone | ZoneInfo | None:
    if raw.upper() in {"UTC", "GMT", "Z"}:
        return UTC
    offset = re.fullmatch(r"(?:UTC|GMT)?([+-])(\d{2}):?(\d{2})", raw, flags=re.I)
    if offset:
        sign, hour, minute = offset.groups()
        if int(hour) < 24 and int(minute) < 60:
            delta = timedelta(hours=int(hour), minutes=int(minute))
            return timezone(delta if sign == "+" else -delta)
    if raw and "/" in raw:
        try:
            return ZoneInfo(raw)
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return None


def game_chronology(
    headers: dict[str, str], imported_at: datetime, platform_start: datetime | None = None
) -> GameChronology:
    tags = {key.lower(): value.strip() for key, value in headers.items()}
    clock = tags.get("timecontrol")
    if clock in {"", "?"}:
        clock = None
    if platform_start is not None:
        precise = platform_start.astimezone(UTC)
        return GameChronology(precise, precise, clock)

    utc_day = _date(tags.get("utcdate", ""))
    local_day = _date(tags.get("date", ""))
    # Date + UTCTime is used by some PGNs that omit the redundant UTCDate tag.
    for day, clock_text, zone in (
        (utc_day or local_day, tags.get("utctime"), UTC),
        (
            local_day or utc_day,
            tags.get("starttime") or tags.get("time"),
            _zone(tags.get("timezone", "")),
        ),
    ):
        if not day or day[1] != 3 or not clock_text:
            continue
        try:
            parsed = time.fromisoformat(clock_text)
        except ValueError:
            continue
        combined = datetime.combine(day[0].date(), parsed)
        if combined.tzinfo or zone:
            precise = combined.replace(tzinfo=combined.tzinfo or zone).astimezone(UTC)
            return GameChronology(precise, precise, clock)
        # The unspecified local wall clock still orders same-day games; don't label it UTC.
        return GameChronology(combined.replace(tzinfo=UTC), None, clock)

    best_day = _most_precise(utc_day, local_day)
    return GameChronology(best_day[0] if best_day else imported_at, None, clock)
