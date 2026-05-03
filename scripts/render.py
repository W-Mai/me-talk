#!/usr/bin/env python3
"""
me-talk · render
Inject stats.json + AI-authored Markdown portrait + curated quotes into the
HTML template, producing a standalone `<root>/index.html`.

Inputs:
  <root>/analysis/stats.json            — from analyze.py
  <root>/analysis/portrait.md           — full portrait, written by AI
  <root>/analysis/tldr.md               — one-paragraph TL;DR, written by AI (optional)
  <root>/analysis/trait_commentary.md   — short note next to radar (optional)
  <root>/analysis/timeline_commentary.md,
  <root>/analysis/projects_commentary.md,
  <root>/analysis/words_commentary.md   — optional inline notes
  <root>/analysis/quotes.json           — [{"text": "...", "tag": "..."}]

Output:
  <root>/index.html
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

TEMPLATE_NAME = "index.html.tmpl"

PLACEHOLDERS = {
    "<!--TLDR_PLACEHOLDER-->":               "tldr.md",
    "<!--TRAIT_COMMENTARY_PLACEHOLDER-->":   "trait_commentary.md",
    "<!--TIMELINE_COMMENTARY_PLACEHOLDER-->":"timeline_commentary.md",
    "<!--PROJECTS_COMMENTARY_PLACEHOLDER-->":"projects_commentary.md",
    "<!--WORDS_COMMENTARY_PLACEHOLDER-->":   "words_commentary.md",
    "<!--PORTRAIT_PLACEHOLDER-->":           "portrait.md",
}


def read_optional(p: Path) -> str:
    if p.exists():
        return p.read_text("utf-8").strip()
    return ""


def render(root: Path, skill_dir: Path):
    tmpl_path = skill_dir / "assets" / TEMPLATE_NAME
    if not tmpl_path.exists():
        print(f"ERROR: template not found: {tmpl_path}", file=sys.stderr)
        return 2
    tmpl = tmpl_path.read_text("utf-8")

    stats_path = root / "analysis" / "stats.json"
    if not stats_path.exists():
        print(f"ERROR: {stats_path} missing. Run analyze.py first.", file=sys.stderr)
        return 2

    stats_text = stats_path.read_text("utf-8")

    # Inject inline markdown sections
    for marker, fname in PLACEHOLDERS.items():
        text = read_optional(root / "analysis" / fname)
        if not text:
            # Leave a subtle hint so the page renders even without AI write-up.
            if marker == "<!--PORTRAIT_PLACEHOLDER-->":
                text = ("_画像待写_ —— 让 AI 读取 `analysis/stats.json` 和 `raw/*/messages.jsonl`,"
                        "按 `references/portrait-template.md` 规范填 `analysis/portrait.md`,然后重跑 render。")
            else:
                text = ""
        tmpl = tmpl.replace(marker, text)

    # Inject stats (raw JSON) and quotes
    tmpl = tmpl.replace("<!--STATS_JSON_PLACEHOLDER-->", stats_text)

    quotes_path = root / "analysis" / "quotes.json"
    if quotes_path.exists():
        quotes = quotes_path.read_text("utf-8").strip() or "[]"
    else:
        quotes = "[]"
    tmpl = tmpl.replace("<!--QUOTES_JSON_PLACEHOLDER-->", quotes)

    out = root / "index.html"
    out.write_text(tmpl, "utf-8")
    print(f"rendered {out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render me-talk index.html from stats + AI Markdown.")
    ap.add_argument("--output", "-o", default=".",
                    help="Project root: uses <root>/analysis/ as input, writes <root>/index.html. Default: CWD.")
    ap.add_argument("--skill-dir", default=None,
                    help="Path to this skill (where assets/index.html.tmpl lives). "
                         "Default: directory containing this script's parent.")
    args = ap.parse_args(argv)

    root = Path(args.output).resolve()
    skill_dir = Path(args.skill_dir).resolve() if args.skill_dir \
        else Path(__file__).resolve().parent.parent
    sys.exit(render(root, skill_dir))


if __name__ == "__main__":
    main()
