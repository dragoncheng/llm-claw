#!/usr/bin/env python3
"""
抖音视频搜索命令行工具

用法:
  python3 douyin_claw.py login
  python3 douyin_claw.py search [选项] <关键词>
  python3 douyin_claw.py video [--comments N] <链接或aweme_id>
  python3 douyin_claw.py analyze [搜索选项] [--comments-per-video N] [--task 任务] <关键词>
  python3 douyin_claw.py batch --queries ... --topic-keywords ... [选项]

Cookie 保存在 douyin_env.json（目录由 LLM_CLAW_ENV_PATH 指定）。

依赖:
  pip install -r requirements.txt
  npm install && npx playwright install chromium  # 或 playwright install chromium
"""

from __future__ import annotations

import os
import sys


def _prefer_local_venv() -> None:
    if os.environ.get("DOUYIN_CLAW_NO_VENV"):
        return
    root = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.abspath(os.path.join(root, ".venv"))
    if os.path.normpath(sys.prefix) == os.path.normpath(venv_dir):
        return
    # 已在其它 virtualenv 中，不强行切换
    if sys.base_prefix != sys.prefix:
        return
    for name in ("python3", "python"):
        venv_py = os.path.join(venv_dir, "bin", name)
        if os.path.isfile(venv_py) and os.access(venv_py, os.X_OK):
            os.execv(venv_py, [venv_py, *sys.argv])
            return


def _require_deps() -> None:
    missing: list[str] = []
    for mod, pip_name in (
        ("execjs", "PyExecJS"),
        ("requests", "requests"),
        ("playwright", "playwright"),
    ):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return
    root = os.path.dirname(os.path.abspath(__file__))
    raise SystemExit(
        "缺少 Python 依赖: "
        + ", ".join(missing)
        + "\n请执行:\n"
        f"  cd {root}\n"
        "  python3 -m venv .venv\n"
        "  .venv/bin/pip install -r requirements.txt\n"
        "  cd .. && npm install   # 在 douyin_claw 目录\n"
        "  .venv/bin/playwright install chromium\n"
        f"  .venv/bin/python {os.path.basename(__file__)} ..."
    )


_prefer_local_venv()
_require_deps()

import json
import os
import sys
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from core.batch_pipeline import run_batch_pipeline
from core.batch_util import DEFAULT_ENTERPRISE_KEYWORDS, FilterKeywords, parse_keyword_csv
from core.client import (
    DouyinClient,
    SearchOptions,
    SearchResult,
    build_analysis_input,
    format_search_failure,
)
from core.dy_util import trans_cookies

ENV_FILENAME = "douyin_env.json"
DOUYIN_HOME = "https://www.douyin.com/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def config_dir() -> str:
    env = os.environ.get("LLM_CLAW_ENV_PATH", "").strip()
    if env:
        return os.path.expanduser(env)
    return os.path.dirname(os.path.abspath(__file__))


def cookie_file_path() -> str:
    return os.path.join(config_dir(), ENV_FILENAME)


def is_logged_in_cookie(parts: dict[str, str]) -> bool:
    sessionid = (parts.get("sessionid") or "").strip()
    if len(sessionid) >= 16:
        return True
    return bool((parts.get("uid_tt") or parts.get("uid_tt_ss") or "").strip())


def save_cookie(cookie_str: str) -> str:
    parts = trans_cookies(cookie_str)
    if not is_logged_in_cookie(parts):
        raise SystemExit("Cookie 缺少有效 sessionid / uid_tt，请确认已在浏览器完成抖音登录")
    path = cookie_file_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"cookie": "; ".join(f"{k}={v}" for k, v in parts.items()),
             "saved_at": datetime.now(timezone.utc).isoformat()},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"已保存凭证到 {path}", file=sys.stderr)
    return path


