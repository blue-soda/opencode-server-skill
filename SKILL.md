---
name: opencode-server
description: Programmatically interact with an OpenCode server via its HTTP API. List sessions as a tree, send scheduled prompts, wake orchestrators, and build multi-agent supervisor loops.
license: MIT
compatibility: opencode
metadata:
  audience: orchestrator
  workflow: multi-agent
  requires: opencode-server
---

## Purpose

This skill teaches agents how to programmatically interact with a running OpenCode server. It provides:

1. **session_tree.py** — Fetch all sessions via `/experimental/session` and display them as a human-readable tree, sorted by recent activity, with keyword filtering.
2. **scheduled_send.py** — Send a prompt to a session at a specified time, with timestamp metadata prepended. Core functions (`load_config`, `send_prompt`, `build_message`) are importable by other modules.
3. **opencode_client.py** — Unified CLI aggregating session management (`list`, `setmain`) and message sending (`send`, `loop`). Imports from `scheduled_send.py` for code reuse.
4. **session_orchestrator.py** — Generic session orchestrator. Creates a session via API, sends initial prompt, optionally updates an external state file, then enters a periodic wakeup loop.
5. **Shared config** — A single `config.json` (or environment variables) for server address, port, and credentials.

---

## Prerequisites

An OpenCode server must already be running:

```bash
opencode serve --hostname 0.0.0.0 --port 4096
```

---

## Configuration

### Option A: config.json (alongside the skill)

```json
{
  "base_url": "http://localhost:4096",
  "user": "opencode",
  "password": "REPLACE_WITH_SERVER_PASSWORD",
  "main_session": ""
}
```

### Option B: Environment Variables (higher priority)

```bash
export OC_BASE_URL="http://localhost:4096"
export OC_USER="opencode"
export OC_PASS="REPLACE_WITH_SERVER_PASSWORD"
export OC_MAIN_SESSION="ses_xxx"
```

Environment variables override config.json values.

---

## Script 1: session_tree.py

### Purpose

List all OpenCode sessions as a parent→child tree, making it easy for a human or orchestrator to understand the multi-agent topology and find session IDs quickly.

### Usage

```bash
# Show all sessions as a tree
python3 session_tree.py

# Filter sessions by title keyword
python3 session_tree.py SpikeMem

# Explicit filter flag
python3 session_tree.py --filter SpikeMem

# Show only root sessions (no parent)
python3 session_tree.py --roots-only

# Output as JSON (for programmatic consumption)
python3 session_tree.py --json

# Specify config file path
python3 session_tree.py --config /path/to/config.json
```

### Output Format

```
[ROOT ] ses_204ad7347ffet9sOxKUDaTH52q  继续推进研究                 OpenCOOD
    ├─ ses_203b686fbffeXgTHAvaXgT8TbT  SpikeMem-sync-monitor
    ├─ ses_203ca6caaffea4C7aUmnxZUbe5  SpikeComm-LIF-fix
    └─ ses_203dcec19ffeK5mwsBLPQvuZm8  SpikeMem-sync-infer
```

- `[ROOT]` marks sessions with no parentID
- Each line shows: full session ID, title, and the last component of directory
- Sessions are sorted by `time.updated` (most recent first)
- Children appear indented under their parent

### Internal Data Structures

```python
id_to_session = {}      # session_id -> full session dict
parent_to_children = {} # parent_id -> list of child session dicts
```

These enable fast lookup by ID or parentID for orchestrator logic.

---

## Script 2: scheduled_send.py

### Purpose

Send a prompt to a session at a specified time. Before the prompt body, it prepends timestamp context so the receiving agent knows when the instruction was originally issued and when it is being delivered.

All core functions are importable: `load_config()`, `send_prompt()`, `build_message()`, `schedule_and_send()`.

### Usage

```bash
# Send after a relative delay (seconds)
python3 scheduled_send.py \
  --session ses_204ad7347ffet9sOxKUDaTH52q \
  --prompt "继续执行下一阶段任务" \
  --in 300

# Send at an absolute time
python3 scheduled_send.py \
  --session ses_204ad7347ffet9sOxKUDaTH52q \
  --prompt "执行每日检查" \
  --at "2026-05-07 09:00:00"

# Use main_session from config
python3 scheduled_send.py \
  --prompt "你是 orchestrator。读取 tasks.md，只执行一个最小下一步。" \
  --in 60
```

### Prompt Format

The actual text sent to the session is:

```
现在是2026-05-06T14:30:00，收到了一条来自2026-05-06T14:25:00的指令：
<original prompt>
```

This ensures the agent has temporal context (when the instruction was created vs when it was received).

### Reusable Functions

```python
from scheduled_send import load_config, send_prompt, build_message, schedule_and_send

config = load_config()                          # dict with base_url, user, password, main_session
send_prompt(config, session_id, "hello")        # send async prompt
msg = build_message("hello", created_at=None)   # wrap prompt with UTC timestamp
schedule_and_send(sess_id, "ping", 300)         # wait 300s then send
```

