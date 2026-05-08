#!/usr/bin/env python3
"""
Send a prompt to an OpenCode session at a scheduled time.

Usage:
  python3 scheduled_send.py --session SESSION_ID --prompt "text" --in SECONDS
  python3 scheduled_send.py --session SESSION_ID --prompt "text" --at "2026-05-07 09:00:00"
  python3 scheduled_send.py --prompt "text" --in 60  (uses main_session from config)

Reusable functions (import from other modules):
  load_config()          -> dict
  send_prompt(config, session_id, text) -> bool
  build_message(original_prompt, created_at=None) -> str
  schedule_and_send(session_id, prompt, delay_seconds, config_path=None) -> None
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

HERE = Path(__file__).parent
DEFAULT_CONFIG = HERE / "config.json"
BJT = timezone(timedelta(hours=8))


def load_config(config_path=None):
    """Load config from file + env vars. Returns dict, does not exit."""
    config = {
        "base_url": "http://localhost:4096",
        "user": "opencode",
        "password": "",
        "main_session": "",
    }
    if config_path is None:
        config_path = DEFAULT_CONFIG
    if os.path.exists(config_path):
        with open(config_path) as f:
            config.update(json.load(f))
    for env_key, cfg_key in [
        ("OC_BASE_URL", "base_url"),
        ("OC_USER", "user"),
        ("OC_PASS", "password"),
        ("OC_MAIN_SESSION", "main_session"),
    ]:
        val = os.environ.get(env_key)
        if val:
            config[cfg_key] = val
    return config


def require_config(config):
    """Validate required config fields, exit on missing."""
    if not config.get("password"):
        sys.exit("Error: OC_PASS or config password is required.")
    return config


def send_prompt(config, session_id, text):
    """Send an async prompt to a session. Returns True on success."""
    url = f"{config['base_url']}/session/{session_id}/prompt_async"
    auth = HTTPBasicAuth(config["user"], config["password"])
    payload = {"parts": [{"type": "text", "text": text}]}
    resp = requests.post(url, json=payload, auth=auth, timeout=30)
    if resp.status_code != 204:
        raise RuntimeError(f"Unexpected response: {resp.status_code} {resp.text}")
    return True


def build_message(original_prompt, created_at=None):
    """Wrap a prompt with Beijing-time timestamp context."""
    if created_at is None:
        created_at = datetime.now(BJT)
    now_ts = datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S (北京时间)")
    created_ts = created_at.strftime("%Y-%m-%d %H:%M:%S (北京时间)")
    return f"现在是{now_ts}，收到了一条来自{created_ts}的指令：\n{original_prompt}"


def schedule_and_send(session_id, prompt, delay_seconds, config_path=None):
    """Wait delay_seconds then send prompt. Returns after sending."""
    config = require_config(load_config(config_path))
    created_at = datetime.now(BJT)
    if delay_seconds > 0:
        print(f"Waiting {delay_seconds}s ...")
        time.sleep(delay_seconds)
    text = build_message(prompt, created_at)
    send_prompt(config, session_id, text)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent to {session_id}")


# ── CLI ───────────────────────────────────────────────────────────


def parse_time(time_str):
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            now = datetime.now()
            if fmt.startswith("%H"):
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
                if dt < now:
                    dt = dt.replace(day=now.day + 1)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {time_str}")


def main():
    parser = argparse.ArgumentParser(
        description="Send a prompt to an OpenCode session at a scheduled time."
    )
    parser.add_argument("--session", "-s", help="Target session ID (defaults to main_session from config)")
    parser.add_argument("--prompt", "-p", required=True, help="The prompt text to send")
    parser.add_argument("--in", dest="delay", type=int, help="Delay in seconds before sending")
    parser.add_argument("--at", dest="at_time", help="Absolute time to send (e.g. '2026-05-07 09:00:00' or '14:30')")
    parser.add_argument("--config", help="Path to config.json")
    args = parser.parse_args()

    if not args.delay and not args.at_time:
        sys.exit("Error: specify either --in SECONDS or --at TIME")

    created_at = datetime.now(BJT)

    if args.delay:
        delay = args.delay
        target_time = datetime.now() + timedelta(seconds=delay)
    else:
        target_time = parse_time(args.at_time)
        delay = (target_time - datetime.now()).total_seconds()
        if delay <= 0:
            sys.exit(f"Error: target time {target_time} is in the past.")

    config = require_config(load_config(args.config))
    session_id = args.session or config.get("main_session", "")
    if not session_id:
        sys.exit("Error: no session ID provided. Use --session or set main_session in config.")

    final_prompt = build_message(args.prompt, created_at)

    print(f"Session: {session_id}")
    print(f"Target time: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Delay: {delay:.0f} seconds")
    print(f"Prompt preview: {args.prompt[:80]}{'...' if len(args.prompt) > 80 else ''}")
    print()

    try:
        print(f"Waiting {delay:.0f}s until {target_time.strftime('%Y-%m-%d %H:%M:%S')} ...")
        time.sleep(delay)
        send_prompt(config, session_id, final_prompt)
        print(f"Prompt sent successfully at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
