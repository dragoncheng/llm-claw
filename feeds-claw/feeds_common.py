#!/usr/bin/env python3
"""Shared helpers for feeds-claw platform savers."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

MYDOC_FEEDS = "14_feeds"
DEFAULT_TIMEOUT = 25
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKC", text or "feed").strip()
    text = re.sub(r'[\\/:*?"<>|]', "-", text)
    text = re.sub(r"\s+", " ", text).strip()
    return (text or "feed")[:max_len].rstrip("- ")


def safe_filename(text: str, max_len: int = 80) -> str:
    return f"{slugify(text, max_len)}.md"


def yaml_quote(value: str) -> str:
    value = (value or "").replace('"', '\\"')
    if not value:
        return '""'
    if re.search(r"[:#\[\]{}|>&*!?,]", value):
        return f'"{value}"'
    return value


def build_markdown(
    *,
    platform: str,
    title: str,
    author: str,
    account: str,
    pub_date: str,
    fetched: str,
    url: str,
    tags: list[str],
    body: str,
) -> str:
    tag_set = ["feeds", platform]
    for t in tags:
        t = t.strip()
        if t and t not in tag_set:
            tag_set.append(t)
    lines = [
        "---",
        f"source: {platform}",
        f"platform: {platform}",
        f"account: {yaml_quote(account)}",
        f"author: {yaml_quote(author)}",
        f"published: {pub_date}",
        f"url: {yaml_quote(url)}",
        f"fetched: {fetched}",
        f"tags: [{', '.join(tag_set)}]",
        f"created: {fetched}",
        "---",
        "",
        f"# {title}",
        "",
        "## 元信息",
        "",
        f"- **平台**：{platform}",
        f"- **账号/来源**：{account or author or '—'}",
        f"- **原文链接**：{url}",
        f"- **抓取日期**：{fetched}",
        "",
        "## 正文",
        "",
        body.strip() or "（未能提取正文）",
        "",
    ]
    return "\n".join(lines)


def download_image(session: requests.Session, url: str, dest: Path, timeout: int) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        resp = session.get(url, timeout=timeout, headers={"User-Agent": MOBILE_UA, "Referer": url})
        if resp.status_code != 200 or not resp.content:
            return False
        ctype = (resp.headers.get("content-type") or "").lower()
        if "png" in ctype:
            dest = dest.with_suffix(".png")
        elif "gif" in ctype:
            dest = dest.with_suffix(".gif")
        elif "webp" in ctype:
            dest = dest.with_suffix(".webp")
        elif dest.suffix not in {".jpg", ".jpeg"}:
            dest = dest.with_suffix(".jpg")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return True
    except Exception:
        return False


def append_images_to_body(
    body: str,
    image_urls: list[str],
    *,
    session: requests.Session,
    assets_dir: Path,
    vault: Path,
    timeout: int,
    dry_run: bool,
) -> tuple[str, int]:
    if not image_urls:
        return body, 0
    parts = [body.rstrip(), ""]
    count = 0
    for i, url in enumerate(image_urls, 1):
        if not url or not url.startswith("http"):
            continue
        if dry_run:
            parts.append(f"\n![image-{i}]({url})\n")
            count += 1
            continue
        dest = assets_dir / f"{i:02d}.jpg"
        if download_image(session, url, dest, timeout):
            rel = dest.relative_to(vault).as_posix()
            parts.append(f"\n![[{rel}]]\n")
            count += 1
    return "\n".join(parts).strip() + "\n", count


def persist_feed(
    parsed: dict[str, Any],
    *,
    vault: Path,
    platform: str,
    url: str,
    tags: list[str],
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    if parsed.get("error"):
        parsed.setdefault("platform", platform)
        parsed.setdefault("url", url)
        return parsed

    title = parsed.get("title") or slugify(url)
    year = datetime.now().strftime("%Y")
    fetched = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(title)
    md_dir = vault / "01_mydoc" / MYDOC_FEEDS / year
    md_path = md_dir / safe_filename(title)
    if md_path.exists() and not force and not dry_run:
        md_path = md_dir / f"{md_path.stem}-{datetime.now().strftime('%H%M%S')}.md"

    assets_dir = vault / "_assets" / "images" / MYDOC_FEEDS / platform / slug
    body = parsed.get("body", "")
    session = requests.Session()
    body, img_n = append_images_to_body(
        body,
        parsed.get("image_urls") or [],
        session=session,
        assets_dir=assets_dir,
        vault=vault,
        timeout=parsed.get("timeout", DEFAULT_TIMEOUT),
        dry_run=dry_run,
    )

    md_text = build_markdown(
        platform=platform,
        title=title,
        author=parsed.get("author", ""),
        account=parsed.get("account", ""),
        pub_date=parsed.get("pub_date", fetched),
        fetched=fetched,
        url=url,
        tags=tags,
        body=body,
    )
    rel = str(md_path.relative_to(vault))
    result = {
        "platform": platform,
        "title": title,
        "source_url": url,
        "md_path": rel,
        "assets_dir": str(assets_dir.relative_to(vault)) if img_n else "",
        "images": img_n,
        "chars": len(body),
        "dry_run": dry_run,
    }
    if dry_run:
        return result
    md_dir.mkdir(parents=True, exist_ok=True)
    if img_n:
        assets_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_text, encoding="utf-8")
    return result
