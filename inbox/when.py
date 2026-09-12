"""Parse the ways a person writes a time: '2026-09-12 16:00', 'fri 9am',
'tomorrow 9:00', 'in 2h', 'today 18:30', '12 sep 15:30'. Local timezone."""
import re
from datetime import datetime, timedelta

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DEFAULT_HOUR = 9


class WhenError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now().astimezone()


def _time(text: str | None) -> tuple[int, int]:
    """'9am', '9:30', '16:00', '4pm', '4.30pm' -> (hour, minute)."""
    if not text:
        return DEFAULT_HOUR, 0
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", text.strip().lower())
    if not m:
        raise WhenError(f"cannot read time '{text}'")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise WhenError(f"cannot read time '{text}'")
    return h, mi


def parse(text: str, now: datetime | None = None) -> datetime:
    now = now or _now()
    t = text.strip().lower()

    # relative: in 2h / in 30m / in 3d
    m = re.fullmatch(r"in\s+(\d+)\s*(m|min|h|hr|d|day|days|hours|minutes)", t)
    if m:
        n, u = int(m.group(1)), m.group(2)[0]
        return now + timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[u]: n})

    # ISO datetime or date
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=DEFAULT_HOUR)
            return dt.replace(tzinfo=now.tzinfo)
        except ValueError:
            pass

    # words: today/tomorrow/weekday/"12 sep", optionally followed by a time
    parts = t.split()
    day_word, time_word = parts[0], " ".join(parts[1:]) or None
    base = None
    if day_word == "today":
        base = now
    elif day_word == "tomorrow":
        base = now + timedelta(days=1)
    elif day_word[:3] in WEEKDAYS:
        target = WEEKDAYS.index(day_word[:3])
        ahead = (target - now.weekday()) % 7
        base = now + timedelta(days=ahead)
    elif len(parts) >= 2 and parts[0].isdigit() and parts[1][:3] in MONTHS:
        day, mon = int(parts[0]), MONTHS.index(parts[1][:3]) + 1
        year = now.year
        base = now.replace(year=year, month=mon, day=day)
        if base.date() < now.date():
            base = base.replace(year=year + 1)
        time_word = " ".join(parts[2:]) or None
    if base is None:
        raise WhenError(f"cannot read '{text}'; try '2026-09-12 16:00', 'fri 9am', 'tomorrow 18:30' or 'in 2h'")
    h, mi = _time(time_word)
    dt = base.replace(hour=h, minute=mi, second=0, microsecond=0)
    if day_word[:3] in WEEKDAYS and dt <= now:
        dt += timedelta(days=7)          # 'fri' on a Friday evening means next Friday
    return dt


def fmt(dt: datetime) -> str:
    return dt.strftime("%a %d %b %H:%M")
