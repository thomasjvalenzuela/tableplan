"""What can I make? Pure ranking and bucketing for recipes checked against the inventory.

Each candidate is a dict: {id, name, rating, minutes, missing: [...], expiring: [...], planned_soon: bool}.
  - Make right now: nothing missing.
  - Almost there: 1–3 missing.
  - Use it up: uses something expiring within the window, at most 3 missing.
Recipes already planned in the next few days are left out (they're handled already).
Order: uses the most expiring food first, then rating, then the quickest, then the name.
"""

ALMOST_MAX = 3


def rank_key(r):
    mins = r.get("minutes")
    return (-len(r.get("expiring") or []), -float(r.get("rating") or 0),
            mins if isinstance(mins, (int, float)) and mins > 0 else 10 ** 6, (r.get("name") or "").lower())


def buckets(cands, limit=60):
    pool = [r for r in cands if not r.get("planned_soon") and r.get("need_n")]
    ready = sorted((r for r in pool if not r["missing"]), key=rank_key)
    almost = sorted((r for r in pool if 1 <= len(r["missing"]) <= ALMOST_MAX), key=lambda r: (len(r["missing"]),) + rank_key(r))
    use_up = sorted((r for r in pool if r.get("expiring") and len(r["missing"]) <= ALMOST_MAX),
                    key=lambda r: rank_key(r)[:1] + (len(r["missing"]),) + rank_key(r)[1:])
    return {"ready": ready[:limit], "almost": almost[:limit], "use_up": use_up[:limit]}


def enough(need_qty, need_unit, stock, convert):
    """Is there enough in stock for one need? stock = [(free_qty|None, unit)]. Unknown amounts count as enough;
    units that don't convert can't be compared, so they count as enough too (better than a false "missing")."""
    if need_qty is None:
        return True
    total = 0.0
    for free, unit in stock:
        if free is None:
            return True
        v = convert(free, unit, need_unit)
        if v is None:
            return True
        total += v
    return total + 1e-6 >= need_qty
