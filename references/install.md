# Installation

## Required local environment

- macOS
- Google Chrome
- A dedicated automation browser/profile that can be reused for ChatGPT and browser-driven workflows
- Python 3
- Chrome DevTools Protocol access on port `9222`

## Python dependencies

Create a local virtual environment inside the skill/project directory and install:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

Current required packages:
- `websockets`

## Runtime expectation

This skill operates via the **ChatGPT web bridge via chatgpt.com**:
- Uses browser automation and CDP
- Requires a Chrome instance running with `--remote-debugging-port=9222`
- Requires being logged in to chatgpt.com in that browser

## Starting the automation browser

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chatgpt-cdp-profile
```

Then open `https://chatgpt.com` and log in before running any scripts.

## ChatGPT account settings

No special account settings are required. The conversation store uses **DOM extraction** — it reads the rendered page content directly rather than calling the ChatGPT REST API. This works regardless of whether Chat History is enabled.

## Verification steps

### 1. Probe — confirm the bridge sees the ChatGPT page

```bash
. .venv/bin/activate
python scripts/chatgpt_web_probe.py probe
```

Expected: JSON with `"title"` and `"url"` pointing to `chatgpt.com`. Inputs list should include `#prompt-textarea`.

### 2. Ask and read back (Round 1)

```bash
python scripts/chatgpt_web_probe.py ask --question "Round 1: What are the top 3 differences between GPT-4o and GPT-4o mini in terms of capability and cost?"
sleep 10
python scripts/chatgpt_web_probe.py read
```

Expected: `sampleTail` contains ChatGPT's reply about GPT-4o vs GPT-4o mini.

### 3. Save Round 1 to subdirectory

```bash
python scripts/chatgpt_conversation_store.py --export-md --project bridge-testing
```

Expected output:
```json
{
  "ok": true,
  "dir": "/Users/<you>/.ai-bridge/chatgpt-bridge/conversations/<slug>--<chatId>",
  "meta": "...meta.json",
  "jsonl": "...conversation.jsonl",
  "totalMessages": 2,
  "newMessagesWritten": 2,
  "md": "...conversation.md"
}
```

Note the `<slug>--<chatId>` value from `"dir"` — you'll need it below.

Verify files were created:
```bash
ls ~/.ai-bridge/chatgpt-bridge/conversations/<slug>--<chatId>/
# should show: conversation.jsonl  meta.json  conversation.md
```

### 4. Send Round 2 and save incrementally

```bash
python scripts/chatgpt_web_probe.py ask --question "Round 2: Give me a one-line summary of when to pick GPT-4o mini over GPT-4o."
sleep 10
python scripts/chatgpt_web_probe.py read
python scripts/chatgpt_conversation_store.py --export-md --project bridge-testing
```

Expected: `totalMessages: 4`, `newMessagesWritten: 2`. Re-running store is safe — existing turns are deduped.

### 5. Navigate to the saved conversation and continue (Round 3)

Get the chat ID from the saved meta:
```bash
cat ~/.ai-bridge/chatgpt-bridge/conversations/<slug>--<chatId>/meta.json
# note the "chatId" field
```

Navigate to it:
```bash
python scripts/chatgpt_web_probe.py navigate --chat-id <chatId>
# or: python scripts/chatgpt_web_probe.py navigate --url https://chatgpt.com/c/<chatId>
```

Expected:
```json
{"ok": true, "navigatedTo": "https://chatgpt.com/c/<chatId>"}
```

Confirm the browser is on the right page:
```bash
sleep 2
python scripts/chatgpt_web_probe.py probe
# "title" and "url" should match the saved conversation
```

Send Round 3 and save:
```bash
python scripts/chatgpt_web_probe.py ask --question "Round 3: What is one real-world use case where GPT-4o is clearly the better choice?"
sleep 12
python scripts/chatgpt_conversation_store.py --export-md --project bridge-testing
```

Expected: `totalMessages: 6`, `newMessagesWritten: 2`.

### 6. Verify the Markdown structure

```bash
cat ~/.ai-bridge/chatgpt-bridge/conversations/<slug>--<chatId>/conversation.md | head -40
```

Expected structure:
```
# <Conversation title>
| Field | Value |
...

---
# Round 1
## User
...
## Assistant
...
---
# Round 2
...
```

Only claim the bridge is working if each step above produces the expected output.
