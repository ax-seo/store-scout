"""Step 2-2: 네이버 부동산에서 상가 매물 수집
네이버 검색 결과 페이지의 부동산 매물 섹션 파싱
(fin.land.naver.com은 지도 타일 기반이라 API 캡처 불가 → 검색 결과 활용)
"""
import asyncio
import json
import re
import urllib.parse
from playwright.async_api import async_playwright
from config import (
    BROWSER_ARGS, VIEWPORT, USER_AGENT, DELAY_SHORT,
    save_json, load_json, log, random_delay
)


async def search_naver_land_listings(page, region, session_path):
    """네이버 검색에서 부동산 매물 섹션 파싱"""
    listings = []

    query = f"{region} 상가 매물"
    encoded = urllib.parse.quote(query)
    search_url = f"https://search.naver.com/search.naver?query={encoded}"

    log(session_path, f"네이버 검색: {query}")
    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    await page.screenshot(path=f"{session_path}/screenshots/naver-search-sangga.png")

    # 방법 1: 부동산 매물 테이블 파싱
    # 네이버 검색에서 "이촌역 상가 매물" → 부동산 매물 리스트 섹션
    body_text = await page.inner_text("body")

    # 매물 테이블 패턴: "거래  매물종류  소재지  건물종류" 이후 행들
    table_section = extract_listing_table(body_text)
    if table_section:
        listings.extend(table_section)
        log(session_path, f"테이블 파싱: {len(table_section)}건")

    # 방법 2: AI 요약 섹션에서 매물 정보 추출
    ai_listings = extract_ai_summary_listings(body_text)
    if ai_listings:
        listings.extend(ai_listings)
        log(session_path, f"AI 요약 파싱: {len(ai_listings)}건")

    # 방법 3: 더 많은 매물 확인 — "네이버 부동산" 링크 클릭
    land_link = await page.query_selector("a[href*='land.naver.com'], a:has-text('네이버페이부동산')")
    if land_link and await land_link.is_visible():
        href = await land_link.get_attribute("href")
        if href:
            log(session_path, f"네이버 부동산 링크: {href}")

    # 매물 수 정보 추출
    count_match = re.search(r'전체\((\d+)\)\s+매매\((\d+)\)\s+전세\((\d+)\)\s+월세\((\d+)\)', body_text)
    if count_match:
        log(session_path, f"매물 현황: 전체 {count_match.group(1)}, 매매 {count_match.group(2)}, 전세 {count_match.group(3)}, 월세 {count_match.group(4)}")

    return listings


def extract_listing_table(text):
    """텍스트에서 부동산 매물 테이블 데이터 추출"""
    listings = []

    # 테이블 행 패턴: "매매  상가점포  한강로2가  단지내상가부동산뱅크  55/20  60,000  1/39  네이버페이부동산"
    # 또는 "월세  상가점포  한강로2가  단지내상가  55/20  5,000/200  1/39"
    pattern = re.compile(
        r'(매매|전세|월세)\s+'          # 거래유형
        r'(\S+)\s+'                     # 매물종류 (상가점포 등)
        r'(\S+)\s+'                     # 소재지
        r'(\S+(?:\s*\S+)?)\s+'          # 건물종류
        r'(\d+/\d+)\s+'                 # 계약/전용면적
        r'([\d,]+(?:/[\d,]+)?)\s+'      # 가격 (매매가 또는 보증금/월세)
        r'(-?\d+/\d+)'                  # 층
    )

    for match in pattern.finditer(text):
        trade_type = match.group(1)
        property_type = match.group(2)
        location = match.group(3)
        building_type = match.group(4)
        area_str = match.group(5)
        price_str = match.group(6)
        floor_str = match.group(7)

        # 면적 파싱
        area_parts = area_str.split("/")
        contract_area = area_parts[0] if area_parts else ""
        exclusive_area = area_parts[1] if len(area_parts) > 1 else ""

        # 가격 파싱
        price = ""
        deposit = ""
        rent = ""

        if trade_type == "매매":
            price = f"매매 {price_str}만"
        elif trade_type == "전세":
            deposit = f"전세 {price_str}만"
        elif trade_type == "월세":
            if "/" in price_str:
                parts = price_str.split("/")
                deposit = f"보증금 {parts[0]}만"
                rent = f"월세 {parts[1]}만"
            else:
                rent = f"월세 {price_str}만"

        listings.append({
            "title": f"{location} {building_type}",
            "trade_type": trade_type,
            "price": price,
            "deposit": deposit,
            "rent": rent,
            "area": f"계약 {contract_area}㎡ / 전용 {exclusive_area}㎡",
            "floor": floor_str,
            "address": location,
            "description": f"{property_type} / {building_type}",
            "realtor": "",
            "url": "",
            "confirmed": False,
        })

    return listings


