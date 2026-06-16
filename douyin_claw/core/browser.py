import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
CHROME_ARGS = ["--disable-blink-features=AutomationControlled"]
DEFAULT_CDP_PORT = 9222
DOUYIN_HOME = "https://www.douyin.com/"


def _proxy_from_env() -> dict[str, str] | None:
    for key in (
        "HTTPS_PROXY", "https_proxy",
        "HTTP_PROXY", "http_proxy",
        "ALL_PROXY", "all_proxy",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            return {"server": val}
    return None


def _is_connection_error(msg: str) -> bool:
    markers = (
        "ERR_CONNECTION_RESET",
        "ERR_CONNECTION_REFUSED",
        "ERR_CONNECTION_CLOSED",
        "ERR_NETWORK_CHANGED",
        "ERR_INTERNET_DISCONNECTED",
        "Connection reset",
        "Connection aborted",
    )
    return any(m in msg for m in markers)


def _format_network_error(err: str) -> str:
    proxy_hint = ""
    if not _proxy_from_env():
        proxy_hint = (
            "  · 若 Chrome 能开抖音但脚本不行，多半是 Playwright 未走系统代理；"
            "可设置 export HTTPS_PROXY=http://127.0.0.1:7890（端口按 Clash 等实际为准）\n"
        )
    return (
        "无法连接 www.douyin.com（连接被重置或拒绝）。\n"
        "请确认：\n"
        "  · 本机 Chrome 能否打开 https://www.douyin.com\n"
        + proxy_hint +
        "  · 海外网络需可访问大陆的节点；国内若开全局 VPN 可尝试关闭后重试\n"
        f"  详情: {err[:240]}"
    )


def douyin_network_ok(*, timeout: float = 8.0) -> tuple[bool, str]:
    import requests

    try:
        resp = requests.get(
            DOUYIN_HOME,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            verify=False,
        )
        if resp.status_code >= 500:
            return False, f"HTTP {resp.status_code}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _playwright_cookies(parsed: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
        for k, v in parsed.items()
        if k
    ]


def _launch_browser(p, *, headless: bool = True, for_login: bool = False):
    # headless 搜索须用 Playwright 内置 Chromium（与 DouYin_Spider 一致）。
    # channel=chrome 的 headless 模式易被抖音识别，search/single 会返回 verify_check。
    if headless:
        opts: dict[str, Any] = {"headless": True, "args": list(CHROME_ARGS)}
        proxy = _proxy_from_env()
        if proxy:
            opts["proxy"] = proxy
        return p.chromium.launch(**opts)
    if for_login:
        # 登录须用户手动操作：用内置 Chromium，避免 channel=chrome 窗口偶发无法点击/输入。
        return p.chromium.launch(headless=False, args=CHROME_ARGS)
    try:
        return p.chromium.launch(
            headless=False,
            channel="chrome",
            args=CHROME_ARGS,
        )
    except Exception:
        return p.chromium.launch(headless=False, args=CHROME_ARGS)


def _launch_search_browser(p, *, headless: bool = True, channel: str | None = None):
    opts: dict[str, Any] = {"headless": headless, "args": list(CHROME_ARGS)}
    proxy = _proxy_from_env()
    if proxy:
        opts["proxy"] = proxy
    if channel:
        opts["channel"] = channel
        try:
            return p.chromium.launch(**opts)
        except Exception:
            opts.pop("channel", None)
    return p.chromium.launch(**opts)


def _launch_real_chrome(p):
    """启动本机 Google Chrome（Playwright 托管，登录场景可能无法点击）。"""
    try:
        return p.chromium.launch(
            headless=False,
            channel="chrome",
            args=CHROME_ARGS,
        )
    except Exception as exc:
        raise SystemExit(
            "未找到 Google Chrome。请安装 Chrome，或改用:\n"
            "  cslogin cookie douyin import   # 手动 F12 粘贴 Cookie"
        ) from exc


def find_chrome_executable() -> str:
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("google-chrome-stable") or "",
    ):
        if path and os.path.isfile(path):
            return path
    raise SystemExit(
        "未找到 Google Chrome。请安装 Chrome，或改用:\n"
        "  cslogin cookie douyin import"
    )


def chrome_profile_dir() -> str:
    env = os.environ.get("LLM_CLAW_ENV_PATH", "").strip()
    if env:
        return os.path.join(os.path.expanduser(env), "chrome_profile")
    return os.path.join(os.path.expanduser("~"), ".cache", "douyin_claw", "chrome_profile")


def wait_cdp_ready(port: int, *, timeout_sec: float = 30) -> None:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"Chrome 调试端口 {port} 未就绪")


def spawn_user_chrome(
    port: int = DEFAULT_CDP_PORT,
    *,
    start_url: str = DOUYIN_HOME,
) -> str:
    """用 subprocess 启动 Chrome（非 Playwright 控制），用户可正常点击/输入。"""
    chrome = find_chrome_executable()
    profile = chrome_profile_dir()
    os.makedirs(profile, exist_ok=True)

    last_err: Exception | None = None
    for attempt in range(6):
        use_port = port + attempt
        args = [
            chrome,
            f"--remote-debugging-port={use_port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            start_url,
        ]
        try:
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            wait_cdp_ready(use_port)
            return f"http://127.0.0.1:{use_port}"
        except Exception as exc:
            last_err = exc
            continue

    raise SystemExit(
        "无法启动 Chrome 调试模式。"
        f" ({last_err})\n"
        "可手动启动后连接:\n"
        f'  "{chrome}" --remote-debugging-port={port} --user-data-dir="{profile}" {start_url}\n'
        "  cslogin cookie douyin chrome --cdp "
        f"http://127.0.0.1:{port}"
    ) from last_err


