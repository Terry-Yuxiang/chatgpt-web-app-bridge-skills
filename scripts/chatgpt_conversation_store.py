#!/usr/bin/env python3
"""
ChatGPT conversation store — DOM-based implementation.

Extracts the conversation directly from the rendered ChatGPT page DOM using
Chrome DevTools Protocol (CDP). Works regardless of whether Chat History is
enabled on the account.

Each saved record contains:
  turn        — 1-indexed round number (user+assistant = 1 turn)
  role        — "user" | "assistant"
  text        — prose text visible in the message
  artifacts   — list of {title, artifact_type, lang, code} for fenced code blocks
  timestamp   — ISO-8601 UTC
  source      — "dom"
"""

import argparse
import asyncio
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import websockets

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Conversations directory — stored outside the skills folder so it survives
# skills updates or deletion.
#
# Resolution order:
#   1. CHATGPT_BRIDGE_CONV_DIR environment variable
#   2. chatgptBridge.conversationsDir in config.json
#   3. Default: ~/.ai-bridge/chatgpt-bridge/conversations/
# ---------------------------------------------------------------------------

def _resolve_conv_dir() -> Path:
    import os
    # 1. env var
    env = os.environ.get('CHATGPT_BRIDGE_CONV_DIR')
    if env:
        return Path(env).expanduser()
    # 2. config.json
    config_path = ROOT / 'config.json'
    if not config_path.exists():
        config_path = ROOT / 'config.example.json'
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding='utf-8'))
            custom = cfg.get('chatgptBridge', {}).get('conversationsDir')
            if custom:
                return Path(custom).expanduser()
        except Exception:
            pass
    # 3. default
    return Path.home() / '.ai-bridge' / 'chatgpt-bridge' / 'conversations'


CONV_DIR = _resolve_conv_dir()
CONV_DIR.mkdir(parents=True, exist_ok=True)


def conv_subdir(stem: str) -> Path:
    """Return (and create) the per-conversation subdirectory {CONV_DIR}/{stem}/."""
    d = CONV_DIR / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_conversation(query: str):
    """
    Fuzzy-search saved conversations by name, abbreviation, or keywords.

    Matching strategy (highest score wins):
    1. chatId prefix match  -> score 100
    2. Token overlap: each query word found anywhere in corpus  -> +1 per token
    3. Prefix match: each query word is a prefix of any corpus word  -> +1 per token
    4. Consecutive-initials match: short ALL-CAPS query (2-5 chars) matches
       the first letters of N consecutive title words  -> +3
    5. Any-initials subsequence: letters of short ALL-CAPS token appear in
       order as first-letters of title words  -> +2

    All comparisons are case-insensitive.
    Returns list sorted by score desc, then savedAt desc:
      [{'chatId', 'title', 'dir', 'savedAt', 'totalTurns', 'score'}, ...]
    """
    q = query.strip()
    tokens = [t.lower() for t in re.split(r'[^a-zA-Z0-9]+', q) if t]
    # ALL-CAPS short tokens (potential acronyms / ticker symbols)
    raw_tokens = re.split(r'[^a-zA-Z0-9]+', q)
    caps_tokens = [t.lower() for t in raw_tokens if t.isupper() and 2 <= len(t) <= 6]

    results = []
    for d in sorted(CONV_DIR.iterdir()):
        meta_file = d / 'meta.json'
        if not d.is_dir() or not meta_file.exists():
            continue
        try:
            m = json.loads(meta_file.read_text(encoding='utf-8'))
        except Exception:
            continue

        chat_id = m.get('chatId', '')
        title = m.get('title', '').strip()
        tags = ' '.join(m.get('tags', []))
        corpus = (d.name + ' ' + title + ' ' + tags).lower()
        corpus_words = re.findall(r'[a-zA-Z0-9]+', corpus)
        title_words = re.findall(r'[a-zA-Z]+', title + ' ' + tags)
        title_initials = [w[0].lower() for w in title_words if w]

        # 1. chatId prefix
        if q.lower().replace('-', '') in chat_id.replace('-', ''):
            score = 100
        else:
            score = 0
            # 2. token overlap (substring of corpus)
            score += sum(1 for t in tokens if t in corpus)
            # 3. prefix match (each token is a prefix of any corpus word)
            score += sum(1 for t in tokens
                         if any(w.startswith(t) for w in corpus_words) and t not in corpus)
            # 4 & 5. acronym / initials matching for caps tokens
            for ct in caps_tokens:
                n = len(ct)
                # 4. consecutive initials: ct[0..n] matches title_initials[i..i+n]
                matched_consec = any(
                    title_initials[i:i+n] == list(ct)
                    for i in range(len(title_initials) - n + 1)
                )
                if matched_consec:
                    score += 3
                    continue
                # 5. subsequence of initials
                idx = 0
                for ch in ct:
                    while idx < len(title_initials) and title_initials[idx] != ch:
                        idx += 1
                    if idx < len(title_initials):
                        idx += 1
                    else:
                        break
                else:
                    score += 2  # full subsequence matched

        if score > 0:
            results.append({
                'chatId': chat_id,
                'title': title,
                'dir': str(d),
                'savedAt': m.get('savedAt', ''),
                'totalTurns': m.get('totalTurns', 0),
                'score': score,
            })

    results.sort(key=lambda x: (-x['score'], x['savedAt']))
    return results


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9]+', '-', text.strip().lower()).strip('-')
    return text[:80] or 'chatgpt-chat'


