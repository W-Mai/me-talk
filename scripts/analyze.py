#!/usr/bin/env python3
"""
me-talk · analyze
Aggregate <root>/raw/<tool>/messages.jsonl into <root>/analysis/stats.json.

Produces everything the HTML template (`assets/index.html`) needs to render:
  - total_messages, per_tool, generated_at
  - length_histogram, timeline_by_date, by_hour, by_weekday
  - projects_top (top 25)
  - traits: regex-bucketed message counts (tone + mode + domain)
  - tool_trait: per-tool trait counts
  - top_en: top latin word tokens
  - top_cn: top CJK bigrams
  - trait_examples: short sample quotes per trait
  - notable_quotes: short punchy user lines likely to appear in the portrait
"""
from __future__ import annotations
import argparse, collections, json, re, sys
from datetime import datetime, timezone
from pathlib import Path


TOOLS = ["claude-code", "opencode", "kiro-cli", "kiro-gui", "trae"]

# ---------------------------------------------------------------------------
# Trait patterns (tone / mode / domain)
# ---------------------------------------------------------------------------

# Trait detection patterns (bilingual: zh + en in the same list).
# All regexes run case-insensitive. Chinese phrases don't need \b; English
# tokens are wrapped with \b to avoid sub-word matches.
PATTERNS: dict[str, list[str]] = {
    # ---------- Tone ----------
    "frustration": [
        # zh
        r"(卧槽|离谱|气死|烦死|崩溃|无语|服了|醉了|我去|天啊)",
        r"为什么还.{0,3}不", r"怎么就.{0,3}不", r"哎+",
        # en
        r"\b(wtf|fuck|shit|damn|ugh|argh|stupid|idiot|annoying|frustrat\w*)\b",
        r"\bwhat the (hell|heck|f\w*)\b",
        r"\bthis is (ridiculous|insane|stupid)\b",
    ],
    "praise_ai": [
        # zh
        r"(厉害|完美|漂亮|搞定|太棒|很棒|牛.?|666+|yyds)",
        r"(这就对了|这才对|就是这样|太好了|不错)",
        # en
        r"\b(nice|perfect|awesome|great|good job|well done|brilliant|"
        r"excellent|exactly|thats? it|that works|lgtm|looks? good)\b",
    ],
    "self_deprecation": [
        # zh
        r"(我又.{0,6}(忘|错|搞))", r"(我太(蠢|傻|菜))",
        r"(哈哈哈|认栽|算我输)",
        # en
        r"\bmy (bad|fault|mistake)\b",
        r"\bi('?m| am) (an idiot|so dumb|so stupid|the problem)\b",
        r"\boops+\b",
    ],
    "politeness": [
        # zh
        r"(请|麻烦你|谢谢|感谢|多谢)",
        # en
        r"\b(please|thanks|thank you|appreciate it|if you (don'?t|do not) mind)\b",
    ],
    "directness": [
        # zh
        r"^(直接|就|别|不要|给我)",
        r"(别废话|别啰嗦|先|立刻|马上)",
        # en
        r"\b(just|simply|no (need|more)|stop|don'?t|do not|right now|asap)\b",
        r"^(do|make|give|fix|write|show|list|run|build)\b",
    ],

    # ---------- Work mode ----------
    "thinking_aloud": [
        # zh
        r"(我觉得|我想|我感觉|我认为|我怀疑|会不会是)",
        r"(是不是.{0,5}导致|会不会.{0,5}是)",
        # en
        r"\bi (think|feel|guess|suspect|wonder|bet)\b",
        r"\bmaybe (it'?s|the|because|we)\b",
        r"\b(could|might) (it be|this be|that be)\b",
    ],
    "precision_request": [
        # zh
        r"(最小|精确|严格|只|仅|必须|不要加|不要改|不要动)",
        r"(按照.{0,10}风格|保持.{0,5}一致)",
        # en
        r"\b(exactly|precisely|strictly|only|minimal|do not (add|change|touch)|"
        r"don'?t (add|change|touch)|keep.{0,10}(consistent|unchanged))\b",
    ],
    "explore_mode": [
        # zh
        r"(看一下|看看|探索|熟悉|分析|梳理|理解|读一下)",
        # en
        r"\b(explore|look (at|into)|read (the|this)|understand|walk (me )?through|"
        r"inspect|analy[sz]e|overview)\b",
    ],
    "design_mode": [
        # zh
        r"(设计|架构|方案|选型|取舍|抽象|重构)",
        # en
        r"\b(design|architecture|approach|trade.?offs?|refactor|abstract(ion)?|"
        r"plan (this|the|out)|how (should|would) we)\b",
    ],
    "debug_mode": [
        # zh
        r"(调试|报错|崩|死循环|不对|不生效|不工作)",
        r"(为什么.{0,5}不(工作|生效|对))",
        # en
        r"\b(debug|error|panic|exception|crash(ed|ing)?|hang(s|ing|ed)?|stuck|"
        r"broken|failing|infinite loop|doesn'?t work|not working|won'?t start|"
        r"segfault|stack trace|traceback)\b",
    ],
    "doc_mode": [
        # zh
        r"(写.{0,5}(文档|博客|注释|说明))",
        r"(润色|整理|总结)",
        # en
        r"\b(write|draft|polish).{0,15}(doc|docs|readme|blog|post|comment|"
        r"comments|description)\b",
        r"\b(summari[sz]e|tidy up|clean up|rewrite this)\b",
    ],

    # ---------- Collaboration ----------
    "correct_ai": [
        # zh
        r"(不对|不是|错了|你.{0,5}(误解|搞错|理解错))",
        r"(我说的是|我想要|你给我|做的是|不是这个)",
        # en
        r"\b(no|nope|wrong|that'?s (wrong|not (it|right)))\b",
        r"\byou (misunderstood|got (it|this) wrong|are wrong)\b",
        r"\bi (said|meant|want|asked for)\b",
        r"\bnot what i (said|meant|want|asked)\b",
    ],
    "continue_request": [
        # zh
        r"^\s*(继续|接着|下一步|然后呢)\s*$",
        # en
        r"^\s*(go on|continue|keep going|next|and then|proceed)\s*\.?\s*$",
    ],
    "stop_request": [
        # zh
        r"(先停|先别|等等|先等|打住|住手|停一下)",
        # en
        r"\b(stop|wait|hold on|hang on|pause|halt|back up|undo that)\b",
    ],
    "meta_rule": [
        # zh
        r"(别|不要).{0,10}(注释|emoji|废话|啰嗦|胡编|瞎.)",
        r"(记住|以后|之后|别再|不要再|下不为例)",
        # en
        r"\b(remember|from now on|going forward|never (do|add|use) this|"
        r"always (do|use|keep)|stop (doing|adding))\b",
        r"\bdon'?t (add|use|write|include) (comments|emoji|emojis)\b",
    ],

    # ---------- Domain (technology — already language-neutral) ----------
    "rust":             [r"\b(rust|cargo|trait|lifetime|tokio|serde)\b"],
    "cpp":              [r"\b(c\+\+|cpp|cmake|gcc|clang|ninja|conan)\b"],
    "python":           [r"\b(python|pip|uv|pytest|numpy|pandas)\b"],
    "web_frontend":     [r"\b(react|vue|vite|tailwind|html|css|javascript|typescript|ts|tsx|jsx)\b"],
    "ai_coding_meta":   [r"\b(claude|kiro|opencode|trae|cursor|prompt|agent|skill)\b"],
}

