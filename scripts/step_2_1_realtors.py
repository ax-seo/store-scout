"""Step 2-1: 네이버 지도에서 부동산 중개업소 검색"""
import asyncio
from playwright.async_api import async_playwright
from config import (
    BROWSER_ARGS, VIEWPORT, USER_AGENT, DELAY_SHORT,
    save_json, load_json, log, random_delay
)
from step_1_1_naver_map_marts import search_naver_map, extract_from_api, deduplicate


async def run(region, session_path):
    """Step 2-1 메인 실행"""
    log(session_path, f"=== Step 2-1 시작: {region} 부동산 중개업소 검색 ===")

    query = f"{region} 부동산"
    all_results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(**BROWSER_ARGS)
        context = await browser.new_context(
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        # API 캡처 우선
        api_results = await extract_from_api(page, query, session_path)

        if api_results:
            all_results.extend(api_results)
        else:
            # DOM 파싱 폴백
            dom_results = await search_naver_map(page, query, session_path)
            all_results.extend(dom_results)

        await browser.close()

    # 중복 제거
    unique_results = deduplicate(all_results)

    # 부동산 중개업소 형태로 정리
    agents = []
    for r in unique_results:
        agents.append({
            "name": r.get("name", ""),
            "phone": r.get("phone", ""),
            "address": r.get("address", ""),
            "category": r.get("category", "부동산"),
        })

    # 결과 저장
    save_json(agents, f"{session_path}/step-2-1-agents.json")

    log(session_path, f"=== Step 2-1 완료: {len(agents)}개 부동산 중개업소 발견 ===")

    return agents


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python step_2_1_realtors.py <region> <session_path>")
        sys.exit(1)

    region = sys.argv[1]
    session_path = sys.argv[2]

    results = asyncio.run(run(region, session_path))

    print(f"\n부동산 중개업소 {len(results)}건:")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r['name']} — {r.get('phone', '번호없음')} — {r.get('address', '')}")
