# llm-claw

LLM / Agent 相关抓取与剪藏工具集，配合 [utils](https://github.com/dragoncheng/utils) 中的 `cslogin` 使用。

## 克隆

```bash
git clone git@github.com:dragoncheng/llm-claw.git
```

在 `utils` 仓库中作为 submodule 引入：

```bash
git submodule add git@github.com:dragoncheng/llm-claw.git llm-claw
git submodule update --init --recursive
```

## 子模块

| 目录 | 说明 |
|------|------|
| [feeds-claw](feeds-claw/) | 多平台信息流剪藏（微信 / 微博 / 抖音 / X 等）→ Obsidian `14_feeds` |
| [wechat-article-claw](wechat-article-claw/) | 微信公众号扫码登录、全量爬虫 |
| [weibo_claw](weibo_claw/) | 微博二维码登录（Playwright） |
| [wx_channels_claw](wx_channels_claw/) | 微信视频号 |
| [otp](otp/) | OTP 工具 |

## 快速开始（feeds 剪藏）

```bash
cd feeds-claw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export CSLOGIN_WIKI_PATH=/path/to/my-wiki
python3 save_feed_to_mydoc.py "https://mp.weixin.qq.com/s/..." --dry-run
```

## 与 cslogin 集成

在 `utils` 仓库中：

```bash
cslogin feeds save <url> [tag...]
cslogin wechat save <url> [tag...]   # 剪藏，走 feeds-claw
cslogin wechat                       # 公众平台扫码，走 wechat-article-claw
```

路径默认为 `$UTILS_PATH/llm-claw/`。

## 敏感文件

以下文件不入库，请本地自行创建：

- `otp/secrets.json`
- `wechat-article-claw/credentials.json`
- `wechat-article-claw/config.json`
- `wechat-article-claw/wechat_token_sync.sh`（参考 `wechat_token_sync.sh.example`）
