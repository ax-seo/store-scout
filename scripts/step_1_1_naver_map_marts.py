"""Step 1-1: 네이버 지도에서 마트/슈퍼마켓 검색
네이버 지도 내부 API 직접 호출 + Playwright iframe 파싱 폴백
"""
import asyncio
import json
import re
import urllib.parse
from playwright.async_api import async_playwright
from config import (
    NAVER_MAP_URL, BROWSER_ARGS, VIEWPORT, USER_AGENT,
    DEFAULT_SEARCH_CATEGORIES, DELAY_SHORT, DELAY_MEDIUM,
    create_session, save_json, log, random_delay
)


async def search_via_api_intercept(page, query, session_path):
    """네이버 지도 페이지 로드 시 모든 API 응답을 캡처하여 데이터 추출"""
    results = []
    api_data = []

    async def capture(response):
        url = response.url
        try:
            # 네이버 지도 내부 검색 API 패턴들
            if response.status == 200 and any(k in url for k in [
                "map.naver.com/p/api/search",
                "map.naver.com/v5/api/search",
                "map.naver.com/p/api/place",
                "pcmap-api.place.naver.com",
                "pcmap.place.naver.com/api",
                "place.map.naver.com",
            ]):
                body = await response.text()
                if body and (body.lstrip().startswith("{") or body.lstrip().startswith("[")):
                    data = json.loads(body)
                    api_data.append({"url": url, "data": data})
        except Exception:
            pass

    page.on("response", capture)

    search_url = f"https://map.naver.com/p/search/{urllib.parse.quote(query)}"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    # 검색 결과 로드 대기 — networkidle 대신 충분한 시간 대기
    await page.wait_for_timeout(8000)

    # 스크린샷
    await page.screenshot(path=f"{session_path}/screenshots/naver-map-{query}.png")

    page.remove_listener("response", capture)

    # 캡처된 API 데이터에서 장소 목록 추출
    for item in api_data:
        places = extract_places_from_response(item["data"])
        if places:
            log(session_path, f"API [{item['url'][:80]}...] → {len(places)}건")
            results.extend(places)

    # 결과에 source_query 추가
    for r in results:
        r["source_query"] = query

    if results:
        log(session_path, f"API 캡처 성공: {query} → {len(results)}건")

    return results


def extract_places_from_response(data):
    """다양한 API 응답 구조에서 장소 리스트 추출"""
    places = []

    if isinstance(data, list):
        for item in data:
            place = parse_place(item)
            if place:
                places.append(place)
        return places

    if not isinstance(data, dict):
        return places

    # 패턴 1: result.place.list
    try:
        place_list = data.get("result", {}).get("place", {}).get("list", [])
        if place_list:
            for item in place_list:
                place = parse_place(item)
                if place:
                    places.append(place)
            return places
    except (AttributeError, TypeError):
        pass

    # 패턴 2: result.list
    try:
        result_list = data.get("result", {}).get("list", [])
        if result_list:
            for item in result_list:
                place = parse_place(item)
                if place:
                    places.append(place)
            return places
    except (AttributeError, TypeError):
        pass

    # 패턴 3: data 자체가 장소 리스트를 포함하는 다른 키
    for key in ["places", "items", "list", "data", "results", "searchResult"]:
        try:
            items = data.get(key, [])
            if isinstance(items, list) and items:
                for item in items:
                    place = parse_place(item)
                    if place:
                        places.append(place)
                if places:
                    return places
        except (AttributeError, TypeError):
            continue

    # 패턴 4: 재귀적으로 탐색
    for key, value in data.items():
        if isinstance(value, dict):
            nested = extract_places_from_response(value)
            if nested:
                return nested

    return places


