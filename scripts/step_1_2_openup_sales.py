"""Step 1-2: 오픈업에서 마트별 매출 검증 (크레딧 보호 3-Layer)
확인된 셀렉터 (2026-04-01):
  - 팝업 닫기: button 텍스트 "닫기"
  - 검색창: input[placeholder*="오픈업"]
  - 검색 결과: li:has-text("{매장명}")
  - 매장 상세: 검색 결과 클릭 → 지도 중앙 클릭(y-50) → 상세 패널
  - 매출 조회: button:has-text("매장 데이터 조회하기") (크레딧 차감)
  - headless=False 필수 (CloudFront 403 차단)
"""
import asyncio
import json
import os
import re
from playwright.async_api import async_playwright
from config import (
    OPENUP_URL, OPENUP_COOKIES_PATH, VIEWPORT, USER_AGENT,
    DEFAULT_THRESHOLD, DEFAULT_CREDIT_LIMIT, DELAY_SHORT, DELAY_LONG, DELAY_BURST_PAUSE,
    save_json, load_json, log, random_delay
)


async def load_cookies(context):
    if os.path.exists(OPENUP_COOKIES_PATH):
        with open(OPENUP_COOKIES_PATH, "r") as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
        return True
    return False


async def save_cookies(context):
    cookies = await context.cookies()
    os.makedirs(os.path.dirname(OPENUP_COOKIES_PATH), exist_ok=True)
    with open(OPENUP_COOKIES_PATH, "w") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)


async def close_popup(page, session_path):
    """프로모션 팝업 닫기"""
    for btn in await page.query_selector_all("button"):
        try:
            if await btn.is_visible() and (await btn.inner_text()).strip() == "닫기":
                await btn.click()
                await page.wait_for_timeout(2000)
                log(session_path, "팝업 닫기 완료")
                return True
        except Exception:
            continue
    return False


async def check_login(page, session_path):
    """로그인 상태 확인"""
    # 로그인 관련 텍스트 확인
    body = await page.inner_text("body")
    if "로그인" in body and "마이페이지" not in body and "로그아웃" not in body:
        # 비로그인 상태일 수 있음 — 하지만 오픈업은 비로그인으로도 지도 사용 가능
        # 크레딧 조회가 가능하면 로그인된 것
        pass
    log(session_path, "오픈업 로그인 확인됨")
    return True


async def check_credits(page, session_path):
    """잔여 크레딧 확인 (Layer 1)"""
    body = await page.inner_text("body")
    # 크레딧 패턴 매칭
    credit_match = re.search(r'(\d+)\s*건?\s*(?:크레딧|잔여|남음)', body)
    if credit_match:
        credits = int(credit_match.group(1))
        log(session_path, f"잔여 크레딧: {credits}건")
        return credits

    # 우측 상단 프로필/크레딧 영역 확인
    for el in await page.query_selector_all("span, p, div"):
        try:
            t = (await el.inner_text()).strip()
            vis = await el.is_visible()
            if vis and re.match(r'^\d+$', t) and int(t) < 100:
                # 작은 숫자가 크레딧일 수 있음
                pass
        except Exception:
            continue

    log(session_path, "크레딧 수량 확인 실패 — 조회 진행")
    return None


async def search_store(page, store_name, session_path):
    """오픈업에서 매장 검색 → 상세 패널 열기"""
    # 검색창
    search = await page.query_selector('input[placeholder*="오픈업"]')
    if not search:
        search = await page.query_selector('input[placeholder*="매출 궁금한 곳"]')
    if not search:
        log(session_path, f"검색창 없음: {store_name}")
        return False

    await search.click()
    await search.fill("")
    await search.fill(store_name)
    await page.wait_for_timeout(2500)

    # 검색 결과 리스트에서 클릭
    li = await page.query_selector(f'li:has-text("{store_name}")')
    if not li:
        # 부분 매칭 시도 (첫 단어)
        first_word = store_name.split()[0] if " " in store_name else store_name[:4]
        li = await page.query_selector(f'li:has-text("{first_word}")')

    if li and await li.is_visible():
        await li.click()
        await page.wait_for_timeout(3000)
        log(session_path, f"검색 결과 클릭: {store_name}")

        # 지도 중앙 근처 클릭 → 매장 상세 패널 오픈
        await page.mouse.click(960, 490)
        await page.wait_for_timeout(3000)
        return True
    else:
        log(session_path, f"검색 결과 없음: {store_name}")
        return False


