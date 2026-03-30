"""오픈업 최초 로그인 — 수동 로그인 후 쿠키 저장"""
import asyncio
import json
import os
from playwright.async_api import async_playwright
from config import OPENUP_URL, OPENUP_COOKIES_PATH, VIEWPORT, USER_AGENT


async def login_and_save():
    """브라우저 열고 수동 로그인 후 쿠키 저장"""
    print(f"""
╔══════════════════════════════════════════════╗
║  오픈업(OpenUp) 로그인 세션 저장              ║
╠══════════════════════════════════════════════╣
║  1. 브라우저가 열립니다                       ║
║  2. 오픈업에 로그인하세요                     ║
║  3. 로그인 완료 후 터미널에서 Enter 누르세요   ║
║  4. 세션 쿠키가 자동 저장됩니다                ║
╚══════════════════════════════════════════════╝
""")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context(
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        await page.goto(OPENUP_URL, wait_until="networkidle")

        print("브라우저에서 오픈업에 로그인하세요...")
        print("로그인 완료 후 Enter를 누르세요: ", end="", flush=True)

        # 비동기 입력 대기
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input)

        # 쿠키 저장
        cookies = await context.cookies()
        os.makedirs(os.path.dirname(OPENUP_COOKIES_PATH), exist_ok=True)
        with open(OPENUP_COOKIES_PATH, "w") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 쿠키 저장 완료: {OPENUP_COOKIES_PATH}")
        print(f"   저장된 쿠키: {len(cookies)}개")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(login_and_save())