STOPWORDS_CN = set("""
的 了 是 我 你 他 她 它 这 那 在 和 与 也 就 都 还 不 吗 吧 呢 啊 嗯 哦
把 被 给 对 让 从 向 到 又 再 只 又 都 还 更 很 非常 一下 一点 现在 今天
请 帮 麻烦 可以 能不能 能 是不是 会不会 有没有 是否 为什么 怎么 怎么样 如何
一个 一些 什么 这个 那个 这些 那些 什么 哪个 哪里
然后 但是 如果 可能 因为 所以 而且 或者 这样 那样
""".split())

STOPWORDS_EN = set("""
the a an of in on to for is are was were be been being and or not no
i my me you your he she it this that these those them they we us our
do does did done have has had will would should could can may might
so but if when then there here what which where how why who whom
code file run make get let use using used new one two old also just
yeah ok okay well actually really kind sort lot lots bit thing things
into from about with without over under such very more most less least
good bad fine nice great only only's still even else already yet
like as than too way ways want wanted wants needed needs got gets
""".split())


def tokenize(text: str):
    en = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text)]
    cn_bi = []
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(chunk) - 1):
            cn_bi.append(chunk[i:i + 2])
    return en, cn_bi


def load(root: Path):
    rows, per_tool = [], {}
    for t in TOOLS:
        p = root / "raw" / t / "messages.jsonl"
        if not p.exists():
            per_tool[t] = 0
            continue
        count = 0
        with open(p, encoding="utf-8") as f:
            for line in f:
                rows.append(json.loads(line))
                count += 1
        per_tool[t] = count
    return rows, per_tool


