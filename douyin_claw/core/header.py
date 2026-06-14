from enum import Enum


class HeaderType(Enum):
    GET = "GET"
    DOC = "DOC"


class Header:
    def __init__(self):
        self.headers = {}

    def set_header(self, key, value):
        self.headers[key] = value
        return self

    def set_referer(self, url):
        return self.set_header("referer", url)

    def get(self):
        return self.headers


class HeaderBuilder:
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    @staticmethod
    def build(header_type):
        header = Header()
        header.set_header("user-agent", HeaderBuilder.ua)
        header.set_header("cache-control", "no-cache")
        header.set_header("pragma", "no-cache")
        header.set_header("sec-ch-ua", '"Chromium";v="125", "Not.A/Brand";v="24"')
        header.set_header("sec-ch-ua-mobile", "?0")
        header.set_header("sec-ch-ua-platform", '"macOS"')
        header.set_header("sec-fetch-dest", "empty")
        header.set_header("sec-fetch-mode", "cors")
        header.set_header("sec-fetch-site", "same-origin")
        header.set_header("accept-language", "zh-CN,zh;q=0.9,en;q=0.8")
        if header_type == HeaderType.GET:
            header.set_header("accept", "application/json, text/plain, */*")
        elif header_type == HeaderType.DOC:
            header.headers.update(
                {
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "upgrade-insecure-requests": "1",
                    "user-agent": HeaderBuilder.ua,
                }
            )
        return header
