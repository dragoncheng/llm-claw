---
name: douyin-claw
description: 抖音 Cookie 登录、关键词搜索、多关键词 batch 批量采集与去重合并。用户要搜抖音、批量多词合并分析时用 search/batch；Cookie 失效时用 login。Use when user mentions 抖音搜索, douyin search, 搜抖音, 多关键词抖音, douyin batch.
---

# douyin-claw — 抖音视频搜索

工具脚本：`llm-claw/douyin_claw/douyin_claw.py`  
凭证：`$LLM_CLAW_ENV_PATH/douyin_env.json`（未设置则用脚本同目录）

## 意图路由（Agent 必遵守）

| 用户意图 | 子命令 | 说明 |
|----------|--------|------|
| 获取/更新抖音登录 Cookie | `login` | Playwright 打开浏览器扫码登录 |
| 按关键词搜索抖音视频 | `search` | 返回 JSON 视频列表 |
| 单条视频详情 + 评论 | `video` | 内置 API |
| 搜索后批量拉评论并生成分析 prompt | `analyze` | 单关键词，输出 `analysis_prompt` |
| 多关键词搜索、过滤、去重合并 | `batch` | 词表由 Agent 传入；Agent 须续做 LLM 分析 |

## batch 多关键词批量（Agent 必遵守）

**脚本不是最终交付。** `batch` 完成搜→滤→合并→结构化；Agent **必须**读 JSON 中 `analysis_input` / `analysis_prompt` 与 `next_step`，按用户意图完成 LLM 分析。

```text
阶段一  python3 douyin_claw.py batch --queries ... --topic-keywords ...
阶段二  Agent 读 analysis_input（或 analysis_prompt）在本对话归纳、核实、出报告
```

| 参数 | 必填 | 含义 |
|------|------|------|
| `--queries` | ✅ | 一个或多个搜索词 |
| `--topic-keywords` | ✅ | 逗号分隔；描述须命中至少其一 |
| `--enterprise-keywords` | | 省略则用通用企业词 |
| `--name` | | JSON `report_name`，默认 `douyin_batch` |
| `--months` | | 默认 `3` |
| `--per-query` | | 每词条数，默认 `35` |
| `--comments-per-video` | | `>0` 时生成 `analysis_prompt` |
| `--task` | | 写入 analysis 任务文案 |

**场景示例：企业火灾**（词表仅写在 SKILL，不进代码）

```bash
python3 douyin_claw.py batch \
  --name 企业火灾 \
  --queries 企业火灾 工厂火灾 厂房起火 仓库火灾 园区火灾 企业着火 生产车间火灾 \
  --topic-keywords 火灾,着火,起火,爆炸,燃烧,浓烟,消防,失火,爆燃,火势 \
  --months 3 --per-query 35 \
  --task "归纳涉事企业、地点、时间线与待核实项"
```

返回 JSON 关键字段：`next_step`、`analysis_input`、`events[]`（含 `company`/`address`/`event_date`/`merge_count`/`video_urls`）。

## 单关键词分析流程（search / analyze）

```text
search / analyze
    → 描述（search 结果里的 title/desc，或 video 详情）
    → 评论（`core/api.py` comment/list API）
    → analysis_input / analysis_prompt（结构化文本）
    → LLM（Cursor Agent、OpenAI、元宝等）做归纳、舆情、实体抽取

视频画面/口播（可选）:
    video_url → ASR（Whisper）或多模态模型 → 并入 analysis_prompt
```

```bash
# 单条：详情 + 30 条评论 + analysis_input
python3 douyin_claw.py video --comments 30 "https://www.douyin.com/video/xxx"

# 批量：搜索 10 条 + 每条 20 评论 + 聚合 analysis_prompt
python3 douyin_claw.py analyze --num 10 --comments-per-video 20 \
  --task "归纳企业火灾涉事单位、地点与舆论焦点" "企业火灾"
```

将 JSON 中的 `analysis_prompt` 交给 Agent 继续分析；或在本对话中粘贴该字段请求总结。

## 运行命令

```bash
# 1) 登录（首次或 Cookie 过期）
cslogin cookie douyin
# 或
python3 douyin_claw.py login

# 2) 搜索视频（JSON stdout）
python3 douyin_claw.py search "企业火灾"
python3 douyin_claw.py search --num 30 --publish-time 180 --sort 2 "工厂火灾"
```

### 搜索参数

| 参数 | 含义 |
|------|------|
| `--num` | 数量，默认 20 |
| `--sort` | `0` 综合 `1` 最多点赞 `2` 最新发布 |
| `--publish-time` | `0` 不限 `1` 一天 `7` 一周 `180` 半年 |
| `--filter-duration` | 空不限；`0-1` `1-5` `5-10000` |
| `--search-range` | `0` 不限 `1` 看过 `2` 未看过 `3` 关注的人 |
| `--content-type` | `0` 不限 `1` 视频 `2` 图文 |

## 搜索原理