def analyze(root: Path):
    compiled = {k: [re.compile(x, re.I) for x in v] for k, v in PATTERNS.items()}
    rows, per_tool = load(root)
    total = len(rows)
    if total == 0:
        print("WARN: no data rows found. Run extract first.", file=sys.stderr)

    by_date = collections.Counter()
    by_hour = collections.Counter()
    by_weekday = collections.Counter()
    projects = collections.Counter()

    trait_counts = {k: 0 for k in compiled}
    trait_examples = {k: [] for k in compiled}
    tool_trait = {t: {k: 0 for k in compiled} for t in TOOLS}

    len_bins = [0, 10, 30, 100, 300, 1000, 3000, 10**9]
    len_labels = ["<10", "10-30", "30-100", "100-300", "300-1k", "1k-3k", "3k+"]
    len_hist = [0] * len(len_labels)

    en_counter = collections.Counter()
    cn_counter = collections.Counter()

    notable = []
    home = str(Path.home())

    for r in rows:
        t = r["tool"]
        txt = r.get("user_text") or ""
        ts_ms = r.get("ts_ms")
        if ts_ms:
            try:
                dt = datetime.fromtimestamp(ts_ms / 1000)
                by_date[dt.date().isoformat()] += 1
                by_hour[dt.hour] += 1
                by_weekday[dt.weekday()] += 1
            except Exception:
                pass
        proj = (r.get("project") or "unknown").replace(home, "~")
        projects[proj] += 1

        L = len(txt)
        for i in range(len(len_bins) - 1):
            if len_bins[i] <= L < len_bins[i + 1]:
                len_hist[i] += 1
                break

        for name, pats in compiled.items():
            if any(p.search(txt) for p in pats):
                trait_counts[name] += 1
                tool_trait[t][name] += 1
                if len(trait_examples[name]) < 5 and 10 < L < 200:
                    trait_examples[name].append({"tool": t, "text": txt, "ts": r.get("ts")})

        en, bi = tokenize(txt)
        for w in en:
            if w in STOPWORDS_EN or len(w) > 20:
                continue
            en_counter[w] += 1
        for b in bi:
            cn_counter[b] += 1

        # Collect short punchy lines that are likely to end up in the portrait.
        # Trigger on meta-rule / correction phrases in either language.
        _notable_triggers_zh = ("别", "不要", "记住", "以后", "不是这个", "我说的是")
        _notable_triggers_en = (" remember ", " never ", " always ", " don't ",
                                " dont ", " not what i ", " i said ", " i meant ",
                                " stop doing ")
        if 10 < L < 120:
            low = " " + txt.lower() + " "
            if any(k in txt for k in _notable_triggers_zh) \
               or any(k in low for k in _notable_triggers_en):
                notable.append({"tool": t, "ts": r.get("ts"), "text": txt})

    # Drop the user's home-dir basename from top words — it leaks from CWD
    # strings embedded in pasted logs/paths and isn't vocabulary.
    home_base = Path.home().name.lower()
    top_en = [[w, c] for w, c in en_counter.most_common(100)
              if c > 5 and w != home_base][:80]

    def cn_ok(bi):
        return not any(ch in STOPWORDS_CN for ch in bi)

    top_cn = [[w, c] for w, c in cn_counter.most_common(500) if cn_ok(w)][:80]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_messages": total,
        "per_tool": per_tool,
        "length_histogram": {"labels": len_labels, "counts": len_hist},
        "timeline_by_date": [{"date": d, "count": c} for d, c in sorted(by_date.items())],
        "by_hour": [by_hour.get(h, 0) for h in range(24)],
        "by_weekday": [by_weekday.get(w, 0) for w in range(7)],
        "projects_top": [{"project": p, "count": c} for p, c in projects.most_common(25)],
        "traits": trait_counts,
        "trait_examples": trait_examples,
        "tool_trait": tool_trait,
        "tool_msg_count": {t: per_tool.get(t, 0) for t in TOOLS},
        "top_en": top_en,
        "top_cn": top_cn,
        "notable_quotes": notable[:60],
    }

    out_dir = root / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "stats.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"wrote {out_path}")

    # short console summary
    print(f"total msgs: {total}")
    print("top traits:")
    for k, v in sorted(trait_counts.items(), key=lambda kv: -kv[1])[:10]:
        pct = f"{v * 100 / total:.1f}%" if total else "n/a"
        print(f"  {k:22s} {v:5d}  ({pct})")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aggregate me-talk raw/ into analysis/stats.json")
    ap.add_argument("--output", "-o", default=".",
                    help="Root dir with raw/, writes to <root>/analysis/. Default: CWD.")
    args = ap.parse_args(argv)
    analyze(Path(args.output).resolve())


if __name__ == "__main__":
    main()
