import json
import re
import urllib.parse
import uuid

import requests

from .auth import DouyinAuth
from .header import HeaderBuilder, HeaderType
from .params import Params


class DouyinAPI:
    douyin_url = "https://www.douyin.com"

    @staticmethod
    def _get(auth: DouyinAuth, api: str, refer: str, params: Params) -> dict:
        headers = HeaderBuilder().build(HeaderType.GET)
        headers.set_referer(refer)
        resp = requests.get(
            f"{DouyinAPI.douyin_url}{api}",
            headers=headers.get(),
            cookies=auth.cookie,
            params=params.get(),
            verify=False,
            timeout=30,
        )
        return json.loads(resp.text)

    @staticmethod
    def _video_url(aweme_id: str) -> str:
        return f"https://www.douyin.com/video/{aweme_id}"

    @staticmethod
    def _resolve_aweme_id(url: str) -> tuple[str, str]:
        if "video" in url:
            aweme_id = url.split("/")[-1].split("?")[0]
            return aweme_id, DouyinAPI._video_url(aweme_id)
        aweme_id = re.findall(r"modal_id=(\d+)", url)[0]
        return aweme_id, DouyinAPI._video_url(aweme_id)

    @staticmethod
    def search_general_work(
        auth: DouyinAuth,
        query: str,
        sort_type: str = "0",
        publish_time: str = "0",
        offset: str = "0",
        filter_duration: str = "",
        search_range: str = "0",
        content_type: str = "0",
        **kwargs,
    ) -> dict:
        api = "/aweme/v1/web/general/search/single/"
        refer = f"https://www.douyin.com/search/{urllib.parse.quote(query)}?aid={uuid.uuid4()}&type=general"
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("search_channel", "aweme_general")
        params.add_param("enable_history", "1")
        use_filter = (
            sort_type != "0" or publish_time != "0" or filter_duration
            or search_range != "0" or content_type != "0"
        )
        if use_filter:
            params.add_param(
                "filter_selected",
                r'{"sort_type":"%s","publish_time":"%s","filter_duration":"%s",'
                r'"search_range":"%s","content_type":"%s"}'
                % (sort_type, publish_time, filter_duration, search_range, content_type),
            )
            params.add_param("search_source", "tab_search")
            params.add_param("is_filter_search", "1")
        else:
            params.add_param("search_source", "normal_search")
            params.add_param("is_filter_search", "0")
        params.add_param("keyword", query)
        params.add_param("query_correct_type", "1")
        params.add_param("from_group_id", "")
        params.add_param("offset", offset)
        params.add_param("count", "25")
        params.add_param("need_filter_settings", "1" if offset == "0" else "0")
        params.add_param("list_type", "single")
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "190600")
        params.add_param("version_name", "19.6.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "50")
        params.add_param("disable_rs", "0")
        params.add_param("support_dash", "1")
        params.add_param("support_h265", "1")
        params.add_param("pc_libra_divert", "Mac")
        params.add_param("pc_search_top_1_params", '{"enable_ai_search_top_1":1}')
        uifid = auth.cookie.get("UIFID") or auth.cookie.get("UIFID_TEMP")
        if uifid:
            params.add_param("uifid", uifid)
        search_id = kwargs.get("search_id")
        if search_id:
            params.add_param("search_id", search_id)
        params.with_web_id(auth, refer)
        params.add_param("msToken", auth.msToken)
        params.add_param("verifyFp", auth.cookie["s_v_web_id"])
        params.add_param("fp", auth.cookie["s_v_web_id"])
        params.with_a_bogus()
        return DouyinAPI._get(auth, api, refer, params)

    @staticmethod
    def search_some_general_work(
        auth: DouyinAuth,
        query: str,
        num: int,
        sort_type: str,
        publish_time: str,
        filter_duration: str = "",
        search_range: str = "0",
        content_type: str = "0",
    ) -> list:
        offset = "0"
        work_list: list = []
        while True:
            res_json = DouyinAPI.search_general_work(
                auth, query, sort_type, publish_time, offset,
                filter_duration, search_range, content_type,
            )
            works = res_json.get("data") or []
            work_list.extend(works)
            if res_json.get("has_more") != 1 or len(work_list) >= num:
                break
            if not works:
                break
            offset = str(int(offset) + len(works))
        return work_list[:num]

    @staticmethod
    def get_work_info(auth: DouyinAuth, url: str) -> dict:
        api = "/aweme/v1/web/aweme/detail/"
        aweme_id, url = DouyinAPI._resolve_aweme_id(url)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("aweme_id", aweme_id)
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "190500")
        params.add_param("version_name", "19.5.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "4.75")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "150")
        params.with_web_id(auth, url)
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        params.add_param("verifyFp", auth.cookie["s_v_web_id"])
        params.add_param("fp", auth.cookie["s_v_web_id"])
        return DouyinAPI._get(auth, api, url, params)

    @staticmethod
    def get_work_out_comment(auth: DouyinAuth, url: str, cursor: str = "0") -> dict:
        api = "/aweme/v1/web/comment/list/"
        aweme_id, url = DouyinAPI._resolve_aweme_id(url)
        params = Params()
        params.add_param("device_platform", "webapp")
        params.add_param("aid", "6383")
        params.add_param("channel", "channel_pc_web")
        params.add_param("aweme_id", aweme_id)
        params.add_param("cursor", cursor)
        params.add_param("count", "20")
        params.add_param("item_type", "0")
        params.add_param("whale_cut_token", "")
        params.add_param("cut_version", "1")
        params.add_param("rcFT", "")
        params.add_param("update_version_code", "170400")
        params.add_param("pc_client_type", "1")
        params.add_param("version_code", "170400")
        params.add_param("version_name", "17.4.0")
        params.add_param("cookie_enabled", "true")
        params.add_param("screen_width", "1707")
        params.add_param("screen_height", "960")
        params.add_param("browser_language", "zh-CN")
        params.add_param("browser_platform", "Win32")
        params.add_param("browser_name", "Edge")
        params.add_param("browser_version", "125.0.0.0")
        params.add_param("browser_online", "true")
        params.add_param("engine_name", "Blink")
        params.add_param("engine_version", "125.0.0.0")
        params.add_param("os_name", "Windows")
        params.add_param("os_version", "10")
        params.add_param("cpu_core_num", "32")
        params.add_param("device_memory", "8")
        params.add_param("platform", "PC")
        params.add_param("downlink", "10")
        params.add_param("effective_type", "4g")
        params.add_param("round_trip_time", "0")
        params.with_web_id(auth, url)
        params.add_param("verifyFp", auth.cookie["s_v_web_id"])
        params.add_param("fp", auth.cookie["s_v_web_id"])
        params.add_param("msToken", auth.msToken)
        params.with_a_bogus()
        return DouyinAPI._get(auth, api, url, params)

    @staticmethod
    def get_comments(auth: DouyinAuth, url: str, max_count: int = 30) -> list:
        cursor = "0"
        out: list = []
        while len(out) < max_count:
            res = DouyinAPI.get_work_out_comment(auth, url, cursor)
            batch = res.get("comments") or []
            if not batch:
                break
            out.extend(batch)
            if not res.get("has_more"):
                break
            cursor = str(res.get("cursor", "0"))
        return out[:max_count]
