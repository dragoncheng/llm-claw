#!/usr/bin/env python3
"""
微信视频号 / 元宝 命令行工具（单文件）

用法:
  python3 wx_channels_cli.py login
  python3 wx_channels_cli.py url <视频号分享链接>
  python3 wx_channels_cli.py yuanbao [--model MODEL] [--search|--no-search] <prompt>
  python3 wx_channels_cli.py yuanbao [--support-functions FUNC[,FUNC...]] <prompt>

Cookie 与 agent_id 保存在 yuanbao_env.json（目录由环境变量 LLM_CLAW_ENV_PATH 指定，未设置则用本脚本所在目录）。

依赖（仅 login 需要）:
  pip install playwright && playwright install chromium
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

ENV_FILENAME = "yuanbao_env.json"
YUANBAO_HOME = "https://yuanbao.tencent.com/"
PROBE_SHARE_URL = "https://weixin.qq.com/sph/A0QJjsz9za"
DEFAULT_CHAT_MODEL_ID = "deep_seek_v3"
KNOWN_CHAT_MODELS = (
    "deep_seek_v3",
    "deep_seek",
    "hunyuan_gpt_175B_0404",
    "hunyuan_t1",
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


@dataclass
class YuanbaoAuth:
    cookie: str
    agent_id: str
    agent_instance_id: str = ""

    @property
    def referer(self) -> str:
        if self.agent_instance_id:
            return f"https://yuanbao.tencent.com/chat/{self.agent_id}/{self.agent_instance_id}"
        return f"https://yuanbao.tencent.com/chat/{self.agent_id}"

    @property
    def x_agentid(self) -> str:
        if self.agent_instance_id:
            return f"{self.agent_id}/{self.agent_instance_id}"
        return self.agent_id


def config_dir() -> str:
    env = os.environ.get("LLM_CLAW_ENV_PATH", "").strip()
    if env:
        return os.path.expanduser(env)
    return os.path.dirname(os.path.abspath(__file__))


def cookie_file_path() -> str:
    return os.path.join(config_dir(), ENV_FILENAME)


# ── Cookie ──────────────────────────────────────────────────────────────


def parse_cookie_parts(cookie_str: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in re.split(r"[;\n\r\t]+", cookie_str or ""):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        k, v = k.strip(), v.strip()
        if k in ("hy_source", "hy_user", "hy_token") and v:
            parts[k] = v
    if "hy_source" not in parts:
        parts["hy_source"] = "web"
    return parts


def format_cookie(parts: dict[str, str]) -> str:
    keys = ("hy_source", "hy_user", "hy_token")
    return "; ".join(f"{k}={parts[k]}" for k in keys if parts.get(k))


def parse_agent_from_url(url: str) -> tuple[str, str]:
    m = re.search(r"yuanbao\.tencent\.com/chat/([^/?#]+)(?:/([^/?#]+))?", url or "")
    if not m:
        return "", ""
    agent_id = (m.group(1) or "").strip()
    instance_id = (m.group(2) or "").strip()
    if agent_id in ("", "chat"):
        return "", ""
    return agent_id, instance_id


def parse_agent_from_x_agentid(value: str) -> tuple[str, str]:
    value = (value or "").strip()
    if not value:
        return "", ""
    if "/" in value:
        agent_id, instance_id = value.split("/", 1)
        return agent_id.strip(), instance_id.strip()
    return value, ""


def save_auth(cookie_str: str, agent_id: str, agent_instance_id: str = "") -> str:
    parts = parse_cookie_parts(cookie_str)
    if not parts.get("hy_user") or not parts.get("hy_token"):
        raise SystemExit("Cookie 缺少 hy_user 或 hy_token")
    agent_id = (agent_id or "").strip()
    if not agent_id:
        raise SystemExit("缺少 agent_id，请重新 login")
    path = cookie_file_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "cookie": format_cookie(parts),
        "hy_source": parts.get("hy_source", "web"),
        "hy_user": parts["hy_user"],
        "hy_token": parts["hy_token"],
        "agent_id": agent_id,
        "agent_instance_id": (agent_instance_id or "").strip(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"已保存凭证到 {path}", file=sys.stderr)
    return path


def load_auth() -> YuanbaoAuth:
    path = cookie_file_path()
    if not os.path.isfile(path):
        raise SystemExit(
            f"未找到 {path}，请先执行 login（凭证目录: {config_dir()}，可用 LLM_CLAW_ENV_PATH 覆盖）:\n"
            f"  python3 {os.path.basename(__file__)} login"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, str):
        raise SystemExit(f"{ENV_FILENAME} 缺少 agent_id，请重新执行 login")
    cookie = ""
    if data.get("cookie"):
        cookie = str(data["cookie"]).strip()
    else:
        parts = {
            "hy_source": data.get("hy_source", "web"),
            "hy_user": data.get("hy_user", ""),
            "hy_token": data.get("hy_token", ""),
        }
        cookie = format_cookie(parts)
    agent_id = str(data.get("agent_id") or data.get("agentId") or "").strip()
    agent_instance_id = str(
        data.get("agent_instance_id") or data.get("agentInstanceId") or ""
    ).strip()
    if not cookie or "hy_user=" not in cookie or "hy_token=" not in cookie:
        raise SystemExit(f"{ENV_FILENAME} 中 Cookie 无效")
    if not agent_id:
        raise SystemExit(f"{ENV_FILENAME} 缺少 agent_id，请重新执行 login")
    return YuanbaoAuth(cookie=cookie, agent_id=agent_id, agent_instance_id=agent_instance_id)


# ── HTTP ────────────────────────────────────────────────────────────────


def http_request(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    cookie: str = "",
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> tuple[int, str]:
    body = None
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    if headers:
        hdrs.update(headers)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if cookie:
        hdrs["Cookie"] = cookie

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, raw


def http_ok(status: int) -> bool:
    return 200 <= status < 300


def cookie_expired_hint() -> str:
    return (
        "元宝 Cookie（hy_token）已失效或过期，请重新执行：\n"
        f"  python3 {os.path.basename(__file__)} login"
    )


def is_cookie_auth_error(*texts: str, status: int = 0) -> bool:
    if status in (401, 403):
        return True
    combined = "\n".join(str(t) for t in texts if t)
    if not combined:
        return False
    low = combined.lower()
    for marker in (
        "20001",
        "401",
        "403",
        "unauthorized",
        "invalid token",
        "not login",
        "hy_token",
        "token expired",
    ):
        if marker in low:
            return True
    for marker in (
        "token无效",
        "token 无效",
        "未登录",
        "登录失效",
        "登录过期",
        "已过期",
        "cookie无效",
        "cookie 无效",
        "请先登录",
        "鉴权失败",
        "凭证无效",
        "凭证过期",
    ):
        if marker in combined:
            return True
    return False


def raise_yuanbao_error(msg: str, *, status: int = 0, body: str = "") -> None:
    detail = msg
    snippet = (body or "")[:500].strip()
    if snippet and snippet not in detail:
        detail = f"{msg}\n{snippet}"
    if is_cookie_auth_error(msg, body, status=status):
        raise SystemExit(f"{cookie_expired_hint()}\n\n原始错误: {detail}")
    raise SystemExit(detail)


def check_yuanbao_json_response(status: int, body: str, context: str) -> dict[str, Any] | None:
    if not http_ok(status):
        raise_yuanbao_error(f"{context} HTTP {status}", status=status, body=body)
    if not (body or "").strip():
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        if is_cookie_auth_error(body, status=status):
            raise_yuanbao_error(context, status=status, body=body)
        raise_yuanbao_error(f"{context} 返回非 JSON", status=status, body=body)
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, dict):
        code = str(err.get("code", ""))
        message = str(err.get("message", ""))
        if is_cookie_auth_error(code, message, body, status=status) or code == "20001":
            raise_yuanbao_error(f"{context}: {code} {message}".strip(), status=status, body=body)
        raise_yuanbao_error(f"{context}: {code} {message}".strip(), status=status, body=body)
    code = data.get("code")
    if code not in (None, 0, "0"):
        msg = str(data.get("msg", ""))
        if is_cookie_auth_error(str(code), msg, body, status=status) or str(code) == "20001":
            raise_yuanbao_error(f"{context}: code={code} msg={msg}".strip(), status=status, body=body)
        raise_yuanbao_error(f"{context}: code={code} msg={msg}".strip(), status=status, body=body)
    return data


def yuanbao_headers(auth: YuanbaoAuth, *, sse: bool = False) -> dict[str, str]:
    h = {
        "Origin": "https://yuanbao.tencent.com",
        "Referer": auth.referer,
        "x-agentid": auth.x_agentid,
        "x-language": "zh-CN",
        "x-platform": "mac",
        "x-source": "web",
        "Cookie": auth.cookie,
    }
    if sse:
        h["Accept"] = "text/event-stream"
    return h


# ── login ───────────────────────────────────────────────────────────────


def cmd_login() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "login 需要 playwright:\n"
            "  pip install playwright\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        return 1

    print("启动浏览器登录元宝…", file=sys.stderr)
    print("请在窗口中完成扫码/登录", file=sys.stderr)

    agent_id = ""
    agent_instance_id = ""

    def capture_agent_from_request(request) -> None:
        nonlocal agent_id, agent_instance_id
        if "yuanbao.tencent.com" not in request.url:
            return
        headers = request.headers
        x_agent = headers.get("x-agentid") or headers.get("X-Agentid") or ""
        aid, iid = parse_agent_from_x_agentid(x_agent)
        if aid:
            agent_id = aid
            if iid:
                agent_instance_id = iid

    def capture_agent_from_url(url: str) -> None:
        nonlocal agent_id, agent_instance_id
        aid, iid = parse_agent_from_url(url)
        if aid:
            agent_id = aid
            if iid:
                agent_instance_id = iid

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=USER_AGENT)
        page = context.new_page()
        page.on("request", capture_agent_from_request)
        page.goto(YUANBAO_HOME, wait_until="domcontentloaded", timeout=60000)
        capture_agent_from_url(page.url)

        deadline = time.time() + 180
        logged_in = False
        while time.time() < deadline:
            capture_agent_from_url(page.url)
            names = {c["name"]: c["value"] for c in context.cookies()}
            if names.get("hy_user") and names.get("hy_token"):
                logged_in = True
                break
            time.sleep(2)

        if not logged_in:
            browser.close()
            print("登录超时", file=sys.stderr)
            return 1

        page.wait_for_timeout(3000)
        capture_agent_from_url(page.url)

        try:
            page.evaluate(
                """async (url) => {
  try {
    await fetch('/api/weixin/get_parse_result', {
      method: 'POST', credentials: 'include',
      headers: { 'content-Type': 'application/json' },
      body: JSON.stringify({ type: 'video_channel_url', url, scene: 1 }),
    });
  } catch (e) {}
}""",
                PROBE_SHARE_URL,
            )
        except Exception:
            pass
        page.wait_for_timeout(2000)
        capture_agent_from_url(page.url)

        parts = parse_cookie_parts(
            "; ".join(
                f"{c['name']}={c['value']}"
                for c in context.cookies()
                if c.get("name") in ("hy_source", "hy_user", "hy_token")
            )
        )
        browser.close()

    cookie = format_cookie(parts)
    if not cookie:
        print("未能提取 Cookie", file=sys.stderr)
        return 1
    if not agent_id:
        print("未能从登录会话获取 agent_id，请登录后停留在元宝对话页再试", file=sys.stderr)
        return 1

    path = save_auth(cookie, agent_id, agent_instance_id)
    print(
        json.dumps(
            {
                "ok": True,
                "file": path,
                "agent_id": agent_id,
                "agent_instance_id": agent_instance_id,
            },
            ensure_ascii=False,
        )
    )
    return 0


# ── url（视频查询）────────────────────────────────────────────────────


def clean_video_url(video_url: str) -> str:
    if not video_url:
        return ""
    parsed = urllib.parse.urlparse(video_url)
    qs = urllib.parse.parse_qs(parsed.query)
    enc = (qs.get("encfilekey") or [""])[0]
    token = (qs.get("token") or [""])[0]
    if enc and token:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?encfilekey={enc}&token={token}"
    return ""


def parse_share_url(share_url: str, auth: YuanbaoAuth) -> dict[str, Any]:
    status, body = http_request(
        "POST",
        "https://yuanbao.tencent.com/api/weixin/get_parse_result",
        data={"type": "video_channel_url", "url": share_url, "scene": 1},
        cookie=auth.cookie,
        headers=yuanbao_headers(auth),
        timeout=30,
    )
    wrapper = check_yuanbao_json_response(status, body, "元宝解析分享链接") or {}
    data = wrapper.get("data") or {}
    if not data.get("wx_export_id") and not data.get("playable_url"):
        raise_yuanbao_error("元宝解析返回为空", body=body)
    return data


def extract_token_export_id(playable_url: str) -> tuple[str, str]:
    if not playable_url:
        return "", ""
    parsed = urllib.parse.urlparse(playable_url)
    qs = urllib.parse.parse_qs(parsed.query)
    return (qs.get("token") or [""])[0], (qs.get("eid") or [""])[0]


def generate_rid() -> str:
    ts = format(int(time.time()), "x")
    rnd = "".join(random.choice("0123456789abcdef") for _ in range(8))
    return f"{ts}-{rnd}"


def get_feed_info(export_id: str, token: str) -> dict[str, Any]:
    rid = generate_rid()
    api = (
        "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
        f"?_rid={rid}&_pageUrl=https%3A%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    )
    payload = {"baseReq": {"generalToken": token}, "exportId": export_id}
    referer = (
        "https://channels.weixin.qq.com/finder-preview/pages/feed"
        f"?entry_card_type=48&comment_scene=39&appid=0&token={urllib.parse.quote(token)}"
        f"&entry_scene=0&eid={urllib.parse.quote(export_id)}"
    )
    status, body = http_request(
        "POST",
        api,
        data=payload,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://channels.weixin.qq.com",
            "Referer": referer,
        },
        timeout=30,
    )
    if not http_ok(status):
        raise_yuanbao_error(f"获取视频详情失败 HTTP {status}", status=status, body=body)
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise_yuanbao_error(f"获取视频详情返回非 JSON: {e}", status=status, body=body)


def map_feed_info(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "errCode": raw.get("errCode", 0),
        "errMsg": raw.get("errMsg", ""),
        "author": {},
        "video": {},
    }
    data = raw.get("data") or {}
    author = data.get("authorInfo") or {}
    feed = data.get("feedInfo") or {}
    out["author"] = {
        "nickname": author.get("nickname", ""),
        "headImgUrl": author.get("headImgUrl", ""),
    }
    video_url = feed.get("videoUrl", "")
    h264 = (feed.get("h264VideoInfo") or {}).get("videoUrl", "")
    h265 = (feed.get("h265VideoInfo") or {}).get("videoUrl", "")
    out["video"] = {
        "description": feed.get("description", ""),
        "videoUrl": video_url,
        "originVideoUrl": clean_video_url(video_url),
        "h264VideoUrl": h264,
        "h265VideoUrl": h265,
        "coverUrl": feed.get("coverUrl", ""),
        "likeCountFmt": feed.get("likeCountFmt", ""),
        "commentCountFmt": feed.get("commentCountFmt", ""),
        "favCountFmt": feed.get("favCountFmt", ""),
        "forwardCountFmt": feed.get("forwardCountFmt", ""),
        "createTime": feed.get("createtime", 0),
    }
    return out


def fetch_video_profile(share_url: str, auth: YuanbaoAuth) -> dict[str, Any]:
    parse_data = parse_share_url(share_url, auth)
    token, export_id = extract_token_export_id(parse_data.get("playable_url", ""))
    if not export_id:
        export_id = parse_data.get("wx_export_id", "")
    feed_raw = get_feed_info(export_id, token)
    feed = map_feed_info(feed_raw)
    video = feed.get("video") or {}
    author = feed.get("author") or {}

    best_download = (
        video.get("originVideoUrl")
        or video.get("h264VideoUrl")
        or video.get("h265VideoUrl")
        or video.get("videoUrl")
        or parse_data.get("playable_url")
        or ""
    )

    return {
        "shareUrl": share_url,
        "author": author.get("nickname") or parse_data.get("author", ""),
        "authorIcon": author.get("headImgUrl") or parse_data.get("author_icon", ""),
        "description": video.get("description") or parse_data.get("desc", ""),
        "desc": parse_data.get("desc", ""),
        "coverUrl": video.get("coverUrl") or parse_data.get("cover_url", ""),
        "downloadUrls": {
            "best": best_download,
            "origin": video.get("originVideoUrl", ""),
            "h264": video.get("h264VideoUrl", ""),
            "h265": video.get("h265VideoUrl", ""),
            "full": video.get("videoUrl", ""),
            "playable": parse_data.get("playable_url", ""),
        },
        "stats": {
            "like": video.get("likeCountFmt", ""),
            "comment": video.get("commentCountFmt", ""),
            "fav": video.get("favCountFmt", ""),
            "forward": video.get("forwardCountFmt", ""),
        },
        "exportId": export_id,
        "parse": parse_data,
        "feed": feed,
    }


def cmd_url(share_url: str) -> int:
    if not share_url.strip():
        raise SystemExit("请提供视频号分享链接")
    auth = load_auth()
    profile = fetch_video_profile(share_url.strip(), auth)
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


# ── yuanbao（对话）──────────────────────────────────────────────────────


class YuanbaoChatOptions:
    def __init__(
        self,
        chat_model_id: str = DEFAULT_CHAT_MODEL_ID,
        support_functions: list[str] | None = None,
    ):
        self.chat_model_id = chat_model_id
        self.support_functions = support_functions or ["supportInternetSearch"]


def parse_support_functions_arg(raw: str) -> list[str]:
    funcs = [x.strip() for x in raw.split(",") if x.strip()]
    if not funcs:
        raise SystemExit("--support-functions 不能为空")
    return funcs


def build_chat_model_ext_info(chat_model_id: str, support_functions: list[str]) -> str:
    internet = (
        "supportInternetSearch"
        if "supportInternetSearch" in support_functions
        else "closeInternetSearch"
    )
    return json.dumps(
        {
            "modelId": chat_model_id,
            "subModelId": "",
            "supportFunctions": {"internetSearch": internet},
        },
        ensure_ascii=False,
    )


def parse_yuanbao_argv(argv: list[str]) -> tuple[YuanbaoChatOptions, str]:
    """解析 yuanbao 子命令参数，返回选项与 prompt。"""
    model = DEFAULT_CHAT_MODEL_ID
    support_functions: list[str] | None = None
    prompt_parts: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--model":
            if i + 1 >= len(argv):
                raise SystemExit("--model 需要指定模型 ID")
            model = argv[i + 1].strip()
            i += 2
            continue
        if arg == "--support-functions":
            if i + 1 >= len(argv):
                raise SystemExit("--support-functions 需要指定功能列表")
            support_functions = parse_support_functions_arg(argv[i + 1])
            i += 2
            continue
        if arg == "--search":
            support_functions = ["supportInternetSearch"]
            i += 1
            continue
        if arg == "--no-search":
            support_functions = ["closeInternetSearch"]
            i += 1
            continue
        if arg.startswith("--"):
            raise SystemExit(f"未知参数: {arg}")
        prompt_parts.append(arg)
        i += 1

    if not model:
        raise SystemExit("--model 不能为空")
    if not prompt_parts:
        raise SystemExit("请提供 prompt")

    if support_functions is None:
        support_functions = ["supportInternetSearch"]

    return YuanbaoChatOptions(model, support_functions), " ".join(prompt_parts)


def parse_sse_text(raw: str) -> str:
    parts: list[str] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            break
        if not data.startswith("{"):
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        err = chunk.get("error")
        if isinstance(err, dict):
            code = str(err.get("code", ""))
            message = str(err.get("message", ""))
            if is_cookie_auth_error(code, message, raw) or code == "20001":
                raise_yuanbao_error(f"元宝对话: {code} {message}".strip(), body=raw)
            raise_yuanbao_error(f"元宝对话: {code} {message}".strip(), body=raw)
        if chunk.get("code") not in (None, 0, "0"):
            code = chunk.get("code")
            msg = str(chunk.get("msg", ""))
            if is_cookie_auth_error(str(code), msg, raw) or str(code) == "20001":
                raise_yuanbao_error(f"元宝对话: code={code} msg={msg}".strip(), body=raw)
        if msg := chunk.get("msg"):
            parts.append(str(msg))
        if content := chunk.get("content"):
            parts.append(str(content))
        for choice in chunk.get("choices") or []:
            delta = (choice or {}).get("delta") or {}
            if t := delta.get("content"):
                parts.append(str(t))
    text = "".join(parts).strip()
    if not text:
        if is_cookie_auth_error(raw):
            raise_yuanbao_error("元宝对话返回为空", body=raw)
        raise_yuanbao_error("元宝对话返回为空", body=raw)
    return text


def create_conversation(auth: YuanbaoAuth) -> str:
    status, body = http_request(
        "POST",
        "https://yuanbao.tencent.com/api/user/agent/conversation/create",
        data={"agentId": auth.agent_id},
        cookie=auth.cookie,
        headers=yuanbao_headers(auth),
    )
    out = check_yuanbao_json_response(status, body, "创建元宝会话") or {}
    chat_id = out.get("id", "")
    if not chat_id:
        raise_yuanbao_error("创建会话失败，未返回会话 ID", status=status, body=body)
    return chat_id


def clear_conversation(auth: YuanbaoAuth, chat_id: str) -> None:
    http_request(
        "POST",
        "https://yuanbao.tencent.com/api/user/agent/conversation/v1/clear",
        data={"conversationIds": [chat_id], "uiOptions": {"noToast": True}},
        cookie=auth.cookie,
        headers=yuanbao_headers(auth),
        timeout=15,
    )


def yuanbao_chat(prompt: str, auth: YuanbaoAuth, options: YuanbaoChatOptions) -> str:
    chat_id = create_conversation(auth)
    try:
        body_payload = {
            "model": "gpt_175B_0404",
            "prompt": prompt,
            "plugin": "Adaptive",
            "displayPrompt": prompt,
            "displayPromptType": 1,
            "options": {
                "imageIntention": {
                    "needIntentionModel": True,
                    "backendUpdateFlag": 2,
                    "intentionStatus": True,
                }
            },
            "agentId": auth.agent_id,
            "supportHint": 1,
            "version": "v2",
            "chatModelId": options.chat_model_id,
            "chatModelExtInfo": build_chat_model_ext_info(
                options.chat_model_id, options.support_functions
            ),
            "applicationIdList": [],
            "supportFunctions": options.support_functions,
        }
        status, body = http_request(
            "POST",
            f"https://yuanbao.tencent.com/api/chat/{chat_id}",
            data=body_payload,
            cookie=auth.cookie,
            headers=yuanbao_headers(auth, sse=True),
            timeout=120,
        )
        if not http_ok(status):
            raise_yuanbao_error(f"元宝对话失败 HTTP {status}", status=status, body=body)
        return parse_sse_text(body)
    finally:
        clear_conversation(auth, chat_id)


def cmd_yuanbao(argv: list[str]) -> int:
    options, prompt = parse_yuanbao_argv(argv)
    auth = load_auth()
    reply = yuanbao_chat(prompt, auth, options)
    print(
        json.dumps(
            {
                "prompt": prompt,
                "agent_id": auth.agent_id,
                "model": options.chat_model_id,
                "supportFunctions": options.support_functions,
                "reply": reply,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# ── main ────────────────────────────────────────────────────────────────


USAGE = f"""用法:
  python3 {os.path.basename(__file__)} login
  python3 {os.path.basename(__file__)} url <视频号分享链接>
  python3 {os.path.basename(__file__)} yuanbao [选项] <prompt>

元宝对话选项:
  --model MODEL              chatModelId，默认 {DEFAULT_CHAT_MODEL_ID}
  --search                   开启联网（默认）
  --no-search                关闭联网
  --support-functions LIST   自定义，逗号分隔
                             如 supportInternetSearch 或 closeInternetSearch

常用模型: {", ".join(KNOWN_CHAT_MODELS)}

凭证文件: LLM_CLAW_ENV_PATH/{ENV_FILENAME}（未设置 LLM_CLAW_ENV_PATH 时为本脚本目录: {config_dir()}）
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE.strip())
        return 0

    cmd = args[0].lower()
    if cmd == "login":
        return cmd_login()
    if cmd == "url":
        if len(args) < 2:
            raise SystemExit("缺少参数: 视频号分享链接")
        return cmd_url(args[1])
    if cmd == "yuanbao":
        if len(args) < 2:
            raise SystemExit("缺少参数: prompt（可用 --help 查看选项）")
        return cmd_yuanbao(args[1:])

    raise SystemExit(f"未知命令: {cmd}\n\n{USAGE}")


if __name__ == "__main__":
    sys.exit(main())
