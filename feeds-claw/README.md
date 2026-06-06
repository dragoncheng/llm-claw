# feeds-claw

多平台信息流剪藏 → `my-wiki/01_mydoc/14_feeds/`。

## 平台与模块

| 平台 | 模块 | 说明 |
|------|------|------|
| 微信公众号 | `fetch_wechat.py` | 公开文章链接；`curl_cffi` 绕过反爬 |
| 微博 | `fetch_weibo.py` | `m.weibo.cn/statuses/show` |
| 抖音 | `fetch_douyin.py` | `iesdouyin.com` SSR `_ROUTER_DATA`；可选 `yt-dlp` |
| X / Twitter | `save_generic_feed.py` | FxTwitter API |
| 其他 | `save_generic_feed.py` | 通用 HTML |

入口：`save_feed_to_mydoc.py`（平台自动识别）。

## 环境

```bash
cd feeds-claw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 环境变量（可选）

| 变量 | 用途 |
|------|------|
| `CSLOGIN_WIKI_PATH` | Vault 根目录 |
| `FEEDS_WEIBO_COOKIE` | 微博浏览器 Cookie（风控时） |
| `FEEDS_DOUYIN_COOKIE` | 抖音 Cookie（登录页/限流时） |

抖音增强（可选）：

```bash
pip install yt-dlp   # 或 brew install yt-dlp
```

## 本地测试

```bash
cd feeds-claw && source .venv/bin/activate
export CSLOGIN_WIKI_PATH=/path/to/my-wiki
python3 save_feed_to_mydoc.py "<url>" --dry-run
```
