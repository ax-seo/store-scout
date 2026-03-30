"""Step 1-2: 오픈업에서 마트별 매출 검증 (크레딧 보호 3-Layer)"""
import asyncio
import json
import os
import re
from playwright.async_api import async_playwright
from config import (
    OPENUP_URL, OPENUP_COOKIES_PATH, BROWSER_ARGS, VIEWPORT, USER_AGENT,
    DEFAULT_THRESHOLD, DEFAULT_CREDIT_LIMIT, DELAY_SHORT, DELAY_LONG, DELAY_BURST_PAUSE,
    save_json, load_json, log, random_delay
)


async def load_cookies(context):
    """저장된 오픈업 쿠키 로드"""
    if os.path.exists(OPENUP_COOKIES_PATH):
        with open(OPENUP_COOKIES_PATH, "r") as f:
            cookies = json.load(f)
        await context.add_cookies(cookies)
        return True
    return False


async def save_cookies(context):
    """현재 세션 쿠키 저장"""
    cookies = await context.cookies()
    os.makedirs(os.path.dirname(OPENUP_COOKIES_PATH), exist_ok=True)
    with open(OPENUP_COOKIES_PATH, "w") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)


async def check_login(page, session_path):
    """로그인 상태 확인"""
    await page.goto(OPENUP_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    # 로그인 상태 판단: 프로필/마이페이지 링크 존재 여부
    login_indicators = [
        "text=마이페이지",
        "text=내 정보",
        "[class*='profile']",
        "[class*='user']",
        "text=로그아웃",
    ]

    for sel in login_indicators:
        try:
            el = await page.query_selector(sel)
            if el:
                log(session_path, "오픈업 로그인 확인됨")
                return True
        except Exception:
            continue

    log(session_path, "⚠️ 오픈업 로그인 필요")
    await page.screenshot(path=f"{session_path}/screenshots/openup-login-required.png")
    return False


async def check_credits(page, session_path):
    """잔여 크레딧 확인 (Layer 1: Pre-flight)"""
    # 마이페이지 또는 크레딧 표시 영역 확인
    credit_selectors = [
        "[class*='credit']",
        "[class*='point']",
        "[class*='ticket']",
        "text=/\\d+\\s*건/",
        "text=/크레딧/",
    ]

    # 마이페이지로 이동하여 크레딧 확인 시도
    try:
        my_page_link = await page.query_selector("text=마이페이지, a[href*='mypage'], a[href*='my']")
        if my_page_link:
            await my_page_link.click()
            await page.wait_for_timeout(3000)
    except Exception:
        pass

    credits = None
    for sel in credit_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = await el.inner_text()
                # 숫자 추출
                numbers = re.findall(r'\d+', text)
                if numbers:
                    credits = int(numbers[0])
                    break
        except Exception:
            continue

    if credits is not None:
        log(session_path, f"잔여 크레딧: {credits}건")
    else:
        log(session_path, "크레딧 수량 확인 실패 — 수동 확인 필요")

    await page.screenshot(path=f"{session_path}/screenshots/openup-credit-check.png")
    return credits


async def search_store_sales(page, store_name, session_path):
    """개별 매장 매출 조회"""
    log(session_path, f"매출 조회: {store_name}")

    # 오픈업 메인으로 이동
    await page.goto(OPENUP_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)

    # 검색창 찾기
    search_selectors = [
        "input[type='search']",
        "input[placeholder*='검색']",
        "input[placeholder*='상호']",
        "input[class*='search']",
        "#searchInput",
    ]

    search_input = None
    for sel in search_selectors:
        try:
            search_input = await page.query_selector(sel)
            if search_input:
                break
        except Exception:
            continue

    if not search_input:
        log(session_path, f"검색창 찾기 실패: {store_name}")
        await page.screenshot(path=f"{session_path}/screenshots/openup-search-fail-{store_name}.png")
        return None

    # 검색 실행
    await search_input.click()
    await search_input.fill("")
    await search_input.type(store_name, delay=50)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(3000)

    # 검색 결과에서 첫번째 매장 클릭
    result_selectors = [
        "li[class*='result'] a",
        "[class*='search-result'] a",
        "[class*='place-item']",
        "text=" + store_name.split()[0],  # 첫 단어로 매칭
    ]

    result_clicked = False
    for sel in result_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(3000)
                result_clicked = True
                break
        except Exception:
            continue

    if not result_clicked:
        log(session_path, f"검색 결과 없음: {store_name}")
        return None

    # 매출 데이터 확인 — "열람하기" 버튼이 있으면 크레딧 차감 필요
    open_button = None
    open_selectors = [
        "text=열람하기",
        "text=매장 데이터 조회",
        "text=데이터 조회하기",
        "button[class*='open']",
        "text=크레딧",
    ]

    for sel in open_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                open_button = el
                break
        except Exception:
            continue

    already_opened = open_button is None

    if not already_opened:
        # 크레딧 차감 필요 — 클릭
        log(session_path, f"크레딧 차감 조회: {store_name}")
        await open_button.click()
        await page.wait_for_timeout(3000)
    else:
        log(session_path, f"이미 열람된 매장: {store_name}")

    # 매출 데이터 추출
    sales_data = await extract_sales_data(page, session_path)

    await page.screenshot(path=f"{session_path}/screenshots/openup-sales-{store_name}.png")

    return {
        "name": store_name,
        "monthly_sales": sales_data.get("monthly_sales"),
        "monthly_sales_display": format_sales(sales_data.get("monthly_sales")),
        "daily_avg": sales_data.get("daily_avg"),
        "is_promising": False,  # 나중에 threshold와 비교
        "credit_used": 0 if already_opened else 1,
        "raw_data": sales_data,
    }


async def extract_sales_data(page, session_path):
    """매출 데이터 추출"""
    sales = {"monthly_sales": None, "daily_avg": None}

    # 페이지 텍스트에서 매출 정보 추출
    try:
        content = await page.content()

        # 월매출 패턴 매칭 (예: "4억 5,000만", "4.5억", "450,000,000")
        patterns = [
            r'월\s*(?:평균\s*)?매출[^\d]*?([\d,]+)\s*만?\s*원?',
            r'([\d,.]+)\s*억\s*(?:([\d,]+)\s*만)?',
            r'월매출[^\d]*([\d,]+)',
        ]

        # 텍스트 기반 추출
        body_text = await page.inner_text("body")

        for pattern in patterns:
            match = re.search(pattern, body_text)
            if match:
                try:
                    raw = match.group(0)
                    # 억 단위 변환
                    eok_match = re.search(r'([\d,.]+)\s*억', raw)
                    man_match = re.search(r'([\d,]+)\s*만', raw)

                    total = 0
                    if eok_match:
                        total += float(eok_match.group(1).replace(",", "")) * 100000000
                    if man_match:
                        total += float(man_match.group(1).replace(",", "")) * 10000

                    if total == 0:
                        # 순수 숫자
                        num_str = re.sub(r'[^\d]', '', match.group(1))
                        if num_str:
                            total = int(num_str)

                    if total > 0:
                        sales["monthly_sales"] = int(total)
                        break
                except (ValueError, IndexError):
                    continue

    except Exception as e:
        log(session_path, f"매출 데이터 추출 실패: {e}")

    return sales


def format_sales(amount):
    """매출 금액을 읽기 쉬운 형태로 변환"""
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
    else:
        return f"{amount:,}원"


async def run(session_path, threshold=DEFAULT_THRESHOLD, credit_limit=DEFAULT_CREDIT_LIMIT, skip=False):
    """Step 1-2 메인 실행"""
    if skip:
        log(session_path, "=== Step 1-2 생략 (--skip-openup) ===")
        # 빈 결과 생성 — 모든 마트를 유망으로 처리
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
        browser = await p.chromium.launch(**BROWSER_ARGS)
        context = await browser.new_context(
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        # 쿠키 로드
        cookie_loaded = await load_cookies(context)
        if cookie_loaded:
            log(session_path, "오픈업 세션 쿠키 로드됨")

        # 로그인 확인
        is_logged_in = await check_login(page, session_path)
        if not is_logged_in:
            log(session_path, "❌ 오픈업 로그인 필요 — 수동 로그인 후 재실행하세요")
            log(session_path, f"  1. 브라우저에서 {OPENUP_URL} 접속")
            log(session_path, f"  2. 로그인 완료")
            log(session_path, f"  3. openup_login.py 실행하여 쿠키 저장")
            await browser.close()
            return []

        # Layer 1: 크레딧 잔량 확인
        credits = await check_credits(page, session_path)

        # Layer 2: 승인 게이트 (CLI에서는 표시만)
        log(session_path, "")
        log(session_path, "━━━━ 크레딧 보호 게이트 ━━━━")
        if credits is not None:
            log(session_path, f"  잔여 크레딧: {credits}건")
        log(session_path, f"  조회 대상: {len(marts)}건")
        log(session_path, f"  예상 최대 소비: {len(marts)}건")
        log(session_path, f"  크레딧 한도: {credit_limit}건")
        log(session_path, "━━━━━━━━━━━━━━━━━━━━━━━━")
        log(session_path, "")

        for mart in marts:
            log(session_path, f"  - {mart['name']}")

        # 각 마트별 매출 조회
        for i, mart in enumerate(marts):
            # Layer 3: 한도 체크
            if total_credits_used >= credit_limit:
                log(session_path, f"⚠️ 크레딧 한도 도달 ({credit_limit}건) — 조회 중단")
                break

            store_name = mart["name"]
            sales_result = await search_store_sales(page, store_name, session_path)

            if sales_result:
                # 유망 판정
                if sales_result["monthly_sales"] and sales_result["monthly_sales"] >= threshold:
                    sales_result["is_promising"] = True

                total_credits_used += sales_result["credit_used"]
                results.append(sales_result)
            else:
                results.append({
                    "name": store_name,
                    "monthly_sales": None,
                    "monthly_sales_display": "조회 실패",
                    "is_promising": False,
                    "credit_used": 0,
                })

            # 연속 조회 후 대기
            if (i + 1) % 10 == 0:
                log(session_path, f"연속 조회 {i+1}건 — {DELAY_BURST_PAUSE}초 대기")
                await page.wait_for_timeout(DELAY_BURST_PAUSE * 1000)
            else:
                random_delay(DELAY_LONG)

        # 쿠키 저장
        await save_cookies(context)
        await browser.close()

    # 결과 저장
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
