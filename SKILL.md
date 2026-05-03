---
name: me-talk
description: Analyse how the user talks to AI coding assistants. Harvests user messages (+ light AI context) from local storage of five tools — claude-code, opencode, kiro-cli, kiro-gui, trae — then produces a written personality portrait backed by quantitative stats and a self-contained HTML dashboard. Use when the user asks to "analyse how I talk to AI / Claude / Cursor / Kiro / Trae", "give me a portrait from my chat history", "根据我和 AI 的聊天记录分析我的性格 / 说话风格 / 画像", or wants to compile cross-tool conversation stats.
---

# me-talk

给用户做一份基于聊天记录的"AI 对话画像":从本地五个工具的存储里抽取**用户消息**,聚合成统计,再由 AI 写一份带数据锚点的文字画像,最后渲染成单页 HTML。

## 产物

在调用时的 CWD(或 `--output` 指定目录)生成:

```
./raw/<tool>/messages.jsonl     # 每条用户消息 + 前后 1-2 条 AI 上下文
./raw/<tool>/stats.json         # 每个工具的轻量计数
./analysis/stats.json           # 聚合统计 (供 HTML 使用)
./analysis/portrait.md          # 完整画像 (由 AI 写)
./analysis/tldr.md              # 一段话画像 (由 AI 写)
./analysis/quotes.json          # 精选金句 (由 AI 选)
./analysis/*_commentary.md      # 各图下的短注 (可选,由 AI 写)
./index.html                    # 自包含可视化,直接浏览器打开
```

## 支持的工具

| tool | 来源 |
|---|---|
| `claude-code` | `~/.claude/projects/*/*.jsonl` |
| `opencode` | `~/.local/share/opencode/storage/{session,message,part}/` |
| `kiro-cli` | `~/Library/Application Support/kiro-cli/data.sqlite3` (conversations_v2) |
| `kiro-gui` | `~/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent/*/*.chat` |
| `trae` | `~/Library/Application Support/Trae/User/workspaceStorage/*/state.vscdb` |

已有的 extractor 仅限这 5 个。存储层 schema 改动需要重调脚本。

## 流程

分四步。**不要跳过任何一步**;缺哪一步 HTML 就渲染不全。

### 1. Extract

```bash
python3 {SKILL_DIR}/scripts/extract.py --output "$PWD"
# or: --tools claude-code,opencode
```

- 轻度脱敏(sk-/Bearer/access_token/ghp_/lark token)已集成,**不擦**路径、项目名、内部 ID(用户自己看的)
- Kiro GUI 的 5000+ `.chat` 文件大多是同一 session 的回放 snapshot,脚本会按 `(user_text[:300], session_id)` 去重
- 所有工具的 AI 都只保留前后最近一条,且最多 600 字,避免 context 爆炸
- 处理时间:首次 30s-2min(主要花在 Kiro GUI)

### 2. Analyze

```bash
python3 {SKILL_DIR}/scripts/analyze.py --output "$PWD"
```

产出 `analysis/stats.json`。维度清单在脚本顶部 `PATTERNS` —— 语气(直给/纠偏/自嘲/客套)、工作模式(explore/design/debug/doc)、协作(continue/stop/立规矩)、技术栈(rust/cpp/python/web)。

### 3. 写画像(你来做)

这一步**必须亲自读数据再写**,不是套模板。

先看 `references/portrait-template.md`(严格遵守里面的写作规范),然后:

1. `cat analysis/stats.json` 看完整指标
2. 抽样读 `raw/*/messages.jsonl` 里 **至少 50 条**(每个工具捞一些),特别是 `notable_quotes` 里那批
3. 如果用户有 `~/.claude/CLAUDE.md` / `~/.config/opencode/AGENTS.md`,读一下,对照「明规则 vs 实际说话风格」的自洽性 —— 这是画像里最值得写的一节
4. 按 `references/portrait-template.md` 产出这几个文件(最少先出 `portrait.md` + `tldr.md` + `quotes.json`):

   ```
   analysis/portrait.md              (~1000-1500 字, 8 个 ### 小节)
   analysis/tldr.md                  (2-4 句)
   analysis/quotes.json              ([{"text":"...","tag":"..."}] × 8-12)
   analysis/trait_commentary.md      (雷达图右侧 2-3 句)   [可选]
   analysis/timeline_commentary.md   (日期图下方 1-2 句)    [可选]
   analysis/projects_commentary.md   (项目图下方 2-4 句)    [可选]
   analysis/words_commentary.md      (词云下方 1-2 句)      [可选]
   ```

**硬性要求**(否则画像会变成 LinkedIn 式空话):

- 每节必须带一个来自 `stats.json` 的数字
- 每节必须嵌一句**原文引用**(从 raw 里找,照抄,别润色)
- 不给价值判断(不说「这很好/这是优点」),只写中性观察
- 不要写开头套话(「综上所述」「从数据中可以看出」)

反例和详细规则全部在 `references/portrait-template.md`,**写之前必读**。

### 4. Render

```bash
python3 {SKILL_DIR}/scripts/render.py --output "$PWD"
```

把 `analysis/*.md` + `analysis/stats.json` + `analysis/quotes.json` 注入 `assets/index.html.tmpl`,生成 `index.html`(自包含,走 CDN 拉 chart.js/marked)。打开方式:

```bash
open index.html     # macOS
# 或 python3 -m http.server 9823 && open http://localhost:9823
```

## 常见问题

### 数据量太小怎么办?

如果某个工具的 `messages.jsonl` 少于 20 条,画像里就别单独把这个工具拎出来说。侧重数据多的那 1-2 个工具。

### Kiro GUI 数据量异常大

`.chat` 文件是每次对话的全量 snapshot,原始条数经常 4 万+,去重后才回到正常量级(约 1000)。`analysis/raw/kiro-gui/stats.json` 里有 `raw_before_dedup` 字段可以确认脚本工作正常。

### 重跑顺序

只改画像不改数据:跳过 extract 和 analyze,只重跑 render。改了 extractor 过滤逻辑:全跑。

### HTML 没内容/图表不显示

需要 HTTP 服务而不是 `file://`:marked 和 chart.js 是 CDN 脚本。用 `python3 -m http.server` 起一个本地服务就行。

## 运行示意(完整一次)

```bash
mkdir -p ~/me-talk-report && cd ~/me-talk-report
python3 ~/.claude/skills/me-talk/scripts/extract.py --output "$PWD"
python3 ~/.claude/skills/me-talk/scripts/analyze.py --output "$PWD"
# --- 到这一步,AI 读 stats.json + 抽样 raw/,按 portrait-template.md 规范写 analysis/*.md + quotes.json ---
python3 ~/.claude/skills/me-talk/scripts/render.py --output "$PWD"
open index.html
```

`{SKILL_DIR}` 指这个 skill 所在目录,Claude Code 下通常是 `~/.claude/skills/me-talk`,OpenCode 下是 `~/.agents/skills/me-talk` 或 `~/.config/opencode/skills/me-talk`。
