#!/usr/bin/env python3
"""
Weibo QR login via Playwright.

Usage:
    python3 weibo_qr_login_playwright.py

Steps:
1. Opens https://login.sina.com.cn/QRcode?entry=sso in a headless-ish browser
2. User scans the QR code with Weibo app and taps "确认登录"
3. On success: extracts SUB / SUBP cookies from all domains
4. Writes WEIBO_COOKIE=SUB=...; SUBP=... to /home/btri/.hermes/hermes-agent/.env
"""

import re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERMES_ENV = Path("/home/btri/.hermes/hermes-agent/.env")
#QR_URL     = "https://login.sina.com.cn/QRcode?entry=sso"
QR_URL     = "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog&disp=popup&url=https%3A%2F%2Fweibo.com%2Fnewlogin%3Ftabtype%3Dweibo%26gid%3D102803%26openLoginLayer%3D0%26url%3Dhttps%3A%2F%2Fweibo.com%2F&from=weibopro"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

def load_env():
    env = {}
    if HERMES_ENV.exists():
        for line in HERMES_ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env

def save_env(key, value):
    env = load_env()
    env[key] = value
    HERMES_ENV.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    print(f"[+] Wrote {key} to {HERMES_ENV}")

def cookie_str_from_context(context):
    """Extract SUB / SUBP from all browser contexts and return 'name=value; ...' string."""
    names = {"SUB", "SUBP"}
    parts = []
    for page in context.pages:
        for cookie in context.cookies(page.url if page.url else []):
            if cookie["name"] in names:
                parts.append(f"{cookie['name']}={cookie['value']}")
    # Also try to get from all known Weibo domains if not found above
    if not parts:
        for cookie in context.cookies([
            "https://weibo.com", "https://login.sina.com.cn",
            "https://m.weibo.cn", "https://www.weibo.com",
        ]):
            if cookie["name"] in names:
                parts.append(f"{cookie['name']}={cookie['value']}")
    parts.sort()
    return "; ".join(parts)

def wait_for_login(context) -> bool:
    """Poll until SUB cookie appears (login success), or return False on timeout."""
    for i in range(200):          # 200 × 3 s = 10 min
        for page in context.pages:
            try:
                cookies = context.cookies([
                    "https://weibo.com", "https://login.sina.com.cn",
                    "https://m.weibo.cn", "https://www.weibo.com",
                ])
                sub  = next((c["value"] for c in cookies if c["name"] == "SUB"),  "")
                subp = next((c["value"] for c in cookies if c["name"] == "SUBP"), "")
                if sub and subp:
                    print(f"\n[+] Logged in!  SUB={sub[:20]}...  SUBP={subp[:20]}...")
                    return True
            except Exception:
                pass
        print(f"  [{i:3d}] waiting for scan... ({i*3}s)", end="\r")
        import time; time.sleep(3)
    return False

def main():
    print("[*] Launching browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,          # visible so user can see the page
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        context = browser.new_context(user_agent=UA)
        page    = context.new_page()

        # Detect QR code loaded
        page.on("response", lambda r: print(f"  → {r.status} {r.url[:60]}") if "qrcode" in r.url.lower() or "captcha" in r.url.lower() else None)

        print(f"[*] Navigating to {QR_URL}")
        page.goto(QR_URL, timeout=30000, wait_until="networkidle")
        print(f"[*] Page title: {page.title()}")
        print("[*] Waiting for you to scan the QR code with Weibo app...")

        if not wait_for_login(context):
            print("\n[-] Timeout — please run the script again.")
            sys.exit(1)

        # Extract and save
        cookie_str = cookie_str_from_context(context)
        if not cookie_str:
            print("[-] Could not find SUB/SUBP cookies")
            sys.exit(1)
        
        print(cookie_str)
        save_env("WEIBO_COOKIE", cookie_str)
        print(f"[+] Cookie written: {cookie_str[:60]}...")
        print("[+] Done! You can now use the Weibo MCP / last30days-cn weibo channel.")

        browser.close()

if __name__ == "__main__":
    main()
