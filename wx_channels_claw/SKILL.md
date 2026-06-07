---
name: wx-channels-claw
description: 微信视频号信息获取与元宝深度分析。用户给视频号分享链接要元数据时用 url 子命令；要解读、总结、对比或延伸分析时用 yuanbao 子命令并传入用户意图。Cookie 失效时提示 cslogin cookie yuanbao 或 login 刷新。Use when user mentions 微信视频号, channels.weixin.qq.com, weixin.qq.com/sph, 视频号链接, 元宝分析视频.
---

# wx-channels-claw — 微信视频号

工具脚本：`llm-claw/wx_channels_claw/wx_channels_claw.py`  
凭证：`$LLM_CLAW_ENV_PATH/yuanbao_env.json`（未设置则用脚本同目录）

## 意图路由（Agent 必遵守）

| 用户意图 | 子命令 | 说明 |
|----------|--------|------|
| 获取视频号**基础信息**（作者、描述、封面、播放/下载链接、点赞评论等） | `url` | 只解析链接，不做 LLM 分析 |
| **分析、总结、解读、对比、延伸讨论**视频或账号内容 | `yuanbao` | 把用户意图原样或整理后作为 prompt 传入 |

**判断要点：**
- 只要「这条视频是什么 / 谁发的 / 链接 / 数据」→ `url`
- 出现「分析、总结、什么意思、帮我看看、对比、评价、提取观点、写摘要」等 → `yuanbao`
- `yuanbao` 的 prompt 中应包含：用户问题 + 相关视频号分享链接（若对话里已有）

**禁止**用 `web_fetch` / 通用爬虫替代本脚本解析视频号链接。

## 运行命令

在 `wx_channels_claw` 目录或指定完整路径执行（需已配置 `yuanbao_env.json`）：

```bash
# 1) 视频号元数据（JSON stdout）
python3 wx_channels_claw.py url "<视频号分享链接>"

# 2) 元宝深度分析（JSON stdout，含 reply 字段）
python3 wx_channels_claw.py yuanbao "<用户意图与链接，自然语言即可>"

# 可选：--search（默认联网） / --no-search / --model deep_seek_v3
python3 wx_channels_claw.py yuanbao --search "总结这条视频的核心观点：https://weixin.qq.com/sph/..."
```

或通过 cslogin（凭证目录一致时）：

```bash
cslogin cookie yuanbao   # 仅 Cookie 过期或首次使用时
```

## 输出说明

**`url`**：返回 JSON，主要字段 `author`、`description`、`coverUrl`、`downloadUrls`、`stats`（点赞/评论/收藏/转发）。

**`yuanbao`**：返回 JSON，阅读 `reply` 作为分析结果；`prompt` 为实际发送内容。

## Cookie 过期处理（必须执行）

若 stderr/stdout 出现以下任一情况，**判定为 Cookie 失效**，不要重试同一请求：

- 文案含：`元宝 Cookie（hy_token）已失效或过期`
- `20001`、`401`/`403`、`未登录`、`登录失效`、`cookie无效`、`凭证过期` 等鉴权错误

**Agent 应对用户说：**

> 元宝凭证已过期，请在本地执行扫码更新：
> `cslogin cookie yuanbao`
> 或 `python3 wx_channels_claw.py login`
> 完成后我再重新获取/分析。

本地环境可说明会弹出浏览器扫码；云服务器勿自动跑 login，请用户在本地更新 `$LLM_CLAW_ENV_PATH/yuanbao_env.json` 后再继续。

## 依赖

```bash
cd llm-claw/wx_channels_claw
pip install -r requirements.txt
# 仅 login 需要：
playwright install chromium
```

## 示例

**用户**：「帮我查一下这个视频号链接的信息 https://weixin.qq.com/sph/xxx」

```bash
python3 wx_channels_claw.py url "https://weixin.qq.com/sph/xxx"
```

**用户**：「分析一下这条视频在讲什么，有什么商业启示 https://weixin.qq.com/sph/xxx」

```bash
python3 wx_channels_claw.py yuanbao "分析这条视频在讲什么，以及有哪些商业启示。视频链接：https://weixin.qq.com/sph/xxx"
```