---

## Script 3: opencode_client.py

### Purpose

Unified CLI for session management and message sending. Imports from `scheduled_send.py` for `load_config`, `send_prompt`, `build_message`. Uses `session_tree.py` (via subprocess) for session listing.

### Usage

```bash
# List all root sessions (human-readable)
python3 opencode_client.py list

# List all root sessions (JSON, for programmatic consumption)
python3 opencode_client.py list --json

# Set default main session
python3 opencode_client.py setmain ses_204ad7347ffet9sOxKUDaTH52q

# Send a single message immediately
python3 opencode_client.py send --prompt "检查训练进度"

# Send a single message with delay (seconds)
python3 opencode_client.py send --prompt "检查训练进度" --in 900

# Send to a specific session
python3 opencode_client.py send --id ses_xxx --prompt "hello" --in 300

# Periodic send every 60 minutes
python3 opencode_client.py loop --prompt "周期性检查" --time 60

# Periodic send every 30 min, start immediately
python3 opencode_client.py loop --prompt "周期性检查" --time 30 --now
```

---

---

## Script 4: session_orchestrator.py

### Purpose

Generic session orchestrator. Creates a new session via `POST /session`, sends the initial prompt, optionally updates an external state JSON file, then enters a periodic wakeup loop. No project-specific logic — all parameters (agent, directory, prompt, interval) are CLI arguments.

### Usage

```bash
# Full orchestration: create session, send prompt, loop every 15min
python3 session_orchestrator.py   -a opencood-main   -d /home/user/Workspace/MyProject   -p "推进所有研究方向"   -t 15

# Create session + send prompt only (no loop)
python3 session_orchestrator.py 
  -a my-agent -d /path/to/proj -p "start" --no-loop

# Update an external state file with the new session ID
python3 session_orchestrator.py   -a build -d . -p "hello"   --state-file state.json --state-key _meta.session_id

# Custom loop prompt
python3 session_orchestrator.py   -a opencood-main -d ~/Workspace/OpenCOOD -p "推进研究"   --loop-prompt "检查训练进度并推进任务" -t 30
```

### How It Works

1. `POST /session` — creates a new session with the specified agent and directory
2. Optionally writes the session ID to a JSON state file (supporting dot-notation keys)
3. `POST /session/:id/prompt_async` — sends the initial prompt
4. If not `--no-loop`: runs `opencode_client.py loop` for periodic wakeup messages


## Key API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/session` | List sessions |
| GET | `/experimental/session` | Full session registry with parentID |
| GET | `/session/:id` | Get one session |
| GET | `/session/:id/children` | Get child sessions |
| GET | `/session/:id/todo` | Read task list |
| GET | `/session/:id/diff` | Read working diff |
| GET | `/session/:id/status` | Read session status |
| GET | `/session/:id/message` | Read messages |
| POST | `/session/:id/prompt_async` | Send asynchronous prompt |
| GET | `/event` | Server-sent event stream |
| GET | `/global/event` | Global event stream |

---

## Safety Rules

1. Never expose credentials in logs, commits, or shared files.
2. Confirm session ID, directory, and title before sending prompts.
3. Prefer short, bounded prompts.
4. Do not instruct agents to run infinite loops.
5. Long-running orchestration belongs in an external supervisor, not inside an LLM session.
6. Use `/diff`, `/todo`, `/status`, `/children` before making orchestration decisions.
7. For destructive actions, require explicit human approval.

---

## Recommended Multi-Agent Architecture

```
External Supervisor (session_orchestrator.py / cron / manual)
  → opencode_client.py send/loop
    → OpenCode Server API
      → Primary Agent Session
        → Worker Sessions (coder)
        → Reviewer Sessions (reviewer)
        → Planner Sessions (planner)
```

The supervisor handles session creation, initial prompting, periodic wakeups, and state file updates. Agents handle reasoning, implementation, review, and planning without worrying about self-wakeup.

---

## Code Structure

```
opencode-server/
├── config.json                # shared server config
├── session_tree.py            # session listing (standalone)
├── scheduled_send.py          # delayed send + reusable library
├── opencode_client.py         # unified CLI (imports scheduled_send)
├── session_orchestrator.py    # generic session orchestrator
└── SKILL.md                   # this file
```

`scheduled_send.py` is the shared library. `opencode_client.py` imports from it for config loading, prompt building, and API sending. `session_tree.py` is called via subprocess by `opencode_client.py` for session listing.

---

## Common Errors

- **401 Unauthorized**: Check credentials in config.json or environment variables.
- **HTML instead of JSON**: Wrong endpoint path or missing session ID. Use the full `/session/:id` path.
- **204 No Content from prompt_async**: This is success. The message was accepted asynchronously. Use `/event` or `/status` to monitor progress.
- **"expected array" at path "parts"**: The body must contain a `parts` array, not a plain `prompt` string.
