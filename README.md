# chatgpt-web-app-bridge-skills

A Claude Code skill that bridges the agent to the **ChatGPT web app** via Chrome DevTools Protocol (CDP). Use it to forward questions or long coding/debugging tasks to ChatGPT, read back real responses, and persist conversations for future reference.

## What it does

- Sends messages to ChatGPT web app from within a Claude Code session
- Reads ChatGPT's responses back into the agent's context
- Saves full conversations (text + code artifacts) as JSONL + Markdown
- Navigates to previously saved conversations to continue them
- Supports routing mode: toggle all messages through the bridge with `/chatgpt start` / `/chatgpt end`

## Prerequisites

- macOS with Google Chrome
- Chrome launched with CDP on port 9222:
  ```bash
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=/tmp/chatgpt-cdp-profile
  ```
- Logged in to chatgpt.com in that browser
- Python 3

## Installation

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Project layout

```
.claude/commands/
  chatgpt.md             <- /chatgpt slash command definition
references/
  install.md             <- full installation and verification steps
  bridge-patterns.md     <- context packet patterns and forwarding prompts
  conversation-continuation.md  <- how to resume a saved conversation
scripts/
  chatgpt_web_probe.py   <- low-level CDP bridge: probe / ask / read / navigate
  chatgpt_conversation_store.py  <- save current chat to conversations/
  bridge_config.py       <- read config.json / config.example.json
config.json              <- bridge policy (autoBridgeAllowed, defaultMode, etc.)
state.json               <- current routing mode and active conversation
SKILL.md                 <- skill definition loaded by Claude Code
```

## Slash commands

| Command | Effect |
|---|---|
| `/chatgpt start` | Enable routing mode — all subsequent messages forwarded to ChatGPT web app |
| `/chatgpt end` | Disable routing mode |
| `/chatgpt +<message>` | Route a single message through the bridge |
| `/chatgpt conversation list` | List all saved conversations |
| `/chatgpt conversation <name> +<message>` | Navigate to a named conversation and send a message |

`<name>` supports fuzzy matching: partial title words, abbreviations, and ticker symbols all work
(e.g. `SMCI` matches `Super Micro Computer's rise and business model`).

## Key scripts

### `chatgpt_web_probe.py`

Low-level CDP operations:

```bash
. .venv/bin/activate

# Check page state
python scripts/chatgpt_web_probe.py probe

# Send a message
python scripts/chatgpt_web_probe.py ask --question "Your question here"

# Read the current page tail
python scripts/chatgpt_web_probe.py read

# Navigate to a saved conversation
python scripts/chatgpt_web_probe.py navigate --chat-id <chatId>
python scripts/chatgpt_web_probe.py navigate --url https://chatgpt.com/c/<chatId>
```

### `chatgpt_conversation_store.py`

Save the current ChatGPT chat to `~/.ai-bridge/chatgpt-bridge/conversations/` (outside the skills folder — survives skills updates or deletion):

```bash
python scripts/chatgpt_conversation_store.py --export-md --project my-project
```

Output: `~/.ai-bridge/chatgpt-bridge/conversations/{slug}--{chatId}/conversation.jsonl`, `meta.json`, `conversation.md`

Re-running is safe — only new turns are appended.

List or search saved conversations:

```bash
python scripts/chatgpt_conversation_store.py --list
python scripts/chatgpt_conversation_store.py --find "SMCI"
```

Add searchable tags (e.g. ticker symbols or abbreviations) to a conversation:

```bash
python scripts/chatgpt_conversation_store.py --tag <chatId-prefix> SMCI stock
```

Tags are stored in `meta.json` and searched by `--find`.

## Verification

See `references/install.md` for the full step-by-step verification sequence covering:
1. Basic probe / ask / read
2. Save conversation to subdirectory
3. Navigate to a saved conversation and continue it

Quick smoke test:

```bash
. .venv/bin/activate
python scripts/chatgpt_web_probe.py probe
python scripts/chatgpt_web_probe.py ask --question "Reply with exactly: CHATGPT_BRIDGE_OK"
sleep 8
python scripts/chatgpt_web_probe.py read
python scripts/chatgpt_conversation_store.py --export-md --project bridge-testing
```

## Conversation Markdown format

Saved `.md` files use this structure for LLM consumption:

```
# Conversation title
| metadata |

---
# Round 1
## User
[message]
## Assistant
[reply]
### Artifact: name
```lang
code
```
```

## config.json fields

```json
{
  "chatgptBridge": {
    "enabled": true,
    "autoBridgeAllowed": false,
    "defaultMode": "diagnosis",
    "useChatGPTWeb": true,
    "requireRealResponse": true,
    "conversationsDir": "~/.ai-bridge/chatgpt-bridge/conversations"
  }
}
```

- `autoBridgeAllowed` — if `true`, agent may auto-invoke bridge for long coding tasks
- `defaultMode` — preferred mode when none specified (`diagnosis` / `patch-plan` / `review` / `compare-options`)
- `requireRealResponse` — never present a local guess as a ChatGPT response
- `conversationsDir` — override where conversations are stored (default: `~/.ai-bridge/chatgpt-bridge/conversations`)

## How conversation extraction works

The store script uses **DOM extraction** — it reads `[data-testid^="conversation-turn-"]` elements directly from the rendered page. This works regardless of whether Chat History is enabled in the ChatGPT account settings, and requires no API authentication beyond the existing browser session.

Code blocks are captured as artifacts from `<pre><code>` elements within each turn. The prose text is read from the markdown/prose container inside each turn element.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Terry-Yuxiang/chatgpt-web-app-bridge-skills&type=Date)](https://star-history.com/#Terry-Yuxiang/chatgpt-web-app-bridge-skills&Date)

## Important constraints

- Never imply ChatGPT answered when the bridge did not actually run
- The automation browser must be running with `--remote-debugging-port=9222`
- When acting as an AI agent: execute bash commands directly — do not invoke `/chatgpt` via the Skill tool
