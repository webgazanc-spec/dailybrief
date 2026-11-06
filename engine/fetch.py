"""Сбор новостей из RSS/Atom-лент.

Принципиально берём ТОЛЬКО то, что издатель сам отдаёт в ленте для
распространения: заголовок, короткое описание, ссылку, дату.
Полные статьи со страниц издателей НЕ скачиваются — это и юридически
чище, и в разы легче по трафику.
"""
from __future__ import annotations

import hashlib
import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "NewsDigestBot/1.0 (RSS reader; respects publisher feeds)"
TIMEOUT = 20

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def item_id(link: str) -> str:
    return hashlib.sha1(link.strip().encode("utf-8")).hexdigest()[:12]


def _parse_date(value: str | None) -> datetime:
    if value:
        value = value.strip()
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(el: ET.Element, *names: str) -> str | None:
    for child in el:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text
    return None


def parse_feed(xml_bytes: bytes, source: dict) -> list[dict]:
    """Разбирает RSS 2.0 / RSS 1.0 / Atom. Возвращает список сырых записей."""
    root = ET.fromstring(xml_bytes)
    entries = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    out = []
    for el in entries:
        title = clean_text(_child_text(el, "title"))
        link = None
        for child in el:
            if _local(child.tag) == "link":
                href = child.get("href")
                rel = child.get("rel", "alternate")
                if href and rel == "alternate":
                    link = href
                    break
                if (child.text or "").strip():
                    link = child.text.strip()
                    break
        if not link:
            guid = _child_text(el, "guid", "id")
            if guid and guid.startswith("http"):
                link = guid.strip()
        if not title or not link:
            continue
        desc = clean_text(_child_text(el, "description", "summary", "content", "encoded"))
        published = _parse_date(_child_text(el, "pubdate", "published", "updated", "date"))
        out.append({
            "id": item_id(link),
            "source_name": source["name"],
            "source_url": link,
            "source_title": title,
            "source_desc": desc[:1500],
            "category": source.get("category", "world"),
            "published": published.isoformat(),
        })
    return out


def fetch_source(source: dict, state: dict) -> list[dict]:
    """Скачивает ленту с условным GET (ETag / Last-Modified) — не грузим
    повторно то, что не менялось. state меняется на месте."""
    url = source["url"]
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    st = state.get(url, {})
    if st.get("etag"):
        headers["If-None-Match"] = st["etag"]
    if st.get("modified"):
        headers["If-Modified-Since"] = st["modified"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(5_000_000)
            state[url] = {
                "etag": resp.headers.get("ETag"),
                "modified": resp.headers.get("Last-Modified"),
            }
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return []
        print(f"  ! {source['name']}: HTTP {e.code}")
        return []
    except Exception as e:  # сеть, таймаут, DNS
        print(f"  ! {source['name']}: {e}")
        return []
    try:
        return parse_feed(body, source)
    except ET.ParseError as e:
        print(f"  ! {source['name']}: не удалось разобрать ленту ({e})")
        return []
