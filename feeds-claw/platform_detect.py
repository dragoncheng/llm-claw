#!/usr/bin/env python3
"""Detect social/feed platform from URL."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

PLATFORM_WECHAT = "wechat"
PLATFORM_WEIBO = "weibo"
PLATFORM_TWITTER = "twitter"
PLATFORM_DOUYIN = "douyin"
PLATFORM_GENERIC = "generic"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (PLATFORM_WECHAT, re.compile(r"(^|\.)mp\.weixin\.qq\.com$|weixin\.qq\.com", re.I)),
    (PLATFORM_WEIBO, re.compile(r"(^|\.)weibo\.(com|cn)$", re.I)),
    (PLATFORM_TWITTER, re.compile(r"(^|\.)?(twitter\.com|x\.com)$", re.I)),
    (PLATFORM_DOUYIN, re.compile(r"(^|\.)?(douyin\.com|iesdouyin\.com|v\.douyin\.com)$", re.I)),
]


@dataclass(frozen=True)
class PlatformInfo:
    platform: str
    host: str
    url: str


def detect_platform(url: str) -> PlatformInfo:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for name, pattern in _PATTERNS:
        if pattern.search(host):
            return PlatformInfo(platform=name, host=host, url=url)
    return PlatformInfo(platform=PLATFORM_GENERIC, host=host, url=url)


def tool_for_platform(platform: str) -> str:
    return {
        PLATFORM_WECHAT: "feeds-claw/fetch_wechat",
        PLATFORM_WEIBO: "feeds-claw/fetch_weibo",
        PLATFORM_TWITTER: "feeds-claw (FxTwitter API)",
        PLATFORM_DOUYIN: "feeds-claw/fetch_douyin",
        PLATFORM_GENERIC: "feeds-claw (generic HTML)",
    }.get(platform, "feeds-claw")
