#!/usr/bin/env python3
"""
me-talk · extract
Harvest user messages (+ light AI context) from supported AI coding tools' local
storage into a normalised JSONL per tool.

Supported tools (built-in extractors):
    claude-code  — ~/.claude/projects/*/*.jsonl
    opencode     — ~/.local/share/opencode/storage/{session,message,part}/
    kiro-cli     — ~/Library/Application Support/kiro-cli/data.sqlite3
    kiro-gui     — ~/Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent/*/*.chat
    trae         — ~/Library/Application Support/Trae/User/workspaceStorage/*/state.vscdb

Output:
    <output>/raw/<tool>/messages.jsonl
    <output>/raw/<tool>/stats.json

Schema (per line):
    {
      "tool":        str,
      "ts":          iso8601 | null,
      "ts_ms":       int | null,
      "session_id":  str | null,
      "project":     str | null,
      "user_text":   str,
      "prev_ai":     str | null,    # trimmed
      "next_ai":     str | null
    }

Redaction:
    Light — only strings that look like secrets/tokens are replaced with
    <REDACTED>. No paths, no names, no feishu IDs.
"""
from __future__ import annotations

import argparse, json, os, re, sqlite3, sys, traceback
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
MAX_AI_SNIPPET = 600

TOOL_NAMES = ("claude-code", "opencode", "kiro-cli", "kiro-gui", "trae")

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

REDACT_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{10,}\b", re.I),
    re.compile(
        r"\b(access_token|refresh_token|api[_\-]?key|secret[_\-]?key)\s*[:=]\s*"
        r"[\"']?([A-Za-z0-9._\-]{10,})[\"']?", re.I,
    ),
    re.compile(r"\bAKID[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[bap]-[A-Za-z0-9\-]{10,}\b"),
    # feishu/lark tokens
    re.compile(r"\b(t-g\w{8,}|u-[A-Za-z0-9_\-]{20,}|cli_[a-z0-9]{10,})\b"),
]


def redact(text):
    if not isinstance(text, str) or not text:
        return text
    for p in REDACT_PATTERNS:
        text = p.sub("<REDACTED>", text)
    return text


def trim(text, limit=MAX_AI_SNIPPET):
    if not text:
        return None
    text = text.strip()
    if len(text) > limit:
        return text[:limit] + f"… [+{len(text) - limit} chars]"
    return text


