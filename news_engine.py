"""
news_engine.py
==============
Section 5 data source. Aggregates macro/geopolitical headlines from:

  1. NewsAPI (newsapi.org) when NEWS_API_KEY is set — primary aggregator.
  2. Public RSS feeds (config.RSS_FEEDS) via feedparser — fallback / supplement.
  3. A small built-in sample feed so the alert engine has something to score
     when the machine is offline or no key is configured.

Returns a normalised list of dicts: {title, summary, source, url, published}.
The alert_engine consumes this list; this module does NO scoring itself —
separation of concerns keeps both testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

import config

try:
    import feedparser
    _HAS_FEEDPARSER = True
except Exception:
    _HAS_FEEDPARSER = False


def _from_newsapi(query: str, page_size: int = 40) -> list[dict]:
    if not config.NEWS_API_KEY:
        return []
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": page_size,
                "from": (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat(),
                "apiKey": config.NEWS_API_KEY,
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        out = []
        for a in r.json().get("articles", []):
            out.append({
                "title": a.get("title") or "",
                "summary": a.get("description") or "",
                "source": (a.get("source") or {}).get("name", "NewsAPI"),
                "url": a.get("url", ""),
                "published": a.get("publishedAt", ""),
            })
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[news_engine] NewsAPI failed: {exc}")
        return []


def _from_rss() -> list[dict]:
    if not _HAS_FEEDPARSER:
        return []
    out = []
    for name, url in config.RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                out.append({
                    "title": getattr(e, "title", ""),
                    "summary": getattr(e, "summary", "") or getattr(e, "description", ""),
                    "source": name,
                    "url": getattr(e, "link", ""),
                    "published": getattr(e, "published", ""),
                })
        except Exception as exc:  # noqa: BLE001
            print(f"[news_engine] RSS failed for {name}: {exc}")
    return out


_SAMPLE = [
    {"title": "Fed officials signal patience as core inflation stays sticky",
     "summary": "Policymakers indicated rates would stay restrictive until disinflation is durable.",
     "source": "Sample", "url": "", "published": ""},
    {"title": "Oil prices spike on Middle East supply concerns",
     "summary": "Brent jumped amid fears of supply disruption and regional conflict.",
     "source": "Sample", "url": "", "published": ""},
    {"title": "Rupee under pressure as dollar strengthens on yields",
     "summary": "INR weakened past key levels as US Treasury yields rose.",
     "source": "Sample", "url": "", "published": ""},
    {"title": "India PMI signals continued manufacturing expansion",
     "summary": "Activity remained firmly in expansion territory above 55.",
     "source": "Sample", "url": "", "published": ""},
    {"title": "Credit spreads widen modestly on growth concerns",
     "summary": "Corporate spreads ticked up as investors trimmed risk.",
     "source": "Sample", "url": "", "published": ""},
]


def fetch_headlines() -> list[dict]:
    """Aggregate, de-duplicate by title, and return the headline pool."""
    items: list[dict] = []
    items += _from_newsapi("(India OR Fed OR RBI OR inflation OR recession OR war OR sanctions)")
    items += _from_rss()
    if not items:                      # fully offline / no keys
        items = list(_SAMPLE)

    seen, deduped = set(), []
    for it in items:
        t = (it.get("title") or "").strip().lower()
        if t and t not in seen:
            seen.add(t)
            deduped.append(it)
    return deduped
