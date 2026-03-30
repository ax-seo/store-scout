"""store-scout 메인 오케스트레이터"""
import asyncio
import argparse
import sys
import os
import time

# 스크립트 디렉토리를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DEFAULT_THRESHOLD, DEFAULT_CREDIT_LIMIT,
    create_session, save_json, log
)
from step_1_1_naver_map_marts import run as run_step_1_1
from step_1_2_openup_sales import run as run_step_1_2
from step_2_1_realtors import run as run_step_2_1
from step_2_2_naver_land import run as run_step_2_2
from step_3_1_report import generate_report


def parse_threshold(value):
    """'4억', '3억', '300000000' 등을 int로 변환"""
    value = str(value).strip()
    if "억" in value:
        num = float(value.replace("억", "").replace(",", "").strip())
        return int(num * 100000000)
    elif "만" in value:
        num = float(value.replace("만", "").replace(",", "").strip())
        return int(num * 10000)
    else:
        return int(value.replace(",", ""))


def format_threshold(value):
    """int를 '4억' 형태로"""
    eok = value // 100000000
    man = (value % 100000000) // 10000
    if eok > 0 and man > 0:
        return f"{eok}억 {man:,}만"
    elif eok > 0:
        return f"{eok}억"
    elif man > 0:
        return f"{man:,}만"
    return str(value)


async def run_pipeline(region, threshold, credit_limit, skip_openup, slack_channel, viz):
    """전체 파이프라인 실행"""
    session_id, session_path = create_session(region)

    # 실행 설정 저장
    config = {
        "region": region,
        "session_id": session_id,
        "threshold": threshold,
        "threshold_display": format_threshold(threshold),
        "credit_limit": credit_limit,
        "skip_openup": skip_openup,
        "slack_channel": slack_channel,
        "viz": viz,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_json(config, f"{session_path}/config.json")

    print(f"""
╔══════════════════════════════════════════════╗
║         /store-scout v1.0                    ║
╠══════════════════════════════════════════════╣
║  지역: {region:<38}║
║  매출 기준: {format_threshold(threshold):<33}║
║  크레딧 한도: {credit_limit:<31}║
║  오픈업: {'생략' if skip_openup else '사용':<35}║
║  세션: {session_id:<38}║
╚══════════════════════════════════════════════╝
""")

    # ━━━ Phase 1: 지역 탐색 ━━━
    print("━━━ Phase 1: 지역 탐색 ━━━")

    # Step 1-1: 마트 검색
    marts = await run_step_1_1(region, session_path)
    if not marts:
        log(session_path, f"❌ {region}에서 마트를 찾지 못했습니다.")
        print(f"\n❌ {region}에서 마트를 찾지 못했습니다.")
        print("검색어를 변경하거나 다른 지역을 시도하세요.")
        return session_path

    print(f"\n  ✅ Step 1-1: {len(marts)}개 마트 발견")
    for m in marts[:5]:
        print(f"     - {m.get('name', '?')}")
    if len(marts) > 5:
        print(f"     ... 외 {len(marts)-5}건")

    # Step 1-2: 매출 검증
    sales = await run_step_1_2(session_path, threshold, credit_limit, skip_openup)
    promising = [s for s in sales if s.get("is_promising")]

    print(f"\n  ✅ Step 1-2: {len(promising)}/{len(sales)} 유망")
    for s in sales:
        status = "✅" if s.get("is_promising") else "❌"
        print(f"     {status} {s.get('name', '?')} — {s.get('monthly_sales_display', '?')}")

    # 유망 마트 없으면 경고하되 계속 진행
    if not promising and not skip_openup:
        print(f"\n  ⚠️ 유망 마트 없음 (기준: 월 {format_threshold(threshold)})")
        print("  매물 수집은 계속 진행합니다.")

    # ━━━ Phase 2: 매물 수집 ━━━
    print("\n━━━ Phase 2: 매물 수집 ━━━")

    # Step 2-1: 부동산 중개업소
    agents = await run_step_2_1(region, session_path)
    print(f"\n  ✅ Step 2-1: {len(agents)}개 부동산 중개업소")
    for a in agents[:3]:
        print(f"     - {a.get('name', '?')} ({a.get('phone', '번호없음')})")
    if len(agents) > 3:
        print(f"     ... 외 {len(agents)-3}건")

    # Step 2-2: 상가 매물
    listings = await run_step_2_2(region, session_path)
    print(f"\n  ✅ Step 2-2: 상가 매물 {listings['total']}건 (매매 {listings['sale_count']}, 임대 {listings['rent_count']})")
    for l in listings["all_listings"][:3]:
        print(f"     - {l.get('title', '?')} — {l.get('price', '')} {l.get('deposit', '')} {l.get('rent', '')}")

    # ━━━ Phase 3: 산출물 ━━━
    print("\n━━━ Phase 3: 산출물 ━━━")

    # Step 3-1: 리포트
    report_content, report_path = generate_report(session_path, region, format_threshold(threshold))
    print(f"\n  ✅ Step 3-1: 리포트 생성 → {report_path}")

    # Step 3-2: 전달
    if slack_channel:
        print(f"\n  📨 슬랙 전송: {slack_channel}")
        # Slack MCP는 Claude Code에서 처리
        log(session_path, f"슬랙 전송 대상: {slack_channel}")

    # 완료 요약
    print(f"""
╔══════════════════════════════════════════════╗
║  ✅ /store-scout 완료                         ║
╠══════════════════════════════════════════════╣
║  마트: {len(marts)}개 발견, {len(promising)}개 유망{' '*24}║
║  매물: {listings['total']}건 (매매 {listings['sale_count']}, 임대 {listings['rent_count']}){' '*18}║
║  중개업소: {len(agents)}곳{' '*32}║
║  리포트: ~/Downloads/{region}-store-scout-*.md{' '*5}║
║  세션: {session_path}{' '*5}║
╚══════════════════════════════════════════════╝
""")

    return session_path


def main():
    parser = argparse.ArgumentParser(description="/store-scout — 상가 매물 조사 자동화")
    parser.add_argument("region", nargs="+", help="조사할 지역명 (역명 또는 지역명)")
    parser.add_argument("--threshold", default="4억", help="유망 판정 월매출 기준 (기본: 4억)")
    parser.add_argument("--credit-limit", type=int, default=DEFAULT_CREDIT_LIMIT, help=f"오픈업 크레딧 최대 사용량 (기본: {DEFAULT_CREDIT_LIMIT})")
    parser.add_argument("--skip-openup", action="store_true", help="오픈업 매출 검증 생략")
    parser.add_argument("--slack", default=None, help="결과 전송 슬랙 채널")
    parser.add_argument("--viz", action="store_true", help="HTML 대시보드 생성")
    parser.add_argument("--headless", action="store_true", help="브라우저 숨김 모드")

    args = parser.parse_args()

    threshold = parse_threshold(args.threshold)

    # headless 모드 설정
    if args.headless:
        from config import BROWSER_ARGS
        BROWSER_ARGS["headless"] = True

    # 각 지역별 실행
    for region in args.region:
        asyncio.run(run_pipeline(
            region=region,
            threshold=threshold,
            credit_limit=args.credit_limit,
            skip_openup=args.skip_openup,
            slack_channel=args.slack,
            viz=args.viz,
        ))


if __name__ == "__main__":
    main()