def collect_cookies_over_cdp(cdp_url: str) -> dict[str, str]:
    """登录完成后连接 CDP，只读取 Cookie，不操控页面。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        try:
            if not browser.contexts:
                raise SystemExit("Chrome 无打开的标签页，请确认已打开 douyin.com")
            return collect_douyin_cookies(browser.contexts[0])
        finally:
            browser.close()


def collect_douyin_cookies(context) -> dict[str, str]:
    """从浏览器上下文读取 douyin.com Cookie（等效 DevTools Request Headers）。"""
    parts: dict[str, str] = {}
    try:
        jar = context.cookies(["https://www.douyin.com", "https://live.douyin.com"])
    except TypeError:
        jar = context.cookies()
    for item in jar:
        domain = item.get("domain") or ""
        name = item.get("name") or ""
        if not name:
            continue
        if domain and "douyin.com" not in domain:
            continue
        parts[name] = item["value"]
    return parts


def _new_browser_context(browser, *, for_login: bool = False):
    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=USER_AGENT,
        locale="zh-CN",
    )
    if for_login:
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
    return context


def _parse_search_single_payload(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\"status_code\".*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def _extract_awemes_from_search_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in data.get("data") or []:
        aweme = item.get("aweme_info", item)
        if aweme.get("aweme_id"):
            out.append(aweme)
    return out


def _search_via_playwright_once(
    cookie_str: str,
    keyword: str,
    num: int,
    *,
    headless: bool = True,
    channel: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    from playwright.sync_api import sync_playwright

    from .dy_util import trans_cookies

    parsed = trans_cookies(cookie_str)
    collected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    nil_type = ""
    search_url = f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}?type=general"

    def ingest_payload(data: dict[str, Any]) -> None:
        nonlocal nil_type
        nil = data.get("search_nil_info") or {}
        hit = nil.get("search_nil_type") or nil.get("search_nil_item")
        if hit:
            nil_type = str(hit)
        if str(data.get("status_code")) in ("2483", "8"):
            return
        for aweme in _extract_awemes_from_search_payload(data):
            aid = str(aweme.get("aweme_id") or "")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                collected.append(aweme)

    def handle_response(response) -> None:
        if "search/single" not in response.url or response.status != 200:
            return
        try:
            payload = _parse_search_single_payload(response.text())
            if payload:
                ingest_payload(payload)
        except Exception:
            pass

    with sync_playwright() as p:
        browser = _launch_search_browser(p, headless=headless, channel=channel)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        context.add_cookies(_playwright_cookies(parsed))
        page = context.new_page()
        page.on("response", handle_response)
        page.goto(DOUYIN_HOME, wait_until="domcontentloaded", timeout=60000)
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(8):
            if len(collected) >= num:
                break
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            time.sleep(2)
        page.wait_for_timeout(2000)
        browser.close()

    if collected:
        nil_type = ""
    return collected[:num], nil_type


def search_via_playwright(
    cookie_str: str, keyword: str, num: int
) -> tuple[list[dict[str, Any]], str, str]:
    """Playwright 搜索兜底。返回 (items, nil_type, error_message)。"""
    if os.environ.get("DOUYIN_CLAW_NO_PW_SEARCH"):
        return [], "", "已跳过 Playwright 搜索（DOUYIN_CLAW_NO_PW_SEARCH=1）"

    ok, net_err = douyin_network_ok()
    if not ok:
        return [], "", _format_network_error(net_err)

    strategies: list[dict[str, Any]] = [{"headless": True, "channel": None}]
    if os.environ.get("DOUYIN_CLAW_PW_VISIBLE"):
        strategies.append({"headless": False, "channel": "chrome"})

    last_err = ""
    for strat in strategies:
        try:
            items, nil = _search_via_playwright_once(
                cookie_str, keyword, num,
                headless=bool(strat["headless"]),
                channel=strat["channel"],
            )
            return items, nil, ""
        except Exception as exc:
            last_err = str(exc)
            if not _is_connection_error(last_err):
                break

    if _is_connection_error(last_err):
        return [], "", _format_network_error(last_err)
    return [], "", f"Playwright 搜索失败: {last_err[:300]}"


def wait_for_search_ready(page, keyword: str, *, timeout_sec: int = 180) -> bool:
    """Wait until browser search API returns at least one result (login verification)."""
    ready = False
    search_url = f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}?type=general"

    def handle_response(response) -> None:
        nonlocal ready
        if ready or "search/single" not in response.url or response.status != 200:
            return
        try:
            payload = _parse_search_single_payload(response.text())
            if payload and _extract_awemes_from_search_payload(payload):
                ready = True
        except Exception:
            pass

    page.on("response", handle_response)
    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if ready:
            return True
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        time.sleep(2)
    return ready


async def sync_douyin_cookies(cookie_str: str, page_url: str = "https://www.douyin.com/") -> str:
    from playwright.async_api import async_playwright

    from .dy_util import trans_cookies

    parsed = trans_cookies(cookie_str)

    async def _launch_async(p):
        return await p.chromium.launch(headless=True)

    async with async_playwright() as p:
        browser = await _launch_async(p)
        context = await browser.new_context(user_agent=USER_AGENT)
        await context.add_cookies(_playwright_cookies(parsed))
        page = await context.new_page()
        await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        cookies = await context.cookies()
        await browser.close()
    merged = {**parsed, **{c["name"]: c["value"] for c in cookies if c.get("name")}}
    return "; ".join(f"{k}={v}" for k, v in merged.items())


def prepare_session_cookies(cookie_str: str, keyword: str = "") -> str:
    import asyncio

    if keyword:
        page_url = f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}?type=general"
    else:
        page_url = "https://www.douyin.com/"
    return asyncio.run(sync_douyin_cookies(cookie_str, page_url))
