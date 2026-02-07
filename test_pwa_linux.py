#!/usr/bin/env python3
"""Test Ghost Chat PWA on Linux desktop + phone interop."""
import asyncio
from playwright.async_api import async_playwright

URL = 'https://notruefireman.org/ghost/'

async def test_linux_pwa():
    print('[*] Testing Ghost Chat PWA on Linux')
    print(f'[*] URL: {URL}')

    async with async_playwright() as pw:
        # Launch with PWA-like window
        browser = await pw.chromium.launch_persistent_context(
            '/tmp/ghost-pwa-test',
            headless=False,
            args=[
                '--app=' + URL,  # PWA mode
                '--window-size=900,700',
                '--window-position=100,100',
            ]
        )

        page = await browser.new_page()
        await page.goto(URL)

        print('[*] Page loaded')
        await page.wait_for_load_state('networkidle')

        # Check PWA installability
        manifest = await page.evaluate("""() => {
            return navigator.getInstalledRelatedApps ? 'supported' : 'check manually';
        }""")
        print(f'[+] Related apps API: {manifest}')

        # Create room
        await page.wait_for_selector('#nick-in')
        await page.fill('#nick-in', 'linux-desktop')
        await page.click('#btn-create')
        print('[*] Creating room...')

        # Wait for QR
        await page.wait_for_selector('#invite-qr svg', timeout=15000)
        print('[+] QR code generated')

        # Screenshot for phone scanning
        await page.screenshot(path='/mnt/shared/ghost_pwa_qr.png', full_page=False)
        print('[*] Screenshot saved: /mnt/shared/ghost_pwa_qr.png')
        print('[*] Scan this QR with your phone to test!')

        # Keep open
        print('[*] Press Ctrl+C to close')
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(test_linux_pwa())