def get_chatgpt_page():
    with urllib.request.urlopen('http://127.0.0.1:9222/json/list', timeout=5) as r:
        pages = json.loads(r.read().decode())
    chatgpt_pages = [
        p for p in pages
        if p.get('type') == 'page' and (
            'chatgpt.com' in p.get('url', '') or 'chat.openai.com' in p.get('url', '')
        )
    ]
    if not chatgpt_pages:
        raise SystemExit('ChatGPT page not found on CDP port 9222')
    return chatgpt_pages[-1]


async def cdp_eval(ws_url, expression, await_promise=True):
    async with websockets.connect(ws_url, max_size=50_000_000) as ws:
        await ws.send(json.dumps({
            'id': 1,
            'method': 'Runtime.evaluate',
            'params': {'expression': expression, 'returnByValue': True, 'awaitPromise': await_promise}
        }))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get('id') == 1:
                result = msg.get('result', {}).get('result', {})
                if result.get('type') == 'string':
                    return result.get('value')
                return result.get('value')


# ---------------------------------------------------------------------------
# DOM extraction (primary) — works regardless of Chat History setting
# ---------------------------------------------------------------------------

JS_EXTRACT_DOM = r'''
(() => {
  // ChatGPT renders each turn as <div data-testid="conversation-turn-N">
  // Inside each turn div there is an element with data-message-author-role="user"|"assistant"
  const turnEls = Array.from(document.querySelectorAll('[data-testid^="conversation-turn-"]'));

  const messages = [];
  turnEls.forEach((turnEl, idx) => {
    const roleEl = turnEl.querySelector('[data-message-author-role]');
    if (!roleEl) return;
    const role = roleEl.getAttribute('data-message-author-role');
    if (role !== 'user' && role !== 'assistant') return;

    // Primary: rendered markdown/prose container
    const mdEl = roleEl.querySelector('.markdown')
      || roleEl.querySelector('[class*="prose"]')
      || roleEl.querySelector('[class*="markdown"]')
      || roleEl;

    // Collect code blocks before getting prose text
    const codeBlocks = Array.from(turnEl.querySelectorAll('pre code')).map(el => ({
      lang: (el.className.match(/language-(\S+)/) || [])[1] || 'text',
      code: el.innerText.trim(),
    }));

    const text = (mdEl.innerText || '').trim();

    messages.push({role, text, codeBlocks, turnIndex: idx});
  });

  return JSON.stringify({source: 'dom', messages});
})()
'''

# ---------------------------------------------------------------------------
# API fetch (optional fallback — requires Chat History to be enabled)
# ---------------------------------------------------------------------------

JS_FETCH_CONVERSATION = '''
(async () => {
  const url = location.href;
  const chatId = (url.match(/\\/c\\/([a-zA-Z0-9-]+)/i) || [])[1];
  if (!chatId) return JSON.stringify({error: 'not on a chat page', url});

  const apiUrl = location.origin + '/backend-api/conversation/' + chatId;
  const resp = await fetch(apiUrl, {credentials: 'include'});
  if (!resp.ok) return JSON.stringify({error: 'API responded ' + resp.status, url: apiUrl});

  const data = await resp.json();
  return JSON.stringify(data);
})()
'''

JS_PAGE_META = r'''
(() => {
  const url = location.href;
  const chatId = (url.match(/\/c\/([a-zA-Z0-9-]+)/i) || [])[1] || 'unknown';
  const title = document.title || '';
  return JSON.stringify({title, url, chatId});
})()
'''


# ---------------------------------------------------------------------------
# DOM-based message parsing
# ---------------------------------------------------------------------------

