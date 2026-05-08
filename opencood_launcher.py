#!/usr/bin/env python3
"""
opencood_launcher.py — OpenCOOD 主流程启动器

功能:
  1. 通过 OpenCode Server API 创建新会话 (agent=opencood-main)
  2. 发送启动提示词
  3. 设置周期性唤醒 (默认每 15 分钟提醒主智能体继续工作)
  4. 将 session_id 写入 task_map.json，便于智能体互操作

用法:
  python3 opencood_launcher.py                        # 使用默认配置
  python3 opencood_launcher.py -p "推进 SpikeToken"    # 自定义启动提示词
  python3 opencood_launcher.py -t 10                   # 每 10 分钟唤醒一次
  python3 opencood_launcher.py --no-loop               # 仅创建会话并发送首条提示词，不进入循环

依赖:
  - OpenCode Server 必须已在运行 (opencode serve)
  - .opencode/agents/ 目录下需要 opencood-main.md 等 agent 模板
  - opencode_client.py (loop 功能)
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

# ── 路径 ──────────────────────────────────────────────────────────
SKILL_DIR = os.path.join(os.path.expanduser("~"),
                         ".config/opencode/skills/opencode-server")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
TASK_MAP_PATH = os.path.join(
    os.path.expanduser("~"),
    "Workspace/OpenCOOD/.opencode/agents/status/task_map.json",
)
LOOP_SCRIPT = os.path.join(SKILL_DIR, "opencode_client.py")

# ── 默认值 ────────────────────────────────────────────────────────
DEFAULT_PROMPT = (
    "你是 OpenCOOD 项目主智能体。读取 task_map.json 和所有方向的管理文档，"
    "按照调度决策框架推进研究任务。"
    "本轮结束后不要询问用户，自主决策并执行。"
)
DEFAULT_INTERVAL = 15  # 分钟
DEFAULT_AGENT = "opencood-main"
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Workspace/OpenCOOD")


def load_config():
    """加载 opencode-server skill 的共享配置."""
    config = {
        "base_url": "http://localhost:4096",
        "user": "opencode",
        "password": "",
        "main_session": "",
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
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


def create_session(config, agent, directory):
    """
    POST /session 创建新会话.
    返回 (session_id, title) 或异常退出.
    """
    url = f"{config['base_url']}/session"
    auth = HTTPBasicAuth(config["user"], config["password"])
    payload = {
        "agent": agent,
        "directory": directory,
    }
    resp = requests.post(url, json=payload, auth=auth, timeout=30)
    data = resp.json()

    if resp.status_code != 200 or "id" not in data:
        sys.exit(f"创建会话失败: {resp.status_code} {resp.text}")

    session_id = data["id"]
    title = data.get("title", "")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 会话已创建")
    print(f"  ID:    {session_id}")
    print(f"  标题:  {title}")
    print(f"  代理:  {agent}")
    return session_id


def send_first_prompt(config, session_id, prompt):
    """
    POST /session/:id/prompt_async 发送启动提示词.
    返回 True 或异常退出.
    """
    url = f"{config['base_url']}/session/{session_id}/prompt_async"
    auth = HTTPBasicAuth(config["user"], config["password"])
    payload = {
        "agent": DEFAULT_AGENT,
        "parts": [{"type": "text", "text": prompt}],
    }
    resp = requests.post(url, json=payload, auth=auth, timeout=30)

    if resp.status_code != 204:
        sys.exit(f"发送提示词失败: {resp.status_code} {resp.text}")

    preview = prompt[:60] + ("..." if len(prompt) > 60 else "")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 启动提示词已发送: \"{preview}\"")
    return True


def update_task_map(session_id):
    """
    更新 task_map.json 的 _meta.main_session_id.
    如果文件不存在则跳过（项目可能尚未 clone 或未初始化）.
    """
    if not os.path.exists(TASK_MAP_PATH):
        print(f"  注意: task_map.json 不存在 ({TASK_MAP_PATH})，跳过更新")
        return
    try:
        with open(TASK_MAP_PATH) as f:
            data = json.load(f)
        data.setdefault("_meta", {})["main_session_id"] = session_id
        data["_meta"]["last_updated"] = datetime.now().isoformat()
        with open(TASK_MAP_PATH, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  task_map.json 已更新 (main_session_id)")
    except Exception as e:
        print(f"  更新 task_map.json 失败: {e}")


def start_loop(session_id, prompt, interval):
    """
    调用 opencode_client.py loop 进行周期性唤醒.
    此调用会阻塞，直到用户 Ctrl+C.
    """
    cmd = [
        sys.executable,
        LOOP_SCRIPT,
        "loop",
        "--id", session_id,
        "--prompt", prompt,
        "--time", str(interval),
        "--now",          # 立即发送第一次
    ]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 进入周期性唤醒模式")
    print(f"  目标会话:  {session_id}")
    print(f"  唤醒间隔:  {interval} 分钟")
    print(f"  提示词:    \"{prompt}\"")
    print("  按 Ctrl+C 停止.\n")
    subprocess.run(cmd)


def main():
    parser = argparse.ArgumentParser(
        description="opencood_launcher — OpenCOOD 主流程启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  opencood_launcher.py                           # 默认配置, 每15分钟唤醒
  opencood_launcher.py -p "推进SpikeToken方向"    # 自定义启动提示词
  opencood_launcher.py -t 10                     # 每10分钟唤醒一次
  opencood_launcher.py --no-loop                 # 仅创建会话 + 发送首条提示词
        """,
    )
    parser.add_argument(
        "--prompt", "-p",
        default=DEFAULT_PROMPT,
        help="启动提示词 (默认: 通用调度指令)",
    )
    parser.add_argument(
        "--time", "-t",
        dest="interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"唤醒间隔, 分钟 (默认: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--no-loop",
        action="store_true",
        help="仅创建会话并发送首条提示词, 不进入循环",
    )
    parser.add_argument(
        "--dir", "-d",
        default=DEFAULT_DIR,
        help=f"项目目录 (默认: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "--agent", "-a",
        default=DEFAULT_AGENT,
        help=f"主智能体名称 (默认: {DEFAULT_AGENT})",
    )
    args = parser.parse_args()

    config = load_config()
    if not config.get("password"):
        sys.exit("错误: 未设置密码。请在 config.json 中设置或设置 OC_PASS 环境变量。")

    print(f"OpenCOOD 启动器")
    print(f"  Server: {config['base_url']}")
    print(f"  Agent:  {args.agent}")
    print(f"  Dir:    {args.dir}")
    print()

    # Step 1: 创建会话
    session_id = create_session(config, args.agent, args.dir)

    # Step 2: 更新 task_map
    update_task_map(session_id)

    # Step 3: 发送启动提示词
    send_first_prompt(config, session_id, args.prompt)

    print()

    # Step 4: 进入周期性唤醒
    if args.no_loop:
        print("--no-loop 模式，不进入循环。会话将自行运行。")
        print(f"如需发送消息: opencodeyes send --id {session_id} -p \"...\"")
        print(f"如需恢复唤醒: opencodeyes loop --id {session_id} -p \"继续推进研究\" -t 15")
    else:
        loop_prompt = "继续推进所有研究方向，根据调度决策框架自主决策并执行。"
        start_loop(session_id, loop_prompt, args.interval)


if __name__ == "__main__":
    main()
