#!/usr/bin/env python3
"""
Auto-detect platform and save feed content to my-wiki:
  01_mydoc/14_feeds/{year}/{title}.md

Routes:
  wechat  → fetch_wechat.py
  weibo   → fetch_weibo.py
  douyin  → fetch_douyin.py
  twitter → save_generic_feed (FxTwitter)
  generic → save_generic_feed (HTML)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from fetch_douyin import save_douyin
from fetch_weibo import save_weibo
from fetch_wechat import save_wechat
from platform_detect import PlatformInfo, detect_platform, tool_for_platform
from save_generic_feed import save_generic


def save_feed(
    url: str,
    vault: Path,
    tags: list[str],
    *,
    platform_hint: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    timeout: int = 25,
) -> dict:
    info: PlatformInfo = detect_platform(url)
    platform = platform_hint or info.platform
    if platform_hint and platform_hint != info.platform:
        info = PlatformInfo(platform=platform_hint, host=info.host, url=info.url)

    if platform == "wechat":
        result = save_wechat(url, vault, tags, dry_run=dry_run, force=force, timeout=timeout)
    elif platform == "weibo":
        result = save_weibo(url, vault, tags, dry_run=dry_run, force=force, timeout=timeout)
    elif platform == "douyin":
        result = save_douyin(url, vault, tags, dry_run=dry_run, force=force, timeout=timeout)
    else:
        result = save_generic(
            info.url,
            vault,
            platform,
            tags,
            dry_run=dry_run,
            force=force,
            timeout=timeout,
        )

    result.setdefault("detected_platform", info.platform)
    result.setdefault("tool", tool_for_platform(platform))
    return result


def main() -> int:
    cli = argparse.ArgumentParser(description="Save feed URL to my-wiki 01_mydoc/14_feeds/")
    cli.add_argument("url", help="Article URL (WeChat, Weibo, X/Twitter, Douyin, …)")
    cli.add_argument("--vault", default=os.environ.get("CSLOGIN_WIKI_PATH", ""))
    cli.add_argument("--platform", default="", help="Force platform: wechat|weibo|twitter|douyin|generic")
    cli.add_argument("--tag", action="append", default=[], dest="tags")
    cli.add_argument("--dry-run", action="store_true")
    cli.add_argument("--force", action="store_true")
    cli.add_argument("--timeout", type=int, default=25)
    args = cli.parse_args()

    vault = Path(args.vault).expanduser() if args.vault else None
    if not vault or not vault.is_dir():
        print(
            json.dumps(
                {"error": "vault_not_found", "message": "Set --vault or CSLOGIN_WIKI_PATH"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    info = detect_platform(args.url)
    platform = args.platform.strip() or info.platform
    print(f"Platform: {platform} (tool: {tool_for_platform(platform)})", file=sys.stderr)

    result = save_feed(
        args.url,
        vault,
        args.tags,
        platform_hint=args.platform.strip() or None,
        dry_run=args.dry_run,
        force=args.force,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("error"):
        return 1
    if not args.dry_run and result.get("md_path"):
        print(f"\nNext: ingest {result['md_path']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
