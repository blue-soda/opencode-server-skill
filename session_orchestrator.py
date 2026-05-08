#!/usr/bin/env python3
"""
session_orchestrator.py — 通用 OpenCode 会话编排器

功能:
  1. 通过 OpenCode Server API 创建新会话 (指定 agent + directory)
  2. 发送启动提示词 (prompt_async)
  3. 可选: 写入外部 JSON 文件的指定字段 (如更新 main_session_id)
  4. 可选: 进入周期性唤醒循环 (opencode_client.py loop)

用法:
  python3 session_orchestrator.py \
    -a build \
    -d /path/to/project \
    -p "你的启动提示词" \
    -t 15

  python3 session_orchestrator.py \
    -a opencood-main \
    -d /home/user/Workspace/MyProject \
    -p "推进所有研究方向" \
    --state-file /path/to/state.json \
    --state-key main_session_id \
    --loop-prompt "继续推进"

依赖:
  - OpenCode Server 必须已在运行 (opencode serve)
  - opencode_client.py 在同一目录
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SKILL_DIR, "config.json")
LOOP_SCRIPT = os.path.join(SKILL_DIR, "opencode_client.py")


def load_config():
    config = {
        "base_url": "http://localhost:4096",
        "user": "opencode",
        "password": "",
    }
    if os.path.exists(DEFAULT_CONFIG):
        with open(DEFAULT_CONFIG) as f:
            config.update(json.load(f))
    for env_key, cfg_key in [
        ("OC_BASE_URL", "base_url"),
        ("OC_USER", "user"),
        ("OC_PASS", "password"),
    ]:
        val = os.environ.get(env_key)
        if val:
            config[cfg_key] = val
    return config


def create_session(base_url, user, password, agent, directory):
    url = f"{base_url}/session"
    auth = HTTPBasicAuth(user, password)
    resp = requests.post(url, json={"agent": agent, "directory": directory}, auth=auth, timeout=30)
    if resp.status_code != 200:
        sys.exit(f"创建会话失败: {resp.status_code} {resp.text}")
    data = resp.json()
    if "id" not in data:
        sys.exit(f"响应缺少 id 字段: {resp.text}")
    return data["id"], data.get("title", "")


def send_prompt(base_url, user, password, session_id, agent, prompt_text):
    url = f"{base_url}/session/{session_id}/prompt_async"
    auth = HTTPBasicAuth(user, password)
    payload = {"agent": agent, "parts": [{"type": "text", "text": prompt_text}]}
    resp = requests.post(url, json=payload, auth=auth, timeout=30)
    if resp.status_code != 204:
        sys.exit(f"发送提示词失败: {resp.status_code} {resp.text}")


def update_state_file(path, key, value):
    """写入 JSON 文件的指定字段。仅更新已存在的文件."""
    if not os.path.exists(path):
        print(f"  跳过: 状态文件不存在 ({path})")
        return
    try:
        with open(path) as f:
            data = json.load(f)
        # 支持点号路径, 如 "_meta.main_session_id"
        parts = key.split(".")
        d = data
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = value
        d.setdefault("last_updated", datetime.now().isoformat() if parts[-1] != "last_updated" else value)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  状态文件已更新: {path} -> {key}")
    except Exception as e:
        print(f"  更新状态文件失败: {e}")


def start_loop(session_id, loop_prompt, interval):
    cmd = [
        sys.executable, LOOP_SCRIPT,
        "loop",
        "--id", session_id,
        "--prompt", loop_prompt,
        "--time", str(interval),
        "--now",
    ]
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 进入周期性唤醒")
    print(f"  会话:  {session_id}")
    print(f"  间隔:  {interval} 分钟")
    print(f"  提示:  \"{loop_prompt}\"")
    print("  按 Ctrl+C 停止.\n")
    subprocess.run(cmd)


def main():
    parser = argparse.ArgumentParser(
        description="session_orchestrator — 通用 OpenCode 会话编排器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  session_orchestrator.py -a build -d /path/to/proj -p "hello" -t 30
  session_orchestrator.py -a opencood-main -d ~/Workspace/OpenCOOD -p "推进研究" --no-loop
  session_orchestrator.py -a my-agent -d . -p "start" --state-file state.json --state-key session_id
        """,
    )
    parser.add_argument("--agent", "-a", required=True, help="智能体名称 (primary agent)")
    parser.add_argument("--dir", "-d", required=True, help="项目目录")
    parser.add_argument("--prompt", "-p", required=True, help="启动提示词")
    parser.add_argument("--time", "-t", dest="interval", type=int, default=15,
                        help="唤醒间隔 (分钟), 默认 15")
    parser.add_argument("--no-loop", action="store_true",
                        help="不进入循环,仅创建会话并发送首条提示词")
    parser.add_argument("--loop-prompt", default="继续推进未完成任务。",
                        help="周期性唤醒提示词 (默认: 继续推进未完成任务。)")
    parser.add_argument("--state-file", help="外部状态 JSON 文件路径")
    parser.add_argument("--state-key", default="session_id",
                        help="写入状态文件的字段名 (支持点号路径, 如 _meta.session_id)")
    args = parser.parse_args()

    config = load_config()
    base_url = config["base_url"]
    user = config["user"]
    password = config["password"]
    if not password:
        sys.exit("错误: 未设置密码。")

    print(f"Session Orchestrator")
    print(f"  Server: {base_url}")
    print(f"  Agent:  {args.agent}")
    print(f"  Dir:    {args.dir}")
    print()

    # 1. Create session
    sid, title = create_session(base_url, user, password, args.agent, args.dir)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 会话已创建: {sid}")
    print(f"  标题: {title}")

    # 2. Update state file
    if args.state_file:
        update_state_file(args.state_file, args.state_key, sid)

    # 3. Send first prompt
    send_prompt(base_url, user, password, sid, args.agent, args.prompt)
    short = args.prompt[:60] + ("..." if len(args.prompt) > 60 else "")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 启动提示词已发送: \"{short}\"")

    # 4. Loop or exit
    if args.no_loop:
        print(f"\n--no-loop: 退出。稍后可用 opencodeyes send/loop --id {sid} 发送消息。")
    else:
        start_loop(sid, args.loop_prompt, args.interval)


if __name__ == "__main__":
    main()