def extract_ai_summary_listings(text):
    """AI 요약 섹션에서 매물 정보 추출"""
    listings = []

    # AI 요약 패턴: "이촌동 점보상가  매매  6억 5,000만원  계약24.36㎡(전용24.36㎡)  이촌1동 먹자골목 내 1층"
    pattern = re.compile(
        r'(\S+(?:\s\S+)?)\s+'              # 매물명
        r'(매매|전세|월세)\s+'               # 거래유형
        r'([\d,]+(?:억\s*)?[\d,]*만?원?)\s+' # 가격
        r'계약([\d.]+)㎡\(전용([\d.]+)㎡\)\s+' # 면적
        r'(.+?)(?:\t|\n|$)'                # 위치/설명
    )

    for match in pattern.finditer(text):
        name = match.group(1)
        trade_type = match.group(2)
        price_str = match.group(3)
        contract_area = match.group(4)
        exclusive_area = match.group(5)
        desc = match.group(6).strip()

        price = ""
        deposit = ""
        rent = ""

        if trade_type == "매매":
            price = f"매매 {price_str}"
        elif trade_type == "전세":
            deposit = f"전세 {price_str}"
        elif trade_type == "월세":
            rent = f"월세 {price_str}"

        listings.append({
            "title": name,
            "trade_type": trade_type,
            "price": price,
            "deposit": deposit,
            "rent": rent,
            "area": f"계약 {contract_area}㎡ / 전용 {exclusive_area}㎡",
            "floor": "",
            "address": desc,
            "description": desc,
            "realtor": "",
            "url": "",
            "confirmed": False,
        })

    return listings


def deduplicate_listings(listings):
    """중복 매물 제거 (제목+가격 기준)"""
    seen = set()
    unique = []
    for l in listings:
        key = (l.get("title", ""), l.get("price", ""), l.get("deposit", ""), l.get("rent", ""))
        if key not in seen:
            seen.add(key)
            unique.append(l)
    return unique


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

        # 네이버 검색 기반 매물 수집
        listings = await search_naver_land_listings(page, region, session_path)

        # 추가: "매매" 전용 검색
        if len([l for l in listings if l["trade_type"] == "매매"]) < 3:
            random_delay(DELAY_SHORT)
            sale_listings = await search_naver_land_listings(
                page, f"{region} 상가 매매", session_path
            )
            listings.extend(sale_listings)

        # 추가: "월세" 전용 검색
        if len([l for l in listings if l["trade_type"] == "월세"]) < 3:
            random_delay(DELAY_SHORT)
            rent_listings = await search_naver_land_listings(
                page, f"{region} 상가 월세", session_path
            )
            listings.extend(rent_listings)

        await browser.close()

    # 중복 제거
    listings = deduplicate_listings(listings)

    # 매매/임대 분류
    sale_listings = [l for l in listings if l.get("trade_type") == "매매"]
    rent_listings = [l for l in listings if l.get("trade_type") in ("전세", "월세")]

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
