#!/usr/bin/env python3
"""
Fetch all OpenCode sessions and display them as a parent->child tree.

Usage:
  python3 session_tree.py [--filter KEYWORD] [--roots-only] [--json] [--config PATH]
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth


def load_config(config_path=None):
    config = {"base_url": "http://localhost:4096", "user": "opencode", "password": "", "main_session": ""}

    if config_path is None:
        config_path = Path(__file__).parent / "config.json"

    if os.path.exists(config_path):
        with open(config_path) as f:
            file_config = json.load(f)
            config.update(file_config)

    for env_key, cfg_key in [
        ("OC_BASE_URL", "base_url"),
        ("OC_USER", "user"),
        ("OC_PASS", "password"),
        ("OC_MAIN_SESSION", "main_session"),
    ]:
        val = os.environ.get(env_key)
        if val:
            config[cfg_key] = val

    if not config["password"]:
        sys.exit("Error: OC_PASS or config password is required. Set it via environment or config.json.")

    return config


def fetch_sessions(config):
    url = f"{config['base_url']}/experimental/session"
    auth = HTTPBasicAuth(config["user"], config["password"])
    resp = requests.get(url, auth=auth, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_tree(sessions):
    id_to_session = {}
    parent_to_children = defaultdict(list)

    for s in sessions:
        sid = s.get("id", "")
        id_to_session[sid] = s
        pid = s.get("parentID", "") or ""
        if pid:
            parent_to_children[pid].append(s)

    return id_to_session, parent_to_children


def parse_updated(ts):
    if not ts:
        return datetime.min
    if isinstance(ts, dict):
        ts = ts.get("updated", "")
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.min


def get_dir_name(session):
    d = session.get("directory", "") or ""
    return os.path.basename(d.rstrip("/")) or d


def filter_sessions(sessions, keyword):
    if not keyword:
        return sessions
    kw = keyword.lower()
    return [s for s in sessions if kw in (s.get("title", "") or "").lower()]


def get_root_sessions(sessions, parent_to_children):
    all_child_ids = set()
    for children in parent_to_children.values():
        for c in children:
            all_child_ids.add(c.get("id", ""))
    return [s for s in sessions if s.get("id", "") not in all_child_ids]


def print_tree(sessions, id_to_session, parent_to_children, roots):
    displayed = set()

    def print_node(session, prefix, is_last):
        sid = session.get("id", "")
        if sid in displayed:
            return
        displayed.add(sid)

        title = (session.get("title", "") or "")[:40]
        dirname = get_dir_name(session)[:25]
        is_root = not (session.get("parentID") or "")
        root_tag = "[ROOT]" if is_root else "       "

        connector = " └─ " if is_last else " ├─ "
        line = f"{root_tag} {connector}{sid}  {title:<40}  {dirname}"
        print(line)

        children = parent_to_children.get(sid, [])
        children.sort(key=lambda s: parse_updated(s.get("time")), reverse=True)
        for i, child in enumerate(children):
            new_prefix = prefix + ("    " if is_last else " │  ")
            print_node(child, new_prefix, i == len(children) - 1)

    for i, root in enumerate(roots):
        root_tag = "[ROOT]"
        sid = root.get("id", "")
        title = (root.get("title", "") or "")[:40]
        dirname = get_dir_name(root)[:25]
        line = f"{root_tag}     {sid}  {title:<40}  {dirname}"
        print(line)

        children = parent_to_children.get(sid, [])
        children.sort(key=lambda s: parse_updated(s.get("time")), reverse=True)
        for j, child in enumerate(children):
            print_node(child, "", j == len(children) - 1)


def main():
    parser = argparse.ArgumentParser(description="List OpenCode sessions as a tree.")
    parser.add_argument("keyword", nargs="?", default="", help="Keyword filter for session titles")
    parser.add_argument("--filter", "-f", dest="filter_kw", default="", help="Keyword filter for session titles")
    parser.add_argument("--roots-only", action="store_true", help="Show only root sessions (no children)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of tree")
    parser.add_argument("--config", help="Path to config.json")
    args = parser.parse_args()

    keyword = args.filter_kw or args.keyword

    config = load_config(args.config)
    sessions = fetch_sessions(config)
    id_to_session, parent_to_children = build_tree(sessions)

    sessions = filter_sessions(sessions, keyword)

    if args.json:
        print(json.dumps(sessions, indent=2, ensure_ascii=False, default=str))
        return

    sessions.sort(key=lambda s: parse_updated(s.get("time")), reverse=True)
    roots = get_root_sessions(sessions, parent_to_children)

    if args.roots_only:
        children_ids = set()
        for children in parent_to_children.values():
            for c in children:
                children_ids.add(c.get("id", ""))
        for s in sessions:
            if s.get("id", "") not in children_ids:
                sid = s.get("id", "")
                title = (s.get("title", "") or "")[:40]
                dirname = get_dir_name(s)[:25]
                print(f"[ROOT]  {sid}  {title:<40}  {dirname}")
        return

    if not roots:
        print("No sessions found.")
        return

    print(f"\nTotal sessions: {len(sessions)} (Root: {len(roots)})")
    print("-" * 120)
    print_tree(sessions, id_to_session, parent_to_children, roots)
    print()


if __name__ == "__main__":
    main()