与 [DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 搜索原理一致，**代码已内置在 `douyin_claw/core/`**，无需外部工程：

1. **API 搜索**：`core/api.py` + `static/dy_ab.js`（`a_bogus` 签名，需 `npm install`，仅依赖 `jsrsasign`）
2. **Playwright 兜底**：API 风控时拦截 `general/search/single`

```bash
cd llm-claw/douyin_claw
pip install -r requirements.txt
npm install   # 仅 jsrsasign，用于 a_bogus 签名
playwright install chromium
python3 douyin_claw.py login
```

## 输出说明

`search` 返回 JSON：

- `videos[]`：每条含 `aweme_id`、`title`、`author`、`create_time_fmt`、`share_url`、`cover_url`、`video_url`、互动数据等
- `search_method`：`api` 或 `playwright`
- `count`：结果数量

## Cookie 获取（与 DouYin_Spider 对齐）

DouYin_Spider 的流程：**日常 Chrome 登录 → F12 复制 Cookie**。  
本工程额外支持 **从已打开的 Chrome 自动读取**（读本机 Cookie 数据库，不控制浏览器）。

### 默认：`cslogin cookie douyin`

```bash
cslogin cookie douyin
```

1. 在本机 **Google Chrome** 打开抖音主页（脚本不控制浏览器）
2. **登录**，并 **搜索一次**（默认关键词「火灾」）完成抖音二次验证
3. 回到终端 **按 Enter** → 自动从 Chrome 配置读取 Cookie 并保存

环境变量 `DOUYIN_LOGIN_VERIFY_KEYWORD` 可改搜索验证关键词。

若已完成登录+搜索，仅刷新 Cookie、跳过引导：

```bash
cslogin cookie douyin read --quick
```

多 Chrome 用户：

```bash
cslogin cookie douyin read --list-profiles
cslogin cookie douyin read --profile "Profile 1"
```

Mac 若报读取失败：系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 勾选终端/Cursor。

保存成功后，若存在 `$LLM_CLAW_ENV_PATH/wechat_token_sync.sh`（与 `cslogin cookie yuanbao` 共用），会自动将 `douyin_env.json` 同步到远程服务器。示例：`cslogin_release/wechat_token_sync.sh.example`。

### 备选：F12 手动复制

```bash
cslogin cookie douyin f12
```

1. `open` 打开抖音 → 登录 → F12 复制 Cookie
2. 按 Enter（Mac 从剪贴板读取）

### 其他

```bash
cslogin cookie douyin import --env ~/workspace/gpt/DouYin_Spider/.env
cslogin cookie douyin chrome   # CDP（不推荐，可能无法交互）
```

| 方式 | 需搜索验证 | 需 F12 | 推荐 |
|---|---|---|---|
| `cookie read`（默认） | ✅ 引导后按 Enter 读 profile | 否 | ✅ |
| `cookie read --quick` | 否（假定已完成） | 否 | 备用 |
| `cookie f12` | 建议 | 是 | 备用 |

## Cookie 过期 / 风控拦截

**Cookie 无效**（「请先登录」「Cookie 无效」等）：

```bash
cslogin cookie douyin              # 真实 Chrome（推荐）
cslogin cookie douyin import       # F12 粘贴
```

**搜索被风控**（JSON 含 `search_nil_type: verify_check`）：

API 直连常返回 `verify_check`；**实际结果靠 Playwright 内置 Chromium 兜底**（须 `playwright install chromium`，与 DouYin_Spider 相同，勿用 headless 的 `channel=chrome`）。

**Playwright 报 `ERR_CONNECTION_RESET`**（无法连接 douyin.com）：

1. 先在 Chrome 确认能否打开 https://www.douyin.com
2. Chrome 能开但脚本不行：Playwright 默认不走系统代理，需手动设置，例如：
   ```bash
   export HTTPS_PROXY=http://127.0.0.1:7890   # Clash 等端口按实际修改
   .venv/bin/python douyin_claw.py search --num 5 "火灾"
   ```
3. 若 API 可用（DouYin_Spider 的 Cookie 能通过 API 搜索），可临时跳过 Playwright：
   ```bash
   export DY_COOKIES='…'   # 来自 DouYin_Spider/.env
   export DOUYIN_CLAW_NO_PW_SEARCH=1
   ```

**verify_check 时的 Cookie 处理**：

1. 重新登录（浏览器由你完全操控，**登录并手动搜索验证后**回到终端按 Enter）：
   ```bash
   cslogin cookie douyin
   ```
2. 或复用 DouYin_Spider 已验证 Cookie：`export DY_COOKIES='…'`（来自 `.env`），或写入 `claw_env/douyin_env.json`
3. 验证：`.venv/bin/python douyin_claw.py search --num 5 "火灾"`

若 API 有结果但被 `--publish-time` 等筛掉，JSON 会含 `raw_count` / `filtered_out`，可尝试去掉时间筛选。

## 依赖

```bash
cd llm-claw/douyin_claw
pip install -r requirements.txt
playwright install chromium
```

## 示例

**用户**：「搜一下抖音上世界杯信息，要 30 条」

```bash
python3 douyin_claw.py search --num 30 --publish-time 180 "世界杯"
```
