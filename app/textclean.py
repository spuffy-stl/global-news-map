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
