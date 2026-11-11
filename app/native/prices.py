"""Prices and budgets: unit prices, picking the best known price, costing amounts and packages, budget periods.

Pure functions (no database, no network) so the money math is easy to test.

A price record is a dict: {source, price, qty, unit, unit_price, base, observed_on, store, url}
  - price: what one package costs (USD); qty/unit: the package size ("1 gal", "12 each")
  - unit_price: USD per base unit; base: "g" (weight), "ml" (volume) or "each" (counted)
Sources, best first: receipt > manual > kroger > ai > bls. A stale record only wins when nothing fresh is known.
Never invent a price: anything without a real source stays unpriced.
"""

import math
from datetime import date, datetime, timedelta, timezone

SOURCES = ("receipt", "manual", "kroger", "ai", "bls")
RANK = {s: i for i, s in enumerate(SOURCES)}
STALE_DAYS = {"receipt": 120, "manual": 365, "kroger": 14, "ai": 45, "bls": 120}
ESTIMATE_SOURCES = {"ai", "bls"}          # shown with ≈
LABEL = {"receipt": "Your receipts", "manual": "Set by you", "kroger": "Kroger", "ai": "Web estimate", "bls": "US average (BLS)"}
BASE_OF_DIM = {"weight": "g", "volume": "ml"}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def base_amount(qty, unit, convert, dimension):
    """(amount in base units, base) for a quantity, or (None, None) when it can't be measured."""
    if qty is None or qty <= 0:
        return None, None
    dim = dimension(unit) if unit else None
    if dim in BASE_OF_DIM:
        b = BASE_OF_DIM[dim]
        v = convert(qty, unit, b)
        return (v, b) if v is not None else (None, None)
    v = convert(qty, unit, "each") if unit else None   # "1 dozen" -> 12
    return float(v if v is not None else qty), "each"  # eggs, cans, "2 avocados", "1 head": counted


def unit_price(price, qty, unit, convert, dimension):
    """USD per base unit for a package: $3.99 for 1 gal -> (0.001054, "ml")."""
    if price is None or price <= 0:
        return None, None
    amt, base = base_amount(qty if qty else 1, unit if qty else "", convert, dimension)
    if not amt:
        return None, None
    return price / amt, base


def is_stale(rec, today):
    try:
        d = date.fromisoformat(str(rec.get("observed_on"))[:10])
    except ValueError:
        return True
    return (today - d).days > STALE_DAYS.get(rec.get("source"), 30)


def best(records, today, base=None):
    """The record to use: fresh before stale, then by source rank, then newest. Only records with a unit price in the
    wanted base (when given) count."""
    ok = [r for r in records if r.get("unit_price") and (base is None or r.get("base") == base)]
    if not ok:
        return None
    return min(ok, key=lambda r: (is_stale(r, today), RANK.get(r.get("source"), 99), _neg_date(r.get("observed_on"))))


def _neg_date(s):
    try:
        return -date.fromisoformat(str(s)[:10]).toordinal()
    except ValueError:
        return 0


def approx(rec, today):
    return rec is None or rec.get("source") in ESTIMATE_SOURCES or is_stale(rec, today)


def cost_used(need_qty, need_unit, records, today, convert, dimension):
    """What the amount a recipe uses costs (partial packages count only the part used).
    Returns {cost, approx, source} or None when it can't be priced."""
    amt, base = base_amount(need_qty, need_unit, convert, dimension)
    if amt is None:
        return None
    rec = best(records, today, base)
    if not rec:
        return None
    return {"cost": amt * rec["unit_price"], "approx": approx(rec, today), "source": rec["source"]}


def cost_to_buy(need_qty, need_unit, records, today, convert, dimension):
    """What buying enough costs: whole packages of the best-priced size (1.5 cups of milk -> one gallon).
    Without a known package size the used amount is priced instead (and marked approximate)."""
    amt, base = base_amount(need_qty if need_qty else 1, need_unit if need_qty else "", convert, dimension)
    rec = best(records, today, base) if amt is not None else None
    if rec is None:
        rec = best(records, today)
        if rec is None:
            return None
        if amt is None or rec.get("base") != base:   # "some garlic": one package
            return {"cost": rec["price"], "packages": 1, "approx": True, "source": rec["source"]}
    pack, pbase = base_amount(rec.get("qty"), rec.get("unit"), convert, dimension) if rec.get("qty") else (None, None)
    if not pack or pbase != base or not rec.get("price"):
        return {"cost": amt * rec["unit_price"], "packages": None, "approx": True, "source": rec["source"]}
    n = max(1, math.ceil(amt / pack - 1e-9))
    return {"cost": n * rec["price"], "packages": n, "approx": approx(rec, today), "source": rec["source"]}


def money(v):
    return round(float(v) + 1e-9, 2)


# ------------------------------------------------------------------ budget periods

def local_today(now_utc, tz):
    """The household's calendar day for a moment: tz is a tzinfo (or None for the server's local time)."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return (now_utc.astimezone(tz) if tz else now_utc.astimezone()).date()


def period_bounds(kind, day, week_start="mon"):
    """[start, end] dates (inclusive) of the week or month containing `day`."""
    if kind == "month":
        start = day.replace(day=1)
        nxt = (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1))
        return start, nxt - timedelta(days=1)
    ws = WEEKDAYS.index(week_start) if week_start in WEEKDAYS else 0
    start = day - timedelta(days=(day.weekday() - ws) % 7)
    return start, start + timedelta(days=6)


def previous_periods(kind, day, n, week_start="mon"):
    """The last n periods ending with the one containing `day`, oldest first."""
    out, d = [], day
    for _ in range(n):
        s, e = period_bounds(kind, d, week_start)
        out.append((s, e))
        d = s - timedelta(days=1)
    return out[::-1]


def budget_level(spent, budget):
    """"" under 80%, "warn" from 80%, "over" from 100%."""
    if not budget or budget <= 0:
        return ""
    r = spent / budget
    return "over" if r >= 1 else "warn" if r >= 0.8 else ""


def waste_value(amount_left, price_paid, records, qty, unit, today, convert, dimension):
    """Value of what was thrown away: the share left of what was paid, else the left amount at the best known price."""
    left = max(0.0, min(1.0, float(amount_left or 0)))
    if left <= 0:
        return 0.0, False
    if price_paid:
        return price_paid * left, False
    if qty:
        r = cost_used(qty * left, unit, records, today, convert, dimension)
        if r:
            return r["cost"], r["approx"]
    rec = best(records, today, "each")
    if rec and rec.get("price"):
        return rec["price"] * left, True
    return 0.0, True


def parse_money(text):
    """'$3.49' / '3.49' / '2 for $5' -> per-item price, or None."""
    import re
    t = str(text or "").replace(",", "")
    m = re.search(r"(\d+)\s*(?:for|/)\s*\$\s*(\d+(?:\.\d{1,2})?)", t, re.I)
    if m and int(m.group(1)) > 0:
        return round(float(m.group(2)) / int(m.group(1)), 2)
    m = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", t)
    return float(m.group(1)) if m and float(m.group(1)) > 0 else None