def assign_turns_from_dom(dom_data: dict) -> list:
    """
    Convert JS_EXTRACT_DOM output into clean JSONL records.

    dom_data['messages'] = [{role, text, codeBlocks:[{lang,code}], turnIndex}, ...]

    Turn N = the Nth user message and its following assistant reply.
    Code blocks are stored as artifacts: {title, artifact_type, lang, code}.
    """
    messages = dom_data.get('messages', [])
    records = []
    turn = 0

    for i, msg in enumerate(messages):
        role = msg.get('role', '')
        if role not in ('user', 'assistant'):
            continue
        if role == 'user':
            turn += 1

        text = (msg.get('text') or '').strip()
        code_blocks = msg.get('codeBlocks') or []

        # Build artifacts list from fenced code blocks
        artifacts = []
        for j, cb in enumerate(code_blocks):
            code = (cb.get('code') or '').strip()
            lang = cb.get('lang') or 'text'
            if code:
                artifacts.append({
                    'title': f'code-block-{j+1}',
                    'artifact_type': 'code',
                    'lang': lang,
                    'code': code,
                })

        # Remove code block text from prose (it's captured as artifacts)
        # text already excludes code because innerText on mdEl excludes <pre> content
        # when codeBlocks are collected separately — no further stripping needed.

        if not text and not artifacts:
            continue

        record = {
            'turn': turn,
            'role': role,
            'text': text,
            'timestamp': now_iso(),
            'source': 'dom',
        }
        if artifacts:
            record['artifacts'] = artifacts
        records.append(record)

    return records


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_existing_ids(path: Path):
    """Return set of (turn, role) already saved."""
    seen = set()
    if not path.exists():
        return seen
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            obj = json.loads(line)
            if 'turn' in obj and 'role' in obj:
                seen.add((obj['turn'], obj['role']))
        except Exception:
            continue
    return seen


def append_jsonl(path: Path, rows):
    with path.open('a', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

def _detect_lang(artifact_type: str, code: str) -> str:
    """Guess a fenced-code-block language tag from artifact type and code content."""
    t = artifact_type.lower()
    if 'python' in t:
        return 'python'
    if 'javascript' in t or 'js' in t:
        return 'js'
    if 'typescript' in t or 'ts' in t:
        return 'ts'
    if 'svg' in code[:60]:
        return 'svg'
    if re.search(r'<canvas|Chart\(|new Chart', code[:300]):
        return 'html'
    if code.lstrip().startswith('<'):
        return 'html'
    if 'function ' in code or 'const ' in code or 'let ' in code:
        return 'js'
    return 'text'


def export_to_md(jsonl_path: Path, meta_path: Path) -> Path:
    """
    Convert a saved JSONL conversation to a Markdown file optimised for LLM reading.

    Structure:
      # <title>
      metadata block
      ---
      # Round N
      ## User
      prose text
      ### Artifact: <title>  (if any)
      ```<lang>
      code
      ```
      ## Assistant
      prose text
      ### Artifact: <title>  (if any)
    """
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    records = [json.loads(l) for l in jsonl_path.read_text(encoding='utf-8').splitlines() if l.strip()]

    lines = []

    # header
    title = meta.get('title', '').strip()
    lines.append(f'# {title}')
    lines.append('')
    lines.append('| Field | Value |')
    lines.append('|---|---|')
    lines.append(f'| Chat ID | `{meta.get("chatId","")}` |')
    lines.append(f'| URL | {meta.get("url","")} |')
    lines.append(f'| Project | {meta.get("project","")} |')
    lines.append(f'| Turns | {meta.get("totalTurns","")} |')
    lines.append(f'| Saved | {meta.get("savedAt","")} |')
    lines.append('')

    # group by turn, emit Round headings
    from collections import defaultdict
    turns: dict = defaultdict(dict)
    for rec in records:
        t = rec.get('turn', 0)
        role = rec.get('role', 'unknown')
        turns[t][role] = rec

    for turn_num in sorted(turns.keys()):
        lines.append('---')
        lines.append(f'# Round {turn_num}')
        lines.append('')

        for role_key, heading in [('user', 'User'), ('assistant', 'Assistant')]:
            rec = turns[turn_num].get(role_key)
            if not rec:
                continue

            lines.append(f'## {heading}')
            lines.append('')

            # prose
            text = rec.get('text', '').strip()
            if text:
                lines.append(text)
                lines.append('')

            # artifacts
            for a in rec.get('artifacts', []):
                lines.append(f'### Artifact: {a["title"]}')
                lines.append('')
                # DOM records carry an explicit lang; API records need detection
                lang = a.get('lang') or _detect_lang(a.get('artifact_type', ''), a.get('code', ''))
                lines.append(f'```{lang}')
                lines.append(a.get('code', '').strip())
                lines.append('```')
                lines.append('')

    md_path = jsonl_path.with_suffix('.md')
    md_path.write_text('\n'.join(lines), encoding='utf-8')
    return md_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def cmd_find(query: str):
    """Print fuzzy-matched conversations as JSON and exit."""
    results = find_conversation(query)
    print(json.dumps(results, ensure_ascii=False, indent=2))


def cmd_list():
    """Print all saved conversations as JSON and exit."""
    rows = []
    for d in sorted(CONV_DIR.iterdir()):
        meta_file = d / 'meta.json'
        if not d.is_dir() or not meta_file.exists():
            continue
        try:
            m = json.loads(meta_file.read_text(encoding='utf-8'))
        except Exception:
            continue
        rows.append({
            'chatId': m.get('chatId', ''),
            'title': m.get('title', '').strip(),
            'tags': m.get('tags', []),
            'dir': str(d),
            'savedAt': m.get('savedAt', '')[:10],
            'totalTurns': m.get('totalTurns', 0),
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_tag(chat_id_prefix: str, tags: list):
    """Add tags to a saved conversation's meta.json."""
    results = find_conversation(chat_id_prefix)
    if not results:
        raise SystemExit(f'No conversation found matching: {chat_id_prefix}')
    target = results[0]
    meta_path = Path(target['dir']) / 'meta.json'
    m = json.loads(meta_path.read_text(encoding='utf-8'))
    existing = set(m.get('tags', []))
    existing.update(tags)
    m['tags'] = sorted(existing)
    meta_path.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'chatId': m['chatId'], 'tags': m['tags']}, indent=2))


