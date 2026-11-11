"""Barcode normalization: UPC-A, UPC-E, EAN-8, EAN-13 and GTIN-14, with check digits.

A misread (bad check digit) is reported as such instead of "not found". normalize() returns the canonical code
(13-digit EAN for UPC/EAN-13, 8 digits for EAN-8) and the variants worth trying with lookup services. Stdlib only.
"""


def check_digit(body):
    """GS1 check digit for the digits before it (works for EAN-8, UPC-A, EAN-13, GTIN-14)."""
    s = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - s % 10) % 10)


def valid(code):
    return code.isdigit() and len(code) in (8, 12, 13, 14) and check_digit(code[:-1]) == code[-1]


def upce_to_upca(code):
    """Expand UPC-E (6 digits, or 7/8 with number system and check digit) to 12-digit UPC-A. None if it can't be."""
    if not code.isdigit():
        return None
    ns, check = "0", None
    if len(code) == 6:
        d = code
    elif len(code) == 7:
        ns, d = code[0], code[1:]
    elif len(code) == 8:
        ns, d, check = code[0], code[1:7], code[7]
    else:
        return None
    if ns not in "01":
        return None
    last = d[5]
    if last in "012":
        body = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        body = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        body = d[0:4] + "00000" + d[4]
    else:
        body = d[0:5] + "0000" + last
    upca = ns + body
    cd = check_digit(upca)
    if check is not None and check != cd:
        return None
    return upca + cd


def normalize(raw):
    """-> {"code": canonical, "try": [codes to look up], "misread": bool, "plu": bool}."""
    code = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(code) in (4, 5):
        return {"code": code, "try": [code], "misread": False, "plu": True}
    if len(code) == 6 or len(code) == 7:
        a = upce_to_upca(code)
        if not a:
            return {"code": code, "try": [], "misread": True, "plu": False}
        return {"code": "0" + a, "try": ["0" + a, a], "misread": False, "plu": False}
    if len(code) == 8:
        tries = []
        if valid(code):
            tries.append(code)                       # EAN-8
        a = upce_to_upca(code)
        if a:
            tries += ["0" + a, a]                    # …or UPC-E with its check digit
        if not tries:
            return {"code": code, "try": [], "misread": True, "plu": False}
        return {"code": tries[0], "try": tries, "misread": False, "plu": False}
    if len(code) == 12:
        if not valid(code):
            return {"code": code, "try": [], "misread": True, "plu": False}
        return {"code": "0" + code, "try": ["0" + code, code], "misread": False, "plu": False}
    if len(code) == 13:
        if not valid(code):
            return {"code": code, "try": [], "misread": True, "plu": False}
        return {"code": code, "try": [code] + ([code[1:]] if code.startswith("0") else []), "misread": False, "plu": False}
    if len(code) == 14:
        if not valid(code):
            return {"code": code, "try": [], "misread": True, "plu": False}
        inner = code[1:] if code.startswith("0") else code
        return {"code": inner, "try": [inner] + ([inner[1:]] if inner.startswith("0") and len(inner) == 13 else []),
                "misread": False, "plu": False}
    return {"code": code, "try": [], "misread": True, "plu": False}
