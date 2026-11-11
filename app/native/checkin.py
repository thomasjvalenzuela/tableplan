"""Kitchen check-in: which items are worth asking about, when the check-in is due, and learning how fast food goes.

Pure functions; the server passes in rows as dicts. Each candidate gets a score and a plain reason; only the most
uncertain (at most 10) are asked. Items confirmed in the last few days aren't asked again.
"""

from datetime import date, datetime, timedelta

MAX_CARDS = 10
QUIET_DAYS = 5          # don't ask about an item confirmed this recently
STILL_DAYS = 21         # "no movement" after three weeks untouched
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def last_slot(now, day="sun", hour=18):
    """The most recent check-in time (e.g. Sunday 18:00) at or before `now`."""
    wd = WEEKDAYS.index(day) if day in WEEKDAYS else 6
    back = (now.weekday() - wd) % 7
    slot = datetime(now.year, now.month, now.day, int(hour)) - timedelta(days=back)
    if slot > now:
        slot -= timedelta(days=7)
    return slot


def is_due(now, last_done, interval_days, day="sun", hour=18):
    """Due once the scheduled slot has passed and the last check-in was before it (every 2 weeks: and ~2 weeks ago)."""
    if not interval_days:
        return False
    slot = last_slot(now, day, hour)
    if last_done is None:
        return True
    if last_done >= slot:
        return False
    return (slot - last_done).days >= interval_days - 1 if interval_days > 7 else True


def cadence(dates):
    """Typical days between purchases (median of the gaps), from 3+ purchase dates; None if unknown."""
    ds = sorted({d for d in (_d(x) for x in dates) if d})
    gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
    if len(gaps) < 2:
        return None
    gaps.sort()
    return gaps[len(gaps) // 2]


def learn(prev_days, prev_n, observed_days, answer):
    """Update the learned days-until-gone for a food. Gone: blend in what happened. Still have past the learned time:
    nudge it later. Running low: a hint it's nearly done (counts a little)."""
    obs = max(1.0, float(observed_days))
    if prev_days is None:
        return (obs, 1) if answer == "gone" else (None, 0)
    if answer == "gone":
        w = 1.0 / min(prev_n + 1, 5)          # an average that keeps adapting
        return prev_days + w * (obs - prev_days), prev_n + 1
    if answer == "have" and obs > prev_days:
        return prev_days + 0.3 * (obs - prev_days), prev_n
    if answer == "low":
        est = obs * 1.25
        return prev_days + 0.15 * (est - prev_days), prev_n
    return prev_days, prev_n


def candidates(items, today, last_event=None, last_asked=None, cadences=None, rates=None, limit=MAX_CARDS):
    """Items worth asking about, most uncertain first: [{id, score, reason}].
    items: pantry rows (dicts); last_event: {id: date of last change}; last_asked: {id: date last confirmed};
    cadences: {food key: typical days between buys}; rates: {food key: learned days until gone}."""
    last_event, last_asked, cadences, rates = last_event or {}, last_asked or {}, cadences or {}, rates or {}
    out = []
    for it in items:
        if it.get("review"):
            continue
        asked = _d(last_asked.get(it["id"]))
        if asked and (today - asked).days < QUIET_DAYS:
            continue
        bought = _d(it.get("purchased_on")) or today
        age = (today - bought).days
        exp = _d(it.get("expires_on"))
        left = float(it.get("amount_left") if it.get("amount_left") is not None else 1)
        key = it.get("key")
        score, reason = 0.0, ""

        def bump(s, r):
            nonlocal score, reason
            if s > score:
                score, reason = s, r
            else:
                score += s * 0.25

        if exp is not None:
            dl = (exp - today).days
            opened = it.get("opened_on") and it.get("expiry_source") == "opened"
            if dl < 0:
                bump(6, f"Opened {(today - _d(it['opened_on'])).days} days ago, past its countdown" if opened else
                     f"Past its use-by date ({-dl} day{'s' if dl != -1 else ''})")
            elif dl <= 2:
                bump(4.5, "Use by today" if dl == 0 else "Use by tomorrow" if dl == 1 else "Use within 2 days")
        if left <= 0.25:
            bump(3.5, "Running low last time")
        rate = rates.get(key)
        if rate and age >= rate:
            bump(4, f"Usually gone after ~{round(rate)} days")
        cad = cadences.get(key)
        if cad and age >= cad and not rate:
            bump(3.8, f"You usually buy {it.get('name', 'this').lower()} every ~{cad} days")
        moved = _d(last_event.get(it["id"])) or bought
        if (today - moved).days >= STILL_DAYS and it.get("location") != "freezer":
            bump(2, f"Not touched in {(today - moved).days // 7} weeks")
        if score > 0:
            out.append({"id": it["id"], "score": round(score, 2), "reason": reason})
    out.sort(key=lambda x: (-x["score"], x["id"]))
    return out[:limit]
