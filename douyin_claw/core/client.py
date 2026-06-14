from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .api import DouyinAPI
from .auth import DouyinAuth
from .browser import search_via_playwright


@dataclass
class SearchOptions:
    keyword: str
    num: int = 20
    sort_type: str = "0"
    publish_time: str = "0"
    filter_duration: str = ""
    search_range: str = "0"
    content_type: str = "0"


@dataclass
class SearchResult:
    videos: list[dict[str, Any]]
    method: str = "api"
    nil_type: str = ""
    api_error: str = ""
    raw_count: int = 0
    filtered_out: int = 0


def search_nil_type(res: dict[str, Any]) -> str:
    nil = res.get("search_nil_info") or {}
    return str(nil.get("search_nil_type") or nil.get("search_nil_item") or "").strip()


def format_search_failure(result: SearchResult, keyword: str) -> str:
    if result.nil_type == "verify_check":
        if result.method == "playwright":
            return (
                f"抖音搜索「{keyword}」被风控拦截（verify_check），Playwright 兜底也未拿到结果。\n"
                "常见原因：\n"
                "  · Cookie 未在浏览器中完成搜索验证（请 cslogin cookie douyin 后手动搜一次再关窗）\n"
                "  · 可临时 export DY_COOKIES=…（DouYin_Spider/.env 中已验证的 Cookie）\n"
                "  · 确认已 playwright install chromium（headless 须用内置 Chromium，非 channel=chrome）"
            )
        return (
            f"抖音搜索「{keyword}」被风控拦截（verify_check），需要人机验证，并非关键词无结果。\n"
            "请在本机浏览器中：\n"
            "  1) cslogin cookie douyin  （或 python3 douyin_claw.py login）\n"
            "  2) 登录后务必在打开的浏览器里手动搜索并完成验证，看到结果后再关闭窗口\n"
            "  3) 再重试 search"
        )
    if result.raw_count and result.filtered_out >= result.raw_count:
        return (
            f"搜索到 {result.raw_count} 条，但筛选条件（publish_time / sort / content_type 等）"
            f"过滤后剩余 0 条。可尝试去掉 --publish-time 等参数。"
        )
    if result.nil_type:
        return f"抖音搜索「{keyword}」无数据（search_nil_type={result.nil_type}）"
    if result.api_error:
        return f"抖音 API 搜索失败: {result.api_error}"
    if result.method == "playwright":
        return (
            f"抖音搜索「{keyword}」：API 与 Playwright 兜底均未拿到结果。\n"
            "可能原因：Cookie 失效、headless 被识别、或需先在浏览器完成验证。\n"
            "建议：cslogin cookie douyin 后手动搜索验证，再重试。"
        )
    return f"未找到与「{keyword}」匹配的视频"


def publish_time_cutoff_ts(publish_time: str) -> int:
    import time

    days_map = {"0": None, "1": 1, "7": 7, "180": 180}
    days = days_map.get(publish_time)
    if not days:
        return 0
    return int(time.time()) - days * 86400


def map_aweme(aweme: dict[str, Any]) -> dict[str, Any]:
    author = aweme.get("author") or {}
    stats = aweme.get("statistics") or {}
    video = aweme.get("video") or {}
    cover = (video.get("cover") or {}).get("url_list") or []
    play = (video.get("play_addr") or {}).get("url_list") or []
    create_ts = int(aweme.get("create_time") or 0)
    aweme_id = str(aweme.get("aweme_id") or "")
    aweme_type = aweme.get("aweme_type")
    work_type = "图集" if aweme_type == 68 else "视频"

    return {
        "aweme_id": aweme_id,
        "title": aweme.get("desc") or "",
        "desc": aweme.get("desc") or "",
        "work_type": work_type,
        "author": author.get("nickname") or "",
        "author_uid": author.get("uid") or "",
        "author_sec_uid": author.get("sec_uid") or "",
        "create_time": create_ts,
        "create_time_fmt": (
            datetime.fromtimestamp(create_ts).strftime("%Y-%m-%d %H:%M:%S") if create_ts else ""
        ),
        "digg_count": stats.get("digg_count", 0),
        "comment_count": stats.get("comment_count", 0),
        "share_count": stats.get("share_count", 0),
        "collect_count": stats.get("collect_count", 0),
        "share_url": f"https://www.douyin.com/video/{aweme_id}" if aweme_id else "",
        "cover_url": cover[0] if cover else "",
        "video_url": play[0] if play else "",
    }


