#!/usr/bin/env python3
"""
session_orchestrator.py — 通用 OpenCode 会话编排器

功能:
  1. 通过 opencode run 在项目目录创建会话 (正确设置 projectID/directory)
  2. 捕获 session ID
  3. 可选: 更新外部 JSON 文件
  4. 可选: 进入周期性唤醒循环 (opencode_client.py loop)

用法:
  python3 session_orchestrator.py \
    -a opencood-main \
    -d /path/to/project \
    -p "启动提示词" \
    -t 15

依赖:
  - OpenCode Server 必须已在运行
  - opencode CLI 必须可用
  - opencode_client.py 在同一目录
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
LOOP_SCRIPT = os.path.join(SKILL_DIR, "opencode_client.py")


def launch_session(agent, directory, prompt, title=None):
    """
    在指定目录运行 opencode run 创建会话, 解析第一个 JSON 事件获取 sessionID.
    返回 session_id 字符串.
    """
    cmd = [
        "opencode", "run",
        "--agent", agent,
        "--format", "json",
    ]
    if title:
        cmd += ["--title", title]
    cmd.append(prompt)

    proc = subprocess.Popen(
        cmd,
        cwd=directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    session_id = None
    try:
        for line in proc.stdout:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                sid = event.get("sessionID")
                if sid:
                    session_id = sid
                    break
            except json.JSONDecodeError:
                continue
    finally:
        # 获取 session ID 后关闭管道, 不等待进程终止 — 会话在服务端继续运行
        proc.stdout.close()

    if not session_id:
        stderr_output = proc.stderr.read() if proc.stderr else ""
        sys.exit(f"无法获取 session ID。stderr: {stderr_output[:200]}")

    return session_id


def update_state_file(path, key, value):
    """写入 JSON 文件的指定字段."""
    if not os.path.exists(path):
        print(f"  跳过: 状态文件不存在 ({path})")
        return
    try:
        with open(path) as f:
            data = json.load(f)
        parts = key.split(".")
        d = data
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = value
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  状态文件已更新: {path} -> {key}")
    except Exception as e:
        print(f"  更新状态文件失败: {e}")


def start_loop(session_id, loop_prompt, interval):
    """启动周期性唤醒循环."""
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
  session_orchestrator.py -a opencood-main -d ~/Workspace/OpenCOOD -p "推进研究" -t 15
  session_orchestrator.py -a build -d /path/to/proj -p "hello" --no-loop
  session_orchestrator.py -a my-agent -d . -p "start" --state-file state.json --state-key session_id
        """,
    )
    parser.add_argument("--agent", "-a", default="build", help="智能体名称 (默认: build)")
    parser.add_argument("--dir", "-d", required=True, help="项目目录")
    parser.add_argument("--prompt", "-p", required=True, help="启动提示词")
    parser.add_argument("--time", "-t", dest="interval", type=int, default=15,
                        help="唤醒间隔 (分钟), 默认 15")
    parser.add_argument("--no-loop", action="store_true",
                        help="不进入循环, 仅创建会话并发送首条提示词")
    parser.add_argument("--loop-prompt", default="继续推进未完成任务。",
                        help="周期性唤醒提示词 (默认: 继续推进未完成任务。)")
    parser.add_argument("--state-file", help="外部状态 JSON 文件路径")
    parser.add_argument("--state-key", default="session_id",
                        help="写入状态文件的字段名 (支持点号路径)")
    parser.add_argument("--title", default=None,
                        help="会话标题 (默认: 使用 prompt 截断)")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        sys.exit(f"错误: 目录不存在: {args.dir}")

    print(f"Session Orchestrator")
    print(f"  Agent:  {args.agent}")
    print(f"  Dir:    {args.dir}")
    print()

    # 1. 启动会话
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 创建会话...")
    sid = launch_session(args.agent, args.dir, args.prompt, args.title)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 会话已创建: {sid}")

    # 2. 更新状态文件
    if args.state_file:
        update_state_file(args.state_file, args.state_key, sid)

    # 3. Loop or exit
    if args.no_loop:
        print(f"\n--no-loop: 退出。会话在 Web UI 中可继续交互。")
    else:
        start_loop(sid, args.loop_prompt, args.interval)


if __name__ == "__main__":
    main()
