Handle the following ChatGPT bridge subcommand from $ARGUMENTS.

Read the project root at the working directory. The venv is at `.venv/` — activate it before running any script: `. .venv/bin/activate`.

---

## Subcommands

### `start`
Enable routing mode for this session.
1. Read `state.json`, set `routingMode` to `true`, write it back.
2. Reply: "**Routing mode ON** — all subsequent messages will be forwarded to the ChatGPT web app."

### `end`
Disable routing mode.
1. Read `state.json`, set `routingMode` to `false` and `activeConversation` to `null`, write it back.
2. Reply: "**Routing mode OFF** — messages will be answered locally."

### `+<message>` (args starts with `+`)
Route this single message through the ChatGPT web bridge, regardless of routing mode.
1. Extract the message: everything after the leading `+` (trim whitespace).
2. Check `state.json` for `activeConversation`. If set, navigate to it first:
   ```
   python scripts/chatgpt_web_probe.py navigate --chat-id <activeConversation>
   sleep 2
   ```
3. Send the message:
   ```
   python scripts/chatgpt_web_probe.py ask --question "<message>"
   ```
4. Wait for the response to complete (poll `read` every 10s until the tail stops changing, max 60s).
5. Save the conversation:
   ```
   python scripts/chatgpt_conversation_store.py --export-md
   ```
6. Show the assistant's response to the user.

### `conversation list`
List all saved conversations.
1. Run:
   ```
   python scripts/chatgpt_conversation_store.py --list
   ```
2. Display the results as a table:
   ```
   #  | Title                        | Chat ID (short)  | Turns | Saved
   ---|------------------------------|------------------|-------|-------
   1  | Understanding attention...   | a262f217         | 4     | 2026-03-21
   ```
3. Note which conversation is currently active (from `state.json` → `activeConversation`).

### `conversation <name> +<message>`
Navigate to a named conversation and send a message.
Parse args: everything before ` +` is the name/search term; everything after ` +` is the message.

1. Run the fuzzy finder:
   ```
   python scripts/chatgpt_conversation_store.py --find "<name>"
   ```
   This returns a JSON array sorted by score. Take the first result (highest score).

   - If the array is **non-empty**: use the top result.
   - If the array is **empty**: the string matcher found nothing. Fall back:
     1. Run `python scripts/chatgpt_conversation_store.py --list` to get all titles.
     2. Use your own semantic reasoning to identify the best match.
        Example: "SMCI" → you know this refers to Super Micro Computer (stock ticker).
     3. If you can confidently identify a match, proceed with that conversation and
        tell the user: "Matched **<title>** via semantic lookup (no keyword overlap found)."
     4. If you genuinely cannot identify a match, show the list and ask the user to clarify.
   - If the top two results have equal score: list both titles and ask the user to be more specific.

2. Navigate to it:
   ```
   python scripts/chatgpt_web_probe.py navigate --chat-id <chatId>
   sleep 2
   python scripts/chatgpt_web_probe.py probe   # verify page title matches
   ```
3. Update `state.json`: set `activeConversation` to the matched `chatId`.
4. Send the message:
   ```
   python scripts/chatgpt_web_probe.py ask --question "<message>"
   ```
5. Wait for response (poll `read` every 10s, max 60s).
6. Save:
   ```
   python scripts/chatgpt_conversation_store.py --export-md
   ```
7. Show the assistant's response and confirm: "Active conversation set to: **<title>**".

---

### Tagging a conversation

To make a conversation findable by abbreviation or ticker symbol, add tags after saving:
```
python scripts/chatgpt_conversation_store.py --tag <chatId-prefix> <tag1> [tag2 ...]
```
Example: `python scripts/chatgpt_conversation_store.py --tag 44cfba67 SMCI stock`

---

## Routing mode behaviour (for `start` / `end` state)

When `state.json` has `routingMode: true`, the agent should treat every subsequent user message as a `+<message>` bridge call — forward it to the ChatGPT web app, read back the response, save, and present the result. This persists until `/chatgpt end` is called.

Check `state.json` at the start of each response when this skill is active.
