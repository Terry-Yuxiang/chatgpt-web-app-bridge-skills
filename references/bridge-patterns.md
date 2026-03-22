# Bridge Patterns

General patterns for using the ChatGPT web bridge effectively.

## Context packet structure

When forwarding a task to ChatGPT, always include a compact environment context packet. Include only what is relevant — do not pad.

```
OS: macOS (Darwin)
Repo: /path/to/repo
Framework: Next.js 14 / Node 20
Package manager: pnpm
Goal: <what you're trying to accomplish>
Command: <exact command being run>
Error:
<exact error output, trimmed to the relevant part>
Constraints: production env, no destructive changes
```

## Forwarding prompts

### Diagnosis mode

Use when you need ChatGPT to identify the root cause of a problem.

```
[Context packet above]

Task: Diagnose this error. Identify the root cause and the most likely fix.
Do not write code yet — just explain what is wrong and why.
```

### Patch-plan mode

Use when you need a concrete patch, not just an explanation.

```
[Context packet above]

Task: Write the minimal patch to fix this. Show only changed lines with file paths.
Do not rewrite files that don't need changing.
```

### Review mode

Use when you want ChatGPT to review a planned fix before you apply it.

```
[Context packet above]

Planned fix:
<your proposed change>

Task: Review this fix. Is it correct? Will it break anything else?
Point out any edge cases or issues I might have missed.
```

### Compare-options mode

Use when you want to evaluate multiple approaches before committing.

```
[Context packet above]

Task: Compare these approaches:
1. <option A>
2. <option B>

Evaluate trade-offs: correctness, performance, maintainability, risk.
Recommend one and explain why.
```

## Polling for response completion

After sending a question, poll `read` until the tail stops changing:

```bash
python scripts/chatgpt_web_probe.py ask --question "..."
sleep 10
python scripts/chatgpt_web_probe.py read  # capture tail1
sleep 10
python scripts/chatgpt_web_probe.py read  # capture tail2
# if tail1 == tail2, response is complete
```

Maximum polling time: 60 seconds for most tasks. For very long tasks (code generation, analysis), allow up to 120 seconds.

## Saving and using conversation history

After each round:
```bash
python scripts/chatgpt_conversation_store.py --export-md
```

The `.md` export is structured for LLM reading:
- Each round is clearly separated
- User and Assistant messages are labeled
- Code artifacts are in fenced blocks with language tags

To reference a prior conversation in a new session:
1. Find it: `python scripts/chatgpt_conversation_store.py --find "keyword"`
2. Read the `.md` file from the returned directory
3. Paste relevant rounds as context into the new session

## Tagging for retrieval

After saving a conversation, add tags to make it findable by abbreviation:

```bash
python scripts/chatgpt_conversation_store.py --tag <chatId-prefix> <tag1> [tag2 ...]
```

Examples:
- `--tag abc123 SMCI stock earnings`
- `--tag def456 nextjs build error webpack`

Tags are searched by `--find` alongside the title and directory name.

## When NOT to use the bridge

- For questions answerable in under 30 seconds locally
- When the user explicitly wants a local answer
- When the browser automation browser is not running
- When you are not logged in to chatgpt.com
- When the task requires access to local files that cannot be pasted (too large, binary)

Always verify the bridge is functioning before committing to it for a long task.
