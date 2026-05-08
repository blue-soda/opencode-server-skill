#!/usr/bin/env python3
"""
opencode_client — OpenCode Server API client.
CLI subcommands: list, setmain, send, loop.

Dependencies: scheduled_send.py (load_config, send_prompt, build_message),
              session_tree.py (used via subprocess for session listing).

Used by: opencodeyes (user-facing wrapper), agent templates.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from scheduled_send import BJT, build_message, load_config, send_prompt

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
SESSION_TREE = os.path.join(HERE, "session_tree.py")


def save_config(config):
    """Write config dict to disk."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_roots():
    """Return list of (session_id, title) for all root sessions."""
    result = subprocess.run(
        [sys.executable, SESSION_TREE, "--json"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    output = result.stdout.strip()
    if not output:
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    roots = []
    for s in data:
        if not s.get("parentID"):
            roots.append((s["id"], s.get("title", "")))
    return roots


def resolve_session(session_id):
    """Resolve session_id from arg or config.main_session."""
    if session_id:
        return session_id
    config = load_config()
    sid = config.get("main_session", "")
    if not sid:
        sys.exit("错误: 未指定 session ID。使用 --id 或先运行 opencodeyes setmain <id>")
    return sid


def require_password():
    config = load_config()
    if not config.get("password"):
        sys.exit("错误: 未设置密码。请在 config.json 中设置或设置 OC_PASS 环境变量。")


# ── CLI subcommands ──────────────────────────────────────────────


def cmd_list(json_output=False):
    roots = get_roots()
    if not roots:
        print("[]" if json_output else "无法获取会话列表。请确认 opencode serve 正在运行。")
        sys.exit(1)
    config = load_config()
    main = config.get("main_session", "")

    if json_output:
        out = [{"id": s, "title": t, "is_main": s == main} for s, t in roots]
        print(json.dumps(out, ensure_ascii=False))
        return

    print(f"{'':<4}{'ROOT ID':<35} {'TITLE':<50}")
    print("-" * 89)
    for sid, title in roots:
        marker = "*" if sid == main else " "
        print(f"{marker:>3} {sid:<35} {title:<50}")
    print(f"\n* = 当前 main_session  共 {len(roots)} 个根会话")


def cmd_setmain(session_id):
    roots = get_roots()
    root_ids = {sid for sid, _ in roots}
    if not root_ids:
        print("无法获取会话列表。请确认 opencode serve 正在运行。")
        sys.exit(1)
    if session_id not in root_ids:
        print(f"错误: {session_id} 不是有效的根会话 ID。")
        print("可用根会话：")
        for sid, title in roots:
            print(f"  {sid}  {title}")
        sys.exit(1)
    config = load_config()
    config["main_session"] = session_id
    save_config(config)
    title = next((t for s, t in roots if s == session_id), "")
    print(f"main_session 已设置为: {session_id}  ({title})")


def cmd_send(session_id, prompt, delay=0):
    require_password()
    sid = resolve_session(session_id)
    config = load_config()
    created_at = datetime.now(BJT)

    if delay > 0:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 等待 {delay}s ...")
        time.sleep(delay)

    text = build_message(prompt, created_at)
    t = datetime.now().strftime("%H:%M:%S")
    send_prompt(config, sid, text)
    print(f"[{t}] 已发送到 {sid}")


def cmd_loop(session_id, prompt, interval, now):
    require_password()
    sid = resolve_session(session_id)
    config = load_config()

    roots = get_roots()
    root_ids = {r[0] for r in roots}
    if roots and sid not in root_ids:
        print(f"警告: {sid} 不在当前根会话列表中。将尝试发送。")

    interval_seconds = interval * 60
    print(f"目标: {sid}")
    print(f"间隔: {interval} 分钟")
    print(f"立即发送: {'是' if now else '否（先等待）'}")
    print(f"Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print("按 Ctrl+C 停止。\n")

    count = 0

    def do_send():
        nonlocal count
        count += 1
        created_at = datetime.now(BJT)
        text = build_message(prompt, created_at)
        t = datetime.now().strftime("%H:%M:%S")
        send_prompt(config, sid, text)
        print(f"[{t}] 第 {count} 次发送成功")

    try:
        if now:
            do_send()
        while True:
            next_time = datetime.now().strftime("%H:%M")
            print(f"等待 {interval} 分钟 (下次约 {next_time} + {interval}m)...")
            time.sleep(interval_seconds)
            do_send()
    except KeyboardInterrupt:
        print(f"\n已停止。共发送 {count} 次。")


# ── CLI entry ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="opencode_client — OpenCode Server API client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    sp_list = sub.add_parser("list", help="列出所有根会话")
    sp_list.add_argument("--json", action="store_true", default=False,
                         help="以 JSON 格式输出")

    sp_set = sub.add_parser("setmain", help="设置默认主会话")
    sp_set.add_argument("session_id", help="根会话 ID")

    sp_send = sub.add_parser("send", help="发送单次消息（可选延迟）")
    sp_send.add_argument("--id", dest="session_id", help="目标 session ID（默认 main_session）")
    sp_send.add_argument("--prompt", "-p", required=True, help="要发送的 prompt 文本")
    sp_send.add_argument("--in", dest="delay", type=int, default=0,
                         help="延迟秒数后发送，默认 0（立即发送）")

    sp_loop = sub.add_parser("loop", help="周期性发送消息")
    sp_loop.add_argument("--id", dest="session_id", help="目标 session ID（默认 main_session）")
    sp_loop.add_argument("--prompt", "-p", required=True, help="要发送的 prompt 文本")
    sp_loop.add_argument("--time", "-t", dest="interval", type=float, default=60,
                         help="发送间隔（分钟），默认 60")
    sp_loop.add_argument("--now", action="store_true", default=False,
                         help="立即发送第一次")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(json_output=args.json)
    elif args.command == "setmain":
        cmd_setmain(args.session_id)
    elif args.command == "send":
        cmd_send(getattr(args, "session_id", None), args.prompt, args.delay)
    elif args.command == "loop":
        cmd_loop(getattr(args, "session_id", None), args.prompt, args.interval, args.now)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
