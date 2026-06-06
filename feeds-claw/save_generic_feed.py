#!/usr/bin/env python3
"""Save Twitter / generic HTML feeds to 01_mydoc/14_feeds/."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from feeds_common import DEFAULT_TIMEOUT, DESKTOP_UA, persist_feed, slugify

PLATFORM_TWITTER = "twitter"


def fetch_twitter(url: str, timeout: int) -> dict:
    path = _twitter_status_path(url)
    if not path:
        return {"error": "twitter_parse", "message": "Not a single-tweet URL."}
    api = f"https://api.fxtwitter.com{path}"
    try:
        r = requests.get(api, timeout=timeout, headers={"User-Agent": DESKTOP_UA})
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return {"error": "twitter_fetch", "message": str(exc)}
    tweet = (data.get("tweet") or {}) if isinstance(data, dict) else {}
    text = tweet.get("text") or tweet.get("content") or ""
    author = (tweet.get("author") or {}).get("name") or ""
    handle = (tweet.get("author") or {}).get("screen_name") or ""
    title = f"@{handle}: {text[:60]}..." if handle and len(text) > 60 else (text[:80] or "Twitter post")
    created = tweet.get("created_at") or ""
    pub_date = datetime.now().strftime("%Y-%m-%d")
    if isinstance(created, str):
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", created)
        if m:
            pub_date = m.group(1)
    body = text
    image_urls: list[str] = []
    media = tweet.get("media") or {}
    photos = media.get("photos") or media.get("all") or []
    for ph in photos:
        u = ph.get("url") if isinstance(ph, dict) else str(ph)
        if u:
            image_urls.append(u)
    return {
        "title": title.strip() or "Twitter",
        "author": author,
        "account": f"@{handle}" if handle else "",
        "pub_date": pub_date,
        "body": body.strip(),
        "image_urls": image_urls,
    }


def _twitter_status_path(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().replace("www.", "")
    if host not in ("twitter.com", "x.com", "mobile.twitter.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 3 and parts[-2] == "status" and parts[-1].isdigit():
        return "/" + "/".join(parts[-3:])
    if len(parts) == 3 and parts[0] == "i" and parts[1] == "status" and parts[2].isdigit():
        return "/" + "/".join(parts)
    return None


def fetch_html(url: str, timeout: int) -> dict:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": DESKTOP_UA}, allow_redirects=True)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        html = r.text
    except Exception as exc:
        return {"error": "http_fetch", "message": str(exc)}
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "title"})
    if og and og.get("content"):
        title = og["content"].strip()
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    author = ""
    au = soup.find("meta", attrs={"name": "author"})
    if au and au.get("content"):
        author = au["content"].strip()
    for tag in soup(["script", "style", "nav", "footer", "header", "iframe"]):
        tag.decompose()
    main = (
        soup.find("article")
        or soup.find(id=re.compile(r"content|article|main", re.I))
        or soup.find(class_=re.compile(r"content|article", re.I))
        or soup.body
    )
    body = main.get_text("\n", strip=True) if main else ""
    body = re.sub(r"\n{3,}", "\n\n", body)
    if len(body) < 80:
        return {
            "error": "no_content",
            "message": "Page needs login or JS render. Try: baoyu-url-to-markdown (CDP) or Web Clipper.",
        }
    return {
        "title": title or slugify(urlparse(url).path),
        "author": author,
        "account": urlparse(url).netloc,
        "pub_date": datetime.now().strftime("%Y-%m-%d"),
        "body": body[:50000],
        "image_urls": [],
    }


def save_generic(
    url: str,
    vault: Path,
    platform: str,
    tags: list[str],
    *,
    dry_run: bool = False,
    force: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    if platform == PLATFORM_TWITTER:
        parsed = fetch_twitter(url, timeout)
    else:
        parsed = fetch_html(url, timeout)

    parsed["timeout"] = timeout
    result = persist_feed(
        parsed,
        vault=vault,
        platform=platform if platform != "generic" else "web",
        url=url,
        tags=tags,
        dry_run=dry_run,
        force=force,
    )
    result.setdefault("tool", f"feeds-claw/save_generic ({platform})")
    return result
