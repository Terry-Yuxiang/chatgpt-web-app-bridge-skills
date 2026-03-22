#!/usr/bin/env python3
"""Low-level ChatGPT web bridge helper.

This script works against an already logged-in chatgpt.com page in the dedicated
Chrome automation browser on CDP port 9222.

Commands:
- probe: inspect page state
- ask: submit a question
- read: read visible tail text from the page
- navigate: navigate to a URL or conversation

This is a bridge helper, not a complete production command by itself.
"""

import argparse
import asyncio
import json
import urllib.request
import websockets


def get_chatgpt_page():
    with urllib.request.urlopen('http://127.0.0.1:9222/json/list', timeout=5) as r:
        pages = json.loads(r.read().decode())
    for p in pages:
        url = p.get('url', '')
        if p.get('type') == 'page' and ('chatgpt.com' in url or 'chat.openai.com' in url):
            return p
    raise SystemExit('ChatGPT page not found on CDP port 9222')


async def cdp_eval(ws_url, expression):
    async with websockets.connect(ws_url, max_size=10_000_000) as ws:
        await ws.send(json.dumps({
            'id': 1,
            'method': 'Runtime.evaluate',
            'params': {
                'expression': expression,
                'returnByValue': True,
                'awaitPromise': True,
            }
        }))
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg.get('id') == 1:
                return msg


def js_probe():
    return r"""
(() => {
  const inputs = Array.from(document.querySelectorAll('div[contenteditable="true"], textarea, input')).map((el, i) => ({
    index: i,
    tag: el.tagName,
    id: el.id || null,
    aria: el.getAttribute('aria-label'),
    placeholder: el.getAttribute('placeholder'),
    text: (el.innerText || el.value || '').slice(0, 120)
  }));
  const buttons = Array.from(document.querySelectorAll('button')).map((el, i) => ({
    index: i,
    text: (el.innerText || '').trim().slice(0, 120),
    aria: el.getAttribute('aria-label'),
    testid: el.getAttribute('data-testid'),
    disabled: !!el.disabled
  })).filter(x => x.text || x.aria).slice(0, 60);
  return {
    title: document.title,
    url: location.href,
    bodyTextSample: (document.body.innerText || '').slice(0, 3000),
    inputs,
    buttons,
  };
})();
"""


def js_ask(question):
    q = json.dumps(question)
    return f"""
(async () => {{
  const q = {q};
  const clickLikeHuman = (el) => ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => el.dispatchEvent(new MouseEvent(type, {{bubbles:true,cancelable:true,view:window}})));

  // Dismiss any overlay using Escape
  document.dispatchEvent(new KeyboardEvent('keydown', {{key:'Escape', bubbles:true, cancelable:true}}));
  await new Promise(r => setTimeout(r, 400));

  // Find ChatGPT's prompt textarea — try #prompt-textarea first, then generic fallback
  let ta = document.getElementById('prompt-textarea');
  if (!ta || ta.getAttribute('contenteditable') !== 'true') {{
    ta = Array.from(document.querySelectorAll('div[contenteditable="true"]')).find(el => {{
      const id = el.id || '';
      const aria = el.getAttribute('aria-label') || '';
      const ph = el.getAttribute('placeholder') || '';
      return /prompt|message|chat/i.test(id + ' ' + aria + ' ' + ph) || true;
    }});
  }}
  if (!ta) return {{ok:false,error:'input not found'}};
  const before = document.body.innerText || '';
  ta.focus();
  // Use execCommand so React's synthetic event system picks up the change
  document.execCommand('selectAll', false, null);
  document.execCommand('delete', false, null);
  document.execCommand('insertText', false, q);
  await new Promise(r => setTimeout(r, 600));

  // Find send button — try data-testid="send-button" first, then aria/type fallbacks
  const btns = Array.from(document.querySelectorAll('button'));
  const send = btns.find(b => !b.disabled && b.getAttribute('data-testid') === 'send-button')
    || btns.find(b => !b.disabled && /send/i.test((b.getAttribute('aria-label')||'') + ' ' + (b.innerText||'')))
    || btns.find(b => !b.disabled && b.getAttribute('type') === 'submit');
  if (!send) return {{ok:false,error:'send button not found'}};
  clickLikeHuman(send);
  await new Promise(r => setTimeout(r, 1200));
  const after = document.body.innerText || '';
  return {{ok:true, bodyChanged: before !== after, hasQuestionAfter: after.includes(q)}};
}})();
"""


def js_read():
    return r"""
(() => {
  const txt = document.body.innerText || '';
  const lines = txt.split('\n').filter(Boolean);
  return {
    title: document.title,
    sampleTail: lines.slice(-120).join('\n').slice(-9000)
  };
})();
"""


def js_navigate(url):
    u = json.dumps(url)
    # Synchronous — do not await after setting href.
    # The page will navigate and sever the CDP connection immediately;
    # we handle that in Python rather than trying to return from JS.
    return f"window.location.href = {u};"


async def main():
    ap = argparse.ArgumentParser(description='Low-level ChatGPT web bridge helper')
    ap.add_argument('command', choices=['probe', 'ask', 'read', 'navigate'])
    ap.add_argument('--question')
    ap.add_argument('--url', help='URL to navigate to (for navigate command)')
    ap.add_argument('--chat-id', help='ChatGPT conversation ID to resume (shorthand for navigate)')
    args = ap.parse_args()

    if args.command == 'ask' and not args.question:
        ap.error('ask command requires --question')
    if args.command == 'navigate' and not args.url and not args.chat_id:
        ap.error('navigate command requires --url or --chat-id')

    page = get_chatgpt_page()
    ws = page['webSocketDebuggerUrl']

    if args.command == 'navigate':
        target_url = args.url or f'https://chatgpt.com/c/{args.chat_id}'
        expr = js_navigate(target_url)
    elif args.command == 'probe':
        expr = js_probe()
    elif args.command == 'ask':
        expr = js_ask(args.question)
    else:
        expr = js_read()

    result = await cdp_eval(ws, expr)

    # For navigate: two success signals —
    #   1. JS returns the URL string (assignment completed before page unloads)
    #   2. CDP error -32000 "navigated or closed" (page unloaded during await)
    if args.command == 'navigate':
        target_url = args.url or f'https://chatgpt.com/c/{args.chat_id}'
        err = result.get('error', {})
        val = result.get('result', {}).get('result', {}).get('value')
        if (err.get('code') == -32000 and 'navigated' in err.get('message', '').lower()) \
                or val == target_url:
            print(json.dumps({'ok': True, 'navigatedTo': target_url}, indent=2))
        else:
            print(json.dumps(val if val is not None else result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result.get('result', {}).get('result', {}).get('value', result), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
