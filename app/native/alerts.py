"""When to warn about missing ingredients: the day-before heads-up and the morning check.

Times are the household's local wall-clock time (naive datetimes in its time zone).
  - Day before: 24 hours before the meal's start-cooking time (eat-at minus how long it takes), or 6 pm the day before
    when the meal has no time. It stays due until the meal starts.
  - Morning: from the morning check time (8:00 by default) on the meal's day, until the meal starts.
"""

from datetime import datetime, time, timedelta

DAY_BEFORE_FALLBACK = time(18, 0)


def _hhmm(s, default=time(8, 0)):
    try:
        h, m = (int(x) for x in str(s).split(":"))
        return time(h, m)
    except (ValueError, TypeError):
        return default


def meal_end(day, start):
    """After this the meal is past: its start time, or the end of its day when it has none."""
    return start or datetime.combine(day, time(23, 59))


def day_before_due(now, day, start=None):
    target = start - timedelta(hours=24) if start else datetime.combine(day - timedelta(days=1), DAY_BEFORE_FALLBACK)
    return target <= now < meal_end(day, start)


def morning_due(now, day, morning="08:00", start=None):
    return now.date() == day and now.time() >= _hhmm(morning) and now < meal_end(day, start)


def due_windows(now, day, start=None, morning="08:00", day_before=True, morning_on=True):
    """The alert windows open right now for one meal: ["day_before"], ["morning"], or both (morning wins on the day)."""
    out = []
    if morning_on and morning_due(now, day, morning, start):
        out.append("morning")
    elif day_before and day_before_due(now, day, start) and now.date() < day:
        out.append("day_before")
    elif day_before and day_before_due(now, day, start) and start and now.date() == day and not morning_on:
        out.append("day_before")
    return out
