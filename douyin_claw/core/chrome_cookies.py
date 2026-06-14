"""从本机已打开的 Chrome 用户配置读取 Cookie（读磁盘 SQLite + 系统密钥链解密）。"""

from __future__ import annotations

import os
import sys
from typing import Iterator


def chrome_user_data_dir() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    if sys.platform.startswith("linux"):
        return os.path.expanduser("~/.config/google-chrome")
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        return os.path.join(local, "Google", "Chrome", "User Data")
    raise SystemExit(f"不支持的平台: {sys.platform}")


def chrome_cookies_file(profile: str = "Default") -> str:
    base = chrome_user_data_dir()
    return os.path.join(base, profile, "Cookies")


def list_chrome_profiles() -> list[str]:
    base = chrome_user_data_dir()
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if os.path.isfile(chrome_cookies_file(name)):
            out.append(name)
    return out


def _iter_browser_cookies(profile: str) -> Iterator:
    import subprocess
    from functools import partial

    path = chrome_cookies_file(profile)
    if not os.path.isfile(path):
        profiles = list_chrome_profiles()
        hint = f"可用 profile: {', '.join(profiles)}" if profiles else "未找到 Chrome 配置目录"
        raise SystemExit(f"Chrome Cookie 文件不存在: {path}\n{hint}")

    # dy_util 会 monkey-patch subprocess.Popen(encoding=utf-8)，导致 Cryptodome 导入失败
    patched_popen = subprocess.Popen
    if isinstance(patched_popen, partial):
        subprocess.Popen = patched_popen.func
    try:
        try:
            import browser_cookie3
        except ImportError as exc:
            raise SystemExit(
                "需要安装 browser-cookie3:\n"
                "  pip install browser-cookie3"
            ) from exc
        yield from browser_cookie3.chrome(cookie_file=path)
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(
            f"读取 Chrome Cookie 失败: {exc}\n"
            "Mac 可能需在 系统设置 → 隐私与安全性 中授予终端「完全磁盘访问权限」。"
        ) from exc
    finally:
        subprocess.Popen = patched_popen


def read_douyin_cookies(profile: str = "Default") -> dict[str, str]:
    """从指定 Chrome profile 读取 douyin.com 相关 Cookie。"""
    parts: dict[str, str] = {}
    for item in _iter_browser_cookies(profile):
        domain = item.domain or ""
        if "douyin.com" not in domain:
            continue
        parts[item.name] = item.value
    return parts