def iso(ts_ms):
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_text_from_content(content):
    """Normalize Claude-style content (str | list[blocks] | dict)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict):
                if blk.get("type") == "text":
                    parts.append(blk.get("text", ""))
                elif "text" in blk and blk.get("type") not in ("tool_use", "tool_result"):
                    parts.append(blk["text"])
            elif isinstance(blk, str):
                parts.append(blk)
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict) and "text" in content:
        return content["text"]
    return ""


def writeout(out_root: Path, tool: str, records: list, stats_extra=None):
    outdir = out_root / "raw" / tool
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "messages.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "tool": tool,
        "count": len(records),
        "earliest": records[0]["ts"] if records else None,
        "latest": records[-1]["ts"] if records else None,
    }
    if stats_extra:
        stats.update(stats_extra)
    with open(outdir / "stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"[{tool}] wrote {len(records)} records -> {outdir/'messages.jsonl'}")


# ---------------------------------------------------------------------------
# 1. Claude Code
# ---------------------------------------------------------------------------

def extract_claude_code(out_root: Path, root: Path | None = None):
    root = root or (HOME / ".claude/projects")
    if not root.exists():
        print("[claude-code] no data dir — skipping", file=sys.stderr)
        return
    rows = []
    for jsonl in sorted(root.rglob("*.jsonl")):
        try:
            project = None
            entries = []
            with open(jsonl, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if project is None and obj.get("cwd"):
                        project = obj["cwd"]
                    if obj.get("type") not in ("user", "assistant"):
                        continue
                    msg = obj.get("message") or {}
                    text = extract_text_from_content(msg.get("content") if isinstance(msg, dict) else None)
                    text = (text or "").strip()
                    if not text:
                        continue
                    if text.startswith(("<command-", "Caveat:", "[SUGGESTION MODE",
                                        "[Request interrupted", "<local-command-stdout>",
                                        "<bash-stdout>")):
                        continue
                    ts = obj.get("timestamp")
                    ts_ms = None
                    if ts:
                        try:
                            ts_ms = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
                        except Exception:
                            pass
                    entries.append((obj["type"], text, ts, ts_ms, obj.get("sessionId")))
            for i, (role, text, ts_iso, ts_ms, sid) in enumerate(entries):
                if role != "user":
                    continue
                prev_ai = next((e[1] for e in reversed(entries[:i]) if e[0] == "assistant"), None)
                next_ai = next((e[1] for e in entries[i+1:] if e[0] == "assistant"), None)
                rows.append({
                    "tool": "claude-code",
                    "ts": ts_iso, "ts_ms": ts_ms,
                    "session_id": sid, "project": project,
                    "user_text": redact(text),
                    "prev_ai": redact(trim(prev_ai)),
                    "next_ai": redact(trim(next_ai)),
                })
        except Exception as e:
            print(f"  WARN claude-code {jsonl}: {e}", file=sys.stderr)
    rows.sort(key=lambda r: r["ts_ms"] or 0)
    writeout(out_root, "claude-code", rows)


# ---------------------------------------------------------------------------
# 2. OpenCode
# ---------------------------------------------------------------------------

def extract_opencode(out_root: Path, root: Path | None = None):
    root = root or (HOME / ".local/share/opencode/storage")
    if not root.exists():
        print("[opencode] no data dir — skipping", file=sys.stderr)
        return
    sessions = {}
    for p in (root / "session").rglob("*.json"):
        try:
            s = json.loads(p.read_text("utf-8"))
            sessions[s["id"]] = s
        except Exception:
            pass
    by_ses: dict[str, list] = {}
    for p in (root / "message").rglob("*.json"):
        try:
            m = json.loads(p.read_text("utf-8"))
            by_ses.setdefault(m["sessionID"], []).append(m)
        except Exception:
            pass
    parts_by_msg: dict[str, list] = {}
    for p in (root / "part").rglob("*.json"):
        try:
            pr = json.loads(p.read_text("utf-8"))
            parts_by_msg.setdefault(pr["messageID"], []).append(pr)
        except Exception:
            pass

    rows = []
    for sid, msgs in by_ses.items():
        ses = sessions.get(sid, {})
        project = ses.get("directory")
        msgs.sort(key=lambda m: (m.get("time") or {}).get("created") or 0)
        msg_texts = []
        for m in msgs:
            role = m.get("role")
            parts = parts_by_msg.get(m["id"], [])
            text = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
            ts_ms = (m.get("time") or {}).get("created") or 0
            msg_texts.append((role, text, ts_ms, m["id"]))
        for i, (role, text, ts_ms, mid) in enumerate(msg_texts):
            if role != "user" or not text:
                continue
            prev_ai = next((e[1] for e in reversed(msg_texts[:i]) if e[0] == "assistant" and e[1]), None)
            next_ai = next((e[1] for e in msg_texts[i+1:] if e[0] == "assistant" and e[1]), None)
            rows.append({
                "tool": "opencode",
                "ts": iso(ts_ms), "ts_ms": ts_ms,
                "session_id": sid, "project": project,
                "user_text": redact(text),
                "prev_ai": redact(trim(prev_ai)),
                "next_ai": redact(trim(next_ai)),
            })
    rows.sort(key=lambda r: r["ts_ms"] or 0)
    writeout(out_root, "opencode", rows)


# ---------------------------------------------------------------------------
# 3. kiro-cli
# ---------------------------------------------------------------------------

def extract_kiro_cli(out_root: Path, db_path: Path | None = None):
    db = db_path or (HOME / "Library/Application Support/kiro-cli/data.sqlite3")
    if not db.exists():
        print("[kiro-cli] no sqlite — skipping", file=sys.stderr)
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("SELECT key, conversation_id, value FROM conversations_v2"):
        project = r["key"]
        try:
            data = json.loads(r["value"])
        except Exception:
            continue
        turns = []
        for h in data.get("history") or []:
            u = h.get("user") or {}
            a = h.get("assistant") or {}
            user_text = ""
            ts_iso = u.get("timestamp")
            cc = u.get("content") or {}
            if isinstance(cc, dict):
                prompt = cc.get("Prompt") or {}
                if isinstance(prompt, dict):
                    user_text = prompt.get("prompt", "") or ""
            ai_text = ""
            resp = a.get("Response") if isinstance(a, dict) else None
            if isinstance(resp, dict):
                ai_text = resp.get("content", "") or ""
            ts_ms = None
            if ts_iso:
                try:
                    ts_ms = int(datetime.fromisoformat(ts_iso).timestamp() * 1000)
                except Exception:
                    pass
            u_clean = user_text.strip()
            if u_clean.startswith(('{"exit_status', '{"output', '<tool result', '{"stderr', '{"stdout')):
                u_clean = ""
            turns.append((u_clean, ai_text.strip(), ts_iso, ts_ms))
        for i, (u_text, a_text, ts_iso, ts_ms) in enumerate(turns):
            if not u_text:
                continue
            prev_ai = turns[i-1][1] if i > 0 else None
            next_ai = a_text if a_text else (turns[i+1][1] if i+1 < len(turns) else None)
            rows.append({
                "tool": "kiro-cli",
                "ts": ts_iso, "ts_ms": ts_ms,
                "session_id": r["conversation_id"], "project": project,
                "user_text": redact(u_text),
                "prev_ai": redact(trim(prev_ai)),
                "next_ai": redact(trim(next_ai)),
            })
    con.close()
    rows.sort(key=lambda r: r["ts_ms"] or 0)
    writeout(out_root, "kiro-cli", rows)


# ---------------------------------------------------------------------------
# 4. Kiro GUI
# ---------------------------------------------------------------------------

_KIRO_WRAP_TAGS = ("EnvironmentContext", "steering-reminder", "file_content",
                   "user_new_message", "context", "fileTree")


def _kiro_strip_wrap(t: str) -> str:
    for tag in _KIRO_WRAP_TAGS:
        t = re.sub(rf"\s*<{tag}[^>]*>.*?</{tag}>\s*$", "", t, flags=re.S)
        t = re.sub(rf"^\s*<{tag}[^>]*>.*?</{tag}>\s*", "", t, flags=re.S)
    return t


def extract_kiro_gui(out_root: Path, root: Path | None = None):
    root = root or (HOME / "Library/Application Support/Kiro/User/globalStorage/kiro.kiroagent")
    if not root.exists():
        print("[kiro-gui] no data dir — skipping", file=sys.stderr)
        return
    files = list(root.rglob("*.chat"))
    print(f"[kiro-gui] scanning {len(files)} .chat files...", file=sys.stderr)
    rows = []
    for p in files:
        try:
            d = json.loads(p.read_text("utf-8"))
        except Exception:
            continue
        meta = d.get("metadata") or {}
        start_ms = meta.get("startTime")
        ts_iso = iso(start_ms) if start_ms else None
        chat = d.get("chat") or []
        for i, msg in enumerate(chat):
            if msg.get("role") != "human":
                continue
            content = msg.get("content")
            text = content if isinstance(content, str) else extract_text_from_content(content)
            text = (text or "").strip()
            if not text:
                continue
            if text.startswith(("# System Prompt", "<identity>",
                                "You are operating in a workspace", "<fileTree>",
                                "<steering-reminder>", "## Included Rules",
                                "<EnvironmentContext>", "<file_content",
                                "<user_new_message>")):
                continue
            clean = _kiro_strip_wrap(text).strip()
            if not clean or len(clean) < 2:
                continue
            if clean.startswith(("Follow these instructions for user requests",
                                 "## Included Rules",
                                 "I am providing you some additional",
                                 "<steering-reminder>")):
                continue
            prev_ai = next((m.get("content", "") for m in reversed(chat[:i])
                            if m.get("role") == "bot" and m.get("content")), None)
            next_ai = next((m.get("content", "") for m in chat[i+1:]
                            if m.get("role") == "bot" and m.get("content")), None)
            rows.append({
                "tool": "kiro-gui",
                "ts": ts_iso, "ts_ms": start_ms,
                "session_id": d.get("executionId") or p.stem,
                "project": None,
                "user_text": redact(clean),
                "prev_ai": redact(trim(prev_ai)),
                "next_ai": redact(trim(next_ai)),
            })
    # dedupe — same turn replayed across .chat snapshots
    seen, dedup = set(), []
    for r in rows:
        k = (r["user_text"][:300], r["session_id"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    dedup.sort(key=lambda r: r["ts_ms"] or 0)
    writeout(out_root, "kiro-gui", dedup, {"raw_before_dedup": len(rows)})


# ---------------------------------------------------------------------------
# 5. Trae
# ---------------------------------------------------------------------------

def extract_trae(out_root: Path, root: Path | None = None):
    ws_root = root or (HOME / "Library/Application Support/Trae/User/workspaceStorage")
    if not ws_root.exists():
        print("[trae] no workspaceStorage — skipping", file=sys.stderr)
        return
    rows = []
    for ws_dir in sorted(ws_root.iterdir()):
        db = ws_dir / "state.vscdb"
        if not db.exists():
            continue
        project = None
        wj = ws_dir / "workspace.json"
        if wj.exists():
            try:
                project = json.loads(wj.read_text("utf-8")).get("folder")
                if project and project.startswith("file://"):
                    from urllib.parse import unquote
                    project = unquote(project[7:])
            except Exception:
                pass
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except Exception:
            continue
        cur = con.cursor()
        try:
            row = cur.execute(
                "SELECT value FROM ItemTable WHERE key='memento/icube-ai-agent-storage'"
            ).fetchone()
        except Exception:
            row = None
        if row and row[0]:
            try:
                data = json.loads(row[0] if isinstance(row[0], str) else row[0].decode("utf-8"))
            except Exception:
                data = None
            if data:
                for sess in (data.get("list") or []):
                    sid = sess.get("sessionId")
                    msgs = sess.get("messages") or []
                    simple = []
                    for m in msgs:
                        role = m.get("role")
                        content = m.get("content")
                        text = content if isinstance(content, str) else extract_text_from_content(content)
                        ts_ms = m.get("timestamp")
                        if isinstance(ts_ms, (int, float)) and ts_ms < 1e12:
                            ts_ms = int(ts_ms * 1000)
                        simple.append((role, (text or "").strip(), ts_ms))
                    for i, (role, text, ts_ms) in enumerate(simple):
                        if role != "user" or not text:
                            continue
                        prev_ai = next((e[1] for e in reversed(simple[:i]) if e[0] == "assistant" and e[1]), None)
                        next_ai = next((e[1] for e in simple[i+1:] if e[0] == "assistant" and e[1]), None)
                        rows.append({
                            "tool": "trae",
                            "ts": iso(ts_ms), "ts_ms": ts_ms,
                            "session_id": sid, "project": project,
                            "user_text": redact(text),
                            "prev_ai": redact(trim(prev_ai)),
                            "next_ai": redact(trim(next_ai)),
                        })
        try:
            row = cur.execute(
                "SELECT value FROM ItemTable WHERE key='icube-ai-agent-storage-input-history'"
            ).fetchone()
        except Exception:
            row = None
        if row and row[0]:
            try:
                arr = json.loads(row[0] if isinstance(row[0], str) else row[0].decode("utf-8"))
            except Exception:
                arr = []
            for item in arr or []:
                it = item.get("inputText") if isinstance(item, dict) else None
                if not it:
                    continue
                ts_ms = item.get("timestamp") or item.get("createdAt") if isinstance(item, dict) else None
                rows.append({
                    "tool": "trae",
                    "ts": iso(ts_ms) if ts_ms else None,
                    "ts_ms": ts_ms,
                    "session_id": f"input-history:{ws_dir.name}",
                    "project": project,
                    "user_text": redact(it.strip()),
                    "prev_ai": None, "next_ai": None,
                })
        con.close()
    seen, dedup = set(), []
    for r in rows:
        k = (r["user_text"][:200], r["session_id"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(r)
    dedup.sort(key=lambda r: r["ts_ms"] or 0)
    writeout(out_root, "trae", dedup)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

EXTRACTORS = {
    "claude-code": extract_claude_code,
    "opencode":    extract_opencode,
    "kiro-cli":    extract_kiro_cli,
    "kiro-gui":    extract_kiro_gui,
    "trae":        extract_trae,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Harvest user messages from AI coding tools.")
    ap.add_argument("--output", "-o", default=".",
                    help="Output root. Default: CWD. Creates <output>/raw/<tool>/.")
    ap.add_argument("--tools", "-t", default="all",
                    help=f"Comma-separated tool names, or 'all'. Known: {', '.join(TOOL_NAMES)}")
    args = ap.parse_args(argv)

    out_root = Path(args.output).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    if args.tools == "all":
        selected = list(TOOL_NAMES)
    else:
        selected = [t.strip() for t in args.tools.split(",") if t.strip()]
        unknown = [t for t in selected if t not in EXTRACTORS]
        if unknown:
            print(f"ERROR: unknown tool(s): {unknown}. Known: {TOOL_NAMES}", file=sys.stderr)
            return 2

    print(f"output root: {out_root}")
    for name in selected:
        print(f"=== extracting {name} ===")
        try:
            EXTRACTORS[name](out_root)
        except Exception:
            traceback.print_exc()

    return 0


if __name__ == "__main__":
    sys.exit(main())
