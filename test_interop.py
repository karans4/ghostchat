#!/usr/bin/env python3
"""Test browser-to-Python Ghost Chat interop.

This test:
1. Starts a browser (offerer)
2. Gets the offer code from browser
3. Python client joins as answerer
4. Verifies bidirectional message exchange
"""
import asyncio
import sys
from playwright.async_api import async_playwright
from ghost_client import GhostClient

URL = 'http://localhost:8091/ghost.html'

async def test_interop():
    print('[*] Starting interop test: Browser (offerer) <-> Python (answerer)')

    # Start browser
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=[
            '--disable-gpu', '--window-size=900,700'
        ])
        ctx = await browser.new_context(viewport={'width': 880, 'height': 680})
        page = await ctx.new_page()

        # Browser creates room
        print('[*] Browser creating room...')
        await page.goto(URL)
        await page.wait_for_selector('#nick-in')
        await page.fill('#nick-in', 'browser-alice')
        await page.click('#btn-create')

        # Wait for offer code
        await page.wait_for_function(
            "document.querySelector('#my-code')?.value?.startsWith('O:')",
            timeout=15000
        )
        offer_code = await page.input_value('#my-code')
        room_url = page.url
        print(f'[+] Browser offer code: {offer_code[:50]}...')

        # Extract room credentials from URL
        hash_part = room_url.split('#')[1]
        room_id, room_key_b64 = hash_part.split('.')
        print(f'[+] Room ID: {room_id}')

        # Python client joins
        print('[*] Python client joining...')
        client = GhostClient(nick='python-bob')
        await client.set_room(room_id, room_key_b64)
        answer_code = await client.accept_offer(offer_code)
        print(f'[+] Python answer code: {answer_code[:50]}...')

        # Browser accepts answer
        await page.fill('#peer-code', answer_code)
        await page.click('#btn-connect')

        # Wait for both sides to connect
        print('[*] Waiting for connection...')
        await page.wait_for_selector('#chat-view', timeout=15000)
        await client.wait_connected(timeout=15.0)
        print('[+] Connected!')

        # Test: Browser sends, Python receives
        print('[*] Test 1: Browser -> Python')
        await page.fill('#msg-in', 'Hello from browser!')
        await page.click('#btn-send')

        # May need to drain the join message first
        msg = await client.receive(timeout=10.0)
        if msg.type == 'sys' and 'joined' in msg.text:
            print(f'[+] Drained join message: {msg.text}')
            msg = await client.receive(timeout=10.0)
        print(f'[+] Python received: {msg.nick}: {msg.text}')
        assert msg.text == 'Hello from browser!', f"Expected 'Hello from browser!', got '{msg.text}'"

        # Test: Python sends, Browser receives
        print('[*] Test 2: Python -> Browser')
        await client.send('Hello from Python!')

        # Wait for message to appear in browser
        await page.wait_for_function(
            """() => {
                const msgs = document.querySelectorAll('#messages .msg');
                for (const m of msgs) {
                    if (m.textContent.includes('Hello from Python!')) return true;
                }
                return false;
            }""",
            timeout=10000
        )
        print('[+] Browser received Python message')

        # Test: Multiple messages
        print('[*] Test 3: Multiple messages')
        for i in range(3):
            await client.send(f'Python message {i}')
            await asyncio.sleep(0.3)

        await page.wait_for_function(
            """() => {
                const msgs = document.querySelectorAll('#messages .msg');
                let count = 0;
                for (const m of msgs) {
                    if (m.textContent.includes('Python message')) count++;
                }
                return count >= 3;
            }""",
            timeout=10000
        )
        print('[+] All messages received')

        print('\n[✓] All interop tests passed!')

        # Cleanup
        await client.close()
        await browser.close()
        return True

if __name__ == '__main__':
    try:
        success = asyncio.run(test_interop())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f'\n[✗] Test failed: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
