"""Step 1-1: 네이버 지도에서 마트/슈퍼마켓 검색"""
import asyncio
import json
import re
from playwright.async_api import async_playwright
from config import (
    NAVER_MAP_URL, BROWSER_ARGS, VIEWPORT, USER_AGENT,
    DEFAULT_SEARCH_CATEGORIES, DELAY_SHORT, DELAY_MEDIUM,
    create_session, save_json, log, random_delay
)


async def search_naver_map(page, query, session_path):
    """네이버 지도에서 검색 후 결과 파싱"""
    results = []

    log(session_path, f"네이버 지도 검색: {query}")

    # 검색 URL 직접 접근
    search_url = f"https://map.naver.com/p/search/{query}"
    await page.goto(search_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    # 검색 결과 iframe 진입 (네이버 지도는 iframe 구조)
    search_iframe = None
    for frame in page.frames:
        if "search" in frame.url:
            search_iframe = frame
            break

    if not search_iframe:
        # iframe 없이 직접 접근 시도
        search_iframe = page

    # 결과 리스트 수집 — 네이버 지도 검색 결과 셀렉터
    # 네이버 지도는 자주 변경되므로 여러 셀렉터 시도
    selectors = [
        "li.VLTHu",           # 검색 결과 리스트 아이템
        "li[data-laim-exp-id]",
        ".place_bluelink",
        "a.place_bluelink",
        "li.UEzoS",
    ]

    items = []
    for sel in selectors:
        try:
            await search_iframe.wait_for_selector(sel, timeout=5000)
            items = await search_iframe.query_selector_all(sel)
            if items:
                log(session_path, f"셀렉터 '{sel}'로 {len(items)}건 발견")
                break
        except Exception:
            continue

    if not items:
        log(session_path, f"검색 결과 없음: {query}")
        # 스크린샷 저장
        await page.screenshot(path=f"{session_path}/screenshots/naver-map-{query}.png")
        return results

    # 각 항목 파싱
    for i, item in enumerate(items):
        try:
            entry = {}

            # 업소명 추출
            name_el = await item.query_selector(".place_bluelink, .TYaxT, a[class*='name'], span[class*='title']")
            if name_el:
                entry["name"] = (await name_el.inner_text()).strip()
            else:
                # 첫번째 링크 텍스트
                first_link = await item.query_selector("a")
                if first_link:
                    entry["name"] = (await first_link.inner_text()).strip()

            if not entry.get("name"):
                continue

            # 주소 추출
            addr_el = await item.query_selector(".LDgIH, .address, span[class*='addr']")
            if addr_el:
                entry["address"] = (await addr_el.inner_text()).strip()

            # 전화번호 추출
            phone_el = await item.query_selector(".xlx7Q, .phone, span[class*='tel']")
            if phone_el:
                entry["phone"] = (await phone_el.inner_text()).strip()

            # 카테고리 추출
            cat_el = await item.query_selector(".YzBgS, .category, span[class*='category']")
            if cat_el:
                entry["category"] = (await cat_el.inner_text()).strip()

            entry["source_query"] = query
            entry["lat"] = None  # 상세 페이지에서 추출 가능
            entry["lng"] = None

            results.append(entry)

        except Exception as e:
            log(session_path, f"항목 {i} 파싱 실패: {e}")
            continue

    # 스크린샷
    await page.screenshot(path=f"{session_path}/screenshots/naver-map-{query}.png")
    log(session_path, f"검색 완료: {query} → {len(results)}건")

    return results


async def extract_from_api(page, query, session_path):
    """네이버 지도 내부 API 응답 캡처로 구조화된 데이터 추출"""
    results = []
    api_responses = []

    # API 응답 캡처 핸들러
    async def handle_response(response):
        url = response.url
        if "place" in url and ("search" in url or "list" in url) and response.status == 200:
            try:
                body = await response.text()
                if body.startswith("{") or body.startswith("["):
                    api_responses.append(json.loads(body))
            except Exception:
                pass

    page.on("response", handle_response)

    search_url = f"https://map.naver.com/p/search/{query}"
    await page.goto(search_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    page.remove_listener("response", handle_response)

    # API 응답에서 데이터 추출
    for resp_data in api_responses:
        try:
            # 네이버 지도 API 응답 구조 파싱
            place_list = None
            if isinstance(resp_data, dict):
                # result.place.list 또는 result.list 패턴
                if "result" in resp_data:
                    result = resp_data["result"]
                    if "place" in result:
                        place_list = result["place"].get("list", [])
                    elif "list" in result:
                        place_list = result["list"]
                elif "places" in resp_data:
                    place_list = resp_data["places"]
            elif isinstance(resp_data, list):
                place_list = resp_data

            if place_list:
                for place in place_list:
                    entry = {
                        "name": place.get("name", place.get("title", "")),
                        "address": place.get("roadAddress", place.get("address", "")),
                        "phone": place.get("phone", place.get("tel", "")),
                        "category": place.get("category", place.get("categoryName", "")),
                        "lat": place.get("y", place.get("lat", None)),
                        "lng": place.get("x", place.get("lng", None)),
                        "source_query": query,
                    }
                    if entry["name"]:
                        # 좌표를 float으로 변환
                        if entry["lat"]:
                            entry["lat"] = float(entry["lat"])
                        if entry["lng"]:
                            entry["lng"] = float(entry["lng"])
                        results.append(entry)
        except Exception as e:
            log(session_path, f"API 응답 파싱 실패: {e}")
            continue

    if results:
        log(session_path, f"API 캡처로 {len(results)}건 추출: {query}")

    return results


def deduplicate(results):
    """이름+주소 기준 중복 제거"""
    seen = set()
    unique = []
    for r in results:
        key = (r.get("name", ""), r.get("address", ""))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


async def run(region, session_path):
    """Step 1-1 메인 실행"""
    log(session_path, f"=== Step 1-1 시작: {region} 마트/슈퍼마켓 검색 ===")

    all_results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(**BROWSER_ARGS)
        context = await browser.new_context(
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        for category in DEFAULT_SEARCH_CATEGORIES:
            query = f"{region} {category}"

            # 방법 1: API 캡처 시도
            api_results = await extract_from_api(page, query, session_path)

            if api_results:
                all_results.extend(api_results)
            else:
                # 방법 2: DOM 파싱 폴백
                dom_results = await search_naver_map(page, query, session_path)
                all_results.extend(dom_results)

            random_delay(DELAY_MEDIUM)

        await browser.close()

    # 중복 제거
    unique_results = deduplicate(all_results)

    # 결과 저장
    output_path = f"{session_path}/step-1-1-marts.json"
    save_json(unique_results, output_path)

    log(session_path, f"=== Step 1-1 완료: {len(unique_results)}건 마트 발견 ===")

    return unique_results


if __name__ == "__main__":
    import sys
    region = sys.argv[1] if len(sys.argv) > 1 else "이촌역"
    session_id, session_path = create_session(region)

    # config 저장
    save_json({
        "region": region,
        "session_id": session_id,
        "session_path": session_path,
    }, f"{session_path}/config.json")

    results = asyncio.run(run(region, session_path))
    print(f"\n총 {len(results)}건 마트 발견:")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r.get('name', '?')} — {r.get('address', '?')}")
    print(f"\n세션: {session_path}")
