# me-talk

> A Claude Code / OpenCode **skill** that turns your chat history with AI coding
> assistants into a quantitative, data-backed portrait of *how* you talk to AI.

`me-talk` harvests your user messages (plus the nearest AI reply for context)
from the local storage of five AI coding tools, aggregates them into a set of
behavioural traits (tone, collaboration mode, work mode), then produces a
single-page HTML dashboard with charts + an AI-written narrative portrait.

Everything runs locally. No data leaves your machine.

![radar view](docs/screenshots/radar.png)

## What it shows

- **KPI row** — total messages, days with data, tools used, average message length
- **Trait radar + bar chart** — directness, correction, precision requests,
  explore / design / debug modes, meta-rules, etc.
- **Time rhythm** — by hour, weekday, and date
- **Tool mix** — which AI assistant you actually lean on
- **Projects** — top directories the conversations happened in
- **Word clouds** — Chinese bigrams + English words
- **Length histogram** — how verbose each message tends to be
- **Quotes + full portrait** — AI-written, backed by the numbers

![length histogram](docs/screenshots/length.png)

## Supported tools

| Tool | Source of truth |
|---|---|
| `claude-code` | `~/.claude/projects/*/*.jsonl` |
| `opencode`    | `~/.local/share/opencode/storage/{session,message,part}/` |
| `kiro-cli`    | `~/Library/Application Support/kiro-cli/data.sqlite3` |
| `kiro-gui`    | `~/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent/*.chat` |
| `trae`        | `~/Library/Application Support/Trae/User/workspaceStorage/*/state.vscdb` |

Paths are macOS-style. Linux/Windows paths haven't been tested yet.

## Install

Clone into the skills directory your agent reads:

```bash
# Claude Code
git clone https://github.com/W-Mai/me-talk ~/.claude/skills/me-talk

# OpenCode
git clone https://github.com/W-Mai/me-talk ~/.agents/skills/me-talk
```

Or symlink one checkout into both:

```bash
git clone https://github.com/W-Mai/me-talk ~/src/me-talk
ln -s ~/src/me-talk ~/.claude/skills/me-talk
ln -s ~/src/me-talk ~/.agents/skills/me-talk
```

Requires Python 3.10+. No third-party packages.

## Usage

Once installed, just ask your agent:

> 帮我分析一下我跟 AI 的聊天记录 / analyse how I talk to Claude

The agent will read `SKILL.md` and drive the pipeline. If you want to run it
manually:

```bash
mkdir -p ~/my-portrait && cd ~/my-portrait

# 1. harvest messages from local storage
python3 ~/.claude/skills/me-talk/scripts/extract.py --output .

# 2. aggregate into stats
python3 ~/.claude/skills/me-talk/scripts/analyze.py --output .

# 3. (agent step) write analysis/portrait.md + tldr.md + quotes.json
#    following references/portrait-template.md

# 4. render the dashboard
python3 ~/.claude/skills/me-talk/scripts/render.py --output .

open index.html   # or: python3 -m http.server 8000 && open http://localhost:8000
```

## Output layout

```
./raw/<tool>/messages.jsonl     # normalised user turns + nearest AI context
./raw/<tool>/stats.json         # per-tool row count + date range
./analysis/stats.json           # aggregated traits, timeline, word frequencies
./analysis/portrait.md          # full narrative portrait (AI-written)
./analysis/tldr.md              # one-paragraph summary (AI-written)
./analysis/quotes.json          # curated punchy lines
./analysis/*_commentary.md      # inline notes next to charts (AI-written, optional)
./index.html                    # standalone dashboard, no server needed after first load
```

## Privacy

- All extraction and rendering runs **locally**.
- Light redaction covers `sk-*`, `Bearer *`, `access_token`, `ghp_*`, and
  common Slack/feishu token shapes. Paths, project names, and everything else
  are preserved — this is your private workspace.
- The skill repo itself contains **no user data**. Generated `raw/`, `analysis/`,
  and `index.html` are in `.gitignore` at the skill level; your own project
  directory is yours to manage.
- Screenshots in this README come from the author's real data — they expose
  high-level trait percentages (e.g. "8.7% correction"), not conversation
  content.

## Patterns are bilingual

The trait-detection regex dictionary covers **Chinese and English in
parallel**, so you get meaningful output whether you prompt in 中文, English,
or mix them freely. To extend: edit `PATTERNS` in `scripts/analyze.py`.

## Design notes

- **Stats are deterministic, portrait is AI-authored.** The same raw data
  always yields the same `stats.json`; the portrait is rewritten per run so it
  stays grounded in current numbers instead of a canned template.
- **Portrait has hard rules.** `references/portrait-template.md` enforces:
  every section must cite a number from `stats.json`, every section must
  include a verbatim quote from `raw/`, no value judgements, no corporate
  filler. This is how you avoid LinkedIn-style fluff.
- **Kiro GUI gotcha.** The `.chat` files are full-session snapshots, not
  append-only logs, so the same turn appears in thousands of files. The
  extractor deduplicates on `(user_text[:300], session_id)` — expect a
  ~40× reduction from raw file count to final turn count.

## License

MIT — see [LICENSE](LICENSE).

---

## 中文帮助段

这是一个 Claude Code / OpenCode 的 skill,能够:

1. **抽取**你跟 5 种 AI 编程助手(Claude Code / OpenCode / Kiro CLI / Kiro GUI / Trae)
   本地留存的聊天记录中的用户发言
2. **聚合**出语气、工作模式、协作方式等多个维度的统计
3. **生成**一份由 AI 根据数字和原话现写的性格画像,附单页 HTML 可视化

用法:在 agent 里说「分析下我跟 AI 的聊天记录」或「根据聊天记录给我画像」即可触发。
agent 会按 `SKILL.md` 的四步流程跑完 extract → analyze → 写画像 → render。

关键字可以是中文也可以是英文,关键词字典两边都兼容。

**数据全部在本地处理,不会离开这台机器**。想推送到 GitHub 做公开 repo 的话,
`.gitignore` 已经把 `raw/` `analysis/` `index.html` 都挡住了,不用担心。
