"""Photo hygiene without image libraries: read an image's pixel size, and strip metadata (EXIF, XMP, IPTC, comments)
so a phone photo never carries its location or camera details into the household's recipes.

JPEG: APP1 (EXIF/XMP), APP12–APP15 and COM segments are dropped; APP0 (JFIF) and APP2 (colour profile) stay.
PNG: eXIf, tEXt, zTXt, iTXt and tIME chunks are dropped.
WebP: EXIF and XMP chunks are dropped and the VP8X flags updated.
Anything else is returned unchanged.
"""

import struct
import zlib

_JPEG_DROP = {0xE1, 0xEC, 0xED, 0xEE, 0xEF, 0xFE}   # APP1, APP12-15, COM
_PNG_DROP = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}


def strip_metadata(blob):
    if blob[:3] == b"\xff\xd8\xff":
        return _strip_jpeg(blob)
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return _strip_png(blob)
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return _strip_webp(blob)
    return blob


def _strip_jpeg(b):
    out, i, n = bytearray(b[:2]), 2, len(b)
    while i + 4 <= n:
        if b[i] != 0xFF:
            return bytes(b)                 # not a marker where one should be: leave the file alone
        marker = b[i + 1]
        if marker == 0xFF:                  # fill byte
            i += 1
            continue
        if marker == 0xDA or marker == 0xD9:   # start of scan: the rest is image data
            out += b[i:]
            return bytes(out)
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += b[i:i + 2]
            i += 2
            continue
        seg_len = struct.unpack(">H", b[i + 2:i + 4])[0]
        end = i + 2 + seg_len
        if seg_len < 2 or end > n:
            return bytes(b)
        if marker not in _JPEG_DROP:
            out += b[i:end]
        i = end
    return bytes(b)


def _strip_png(b):
    out, i = bytearray(b[:8]), 8
    while i + 12 <= len(b):
        ln = struct.unpack(">I", b[i:i + 4])[0]
        typ = b[i + 4:i + 8]
        end = i + 12 + ln
        if end > len(b):
            return bytes(b)
        if typ not in _PNG_DROP:
            out += b[i:end]
        i = end
        if typ == b"IEND":
            break
    return bytes(out)


def _strip_webp(b):
    chunks, i = [], 12
    while i + 8 <= len(b):
        typ = b[i:i + 4]
        ln = struct.unpack("<I", b[i + 4:i + 8])[0]
        end = i + 8 + ln + (ln & 1)
        if end > len(b) + 1:
            return bytes(b)
        if typ not in (b"EXIF", b"XMP "):
            data = bytearray(b[i:min(end, len(b))])
            if typ == b"VP8X" and len(data) >= 9:
                data[8] &= ~(0x08 | 0x04) & 0xFF   # clear the EXIF and XMP flags
            chunks.append(bytes(data))
        i = end
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def size(b):
    """(width, height) of a JPEG, PNG, GIF or WebP, or None."""
    try:
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", b[16:24])
        if b[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", b[6:10])
        if b[:3] == b"\xff\xd8\xff":
            i = 2
            while i + 9 < len(b):
                if b[i] != 0xFF:
                    return None
                m = b[i + 1]
                if m == 0xFF:
                    i += 1
                    continue
                ln = struct.unpack(">H", b[i + 2:i + 4])[0]
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", b[i + 5:i + 9])
                    return w, h
                i += 2 + ln
            return None
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            typ = b[12:16]
            if typ == b"VP8X":
                return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
            if typ == b"VP8 ":
                w, h = struct.unpack("<HH", b[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if typ == b"VP8L":
                bits = int.from_bytes(b[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except (struct.error, IndexError):
        return None
    return None


def png_chunk(typ, data):
    """Build a PNG chunk (used by the tests)."""
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
