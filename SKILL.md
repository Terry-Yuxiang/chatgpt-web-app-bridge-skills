---
name: chatgpt-web-app-bridge-skills
description: Bridge selected coding questions and long implementation or debugging subtasks to ChatGPT, especially for web-app and production-environment work. Use when the user wants the assistant to forward a problem to ChatGPT, include environment/runtime/build context, wait for ChatGPT's real response, and then use that response downstream to save tokens during longer coding or debugging workflows.
---

Use this skill when the user wants a **ChatGPT bridge**, not a purely local answer.

What this skill is for:
- forwarding selected questions to ChatGPT
- forwarding long coding or debugging subtasks to ChatGPT
- including compact but sufficient environment context
- waiting for ChatGPT's real answer before proceeding
- using ChatGPT as an external reasoning/coding assist layer to save tokens

Current bridge modes:
1. **ChatGPT web bridge via chatgpt.com**
   - validated on this machine
   - uses the dedicated automation browser and Chrome CDP on port `9222`

Hard boundary:
- Never imply ChatGPT answered when the bridge did not actually run.
- Never present a local guess as if it came from ChatGPT.

Auto-bridge policy:
- Read `config.json` if present, otherwise fall back to `config.example.json`.
- Respect `chatgptBridge.autoBridgeAllowed`.
- If `autoBridgeAllowed=false`, do not auto-start ChatGPT for eligible tasks without user intent.
- If `autoBridgeAllowed=true`, ChatGPT may be invoked automatically for long coding/debugging tasks that clearly benefit from external reasoning.

Routing mode (session state):
- Read `state.json` at the start of each response.
- If `routingMode: true`, forward every user message to the ChatGPT web bridge (same as `/chatgpt +<message>`).
- If `activeConversation` is set, navigate to that conversation before sending.
- Routing mode is toggled via `/chatgpt start` and `/chatgpt end`.

Standard bridge workflow:
1. Decide whether the task should be forwarded to ChatGPT.
2. Build a compact environment context packet.
3. Choose the actual bridge path:
   - chatgpt.com browser bridge
4. Feed ChatGPT the task in a direct way:
   - paste the task content directly into ChatGPT, or
   - upload the relevant file(s) to ChatGPT
   Do not rely on ChatGPT inferring local file contents that were never pasted or uploaded.
5. Wait for ChatGPT's real output.
6. Use that output as guidance, patch plan, implementation hint, or comparison answer.
7. Tell the user when the result came from ChatGPT.

Multi-turn conversation save policy:
- Save after **every completed assistant turn** (not only at end of session).
- Run `scripts/chatgpt_conversation_store.py --export-md` after each round.
- Each conversation is stored under `~/.ai-bridge/chatgpt-bridge/conversations/{slug}--{chatId}/` (outside the skills folder — persists across skills updates):
  - `conversation.jsonl` — structured records, one per message
  - `meta.json` — chat ID, title, URL, total turns, saved timestamp
  - `conversation.md` — LLM-readable export (Round -> User/Assistant heading structure)
- Saving is idempotent: re-running only appends new turns.

Conversation continuation workflow:
1. Read `meta.json` from the target conversation directory to get `chatId` and `url`.
2. Navigate the automation browser to that conversation:
   ```
   python scripts/chatgpt_web_probe.py navigate --chat-id <chatId>
   ```
   Or equivalently:
   ```
   python scripts/chatgpt_web_probe.py navigate --url https://chatgpt.com/c/<chatId>
   ```
3. Wait ~2 seconds for the page to load, then verify with `probe` or `read`.
4. Continue the conversation with `ask`:
   ```
   python scripts/chatgpt_web_probe.py ask --question "..."
   ```
5. After the assistant responds, save the updated conversation:
   ```
   python scripts/chatgpt_conversation_store.py --export-md
   ```

Question/answer bridge standard:
1. send the question
2. wait until ChatGPT fully finishes answering
3. read only the new visible answer for this query
4. do not mix old answers into the new result

Minimum environment context to include for web-app tasks:
- operating system and machine type
- repo path / project path
- framework/runtime (for example Next.js, Node version)
- package manager if known
- relevant browser or automation context if relevant
- exact failing command or goal
- exact error snippet
- constraints (production, staging, local only, no destructive changes, etc.)

Good fit examples:
- failing web-app build or deploy
- long debugging branches
- comparing alternate implementation strategies
- asking ChatGPT for a patch approach before local execution
- asking ChatGPT to review a planned fix in a production-like environment

Bad fit examples:
- tiny questions that are faster to answer locally
- cases where the user explicitly asked for real ChatGPT output but ChatGPT is unavailable
- situations where direct local verification matters more than extra ChatGPT reasoning

Slash commands (`.claude/commands/`):
- `/chatgpt start` — enable routing mode (all messages forwarded to ChatGPT web app)
- `/chatgpt end` — disable routing mode
- `/chatgpt +<message>` — route a single message through the bridge
- `/chatgpt conversation list` — list all saved conversations
- `/chatgpt conversation <name> +<message>` — navigate to a named conversation and send a message

Bundled resources:
- `state.json` for current routing mode and active conversation state
- `references/install.md` for required local environment and dependency setup
- `references/bridge-patterns.md` for prompt-shaping and context-packet patterns
- `references/conversation-continuation.md` for resuming a saved conversation in the browser
- `scripts/chatgpt_web_probe.py` for validated low-level chatgpt.com bridge operations (probe / ask / read / navigate)
- `scripts/bridge_config.py` for config and auto-bridge policy control
- `scripts/chatgpt_conversation_store.py` for saving ChatGPT chat state into per-conversation subdirectories with jsonl + meta + md
