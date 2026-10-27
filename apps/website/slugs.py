"""
Slugs: the text in product and category addresses (/products-item/<slug>,
/products-category/<slug>).

A valid slug has only Persian or Latin letters, digits, "-" and "_" (the old
admin's rule). make_slug() builds one from a title the way the old site did:
half-spaces and punctuation dropped, spaces turned into "-", "-2", "-3" for
repeats; and it also writes Persian ی/ک and drops invisible marks, which the
old site kept.

Lookups use slug_key(), so an address finds its page however it was typed or
copied: Arabic or Persian ي/ی and ك/ک, invisible marks (RLM, ZWJ), Persian
digits, percent-encoding, upper case. Stored slugs that Google already knows
are left as they are; only invalid or empty ones are rewritten (fix_slugs).
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

MAX_LENGTH = 200
VALID = re.compile(r"^[؀-ۿa-zA-Z0-9\-_]+$")

_LETTERS = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
_NOT_ALLOWED = re.compile(r"[^؀-ۿa-z0-9\-_]+")


def is_valid(slug: str) -> bool:
    return bool(slug) and len(slug) <= MAX_LENGTH and bool(VALID.match(slug))


def slug_key(text: str) -> str:
    """The comparable form of a slug or title (see module docstring)."""
    text = text or ""
    for _ in range(3):  # addresses can arrive encoded more than once
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    # Drop accents (é -> e) and format characters: RLM, LRM, ZWJ and ZWNJ (half-space).
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Mn", "Cf") or "؀" <= ch <= "ۿ")
    text = unicodedata.normalize("NFC", text).translate(_LETTERS).lower()
    text = re.sub(r"\s+", "-", text.strip())
    text = _NOT_ALLOWED.sub("", text)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    return text[:MAX_LENGTH].strip("-_")


def make_slug(title: str, taken: set[str], fallback: str = "") -> str:
    """A valid slug for title whose key is not in taken (keys); adds -2, -3, ... like the old site."""
    base = slug_key(title) or slug_key(fallback) or "product"
    slug, n = base, 1
    while slug_key(slug) in taken:
        n += 1
        slug = f"{base[:MAX_LENGTH - len(str(n)) - 1]}-{n}"
    return slug
