# llm-claw

LLM / Agent 相关抓取与剪藏工具集

## 子模块

| 目录 | 说明 |
|------|------|
| [feeds-claw](feeds-claw/) | 多平台信息流剪藏（微信 / 微博 / 抖音 / X 等）→ Obsidian `14_feeds` |
| [wechat-article-claw](wechat-article-claw/) | 微信公众号扫码登录、全量爬虫 |
| [weibo_claw](weibo_claw/) | 微博扫码登录，Cookie 写入 `weibo_env.json` |
| [wx_channels_claw](wx_channels_claw/) | 微信视频号 |
| [douyin_claw](douyin_claw/) | 抖音 Cookie、搜索、单条 analyze、`batch` 多关键词去重合并 |
| [otp](otp/) | OTP 工具 |

## 快速开始（feeds 剪藏）

```bash
cd feeds-claw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export CSLOGIN_WIKI_PATH=/path/to/my-wiki
python3 save_feed_to_mydoc.py "https://mp.weixin.qq.com/s/..." --dry-run
```

## douyin_claw 快速开始

```bash
cd douyin_claw
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install   # 仅 jsrsasign（a_bogus 签名）
playwright install chromium
python3 douyin_claw.py login
python3 douyin_claw.py search --num 10 "关键词"

# 多关键词 batch（词表见 douyin_claw/SKILL.md）
python3 douyin_claw.py batch \
  --name 企业火灾 \
  --queries 企业火灾 工厂火灾 \
  --topic-keywords 火灾,着火,起火,爆炸,消防
```

## cslogin 凭证登录

```bash
cslogin cookie wechat    # → wechat_env.json
cslogin cookie yuanbao   # → yuanbao_env.json
cslogin cookie weibo     # → weibo_env.json
cslogin cookie douyin    # → douyin_env.json（保存后可选同步到服务器，见 wechat_token_sync.sh）
```

## LLM_CLAW_ENV_PATH

`LLM_CLAW_ENV_PATH` 表示相关凭证和环境保存的目录；未设置时各子模块默认使用各自脚本所在目录。

| 文件 | 模块 |
|------|------|
| `wechat_env.json` | wechat-article-claw |
| `weibo_env.json` | weibo_claw |
| `yuanbao_env.json` | wx_channels_claw |
| `douyin_env.json` | douyin_claw |