def parse_place(item):
    """개별 장소 데이터를 표준 형식으로 변환"""
    if not isinstance(item, dict):
        return None

    name = (
        item.get("name") or item.get("title") or item.get("placeName") or
        item.get("businessName") or ""
    )
    if not name:
        return None

    address = (
        item.get("roadAddress") or item.get("address") or
        item.get("fullRoadAddress") or item.get("fullAddress") or ""
    )

    phone = (
        item.get("phone") or item.get("tel") or
        item.get("virtualPhone") or item.get("phoneNumber") or ""
    )

    category = (
        item.get("category") or item.get("categoryName") or
        item.get("businessCategory") or ""
    )

    lat = item.get("y") or item.get("lat") or item.get("latitude") or None
    lng = item.get("x") or item.get("lng") or item.get("longitude") or None

    try:
        if lat is not None:
            lat = float(lat)
        if lng is not None:
            lng = float(lng)
    except (ValueError, TypeError):
        lat = None
        lng = None

    return {
        "name": str(name).strip(),
        "address": str(address).strip(),
        "phone": str(phone).strip(),
        "category": str(category).strip(),
        "lat": lat,
        "lng": lng,
    }


async def search_via_iframe(page, query, session_path):
    """네이버 지도 검색 결과 iframe에서 DOM 파싱"""
    results = []

    log(session_path, f"iframe 파싱 시도: {query}")

    search_url = f"https://map.naver.com/p/search/{urllib.parse.quote(query)}"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # searchIframe 찾기
    search_iframe = None
    for frame in page.frames:
        frame_url = frame.url
        if "search" in frame_url and "naver" in frame_url:
            search_iframe = frame
            break

    if not search_iframe:
        # 모든 프레임 URL 로그
        for f in page.frames:
            log(session_path, f"  frame: {f.url[:100]}")
        log(session_path, "searchIframe 찾기 실패")
        return results

    log(session_path, f"searchIframe 발견: {search_iframe.url[:80]}")

    # iframe 내에서 리스트 아이템 찾기
    # 네이버 지도 검색 결과의 일반적 구조: <li> 안에 업소 정보
    try:
        await search_iframe.wait_for_selector("li", timeout=10000)
        items = await search_iframe.query_selector_all("li")

        for item in items:
            try:
                text = await item.inner_text()
                lines = [l.strip() for l in text.split("\n") if l.strip()]

                if len(lines) < 2:
                    continue

                # 첫줄이 업소명일 가능성 높음
                name = lines[0]

                # 너무 짧거나 숫자만인 경우 skip
                if len(name) < 2 or name.isdigit():
                    continue

                # 주소/전화 등 추출
                address = ""
                phone = ""
                category = ""

                for line in lines[1:]:
                    if re.match(r'서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주', line):
                        address = line
                    elif re.match(r'0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}', line):
                        phone = line
                    elif not category and len(line) < 20 and not line[0].isdigit():
                        category = line

                # 유효한 항목만 추가 (마트/슈퍼 관련)
                entry = {
                    "name": name,
                    "address": address,
                    "phone": phone,
                    "category": category,
                    "lat": None,
                    "lng": None,
                    "source_query": query,
                }
                results.append(entry)

            except Exception:
                continue

    except Exception as e:
        log(session_path, f"iframe DOM 파싱 실패: {e}")

    # 스크린샷
    await page.screenshot(path=f"{session_path}/screenshots/naver-map-iframe-{query}.png")

    if results:
        log(session_path, f"iframe 파싱: {query} → {len(results)}건")

    return results


def deduplicate(results):
    """이름 기준 중복 제거"""
    seen = set()
    unique = []
    for r in results:
        name = r.get("name", "").strip()
        if name and name not in seen:
            seen.add(name)
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

            # 방법 1: API 응답 캡처 (가장 정확)
            api_results = await search_via_api_intercept(page, query, session_path)

            if api_results:
                all_results.extend(api_results)
            else:
                # 방법 2: iframe DOM 파싱 폴백
                iframe_results = await search_via_iframe(page, query, session_path)
                all_results.extend(iframe_results)

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
