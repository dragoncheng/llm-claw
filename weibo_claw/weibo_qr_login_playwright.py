#!/usr/bin/env python3
"""
微博扫码登录，提取 Cookie 并保存到 weibo_env.json。

用法:
    python3 weibo_qr_login_playwright.py

凭证路径: $LLM_CLAW_ENV_PATH/weibo_env.json（未设置 LLM_CLAW_ENV_PATH 时用本脚本目录）

依赖:
    pip install playwright && playwright install chromium
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ENV_FILENAME = "weibo_env.json"
QR_URL = (
    "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog&disp=popup"
    "&url=https%3A%2F%2Fweibo.com%2Fnewlogin%3Ftabtype%3Dweibo%26gid%3D102803%26openLoginLayer%3D0"
    "%26url%3Dhttps%3A%2F%2Fweibo.com%2F&from=weibopro"
)
WEIBO_DOMAINS = [
    "https://weibo.com",
    "https://login.sina.com.cn",
    "https://m.weibo.cn",
    "https://www.weibo.com",
]
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)


def config_dir() -> Path:
    env = os.environ.get("LLM_CLAW_ENV_PATH", "").strip()
    if env:
        return Path(os.path.expanduser(env))
    return Path(__file__).resolve().parent


def env_file_path() -> Path:
    return config_dir() / ENV_FILENAME


def save_weibo_env(cookie: str) -> Path:
    path = env_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cookie": cookie,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_weibo_env() -> dict:
    path = env_file_path()
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def cookie_str_from_context(context) -> str:
    names = {"SUB", "SUBP"}
    found: dict[str, str] = {}
    for cookie in context.cookies(WEIBO_DOMAINS):
        if cookie["name"] in names:
            found[cookie["name"]] = cookie["value"]
    return "; ".join(f"{k}={found[k]}" for k in sorted(found))


def wait_for_login(context) -> bool:
    for i in range(200):
        try:
            cookies = context.cookies(WEIBO_DOMAINS)
            sub = next((c["value"] for c in cookies if c["name"] == "SUB"), "")
            subp = next((c["value"] for c in cookies if c["name"] == "SUBP"), "")
            if sub and subp:
                print(f"\n[+] Logged in!  SUB={sub[:20]}...  SUBP={subp[:20]}...")
                return True
        except Exception:
            pass
        print(f"  [{i:3d}] waiting for scan... ({i * 3}s)", end="\r")
        time.sleep(3)
    return False


def main() -> int:
    print(f"[*] Credential file: {env_file_path()}")
    print("[*] Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(user_agent=UA)
        page = context.new_page()

        page.on(
            "response",
            lambda r: print(f"  → {r.status} {r.url[:60]}")
            if "qrcode" in r.url.lower() or "captcha" in r.url.lower()
            else None,
        )

        print(f"[*] Navigating to login page")
        page.goto(QR_URL, timeout=30000, wait_until="networkidle")
        print(f"[*] Page title: {page.title()}")
        print("[*] Waiting for you to scan the QR code with Weibo app...")

        if not wait_for_login(context):
            print("\n[-] Timeout — please run the script again.")
            return 1

        cookie_str = cookie_str_from_context(context)
        if not cookie_str or "SUB=" not in cookie_str:
            print("[-] Could not find SUB/SUBP cookies")
            return 1

        path = save_weibo_env(cookie_str)
        print(f"[+] Saved cookie to {path}")
        print(f"[+] Cookie preview: {cookie_str[:60]}...")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
