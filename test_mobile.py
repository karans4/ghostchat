#!/usr/bin/env python3
"""Test Ghost Chat mobile PWA experience using Playwright mobile emulation."""
import asyncio
from playwright.async_api import async_playwright

URL = 'https://karans4.github.io/ghostchat/'
# URL = 'http://localhost:8091/ghost.html'

# iPhone 14 Pro dimensions and user agent
MOBILE_VIEWPORT = {'width': 393, 'height': 852}
MOBILE_USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'

async def test_mobile():
    print('[*] Testing Ghost Chat mobile PWA experience')
    print(f'[*] URL: {URL}')
    print(f'[*] Viewport: {MOBILE_VIEWPORT}')

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=[
            '--disable-gpu',
            f'--window-size={MOBILE_VIEWPORT["width"]},{MOBILE_VIEWPORT["height"]}',
        ])

        # Create mobile context
        ctx = await browser.new_context(
            viewport=MOBILE_VIEWPORT,
            user_agent=MOBILE_USER_AGENT,
            device_scale_factor=3,  # Retina display
            is_mobile=True,
            has_touch=True,
        )

        page = await ctx.new_page()

        # Enable PWA display mode detection
        await page.goto(URL)
        print('[*] Page loaded')

        # Wait for load
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)

        # Check manifest
        manifest = await page.evaluate("""() => {
            const link = document.querySelector('link[rel="manifest"]');
            if (!link) return null;
            return fetch(link.href).then(r => r.json()).catch(() => null);
        }""")
        print(f'[+] Manifest: {manifest["name"] if manifest else "NOT FOUND"}')
        if manifest:
            print(f'    display: {manifest.get("display", "not set")}')
            print(f'    start_url: {manifest.get("start_url", "not set")}')
            print(f'    theme_color: {manifest.get("theme_color", "not set")}')

        # Check service worker
        sw = await page.evaluate("""() => {
            return navigator.serviceWorker ? 'supported' : 'not supported';
        }""")
        print(f'[+] Service Worker: {sw}')

        # Check standalone mode capability
        standalone = await page.evaluate("""() => {
            return window.matchMedia('(display-mode: standalone)').matches;
        }""")
        print(f'[+] Standalone mode: {standalone}')

        # Screenshot home screen
        await page.screenshot(path='/mnt/shared/ghost_mobile_home.png', full_page=False)
        print('[*] Screenshot saved: /mnt/shared/ghost_mobile_home.png')

        # Test creating a room
        print('[*] Testing room creation...')
        await page.wait_for_selector('#nick-in')
        await page.fill('#nick-in', 'mobile-test')
        await page.click('#btn-create')

        await page.wait_for_function(
            "document.querySelector('#my-code')?.value?.startsWith('O:')",
            timeout=15000
        )
        offer = await page.input_value('#my-code')
        print(f'[+] Room created, offer code: {offer[:40]}...')

        # Screenshot room creation
        await page.screenshot(path='/mnt/shared/ghost_mobile_room.png', full_page=False)
        print('[*] Screenshot saved: /mnt/shared/ghost_mobile_room.png')

        # Check QR code visibility
        qr = await page.query_selector('#offer-qr svg, #offer-qr img')
        print(f'[+] QR code visible: {qr is not None}')

        # Check layout doesn't overflow
        overflow = await page.evaluate("""() => {
            const body = document.body;
            return body.scrollWidth > body.clientWidth || body.scrollHeight > body.clientHeight;
        }""")
        print(f'[+] Layout overflow: {overflow}')

        # Test touch targets (minimum 44x44px for accessibility)
        touch_targets = await page.evaluate("""() => {
            const buttons = document.querySelectorAll('button');
            const small = [];
            buttons.forEach(b => {
                const rect = b.getBoundingClientRect();
                if (rect.width < 44 || rect.height < 44) {
                    small.push({text: b.textContent.slice(0,20), w: rect.width, h: rect.height});
                }
            });
            return small;
        }""")
        if touch_targets:
            print(f'[!] Small touch targets: {len(touch_targets)}')
            for t in touch_targets[:3]:
                print(f'    {t}')
        else:
            print('[+] All touch targets adequate (>=44px)')

        print('\n[✓] Mobile test complete')
        print('[*] Browser will stay open for manual testing')
        print('[*] Press Ctrl+C to close')

        # Keep browser open
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(test_mobile())
