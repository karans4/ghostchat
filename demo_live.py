#!/usr/bin/env python3
"""Live demo: Claude + Ollama chatting in Ghost Chat, visible in browser.
Creates room, shows QR code, connects bot, exchanges messages.
Browser stays open for user to join from phone.
"""
import time, requests, sys
from playwright.sync_api import sync_playwright

URL = 'http://localhost:8091/ghost.html'

def ollama(text):
    r = requests.post('http://localhost:11434/api/chat', json={
        'model': 'qwen2.5:3b',
        'messages': [
            {'role': 'system', 'content': 'You are a friendly AI in an encrypted P2P chat room called Ghost Chat. Keep responses to 1-2 short sentences. Be casual and fun.'},
            {'role': 'user', 'content': text}
        ],
        'stream': False
    }, timeout=120)
    return r.json()['message']['content'].strip().split('\n')[0]

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=[
            '--disable-gpu', '--window-size=900,700', '--window-position=50,50'
        ])
        ctx = browser.new_context(viewport={'width': 880, 'height': 680})

        # === TAB 1: Claude creates room ===
        claude = ctx.new_page()
        claude.goto(URL)
        claude.wait_for_selector('#nick-in')
        claude.fill('#nick-in', 'claude')
        claude.click('#btn-create')
        print('[*] Room created as "claude"')

        # Wait for offer code
        claude.wait_for_function(
            "document.querySelector('#my-code')?.value?.startsWith('O:')",
            timeout=15000
        )
        offer = claude.input_value('#my-code')
        room_url = claude.url
        print(f'[*] Room URL: {room_url}')

        # Screenshot the QR code
        time.sleep(1)
        claude.screenshot(path='/mnt/shared/ghost_qr.png', full_page=False)
        print('[*] QR screenshot saved to /mnt/shared/ghost_qr.png')

        # === TAB 2: Ollama bot joins ===
        bot = ctx.new_page()
        bot.goto(URL)
        bot.wait_for_selector('#nick-in')
        bot.fill('#nick-in', 'qwen')
        bot.click('#btn-join')
        bot.wait_for_selector('#room-url')
        bot.fill('#room-url', room_url)
        bot.click('#btn-go')
        print('[*] qwen joining...')

        bot.wait_for_selector('#host-code', timeout=15000)
        bot.fill('#host-code', offer)
        bot.click('#btn-process')

        bot.wait_for_function(
            "document.querySelector('#my-answer')?.value?.startsWith('A:')",
            timeout=15000
        )
        answer = bot.input_value('#my-answer')
        print('[*] Got answer code')

        # Claude accepts answer
        claude.fill('#peer-code', answer)
        claude.click('#btn-connect')

        # Wait for chat
        claude.wait_for_selector('#chat-view', timeout=15000)
        bot.wait_for_selector('#chat-view', timeout=15000)
        print('[+] Connected! Both in chat.\n')

        # === CLAUDE SAYS SOMETHING ===
        claude.fill('#msg-in', "hey qwen, what do you think about peer-to-peer encrypted chat?")
        claude.click('#btn-send')
        print('[claude] hey qwen, what do you think about peer-to-peer encrypted chat?')
        time.sleep(2)

        # === OLLAMA RESPONDS ===
        reply = ollama("hey qwen, what do you think about peer-to-peer encrypted chat?")
        bot.fill('#msg-in', reply)
        bot.click('#btn-send')
        print(f'[qwen] {reply}')
        time.sleep(1)

        # Another exchange
        claude.fill('#msg-in', "waiting for karan to join from his phone. he's going to scan the QR code.")
        claude.click('#btn-send')
        print('[claude] waiting for karan to join from his phone...')
        time.sleep(2)

        reply2 = ollama("The creator said they're waiting for a human named Karan to join from his phone by scanning a QR code. Say something welcoming.")
        bot.fill('#msg-in', reply2)
        bot.click('#btn-send')
        print(f'[qwen] {reply2}')
        time.sleep(1)

        # Switch to claude's tab and screenshot the chat
        claude.bring_to_front()
        time.sleep(0.5)
        claude.screenshot(path='/mnt/shared/ghost_chat.png', full_page=False)
        print('\n[*] Chat screenshot saved to /mnt/shared/ghost_chat.png')
        print(f'[*] Room link: {room_url}')
        print('[*] Browser is open. Scan QR from /mnt/shared/ghost_qr.png to join.')
        print('[*] Press Ctrl+C to close.\n')

        # Keep browser open for user to join
        try:
            while True:
                time.sleep(5)
                # Check for new messages from user on claude's side
                msgs = claude.evaluate("""() => {
                    const els = document.querySelectorAll('#messages .msg:not(.sys)');
                    return Array.from(els).map(el => el.textContent);
                }""")
                # If there's a new message not from claude or qwen, have qwen respond
                for m in msgs:
                    if '] karan:' in m.lower() or ('] ' in m and 'claude:' not in m and 'qwen:' not in m):
                        # Extract message text
                        parts = m.split('] ', 1)
                        if len(parts) > 1:
                            content = parts[1]
                            if ':' in content:
                                text = content.split(':', 1)[1].strip()
                                if text and not hasattr(main, '_seen'):
                                    main._seen = set()
                                if text and text not in getattr(main, '_seen', set()):
                                    main._seen = getattr(main, '_seen', set()) | {text}
                                    print(f'[user] {text}')
                                    r = ollama(text)
                                    bot.fill('#msg-in', r)
                                    bot.click('#btn-send')
                                    print(f'[qwen] {r}')

        except KeyboardInterrupt:
            pass
        finally:
            browser.close()

if __name__ == '__main__':
    main()
