#!/usr/bin/env python3
"""Weibo (微博) dedicated fetcher for feeds-claw."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from feeds_common import DESKTOP_UA, MOBILE_UA, DEFAULT_TIMEOUT, persist_feed, slugify

WEIBO_API = "https://m.weibo.cn/statuses/show"
WEIBO_MOBILE_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Referer": "https://m.weibo.cn/",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}


def _weibo_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(WEIBO_MOBILE_HEADERS)
    cookie = os.environ.get("FEEDS_WEIBO_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return soup.get_text("\n", strip=True)


def _parse_created_at(raw: str) -> str:
    if not raw:
        return datetime.now().strftime("%Y-%m-%d")
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return datetime.now().strftime("%Y-%m-%d")


def extract_mid_from_url(url: str) -> str | None:
    u = url.strip()
    for pat in (
        r"m\.weibo\.cn/(?:detail|status)/(\d+)",
        r"weibo\.cn/\d+/(\w+)",
    ):
        m = re.search(pat, u, re.I)
        if m and m.group(1).isdigit():
            return m.group(1)
    return None


def extract_mid_from_html(html: str) -> str | None:
    for pat in (
        r'"mid"\s*:\s*"(\d{10,})"',
        r"status_id['\"]?\s*[:=]\s*['\"]?(\d{10,})",
        r"fid=(\d{10,})",
        r"/status/(\d{10,})",
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def resolve_weibo_mid(url: str, session: requests.Session, timeout: int) -> str | None:
    mid = extract_mid_from_url(url)
    if mid:
        return mid
    try:
        r = session.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={**WEIBO_MOBILE_HEADERS, "User-Agent": DESKTOP_UA},
        )
        r.raise_for_status()
        mid = extract_mid_from_url(r.url) or extract_mid_from_html(r.text)
        if mid:
            return mid
    except Exception:
        pass
    return None


def _pics_from_status(data: dict) -> list[str]:
    urls: list[str] = []
    pics = data.get("pics") or []
    for p in pics:
        if isinstance(p, dict):
            u = p.get("large", {}).get("url") or p.get("url") or p.get("bmiddle_pic")
            if u:
                urls.append(u if u.startswith("http") else "https:" + u)
    pic_infos = data.get("pic_infos") or {}
    if isinstance(pic_infos, dict):
        for info in pic_infos.values():
            if not isinstance(info, dict):
                continue
            large = info.get("large") or info.get("bmiddle") or {}
            u = large.get("url") if isinstance(large, dict) else None
            if u:
                urls.append(u if u.startswith("http") else "https:" + u)
    return urls


def _status_to_parsed(status: dict, source_url: str) -> dict[str, Any]:
    user = status.get("user") or {}
    screen = user.get("screen_name") or ""
    text = _html_to_text(status.get("text") or "")
    parts = [text] if text else []

    rt = status.get("retweeted_status")
    if isinstance(rt, dict):
        rt_user = (rt.get("user") or {}).get("screen_name") or ""
        rt_text = _html_to_text(rt.get("text") or "")
        if rt_text:
            parts.append(f"\n\n---\n\n**转发 @{rt_user}**\n\n{rt_text}")

    body = "\n".join(p for p in parts if p).strip()
    title = text[:80] + ("…" if len(text) > 80 else "") if text else f"微博 {status.get('id', '')}"
    return {
        "title": title or slugify(source_url),
        "author": screen,
        "account": f"@{screen}" if screen else urlparse(source_url).netloc,
        "pub_date": _parse_created_at(status.get("created_at") or ""),
        "body": body,
        "image_urls": _pics_from_status(status),
        "timeout": DEFAULT_TIMEOUT,
    }


def fetch_weibo_content(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    session = _weibo_session()
    mid = resolve_weibo_mid(url, session, timeout)
    if not mid:
        return {
            "error": "weibo_id",
            "message": "无法从链接解析微博 ID；可设置 FEEDS_WEIBO_COOKIE（浏览器 Cookie）后重试。",
            "url": url,
        }

    try:
        r = session.get(WEIBO_API, params={"id": mid}, timeout=timeout)
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:
        return {"error": "weibo_api", "message": str(exc), "mid": mid}

    if payload.get("ok") != 1:
        msg = payload.get("msg") or payload.get("message") or "API returned ok!=1"
        return {
            "error": "weibo_api",
            "message": f"{msg}（可设置 FEEDS_WEIBO_COOKIE）",
            "mid": mid,
        }

    status = payload.get("data")
    if not isinstance(status, dict):
        return {"error": "weibo_api", "message": "Empty status data", "mid": mid}

    parsed = _status_to_parsed(status, url)
    if not parsed.get("body"):
        return {"error": "no_content", "message": "微博正文为空", "mid": mid}
    return parsed


def save_weibo(
    url: str,
    vault: Path,
    tags: list[str],
    *,
    dry_run: bool = False,
    force: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    parsed = fetch_weibo_content(url, timeout=timeout)
    parsed["timeout"] = timeout
    result = persist_feed(
        parsed,
        vault=vault,
        platform="weibo",
        url=url,
        tags=tags,
        dry_run=dry_run,
        force=force,
    )
    result.setdefault("tool", "feeds-claw/fetch_weibo")
    return result