def filter_videos(videos: list[dict[str, Any]], opts: SearchOptions) -> list[dict[str, Any]]:
    cutoff = publish_time_cutoff_ts(opts.publish_time)
    out: list[dict[str, Any]] = []
    for v in videos:
        ts = int(v.get("create_time") or 0)
        if cutoff and ts < cutoff:
            continue
        if opts.content_type == "1" and v.get("work_type") != "视频":
            continue
        if opts.content_type == "2" and v.get("work_type") != "图集":
            continue
        out.append(v)
    return out


def map_comment(raw: dict[str, Any]) -> dict[str, Any]:
    user = raw.get("user") or {}
    create_ts = int(raw.get("create_time") or 0)
    return {
        "cid": raw.get("cid") or "",
        "text": raw.get("text") or "",
        "digg_count": raw.get("digg_count", 0),
        "reply_count": raw.get("reply_comment_total", 0),
        "user": user.get("nickname") or "",
        "create_time_fmt": (
            datetime.fromtimestamp(create_ts).strftime("%Y-%m-%d %H:%M:%S") if create_ts else ""
        ),
    }


def build_analysis_input(
    video: dict[str, Any],
    description: str,
    comments: list[dict[str, Any]],
    extra_context: str = "",
) -> str:
    lines = [
        f"【视频】{video.get('share_url', '')}",
        f"【作者】{video.get('author', '')}",
        f"【发布时间】{video.get('create_time_fmt', '')}",
        f"【描述】{description}",
        f"【互动】点赞 {video.get('digg_count', 0)} | 评论 {video.get('comment_count', 0)} | "
        f"分享 {video.get('share_count', 0)}",
    ]
    if extra_context:
        lines.append(f"【补充】{extra_context}")
    if comments:
        lines.append("【热门评论】")
        for i, c in enumerate(comments[:20], 1):
            lines.append(f"{i}. ({c.get('digg_count', 0)}赞) {c.get('user', '')}: {c.get('text', '')}")
    return "\n".join(lines)


class DouyinClient:
    def __init__(self, cookie_str: str):
        self._cookie_str = cookie_str
        self.auth = DouyinAuth()
        self.auth.prepare_auth(cookie_str)

    def search(self, opts: SearchOptions) -> SearchResult:
        raw_items: list[dict[str, Any]] = []
        method = "api"
        nil_type = ""
        api_error = ""
        offset = "0"

        try:
            while len(raw_items) < opts.num:
                res = DouyinAPI.search_general_work(
                    self.auth,
                    opts.keyword,
                    opts.sort_type,
                    opts.publish_time,
                    offset,
                    opts.filter_duration,
                    opts.search_range,
                    opts.content_type,
                )
                if offset == "0":
                    nil_type = search_nil_type(res)
                works = res.get("data") or []
                for item in works:
                    aweme = item.get("aweme_info", item)
                    if aweme.get("aweme_id"):
                        raw_items.append(aweme)
                if res.get("has_more") != 1 or not works:
                    break
                offset = str(int(offset) + len(works))
        except Exception as exc:
            api_error = str(exc)

        pw_nil = ""
        if not raw_items:
            method = "playwright"
            raw_items, pw_nil = search_via_playwright(
                self._cookie_str, opts.keyword, max(opts.num, 10)
            )
            if raw_items:
                nil_type = ""
            elif pw_nil and not nil_type:
                nil_type = pw_nil

        mapped = [map_aweme(a) for a in raw_items]
        raw_count = len(mapped)
        videos = filter_videos(mapped, opts)
        return SearchResult(
            videos=videos[: opts.num],
            method=method,
            nil_type=nil_type,
            api_error=api_error,
            raw_count=raw_count,
            filtered_out=raw_count - len(videos),
        )

    def video_detail(self, url: str, max_comments: int = 30) -> dict[str, Any]:
        detail_raw = DouyinAPI.get_work_info(self.auth, url)
        aweme = detail_raw.get("aweme_detail") or {}
        video = map_aweme(aweme) if aweme.get("aweme_id") else {"share_url": url}
        comments_raw = DouyinAPI.get_comments(self.auth, url, max_comments)
        comments = [map_comment(c) for c in comments_raw]
        description = video.get("desc") or video.get("title") or ""
        return {
            "video": video,
            "description": description,
            "statistics": {
                "digg_count": video.get("digg_count", 0),
                "comment_count": video.get("comment_count", 0),
                "share_count": video.get("share_count", 0),
                "collect_count": video.get("collect_count", 0),
            },
            "comments_fetched": len(comments),
            "comments": comments,
            "video_url": video.get("video_url") or "",
            "analysis_input": build_analysis_input(video, description, comments),
        }