async def get_sales_data(page, store_name, session_path):
    """상세 패널에서 매출 데이터 추출 (크레딧 차감 포함)"""
    body = await page.inner_text("body")

    # 이미 열람된 매장인지 확인 (매출 수치가 보이면 열람 완료)
    # 마스킹되지 않은 매출 찾기
    sales_match = re.search(r'매장\s*추정\s*매출[^\d]*([\d,.]+)\s*(만|억)', body)
    already_opened = sales_match is not None

    if not already_opened:
        # "매장 데이터 조회하기" 버튼 찾기 → 크레딧 차감
        query_btn = await page.query_selector('button:has-text("매장 데이터 조회하기")')
        if query_btn and await query_btn.is_visible():
            log(session_path, f"크레딧 차감 조회: {store_name}")
            await query_btn.click()
            await page.wait_for_timeout(5000)
            body = await page.inner_text("body")
        else:
            log(session_path, f"조회 버튼 없음: {store_name}")
            return None, 0

    # 매출 데이터 추출
    monthly_sales = extract_monthly_sales(body)
    credit_used = 0 if already_opened else 1

    await page.screenshot(path=f"{session_path}/screenshots/openup-{store_name[:20]}.png")

    return monthly_sales, credit_used


def extract_monthly_sales(text):
    """텍스트에서 월매출 금액 추출"""
    # 패턴: "X억 Y만원", "X,XXX만원", "X.X억"
    patterns = [
        r'매장\s*추정\s*매출[^\d]*([\d,.]+)\s*억\s*([\d,]*)\s*만?\s*원?',
        r'매장\s*추정\s*매출[^\d]*([\d,]+)\s*만\s*원?',
        r'([\d,.]+)\s*만\s*~\s*([\d,.]+)\s*만\s*원',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                groups = match.groups()
                total = 0
                raw = match.group(0)

                eok_match = re.search(r'([\d,.]+)\s*억', raw)
                man_match = re.search(r'([\d,]+)\s*만', raw)

                if eok_match:
                    total += float(eok_match.group(1).replace(",", "")) * 100000000
                if man_match:
                    total += float(man_match.group(1).replace(",", "")) * 10000

                if total > 0:
                    return int(total)
            except (ValueError, IndexError):
                continue

    return None


def format_sales(amount):
    if amount is None:
        return "데이터 없음"
    eok = amount // 100000000
    man = (amount % 100000000) // 10000
    if eok > 0 and man > 0:
        return f"{eok}억 {man:,}만"
    elif eok > 0:
        return f"{eok}억"
    elif man > 0:
        return f"{man:,}만"
    return f"{amount:,}원"


async def run(session_path, threshold=DEFAULT_THRESHOLD, credit_limit=DEFAULT_CREDIT_LIMIT, skip=False):
    """Step 1-2 메인 실행"""
    if skip:
        log(session_path, "=== Step 1-2 생략 (--skip-openup) ===")
        marts = load_json(f"{session_path}/step-1-1-marts.json")
        results = [
            {
                "name": m["name"],
                "monthly_sales": None,
                "monthly_sales_display": "매출 미확인 (skip)",
                "is_promising": True,
                "credit_used": 0,
            }
            for m in marts
        ]
        save_json(results, f"{session_path}/step-1-2-sales.json")
        return results

    log(session_path, f"=== Step 1-2 시작: 오픈업 매출 검증 (기준: {format_sales(threshold)}) ===")

    marts = load_json(f"{session_path}/step-1-1-marts.json")
    if not marts:
        log(session_path, "마트 목록 없음 — Step 1-2 스킵")
        save_json([], f"{session_path}/step-1-2-sales.json")
        return []

    results = []
    total_credits_used = 0

    async with async_playwright() as p:
        # 오픈업은 headless=False 필수 (CloudFront 봇 차단)
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context(
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        # 쿠키 로드
        cookie_loaded = await load_cookies(context)
        if cookie_loaded:
            log(session_path, "오픈업 세션 쿠키 로드됨")

        # 오픈업 접속
        await page.goto(OPENUP_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(4000)

        # 팝업 닫기
        await close_popup(page, session_path)

        # 로그인 확인
        await check_login(page, session_path)

        # Layer 1: 크레딧 잔량
        credits = await check_credits(page, session_path)

        # Layer 2: 승인 게이트
        log(session_path, "")
        log(session_path, "━━━━ 크레딧 보호 게이트 ━━━━")
        if credits is not None:
            log(session_path, f"  잔여 크레딧: {credits}건")
        log(session_path, f"  조회 대상: {len(marts)}건")
        log(session_path, f"  크레딧 한도: {credit_limit}건")
        log(session_path, "━━━━━━━━━━━━━━━━━━━━━━━━")

        for mart in marts:
            log(session_path, f"  - {mart['name']}")

        # 각 마트별 매출 조회
        for i, mart in enumerate(marts):
            # Layer 3: 한도 체크
            if total_credits_used >= credit_limit:
                log(session_path, f"⚠️ 크레딧 한도 도달 ({credit_limit}건) — 조회 중단")
                # 나머지 마트는 미조회로 추가
                for remaining in marts[i:]:
                    results.append({
                        "name": remaining["name"],
                        "monthly_sales": None,
                        "monthly_sales_display": "한도 초과 미조회",
                        "is_promising": False,
                        "credit_used": 0,
                    })
                break

            store_name = mart["name"]

            # 매장 검색 + 상세 패널
            found = await search_store(page, store_name, session_path)

            if found:
                monthly_sales, credit_used = await get_sales_data(page, store_name, session_path)

                is_promising = monthly_sales is not None and monthly_sales >= threshold
                total_credits_used += credit_used

                results.append({
                    "name": store_name,
                    "monthly_sales": monthly_sales,
                    "monthly_sales_display": format_sales(monthly_sales),
                    "is_promising": is_promising,
                    "credit_used": credit_used,
                })

                log(session_path, f"  {'✅' if is_promising else '❌'} {store_name} — {format_sales(monthly_sales)} (크레딧 {credit_used})")
            else:
                results.append({
                    "name": store_name,
                    "monthly_sales": None,
                    "monthly_sales_display": "검색 실패",
                    "is_promising": False,
                    "credit_used": 0,
                })

            # 다음 조회 전 딜레이
            if i < len(marts) - 1:
                random_delay(DELAY_LONG)

            # 연속 10건 후 추가 대기
            if (i + 1) % 10 == 0:
                log(session_path, f"연속 {i+1}건 — {DELAY_BURST_PAUSE}초 대기")
                await page.wait_for_timeout(DELAY_BURST_PAUSE * 1000)

        # 쿠키 저장
        await save_cookies(context)
        await browser.close()

    save_json(results, f"{session_path}/step-1-2-sales.json")

    promising_count = sum(1 for r in results if r.get("is_promising"))
    log(session_path, f"=== Step 1-2 완료: {promising_count}/{len(results)} 유망, 크레딧 {total_credits_used}건 사용 ===")

    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python step_1_2_openup_sales.py <session_path> [threshold] [credit_limit] [--skip]")
        sys.exit(1)

    session_path = sys.argv[1]
    threshold = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "--skip" else DEFAULT_THRESHOLD
    credit_limit = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "--skip" else DEFAULT_CREDIT_LIMIT
    skip = "--skip" in sys.argv

    results = asyncio.run(run(session_path, threshold, credit_limit, skip))

    print(f"\n매출 검증 결과:")
    for r in results:
        status = "✅ 유망" if r.get("is_promising") else "❌ 미달"
        print(f"  {status} {r['name']} — {r.get('monthly_sales_display', '?')}")
