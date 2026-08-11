"""Shared RSS/Atom parsing helpers.

Extracted from ``india_news`` so the Google News fetcher can reuse the same
feed parsing rather than carrying a second, subtly-different copy. Only pure
parsing and formatting live here — each caller keeps its own network fetch so
it can cache and mock independently.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional

_TAG_RE = re.compile(r"<[^>]+>")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36 TradingAgents/0.2"
    ),
    "Accept": "application/rss+xml,application/xml,text/xml,*/*",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_of(parent: ET.Element, child_name: str) -> str:
    for child in parent:
        if local_name(child.tag) == child_name:
            return (child.text or "").strip()
    return ""


def parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def clean_summary(value: str) -> str:
    cleaned = html.unescape(_TAG_RE.sub("", value or "")).replace("\n", " ").strip()
    return re.sub(r"\s+", " ", cleaned)


def article_from_rss_item(item: ET.Element, source: str) -> dict:
    return {
        "title": text_of(item, "title") or "No title",
        "summary": clean_summary(text_of(item, "description") or text_of(item, "summary")),
        "link": text_of(item, "link"),
        "published": parse_date(text_of(item, "pubDate") or text_of(item, "published")),
        "source": source,
    }


def article_from_atom_entry(entry: ET.Element, source: str) -> dict:
    link = ""
    for child in entry:
        if local_name(child.tag) == "link":
            link = child.attrib.get("href", "")
            if link:
                break
    return {
        "title": text_of(entry, "title") or "No title",
        "summary": clean_summary(text_of(entry, "summary") or text_of(entry, "content")),
        "link": link,
        "published": parse_date(text_of(entry, "updated") or text_of(entry, "published")),
        "source": source,
    }


def parse_feed(xml_text: str, source: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    if root.tag.endswith("rss"):
        return [article_from_rss_item(item, source) for item in root.findall(".//item")]

    entries = [el for el in root.iter() if local_name(el.tag) == "entry"]
    return [article_from_atom_entry(entry, source) for entry in entries]


def sort_articles(articles: Iterable[dict]) -> list[dict]:
    def sort_key(item: dict) -> float:
        published = item.get("published")
        return published.timestamp() if published is not None else 0.0

    return sorted(articles, key=sort_key, reverse=True)


def dedupe_articles(articles: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for article in articles:
        key = (article.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


def format_articles(articles: list[dict], heading: str, *, empty: str) -> str:
    if not articles:
        return empty

    lines = [f"## {heading}"]
    for article in articles:
        title = article.get("title", "No title")
        source = article.get("source", "Unknown")
        published = article.get("published")
        date_part = published.strftime("%Y-%m-%d") if published else "date unknown"
        lines.append(f"### {title} (source: {source}, {date_part})")
        summary = article.get("summary", "")
        if summary:
            lines.append(summary[:500])
        link = article.get("link", "")
        if link:
            lines.append(f"Link: {link}")
        lines.append("")
    return "\n".join(lines).strip()
