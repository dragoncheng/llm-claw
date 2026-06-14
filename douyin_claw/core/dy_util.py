import json
import os
import random
import re
import subprocess
import urllib.parse
from functools import partial

import requests

requests.packages.urllib3.disable_warnings()
subprocess.Popen = partial(subprocess.Popen, encoding="utf-8")

import execjs

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_node_modules = os.path.join(PACKAGE_ROOT, "node_modules")
_dy_path = os.path.join(PACKAGE_ROOT, "static", "dy_ab.js")
dy_js = execjs.compile(open(_dy_path, "r", encoding="utf-8").read(), cwd=_node_modules)


def trans_cookies(cookies_str: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for chunk in re.split(r"[;\n\r\t]+", cookies_str or ""):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        k = k.strip()
        if not k:
            continue
        cookies[k] = v.strip()
    return cookies


def generate_a_bogus(query: str, data: str = "") -> str:
    return dy_js.call("get_ab", query, data)


def generate_verify_fp() -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    def _rand(n: int) -> str:
        return "".join(chars[random.randint(0, len(chars) - 1)] for _ in range(n))
    return f"verify_{_rand(8)}_{_rand(4)}_{_rand(4)}_{_rand(4)}_{_rand(4)}_{_rand(4)}_{_rand(4)}_{_rand(4)}"


def generate_msToken(randomlength: int = 107) -> str:
    base_str = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789="
    return "".join(base_str[random.randint(0, len(base_str) - 1)] for _ in range(randomlength))


def generate_fake_webid(random_length: int = 19) -> str:
    base_str = "0123456789"
    return "".join(base_str[random.randint(0, len(base_str) - 1)] for _ in range(random_length))


def generate_webid(auth=None, url: str = "") -> str:
    if not url:
        url = "https://www.douyin.com/discover?modal_id=7376449060384935209"
    try:
        from .header import HeaderBuilder, HeaderType

        headers = HeaderBuilder().build(HeaderType.DOC)
        headers.set_header("cookie", auth.cookie_str if auth else "")
        response = requests.get(url, headers=headers.get(), verify=False, timeout=30)
        user_unique_id = re.findall(r'\\"user_unique_id\\":\\"(.*?)\\"', response.text)[0]
        return user_unique_id
    except Exception:
        return generate_fake_webid()


def splice_url(params: dict) -> str:
    parts = []
    for key, value in params.items():
        if value is None:
            value = ""
        parts.append(f"{key}={urllib.parse.quote(str(value))}")
    return "&".join(parts)
