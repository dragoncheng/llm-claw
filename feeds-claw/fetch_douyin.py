#!/usr/bin/env python3
"""Douyin (抖音) dedicated fetcher for feeds-claw."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

from feeds_common import MOBILE_UA, DEFAULT_TIMEOUT, persist_feed, slugify

IES_SHARE = "https://www.iesdouyin.com/share/video/{aweme_id}/"
NOTE_SHARE = "https://www.iesdouyin.com/share/note/{note_id}/"


def _douyin_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": MOBILE_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    cookie = os.environ.get("FEEDS_DOUYIN_COOKIE", "").strip()
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def resolve_aweme_id(url: str, session: requests.Session, timeout: int) -> tuple[str, str]:
    """Return (kind, id) where kind is video|note."""
    u = url.strip()
    if not u.startswith("http"):
        u = "https://" + u

    m = re.search(r"/video/(\d+)", u)
    if m:
        return "video", m.group(1)
    m = re.search(r"/note/(\d+)", u)
    if m:
        return "note", m.group(1)
    m = re.search(r"modal_id=(\d+)", u)
    if m:
        return "video", m.group(1)

    try:
        r = session.get(u, timeout=timeout, allow_redirects=True)
        final = r.url
        m = re.search(r"/video/(\d+)", final) or re.search(r"/note/(\d+)", final)
        if m:
            kind = "note" if "/note/" in final else "video"
            return kind, m.group(1)
        m = re.search(r'"awemeId"\s*:\s*"(\d+)"', r.text) or re.search(r'"itemId"\s*:\s*"(\d+)"', r.text)
        if m:
            return "video", m.group(1)
    except Exception:
        pass
    return "", ""


def _find_item_list(obj: Any) -> list[dict]:
    if isinstance(obj, dict):
        il = obj.get("item_list")
        if isinstance(il, list) and il and isinstance(il[0], dict) and il[0].get("desc") is not None:
            return il
        if isinstance(il, list) and il and isinstance(il[0], dict):
            return il
        for v in obj.values():
            found = _find_item_list(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_item_list(v)
            if found:
                return found
    return []


def _parse_router_data(html: str) -> dict | None:
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _item_to_parsed(item: dict, source_url: str) -> dict[str, Any]:
    author = item.get("author") or {}
    nickname = author.get("nickname") or author.get("unique_id") or ""
    desc = (item.get("desc") or item.get("title") or "").strip()
    title = desc[:80] + ("…" if len(desc) > 80 else "") if desc else f"抖音 {item.get('aweme_id', '')}"

    body_parts = [desc] if desc else []
    stats = []
    for k, label in (("digg_count", "赞"), ("comment_count", "评论"), ("share_count", "分享")):
        if item.get(k) is not None:
            stats.append(f"{label} {item[k]}")
    if stats:
        body_parts.append("\n".join(f"- {s}" for s in stats))

    video = item.get("video") or {}
    play = video.get("play_addr") or {}
    urls = play.get("url_list") or []
    if urls:
        play_url = urls[0].replace("playwm", "play")
        body_parts.append(f"\n[视频播放链接]({play_url})")

    image_urls: list[str] = []
    images = item.get("images") or []
    if isinstance(images, list):
        for im in images:
            if isinstance(im, dict):
                u = None
                url_list = im.get("url_list") or []
                if url_list:
                    u = url_list[0]
                elif im.get("uri"):
                    u = im.get("uri")
                if u and str(u).startswith("http"):
                    image_urls.append(str(u))
    cover = (video.get("cover") or {}).get("url_list") or []
    if cover and cover[0].startswith("http"):
        image_urls.insert(0, cover[0])

    music = item.get("music") or {}
    if music.get("title"):
        body_parts.append(f"\n**BGM**：{music.get('title')}")

    return {
        "title": title or slugify(source_url),
        "author": nickname,
        "account": f"@{author.get('unique_id')}" if author.get("unique_id") else nickname,
        "pub_date": datetime.now().strftime("%Y-%m-%d"),
        "body": "\n\n".join(body_parts).strip(),
        "image_urls": image_urls,
    }


def _fetch_via_iesdouyin(aweme_id: str, kind: str, session: requests.Session, timeout: int) -> dict[str, Any]:
    share_url = NOTE_SHARE.format(note_id=aweme_id) if kind == "note" else IES_SHARE.format(aweme_id=aweme_id)
    r = session.get(share_url, timeout=timeout)
    r.raise_for_status()
    router = _parse_router_data(r.text)
    if router:
        items = _find_item_list(router)
        if items:
            return _item_to_parsed(items[0], share_url)

    soup = BeautifulSoup(r.text, "html.parser")
    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    title = (og_title.get("content") if og_title else "") or f"抖音 {aweme_id}"
    desc = (og_desc.get("content") if og_desc else "") or ""
    if desc and "来抖音，记录美好生活" in desc and len(desc) < 60:
        desc = ""

    filter_msg = ""
    if router:
        vinfo = router.get("loaderData", {})
        for v in vinfo.values() if isinstance(vinfo, dict) else []:
            if isinstance(v, dict):
                res = v.get("videoInfoRes") or {}
                fl = res.get("filter_list") or []
                if fl and isinstance(fl[0], dict):
                    filter_msg = fl[0].get("filter_reason") or ""

    if not desc and filter_msg:
        return {
            "error": "douyin_unavailable",
            "message": f"视频不可用（{filter_msg}）。链接可能已删除或需登录；可设置 FEEDS_DOUYIN_COOKIE 或使用 yt-dlp。",
            "aweme_id": aweme_id,
        }

    body = desc or f"（仅获取到页面摘要）\n\n原文：[{share_url}]({share_url})"
    return {
        "title": title[:80],
        "author": "",
        "account": "douyin",
        "pub_date": datetime.now().strftime("%Y-%m-%d"),
        "body": body,
        "image_urls": [],
    }


def _fetch_via_ytdlp(url: str, timeout: int) -> dict[str, Any] | None:
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return None
    try:
        proc = subprocess.run(
            [
                ytdlp,
                "--no-download",
                "--print",
                "%(title)s\n%(uploader)s\n%(description)s\n%(webpage_url)s",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=min(timeout * 2, 120),
        )
        if proc.returncode != 0:
            return None
        lines = proc.stdout.strip().split("\n", 3)
        if len(lines) < 4:
            return None
        title, uploader, desc, page_url = lines[0], lines[1], lines[2], lines[3]
        body = (desc or "").strip()
        if page_url:
            body += f"\n\n[原页]({page_url})"
        return {
            "title": title or slugify(url),
            "author": uploader,
            "account": uploader,
            "pub_date": datetime.now().strftime("%Y-%m-%d"),
            "body": body or title,
            "image_urls": [],
        }
    except Exception:
        return None


def fetch_douyin_content(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    session = _douyin_session()
    kind, aweme_id = resolve_aweme_id(url, session, timeout)
    if not aweme_id:
        ytdlp_parsed = _fetch_via_ytdlp(url, timeout)
        if ytdlp_parsed:
            return ytdlp_parsed
        return {
            "error": "douyin_id",
            "message": "无法解析抖音视频/笔记 ID；请使用完整分享链接（v.douyin.com 或 iesdouyin.com）。",
            "url": url,
        }

    parsed = _fetch_via_iesdouyin(aweme_id, kind or "video", session, timeout)
    if parsed.get("error"):
        ytdlp_parsed = _fetch_via_ytdlp(url, timeout)
        if ytdlp_parsed:
            return ytdlp_parsed
    return parsed


def save_douyin(
    url: str,
    vault: Path,
    tags: list[str],
    *,
    dry_run: bool = False,
    force: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    parsed = fetch_douyin_content(url, timeout=timeout)
    parsed["timeout"] = timeout
    result = persist_feed(
        parsed,
        vault=vault,
        platform="douyin",
        url=url,
        tags=tags,
        dry_run=dry_run,
        force=force,
    )
    result.setdefault("tool", "feeds-claw/fetch_douyin")
    return result
