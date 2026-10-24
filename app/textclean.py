"""Headline text cleaning (SMA-694).

Feeds ship messy text: titles with raw HTML anchors (Bangladesh served
`<a href=...>` in titles because crawl_feed only cleaned summaries),
summaries with unresolved HTML entities (`&#039;`) that then get escaped
a second time on render, WordPress boilerplate ("The post ... appeared
first on ...", "Continue reading"), and summaries that merely repeat
the title. Everything stored goes through here — at crawl time in
crawler.crawl_feed, and once over existing rows at startup (db).
"""
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# WordPress cross-post boilerplate, typically the final sentence.
_APPEARED_FIRST_RE = re.compile(
    r"\s*The post .{1,300}? appeared first on .{1,120}?\.(?=\s|$)",
    re.IGNORECASE,
)
# Trailing "Continue reading ..." link text (no sentence end after it).
_CONTINUE_READING_RE = re.compile(
    r"\s*(?:\[|\(|…|\.\.\.)?\s*Continue reading\b[^.]{0,60}$",
    re.IGNORECASE,
)

SUMMARY_LIMIT = 300
TITLE_LIMIT = 500


def _base(text):
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    # A second pass catches double-encoded entities (&amp;#039;).
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def clean_title(text, limit=TITLE_LIMIT):
    return _base(text)[:limit]


def _trim_sentence(text, limit):
    """Trim to ~limit chars, preferring a sentence boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    best = max(cut.rfind(p) for p in (". ", "! ", "? ", "… "))
    if best >= limit // 2:
        return cut[: best + 1].strip()
    space = cut.rfind(" ")
    trimmed = cut[:space].rstrip() if space > 0 else cut
    return trimmed + "…"


def clean_summary(text, title="", limit=SUMMARY_LIMIT):
    text = _base(text)
    text = _APPEARED_FIRST_RE.sub("", text)
    text = _CONTINUE_READING_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    text = _trim_sentence(text, limit)
    # A summary that just repeats the headline adds nothing to the card.
    if title and text.lower() == title.strip().lower():
        return ""
    return text


# --- Dedupe keys (SMA-695) ---------------------------------------------------

_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_title(title):
    """Case/punctuation-insensitive title key for duplicate detection:
    re-posted live blogs and roundups resurface with new URLs and light
    edits to casing/punctuation, which UNIQUE(url, country) can't catch."""
    return _NON_WORD_RE.sub(" ", (title or "").lower()).strip()


def normalize_url(url):
    """Drop utm_* tracking params and the fragment so the same story
    re-posted with different tracking strings hits UNIQUE(url, country).
    Other query params are kept — some feeds use ?id= as story identity."""
    try:
        parts = urlsplit(url)
        kept = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(kept), ""))
    except Exception:
        return url


# Scripts whose titles read as unexpected languages on the world list
# (Arabic, Hebrew, Greek, Cyrillic, Devanagari, Thai, CJK, Hangul, ...).
_NON_LATIN_RE = re.compile(
    "[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF"
    "\uFB50-\uFDFF\uFE70-\uFEFF\u0370-\u03FF\u0400-\u04FF"
    "\u0900-\u097F\u0E00-\u0E7F\u3040-\u30FF\u4E00-\u9FFF"
    "\uAC00-\uD7AF]"
)


def is_non_latin(title):
    """True when the title uses a non-Latin script. The world list prefers
    Latin-script titles (SMA-695) so the homepage and hook teaser don't
    open in a script most visitors can't read; Latin-script languages
    (French, Spanish, German, ...) are unaffected."""
    return bool(_NON_LATIN_RE.search(title or ""))