def load_cookie() -> str:
    env_cookie = os.environ.get("DY_COOKIES", "").strip()
    if env_cookie and is_logged_in_cookie(trans_cookies(env_cookie)):
        return env_cookie

    path = cookie_file_path()
    if not os.path.isfile(path):
        raise SystemExit(
            f"未找到 {path}，请先执行 login（凭证目录: {config_dir()}）:\n"
            f"  python3 {os.path.basename(__file__)} login"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    cookie = str(data.get("cookie") or "").strip()
    if not cookie or not is_logged_in_cookie(trans_cookies(cookie)):
        raise SystemExit(f"{ENV_FILENAME} 中 Cookie 无效，请重新 login")
    return cookie


def _wait_user_login_done() -> bool:
    """等用户在终端确认已完成登录；期间不操控浏览器页面。"""
    if sys.stdin.isatty():
        try:
            input()
            return True
        except (EOFError, KeyboardInterrupt):
            print("已取消", file=sys.stderr)
            return False

    print("非交互终端：请在浏览器完成登录，脚本最多等待 5 分钟…", file=sys.stderr)
    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(2)
    return True


def _finalize_cookie_save(parts: dict[str, str], *, source: str) -> int:
    from core.browser import search_via_playwright

    if not is_logged_in_cookie(parts):
        print("Cookie 缺少有效 sessionid / uid_tt，请确认已在浏览器完成抖音登录", file=sys.stderr)
        return 1

    verify_keyword = os.environ.get("DOUYIN_LOGIN_VERIFY_KEYWORD", "世界杯").strip() or "世界杯"
    cookie = "; ".join(f"{k}={v}" for k, v in parts.items())
    path = save_cookie(cookie)

    print("正在探测搜索能力…", file=sys.stderr)
    test_items, _, pw_err = search_via_playwright(cookie, verify_keyword, 3)
    result = {
        "ok": True,
        "file": path,
        "source": source,
        "search_verified": bool(test_items),
        "playwright_probe_count": len(test_items),
        "has_s_v_web_id": bool(parts.get("s_v_web_id")),
    }
    if pw_err:
        result["playwright_error"] = pw_err
    if not test_items:
        if pw_err:
            print(pw_err, file=sys.stderr)
        if source == "chrome_profile":
            hint = (
                "Cookie 已保存，但搜索探测仍为 0 条。"
                "请在 Chrome 里手动搜索一次完成验证，然后重新执行:\n"
                "  cslogin cookie douyin read"
            )
        elif source == "chrome_f12":
            hint = "Cookie 已保存，但搜索探测仍为 0 条。请确认 F12 复制的 Cookie 来自已登录且能搜索的 Chrome。"
        else:
            hint = (
                "Cookie 已保存，但搜索探测仍为 0 条。"
                "请重新获取 Cookie（推荐: cslogin cookie douyin read）。"
            )
        print(hint, file=sys.stderr)
        result["warning"] = "playwright_probe_empty"
    else:
        print(f"搜索验证通过（探测到 {len(test_items)} 条）", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_login() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("login 需要: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    from core.browser import search_via_playwright, _launch_browser, _new_browser_context

    verify_keyword = os.environ.get("DOUYIN_LOGIN_VERIFY_KEYWORD", "世界杯").strip() or "世界杯"
    print("启动 Playwright Chromium 登录（备用方式，搜索 Cookie 质量可能不如 Chrome）…", file=sys.stderr)
    print("更推荐: cslogin cookie douyin  或  cookie chrome", file=sys.stderr)
    print("请在浏览器中完成登录（扫码/手机/验证码）。", file=sys.stderr)
    print(f"建议登录后手动搜索「{verify_keyword}」并完成风控验证。", file=sys.stderr)
    print("全部完成后回到此终端，按 Enter 保存 Cookie（脚本不会自动跳转或滚动页面）…", file=sys.stderr)

    with sync_playwright() as p:
        browser = _launch_browser(p, headless=False, for_login=True)
        context = _new_browser_context(browser, for_login=True)
        page = context.new_page()
        page.goto(DOUYIN_HOME, wait_until="domcontentloaded", timeout=60000)

        if not _wait_user_login_done():
            browser.close()
            return 1

        parts = {c["name"]: c["value"] for c in context.cookies() if c.get("name")}
        browser.close()

    return _finalize_cookie_save(parts, source="playwright_login")


def _read_cookie_import_source(argv: list[str]) -> str:
    if not argv:
        print(
            "请粘贴 Chrome 登录 www.douyin.com 后、F12 → Network → 任意请求 → Request Headers 里的 Cookie。\n"
            "粘贴完成后按 Enter，再按 Ctrl-D（Mac）结束输入：",
            file=sys.stderr,
        )
        return sys.stdin.read().strip()

    if argv[0] == "--file" and len(argv) >= 2:
        with open(os.path.expanduser(argv[1]), encoding="utf-8") as f:
            raw = f.read().strip()
    elif argv[0] == "--env" and len(argv) >= 2:
        with open(os.path.expanduser(argv[1]), encoding="utf-8") as f:
            raw = f.read()
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("DY_COOKIES="):
                raw = line.split("=", 1)[1].strip().strip("'\"")
                break
        else:
            raise SystemExit("未在 .env 中找到 DY_COOKIES=")
    else:
        raw = " ".join(argv).strip()

    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()
    return raw


def _open_douyin_in_chrome() -> None:
    """在本机 Google Chrome 打开抖音（非 Playwright，用户完全自控）。"""
    if sys.platform == "darwin":
        subprocess.run(["open", "-a", "Google Chrome", DOUYIN_HOME], check=False)
    elif sys.platform.startswith("linux"):
        for cmd in (
            ["google-chrome", DOUYIN_HOME],
            ["google-chrome-stable", DOUYIN_HOME],
            ["chromium-browser", DOUYIN_HOME],
            ["xdg-open", DOUYIN_HOME],
        ):
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.run(cmd, check=False)
                return
        print(f"请手动在 Chrome 打开: {DOUYIN_HOME}", file=sys.stderr)
    else:
        print(f"请手动在 Chrome 打开: {DOUYIN_HOME}", file=sys.stderr)


def _open_douyin_in_system_browser() -> None:
    _open_douyin_in_chrome()


def _read_clipboard_cookie() -> str:
    if sys.platform != "darwin":
        return ""
    try:
        proc = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
        text = (proc.stdout or "").strip()
    except Exception:
        return ""
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    if ("sessionid=" in text or "sid_tt=" in text) and len(text) > 40:
        return text
    return ""


def cmd_cookie_guide(argv: list[str]) -> int:
    verify_keyword = os.environ.get("DOUYIN_LOGIN_VERIFY_KEYWORD", "世界杯").strip() or "世界杯"

    print("", file=sys.stderr)
    print("抖音 Cookie 获取（DouYin_Spider 同款：你自己的 Chrome + F12）", file=sys.stderr)
    print("脚本不会启动或控制任何浏览器窗口。", file=sys.stderr)
    print("", file=sys.stderr)
    _open_douyin_in_system_browser()
    print("已在系统默认浏览器打开抖音。", file=sys.stderr)
    print("", file=sys.stderr)
    print("请完成以下步骤：", file=sys.stderr)
    print(f"  1. 在 Chrome 登录 {DOUYIN_HOME}", file=sys.stderr)
    print(f"  2. 建议搜索「{verify_keyword}」并完成验证", file=sys.stderr)
    print("  3. F12 → Network（网络）→ 刷新页面", file=sys.stderr)
    print("  4. 点击任意请求 → Headers → Request Headers → 复制 Cookie", file=sys.stderr)
    print("  5. 复制后回到此终端", file=sys.stderr)
    print("", file=sys.stderr)
    print("按 Enter 继续（Mac 将自动从剪贴板读取 Cookie）…", file=sys.stderr)

    if not _wait_user_login_done():
        return 1

    cookie_str = _read_clipboard_cookie()
    if cookie_str:
        print("已从剪贴板读取 Cookie。", file=sys.stderr)
    else:
        print(
            "剪贴板中未检测到 Cookie，请粘贴 F12 复制的 Cookie，"
            "完成后按 Enter，再按 Ctrl-D 结束：",
            file=sys.stderr,
        )
        cookie_str = sys.stdin.read().strip()
        if cookie_str.lower().startswith("cookie:"):
            cookie_str = cookie_str.split(":", 1)[1].strip()

    if not cookie_str:
        raise SystemExit("Cookie 为空")
    return _finalize_cookie_save(trans_cookies(cookie_str), source="chrome_f12")


def cmd_cookie_read(argv: list[str]) -> int:
    from core.chrome_cookies import list_chrome_profiles, read_douyin_cookies

    profile = os.environ.get("CHROME_PROFILE", "Default").strip() or "Default"
    quick = False
    i = 0
    while i < len(argv):
        if argv[i] == "--profile" and i + 1 < len(argv):
            profile = argv[i + 1].strip()
            i += 2
            continue
        if argv[i] == "--list-profiles":
            profiles = list_chrome_profiles()
            print(json.dumps({"profiles": profiles}, ensure_ascii=False))
            return 0
        if argv[i] == "--quick":
            quick = True
            i += 1
            continue
        raise SystemExit(
            f"未知参数: {argv[i]}（可用: --profile NAME | --list-profiles | --quick）"
        )

    verify_keyword = os.environ.get("DOUYIN_LOGIN_VERIFY_KEYWORD", "世界杯").strip() or "世界杯"

    if not quick:
        print("", file=sys.stderr)
        print("抖音 Cookie 获取：Chrome 登录 + 搜索验证 + 自动读取", file=sys.stderr)
        print("脚本不会控制浏览器，仅在你按 Enter 后读取 Chrome 配置中的 Cookie。", file=sys.stderr)
        print("", file=sys.stderr)
        _open_douyin_in_chrome()
        print(f"已在 Google Chrome 打开 {DOUYIN_HOME}", file=sys.stderr)
        print("", file=sys.stderr)
        print("请在本机 Chrome 中完成：", file=sys.stderr)
        print("  1. 登录抖音", file=sys.stderr)
        print(f"  2. 搜索「{verify_keyword}」并完成二次验证，直到能看到搜索结果", file=sys.stderr)
        print("  3. 回到此终端按 Enter，自动读取 Cookie 并保存", file=sys.stderr)
        print("", file=sys.stderr)
        if not _wait_user_login_done():
            return 1

    print(f"从 Chrome profile「{profile}」读取 douyin.com Cookie…", file=sys.stderr)
    parts = read_douyin_cookies(profile)
    if not parts:
        profiles = list_chrome_profiles()
        raise SystemExit(
            f"未读到 douyin.com Cookie。请确认已在 Chrome（profile: {profile}）"
            f"登录并完成搜索验证后再按 Enter。\n"
            f"可用 profile: {', '.join(profiles) or '无'}"
        )
    print(f"读到 {len(parts)} 个 Cookie 字段", file=sys.stderr)
    return _finalize_cookie_save(parts, source="chrome_profile")


def cmd_cookie_chrome(argv: list[str]) -> int:
    from core.browser import DEFAULT_CDP_PORT, collect_cookies_over_cdp, spawn_user_chrome

    print(
        "警告: CDP/调试模式 Chrome 可能被抖音限制交互。"
        "若无法点击，请改用: cslogin cookie douyin",
        file=sys.stderr,
    )

    cdp_url = os.environ.get("DOUYIN_CDP_URL", "").strip()
    cdp_port = int(os.environ.get("DOUYIN_CDP_PORT", str(DEFAULT_CDP_PORT)))
    i = 0
    while i < len(argv):
        if argv[i] == "--cdp" and i + 1 < len(argv):
            cdp_url = argv[i + 1].strip().rstrip("/")
            i += 2
            continue
        if argv[i] == "--port" and i + 1 < len(argv):
            cdp_port = int(argv[i + 1])
            i += 2
            continue
        raise SystemExit(f"未知参数: {argv[i]}（可用: --cdp URL | --port N）")

    verify_keyword = os.environ.get("DOUYIN_LOGIN_VERIFY_KEYWORD", "世界杯").strip() or "世界杯"

    if not cdp_url:
        print("正在启动 Chrome（系统进程，非 Playwright 控制，可正常点击/输入）…", file=sys.stderr)
        print(f"1) 在打开的 Chrome 窗口登录 {DOUYIN_HOME}", file=sys.stderr)
        print(f"2) 建议手动搜索「{verify_keyword}」并完成验证", file=sys.stderr)
        print("3) 完成后回到终端按 Enter — 将自动读取 Cookie", file=sys.stderr)
        cdp_url = spawn_user_chrome(cdp_port)
        print(f"Chrome 已启动（CDP: {cdp_url}）", file=sys.stderr)
    else:
        print(f"请先在 Chrome（{cdp_url}）中登录 {DOUYIN_HOME}", file=sys.stderr)
        print("完成后回到终端按 Enter …", file=sys.stderr)

    if not _wait_user_login_done():
        return 1

    print("正在读取 Cookie…", file=sys.stderr)
    parts = collect_cookies_over_cdp(cdp_url)
    return _finalize_cookie_save(parts, source="chrome")


def cmd_cookie(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(
            "用法:\n"
            f"  python3 {os.path.basename(__file__)} cookie read [--profile Default]  # Chrome 登录+搜索后按 Enter 读取\n"
            f"  python3 {os.path.basename(__file__)} cookie read --quick           # 跳过引导，直接读 profile\n"
            f"  python3 {os.path.basename(__file__)} cookie              # F12 引导\n"
            f"  python3 {os.path.basename(__file__)} cookie import [--env PATH]\n"
            f"  python3 {os.path.basename(__file__)} cookie chrome [--port N]\n"
            "\n"
            "推荐 cookie read：读取本机 Chrome 配置中的 Cookie，Chrome 可保持打开。",
            file=sys.stderr,
        )
        return 0
    if not argv:
        return cmd_cookie_read([])

    sub = argv[0].lower()
    if sub == "read":
        return cmd_cookie_read(argv[1:])
    if sub in ("guide", "f12"):
        return cmd_cookie_guide(argv[1:])
    if sub == "chrome":
        return cmd_cookie_chrome(argv[1:])
    if sub == "import":
        return _cmd_cookie_import(argv[1:])
    raise SystemExit(f"未知子命令: {sub}（可用: cookie read | cookie import | cookie chrome）")


def _cmd_cookie_import(argv: list[str]) -> int:
    cookie_str = _read_cookie_import_source(argv)
    if not cookie_str:
        raise SystemExit("Cookie 为空")
    parts = trans_cookies(cookie_str)
    return _finalize_cookie_save(parts, source="chrome_import")


def normalize_video_url(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if __import__("re").fullmatch(r"\d+", s):
        return f"https://www.douyin.com/video/{s}"
    if s.startswith("http"):
        return s
    raise SystemExit("请提供抖音视频链接或 aweme_id")


def parse_search_argv(argv: list[str]) -> SearchOptions:
    num, sort_type, publish_time = 20, "0", "0"
    filter_duration, search_range, content_type = "", "0", "0"
    keyword_parts: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--num":
            num = int(argv[i + 1]); i += 2; continue
        if arg == "--sort":
            sort_type = argv[i + 1].strip(); i += 2; continue
        if arg == "--publish-time":
            publish_time = argv[i + 1].strip(); i += 2; continue
        if arg == "--filter-duration":
            filter_duration = argv[i + 1].strip(); i += 2; continue
        if arg == "--search-range":
            search_range = argv[i + 1].strip(); i += 2; continue
        if arg == "--content-type":
            content_type = argv[i + 1].strip(); i += 2; continue
        if arg.startswith("--"):
            raise SystemExit(f"未知参数: {arg}")
        keyword_parts.append(arg)
        i += 1
    keyword = " ".join(keyword_parts).strip()
    if not keyword:
        raise SystemExit("请提供搜索关键词")
    if not 1 <= num <= 100:
        raise SystemExit("--num 范围 1-100")
    return SearchOptions(keyword, num, sort_type, publish_time, filter_duration, search_range, content_type)


def search_result_payload(result: SearchResult, opts: SearchOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "keyword": opts.keyword,
        "options": vars(opts),
        "search_method": result.method,
        "count": len(result.videos),
        "videos": result.videos,
    }
    if result.nil_type:
        payload["search_nil_type"] = result.nil_type
    if result.raw_count:
        payload["raw_count"] = result.raw_count
        payload["filtered_out"] = result.filtered_out
    if not result.videos:
        message = format_search_failure(result, opts.keyword)
        payload["error"] = message.split("\n", 1)[0]
        print(message, file=sys.stderr)
    return payload


def cmd_search(argv: list[str]) -> int:
    opts = parse_search_argv(argv)
    client = DouyinClient(load_cookie())
    result = client.search(opts)
    print(json.dumps(search_result_payload(result, opts), ensure_ascii=False, indent=2))
    if not result.videos and result.nil_type == "verify_check":
        return 1
    return 0


def cmd_video(argv: list[str]) -> int:
    max_comments = 30
    url_parts: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--comments":
            max_comments = int(argv[i + 1]); i += 2; continue
        url_parts.append(argv[i]); i += 1
    if not url_parts:
        raise SystemExit("请提供视频链接或 aweme_id")
    url = normalize_video_url(" ".join(url_parts))
    bundle = DouyinClient(load_cookie()).video_detail(url, max_comments)
    print(json.dumps(bundle, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(argv: list[str]) -> int:
    max_comments = 20
    task = "请根据视频描述与评论，总结主题、关键信息、舆论倾向与可行动建议。"
    search_argv: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--comments-per-video":
            max_comments = int(argv[i + 1]); i += 2; continue
        if argv[i] == "--task":
            task = argv[i + 1]; i += 2; continue
        search_argv.append(argv[i]); i += 1
    opts = parse_search_argv(search_argv)
    cookie_str = load_cookie()
    client = DouyinClient(cookie_str)
    result = client.search(opts)
    if not result.videos:
        raise SystemExit(format_search_failure(result, opts.keyword))
    videos = result.videos
    bundles: list[dict[str, Any]] = []
    for i, v in enumerate(videos, 1):
        url = v.get("share_url") or ""
        print(f"拉取详情与评论 [{i}/{len(videos)}] {url}", file=sys.stderr)
        try:
            bundle = client.video_detail(url, max_comments)
            bundle["search_snapshot"] = v
            bundles.append(bundle)
        except Exception as e:
            bundles.append({
                "video": v,
                "description": v.get("desc") or "",
                "comments": [],
                "error": str(e),
                "analysis_input": build_analysis_input(v, v.get("desc") or "", []),
            })
        time.sleep(0.5)
    combined = "\n\n---\n\n".join(b["analysis_input"] for b in bundles if b.get("analysis_input"))
    analysis_prompt = f"【分析任务】{task}\n\n【数据】共 {len(bundles)} 条视频\n\n{combined}"
    print(json.dumps({
        "keyword": opts.keyword,
        "search_method": result.method,
        "task": task,
        "video_count": len(bundles),
        "videos": bundles,
        "analysis_prompt": analysis_prompt,
        "next_step": "将 analysis_prompt 交给 LLM 完成深度分析；画面/口播需对 video_url 做 ASR 后追加",
    }, ensure_ascii=False, indent=2))
    return 0


def _collect_flag_values(argv: list[str], start: int) -> tuple[list[str], int]:
    values: list[str] = []
    i = start
    while i < len(argv) and not argv[i].startswith('--'):
        values.append(argv[i])
        i += 1
    return values, i


def parse_batch_argv(argv: list[str]) -> dict[str, Any]:
    months = 3.0
    per_query = 35
    comments_per_video = 0
    task = ''
    report_name = 'douyin_batch'
    queries: list[str] = []
    topic_keywords: tuple[str, ...] = ()
    enterprise_keywords: tuple[str, ...] = DEFAULT_ENTERPRISE_KEYWORDS

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '--months':
            months = float(argv[i + 1]); i += 2; continue
        if arg == '--per-query':
            per_query = int(argv[i + 1]); i += 2; continue
        if arg == '--comments-per-video':
            comments_per_video = int(argv[i + 1]); i += 2; continue
        if arg == '--task':
            task = argv[i + 1]; i += 2; continue
        if arg == '--name':
            report_name = argv[i + 1]; i += 2; continue
        if arg == '--queries':
            queries, i = _collect_flag_values(argv, i + 1); continue
        if arg == '--topic-keywords':
            topic_keywords = parse_keyword_csv(argv[i + 1]); i += 2; continue
        if arg == '--enterprise-keywords':
            enterprise_keywords = parse_keyword_csv(argv[i + 1]); i += 2; continue
        raise SystemExit(f'未知参数: {arg}')

    if not queries:
        raise SystemExit(
            'batch 须指定 --queries（一个或多个搜索词）。\n'
            '示例见 llm-claw/douyin_claw/SKILL.md'
        )
    if not topic_keywords:
        raise SystemExit(
            'batch 须指定 --topic-keywords（逗号分隔的主题过滤词）。\n'
            '示例见 llm-claw/douyin_claw/SKILL.md'
        )

    return {
        'months': months,
        'per_query': per_query,
        'comments_per_video': comments_per_video,
        'task': task,
        'report_name': report_name,
        'queries': queries,
        'filter_keywords': FilterKeywords(topic=topic_keywords, enterprise=enterprise_keywords),
    }


def cmd_batch(argv: list[str]) -> int:
    opts = parse_batch_argv(argv)
    client = DouyinClient(load_cookie())
    result = run_batch_pipeline(client, **opts)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


USAGE = f"""用法:
  python3 {os.path.basename(__file__)} cookie read [--profile Default]  # 从已打开 Chrome 自动读
  python3 {os.path.basename(__file__)} cookie              # F12 引导
  python3 {os.path.basename(__file__)} login               # 备用
  python3 {os.path.basename(__file__)} search [选项] <关键词>
  python3 {os.path.basename(__file__)} video [--comments N] <链接或aweme_id>
  python3 {os.path.basename(__file__)} analyze [搜索选项] [--comments-per-video N] [--task 任务] <关键词>
  python3 {os.path.basename(__file__)} batch --queries <词1> [词2 ...] --topic-keywords <逗号分隔> [选项]

batch：多关键词搜索、主题过滤、去重合并；返回 JSON 供 Agent/LLM 继续分析（见 SKILL.md）。

安装:
  pip install -r requirements.txt
  npm install
  playwright install chromium

凭证: {ENV_FILENAME}（目录: {config_dir()}）
环境: LLM_CLAW_ENV_PATH 可覆盖凭证目录
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE.strip())
        return 0
    cmd = args[0].lower()
    if cmd == "login":
        return cmd_login()
    if cmd == "cookie":
        return cmd_cookie(args[1:])
    if cmd == "search":
        if len(args) < 2:
            raise SystemExit("缺少参数: 关键词")
        return cmd_search(args[1:])
    if cmd == "video":
        if len(args) < 2:
            raise SystemExit("缺少参数: 视频链接或 aweme_id")
        return cmd_video(args[1:])
    if cmd == "analyze":
        if len(args) < 2:
            raise SystemExit("缺少参数: 关键词")
        return cmd_analyze(args[1:])
    if cmd == "batch":
        return cmd_batch(args[1:])
    raise SystemExit(f"未知命令: {cmd}\n\n{USAGE}")


if __name__ == "__main__":
    sys.exit(main())
