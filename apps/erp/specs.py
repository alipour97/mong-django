"""The product's spec table (جنس، فصل کالا، قواره، گروه قد، سبک), as each sales software states it.

A connector stores the specs in Product.attributes under these labels; the product page shows them in this order,
and LEBAZAI's AI profile fills what the software leaves out (catalog.product_specs).

Dadehfa keeps them in three places of its Products table, with the old site's labels shifted by one:
ShortDesc is "#سبک\\n regular#فصل\\n 4052#گروه\\n casual (روزمره)#رده سني\\n …#قواره\\n Short", where «سبک» is
the fit, «گروه» the style and «قواره» the length; ProductStyleTitle repeats the fit and ProductSeasonTitle the
season. The season is the collection code: the year, then the collection (4052 = 1405, پاییز و زمستان).
"""

from __future__ import annotations

import re
from urllib.parse import unquote

MATERIAL, SEASON, FIT, LENGTH, STYLE = "جنس", "فصل کالا", "قواره", "گروه قد", "سبک"
ORDER = (MATERIAL, SEASON, FIT, LENGTH, STYLE)

SPRING_SUMMER, AUTUMN_WINTER, NOWRUZ, ALL_SEASONS = "بهار و تابستان", "پاییز و زمستان", "نوروز", "چهارفصل"
# The collection digit of the season code, Mong's rule: 1 spring-summer, 2 autumn-winter, 3 Nowruz, 4 all-season.
_SEASON_DIGIT = {"1": SPRING_SUMMER, "2": AUTUMN_WINTER, "3": NOWRUZ, "4": ALL_SEASONS}

_FIT = {
    "regular": "رگولار", "loose": "آزاد", "straight": "راسته", "baggy": "بگی", "over": "اورسایز",
    "oversize": "اورسایز", "mom style": "مام استایل", "mom": "مام استایل", "slim fit": "اسلیم فیت",
    "slim": "اسلیم", "fit": "فیت", "wide": "واید (گشاد)", "bootcut": "بوت‌کات", "closh": "کلوش",
    "pleated": "پلیسه", "a- line": "A لاین", "a-line": "A لاین", "skinny": "اسکینی",
}
_LENGTH = {
    "short": "کوتاه", "medium": "متوسط", "regular": "متوسط", "long": "بلند", "crop": "کراپ", "cropped": "کراپ",
    "maxi": "ماکسی (خیلی بلند)",
}
_STYLE = {
    "casual": "کژوال (روزمره)", "trend": "ترند (مزونی)", "party wear": "مجلسی", "formal": "فرمال (رسمی)",
    "basic": "بیسیک",
}

_ARABIC = str.maketrans({"ي": "ی", "ك": "ک"})
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").translate(_ARABIC)).strip()


def _english_key(value: str) -> str:
    """«casual (روزمره)» -> "casual"; «formal(رسمي)» -> "formal"."""
    return _clean(value).split("(")[0].strip().lower()


def season(value) -> str:
    """A season code (4052, 983) or a season already in words."""
    text = _clean(value).translate(_PERSIAN_DIGITS)
    if not text:
        return ""
    if text.isdigit():
        return _SEASON_DIGIT.get(text[-1], "")
    return text


def fit(value) -> str:
    text = _clean(value)
    return _FIT.get(text.lower(), text) if text else ""


def length(value) -> str:
    text = _clean(value)
    return _LENGTH.get(text.lower(), text) if text else ""


def style(value) -> str:
    text = _clean(value)
    return _STYLE.get(_english_key(text), text) if text else ""


def from_short_desc(short_desc: str) -> dict[str, str]:
    """Dadehfa's ShortDesc, read with the labels the values really carry."""
    raw = {}
    for chunk in (short_desc or "").split("%23"):
        label, _, value = chunk.partition("%0a%20")
        label, value = _clean(unquote(label)), _clean(unquote(value))
        if label and value:
            raw[label] = value
    return {SEASON: season(raw.get("فصل")), FIT: fit(raw.get("سبک")), LENGTH: length(raw.get("قواره")),
            STYLE: style(raw.get("گروه"))}


def dadehfa(short_desc: str, season_title: str, style_title: str) -> dict[str, str]:
    specs = from_short_desc(short_desc)
    specs[SEASON] = season(season_title) or specs[SEASON]
    specs[FIT] = fit(style_title) or specs[FIT]
    return clean(specs)


def clean(specs: dict) -> dict[str, str]:
    """Only the known labels with a value, in the table's order."""
    return {label: specs[label] for label in ORDER if specs.get(label)}
