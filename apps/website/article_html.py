"""
What a blog article's HTML may contain.

Articles come from the admin's editor or from an article package (a zip with
article.html and its photos, adminapi/blog_package.py). Either way the stored
HTML keeps only structure: headings, paragraphs, lists, links, photos, tables,
note boxes, an FAQ and product placeholders. Inline styles, scripts and classes
outside the list below are dropped, so every article looks like the site
(the storefront's blog stylesheet) and not like whatever the writer pasted.

    <div data-product="..."></div>        one product card
    <div data-products="..., ..."></div>  a row of product cards
    <aside class="note|tip|warning">      a box
    <a class="button" href="...">          a button link
    <p class="lead">                      the opening paragraph
    <section class="faq"> <details><summary>question</summary> answer </details> ... </section>

clean() is what is stored; prepare() is what the site shows (heading ids, the
table of contents, the FAQ, responsive photos and lazy loading).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, Tag
from django.conf import settings

from . import images

ALLOWED = {
    "p", "h2", "h3", "h4", "strong", "em", "a", "ul", "ol", "li", "blockquote", "figure", "figcaption", "img",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "hr", "br", "aside", "details", "summary",
    "section", "div", "mark", "small", "sub", "sup", "cite", "q", "abbr", "code",
}
RENAMED = {"b": "strong", "i": "em", "h1": "h2", "h5": "h4", "h6": "h4"}
# Removed with everything inside; any other tag is unwrapped (its text stays).
REMOVED = {
    "script", "style", "iframe", "object", "embed", "form", "input", "button", "select", "textarea", "noscript",
    "svg", "canvas", "video", "audio", "source", "link", "meta", "title", "head", "template",
}
ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "ol": {"start"},
    "abbr": {"title"},
    "h2": {"id"}, "h3": {"id"}, "h4": {"id"},
    "div": {"data-product", "data-products"},
}
CLASSES = {
    "a": {"button"},
    "aside": {"note", "tip", "warning"},
    "p": {"lead"},
    "section": {"faq"},
}
SAFE_HREF = re.compile(r"(?i)^(https?://|mailto:|tel:|/|#)")
SAFE_SRC = re.compile(r"(?i)^(https?://|/|data:image/(png|jpe?g|webp|gif);)")
ANCHOR = re.compile(r"^[^\s\"'<>#]{1,80}$")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def _clean_tag(tag: Tag) -> None:
    name = RENAMED.get(tag.name, tag.name)
    tag.name = name
    keep = ATTRIBUTES.get(name, set())
    classes = [c for c in tag.get("class") or [] if c in CLASSES.get(name, set())]
    tag.attrs = {k: v for k, v in tag.attrs.items() if k in keep}
    if classes:
        tag["class"] = classes
    if name == "a":
        href = images.strip_domain((tag.get("href") or "").strip())
        if href and SAFE_HREF.match(href):
            tag["href"] = href
        else:
            tag.attrs.pop("href", None)
    elif name == "img":
        src = images.strip_domain((tag.get("src") or "").strip())
        if src and SAFE_SRC.match(src):
            tag["src"] = src
        else:
            tag.attrs.pop("src", None)
        for dim in ("width", "height"):
            if not str(tag.get(dim, "")).isdigit():
                tag.attrs.pop(dim, None)
    elif name in ("h2", "h3", "h4") and not ANCHOR.match(tag.get("id") or ""):
        tag.attrs.pop("id", None)


def _is_empty(tag: Tag) -> bool:
    return not tag.get_text(strip=True) and not tag.find(["img", "br", "hr", "div"])


def clean(html: str) -> str:
    """The article as stored: allowed tags and attributes only."""
    soup = _soup(html)
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for tag in soup.find_all(list(REMOVED)):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED and tag.name not in RENAMED:
            tag.unwrap()
            continue
        _clean_tag(tag)
        if tag.name == "a" and not tag.get("href"):
            tag.unwrap()
        elif tag.name == "img" and not tag.get("src"):
            tag.decompose()
        elif tag.name == "div" and not (tag.get("data-product") or tag.get("data-products")):
            tag.unwrap()
        elif tag.name == "div":
            tag.clear()
    for tag in soup.find_all(["p", "li", "h2", "h3", "h4", "strong", "em", "aside", "blockquote", "figure"]):
        if tag.parent is not None and _is_empty(tag):
            tag.decompose()
    return _tidy(str(soup))


def _tidy(html: str) -> str:
    html = re.sub(r"[ \t]*\n\s*\n+", "\n", html)
    return html.replace("\xa0", " ").strip()


# -----------------------------------------------------------------------------
# What the site shows
# -----------------------------------------------------------------------------
IMG_WIDTHS = (384, 640, 828, 1080)
# The article column is at most 760 CSS px wide (storefront blog stylesheet).
IMG_SIZES = "(max-width: 820px) 100vw, 760px"


@dataclass
class Prepared:
    html: str
    toc: list[dict] = field(default_factory=list)
    faq: list[dict] = field(default_factory=list)
    words: int = 0


def product_refs(html: str) -> list[str]:
    """Every product reference in the placeholders, in order."""
    out: list[str] = []
    for div in _soup(html).find_all("div"):
        out += split_refs(div.get("data-product") or "") + split_refs(div.get("data-products") or "")
    return out


def split_refs(value: str) -> list[str]:
    return [r.strip() for r in re.split(r"[,،\n]", value or "") if r.strip()]


def anchor(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^\w\-]+", "-", text.strip().lower()).strip("-")[:60] or "section"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    taken.add(out)
    return out


def responsive(src: str) -> dict:
    """src/srcset for a stored image path; built images (/img/...) come in several widths."""
    url = images.site_media_url(src)
    if not src.startswith(f"{settings.PUBLIC_IMG_PATH}/"):
        return {"src": url}
    return {
        "src": f"{url}?w=828",
        "srcset": ", ".join(f"{url}?w={w} {w}w" for w in IMG_WIDTHS),
        "sizes": IMG_SIZES,
    }


def prepare(html: str, render_products) -> Prepared:
    """
    The article for the page. render_products(refs, single) returns the card markup
    for the placeholders (storefront/blog.py), or "" when none of them is on sale.
    """
    soup = _soup(clean(html))
    taken: set[str] = set()
    toc = []
    for h in soup.find_all(["h2", "h3"]):
        h["id"] = h.get("id") if h.get("id") and h["id"] not in taken else anchor(h.get_text(" ", strip=True), taken)
        taken.add(h["id"])
        toc.append({"id": h["id"], "text": h.get_text(" ", strip=True), "level": int(h.name[1])})

    for img in soup.find_all("img"):
        img.attrs.update(responsive(img["src"]))
        img["loading"], img["decoding"] = "lazy", "async"
        img["alt"] = img.get("alt") or ""

    for a in soup.find_all("a", href=True):
        if a["href"].startswith(("http://", "https://")):
            a["target"], a["rel"] = "_blank", "noopener"

    for table in soup.find_all("table"):
        wrap = soup.new_tag("div", attrs={"class": "table-wrap"})
        table.wrap(wrap)

    for div in soup.find_all("div", attrs={"data-product": True}) + soup.find_all("div", attrs={"data-products": True}):
        single = div.has_attr("data-product")
        markup = render_products(split_refs(div.get("data-product") or div.get("data-products")), single)
        if markup:
            div.replace_with(BeautifulSoup(markup, "html.parser"))
        else:
            div.decompose()

    faq = []
    for section in soup.find_all("section", class_="faq"):
        for d in section.find_all("details"):
            summary = d.find("summary")
            if not summary:
                continue
            question = summary.get_text(" ", strip=True)
            answer = " ".join(t.strip() for t in d.find_all(string=True) if t.find_parent("summary") is None and t.strip())
            if question and answer:
                faq.append({"question": question, "answer": answer})

    words = len(soup.get_text(" ", strip=True).split())
    return Prepared(html=str(soup), toc=toc, faq=faq, words=words)


def plain_text(html: str) -> str:
    return " ".join(_soup(html).get_text(" ", strip=True).split())
