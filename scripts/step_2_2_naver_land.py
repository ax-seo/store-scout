"""Step 2-2: 네이버 부동산에서 상가 매물 수집"""
import asyncio
import json
import re
from playwright.async_api import async_playwright
from config import (
    NAVER_LAND_URL, BROWSER_ARGS, VIEWPORT, USER_AGENT, DELAY_SHORT,
    save_json, load_json, log, random_delay
)


async def capture_land_api(page, region, session_path):
    """네이버 부동산 내부 API 응답 캡처"""
    articles = []
    api_responses = []

    async def handle_response(response):
        url = response.url
        # 매물 리스트 API 응답 캡처
        if ("article" in url or "complex" in url) and response.status == 200:
            try:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type or "javascript" in content_type:
                    body = await response.text()
                    if body.startswith("{") or body.startswith("["):
                        api_responses.append({"url": url, "data": json.loads(body)})
            except Exception:
                pass

    page.on("response", handle_response)

    # 네이버 부동산 상가 매물 페이지 접속
    # 지역명으로 검색 후 상가 필터
    await page.goto(f"{NAVER_LAND_URL}/offices", wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    # 검색창에 지역 입력
    search_selectors = [
        "input[id='queryInput']",
        "input[placeholder*='검색']",
        "input[type='search']",
        ".search_area input",
    ]

    search_input = None
    for sel in search_selectors:
        try:
            search_input = await page.query_selector(sel)
            if search_input:
                break
        except Exception:
            continue

    if search_input:
        await search_input.click()
        await search_input.fill("")
        await search_input.type(region, delay=80)
        await page.wait_for_timeout(1500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        # 자동완성 결과 클릭 (첫번째)
        autocomplete_selectors = [
            ".search_list li:first-child",
            "[class*='suggest'] li:first-child",
            "[class*='autocomplete'] li:first-child",
        ]
        for sel in autocomplete_selectors:
            try:
                ac = await page.query_selector(sel)
                if ac:
                    await ac.click()
                    await page.wait_for_timeout(3000)
                    break
            except Exception:
                continue

    # 상가 필터 적용
    await apply_commercial_filter(page, session_path)
    await page.wait_for_timeout(5000)

    page.remove_listener("response", handle_response)

    # API 응답에서 매물 데이터 추출
    for resp in api_responses:
        try:
            data = resp["data"]
            article_list = None

            if isinstance(data, dict):
                # articleList 또는 body 패턴
                if "articleList" in data:
                    article_list = data["articleList"]
                elif "body" in data:
                    article_list = data["body"]
                elif "result" in data:
                    result = data["result"]
                    if isinstance(result, dict) and "list" in result:
                        article_list = result["list"]

            if article_list:
                for art in article_list:
                    entry = parse_api_article(art)
                    if entry:
                        articles.append(entry)
        except Exception as e:
            log(session_path, f"API 매물 파싱 실패: {e}")

    return articles


async def apply_commercial_filter(page, session_path):
    """상가 필터 적용 (아파트/사무실/공장 등 제외)"""
    # 매물 종류 필터 버튼 찾기
    filter_selectors = [
        "text=상가",
        "[data-value='D02']",
        "label:has-text('상가')",
        "button:has-text('상가')",
    ]

    for sel in filter_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(2000)
                log(session_path, "상가 필터 적용됨")
                return True
        except Exception:
            continue

    log(session_path, "상가 필터 버튼 찾기 실패 — 기본 필터로 진행")
    return False


def parse_api_article(art):
    """API 응답의 개별 매물 파싱"""
    try:
        # 거래 유형 판별
        trade_type = art.get("tradeTypeName", art.get("dealOrWarrantPrc", ""))
        price = ""
        deposit = ""
        rent = ""

        deal_price = art.get("dealOrWarrantPrc", "")
        rent_price = art.get("rentPrc", "")

        if "매매" in str(trade_type):
            price = f"매매 {deal_price}"
        elif "전세" in str(trade_type):
            deposit = f"전세 {deal_price}"
        elif "월세" in str(trade_type):
            deposit = f"보증금 {deal_price}"
            rent = f"월세 {rent_price}"
        else:
            price = deal_price

        return {
            "title": art.get("articleName", art.get("atclNm", "")),
            "trade_type": str(trade_type),
            "price": price,
            "deposit": deposit,
            "rent": rent,
            "area": f"{art.get('area1', art.get('spc1', ''))}㎡",
            "floor": art.get("floorInfo", art.get("atclFlrInfo", "")),
            "address": art.get("roadAddress", art.get("address", "")),
            "description": art.get("articleDesc", art.get("atclCfmYmd", "")),
            "realtor": art.get("realtorName", art.get("rltrNm", "")),
            "url": f"https://new.land.naver.com/offices?articleNo={art.get('articleNo', art.get('atclNo', ''))}",
            "confirmed": art.get("isConfirm", art.get("cfmYn", "")) == "Y",
        }
    except Exception:
        return None


async def scrape_dom_listings(page, session_path):
    """DOM 파싱으로 매물 리스트 추출 (API 캡처 실패 시 폴백)"""
    listings = []

    # 매물 리스트 셀렉터
    item_selectors = [
        ".item_inner",
        "[class*='article_item']",
        "li[class*='item']",
        ".list_item",
    ]

    items = []
    for sel in item_selectors:
        try:
            items = await page.query_selector_all(sel)
            if items:
                log(session_path, f"DOM 셀렉터 '{sel}'로 {len(items)}건 발견")
                break
        except Exception:
            continue

    for item in items:
        try:
            entry = {}

            # 제목
            title_el = await item.query_selector("[class*='name'], [class*='title'], .item_title")
            if title_el:
                entry["title"] = (await title_el.inner_text()).strip()

            # 가격
            price_el = await item.query_selector("[class*='price'], .price_line")
            if price_el:
                price_text = (await price_el.inner_text()).strip()
                entry["price"] = price_text

            # 면적
            area_el = await item.query_selector("[class*='area'], [class*='spec']")
            if area_el:
                entry["area"] = (await area_el.inner_text()).strip()

            # 층
            floor_el = await item.query_selector("[class*='floor']")
            if floor_el:
                entry["floor"] = (await floor_el.inner_text()).strip()

            if entry.get("title"):
                entry.setdefault("trade_type", "")
                entry.setdefault("deposit", "")
                entry.setdefault("rent", "")
                entry.setdefault("address", "")
                entry.setdefault("description", "")
                entry.setdefault("realtor", "")
                entry.setdefault("url", "")
                entry.setdefault("confirmed", False)
                listings.append(entry)
        except Exception:
            continue

    return listings


async def run(region, session_path):
    """Step 2-2 메인 실행"""
    log(session_path, f"=== Step 2-2 시작: {region} 상가 매물 수집 ===")

    async with async_playwright() as p:
        browser = await p.chromium.launch(**BROWSER_ARGS)
        context = await browser.new_context(
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        # 방법 1: API 캡처
        listings = await capture_land_api(page, region, session_path)

        # 방법 2: DOM 파싱 폴백
        if not listings:
            log(session_path, "API 캡처 실패 — DOM 파싱 시도")
            listings = await scrape_dom_listings(page, session_path)

        await page.screenshot(path=f"{session_path}/screenshots/naver-land-results.png")
        await browser.close()

    # 매매/임대 분류
    sale_listings = [l for l in listings if "매매" in str(l.get("trade_type", "")) or "매매" in str(l.get("price", ""))]
    rent_listings = [l for l in listings if l not in sale_listings]

    result = {
        "total": len(listings),
        "sale_count": len(sale_listings),
        "rent_count": len(rent_listings),
        "sale_listings": sale_listings,
        "rent_listings": rent_listings,
        "all_listings": listings,
    }

    save_json(result, f"{session_path}/step-2-2-listings.json")

    log(session_path, f"=== Step 2-2 완료: 총 {len(listings)}건 (매매 {len(sale_listings)}, 임대 {len(rent_listings)}) ===")

    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python step_2_2_naver_land.py <region> <session_path>")
        sys.exit(1)

    region = sys.argv[1]
    session_path = sys.argv[2]

    result = asyncio.run(run(region, session_path))

    print(f"\n상가 매물 {result['total']}건:")
    for i, l in enumerate(result["all_listings"][:10], 1):
        print(f"  {i}. {l.get('title', '?')} — {l.get('price', '')} {l.get('deposit', '')} {l.get('rent', '')}")