async def main():
    ap = argparse.ArgumentParser(description='Persist current ChatGPT chat to JSONL + metadata (DOM-based)')
    ap.add_argument('--project', default='general')
    ap.add_argument('--export-md', action='store_true', help='also write a Markdown file alongside the JSONL')
    ap.add_argument('--find', metavar='QUERY', help='fuzzy-search saved conversations and exit')
    ap.add_argument('--list', action='store_true', help='list all saved conversations and exit')
    ap.add_argument('--tag', nargs='+', metavar='TAG',
                    help='add tags to a conversation: --tag <chatId-prefix> <tag1> [tag2 ...]')
    args = ap.parse_args()

    if args.find:
        cmd_find(args.find)
        return
    if args.list:
        cmd_list()
        return
    if args.tag:
        if len(args.tag) < 2:
            ap.error('--tag requires a chatId prefix followed by at least one tag')
        cmd_tag(args.tag[0], args.tag[1:])
        return

    page = get_chatgpt_page()
    ws_url = page['webSocketDebuggerUrl']

    # Get page meta (title, url, chatId)
    meta_raw = await cdp_eval(ws_url, JS_PAGE_META, await_promise=False)
    if not meta_raw:
        raise SystemExit('Could not read page meta')
    meta_info = json.loads(meta_raw)
    title = meta_info.get('title', 'ChatGPT')
    url = meta_info.get('url', '')
    chat_id = meta_info.get('chatId', 'unknown')

    # Extract conversation from DOM (works without Chat History)
    dom_raw = await cdp_eval(ws_url, JS_EXTRACT_DOM, await_promise=False)
    if not dom_raw:
        raise SystemExit('DOM extraction returned no data')
    dom_data = json.loads(dom_raw)
    if 'error' in dom_data:
        raise SystemExit(f"DOM extraction error: {dom_data['error']}")

    records = assign_turns_from_dom(dom_data)
    if not records:
        raise SystemExit('No messages found in DOM — is a ChatGPT conversation open?')

    # File paths — each conversation lives in its own subdirectory
    slug = slugify(title.strip())
    stem = f"{slug}--{chat_id}"
    conv_dir = conv_subdir(stem)
    meta_path = conv_dir / 'meta.json'
    jsonl_path = conv_dir / 'conversation.jsonl'

    # Save meta
    meta_path.write_text(json.dumps({
        'chatId': chat_id,
        'title': title,
        'url': url,
        'project': args.project,
        'savedAt': now_iso(),
        'source': 'dom',
        'totalTurns': max((r['turn'] for r in records), default=0),
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    # Dedup by (turn, role)
    seen = load_existing_ids(jsonl_path)
    new_rows = [r for r in records if (r['turn'], r['role']) not in seen]
    append_jsonl(jsonl_path, new_rows)

    result = {
        'ok': True,
        'dir': str(conv_dir),
        'meta': str(meta_path),
        'jsonl': str(jsonl_path),
        'totalMessages': len(records),
        'newMessagesWritten': len(new_rows),
    }
    if args.export_md:
        md_path = export_to_md(jsonl_path, meta_path)
        result['md'] = str(md_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
