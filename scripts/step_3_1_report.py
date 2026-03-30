"""Step 3-1: 통합 리포트 생성"""
import os
import time
import shutil
from config import save_json, load_json, log


def generate_report(session_path, region, threshold_display="4억"):
    """마크다운 리포트 생성"""
    log(session_path, f"=== Step 3-1 시작: 통합 리포트 생성 ===")

    # Step별 데이터 로드
    marts = safe_load(f"{session_path}/step-1-1-marts.json", [])
    sales = safe_load(f"{session_path}/step-1-2-sales.json", [])
    agents = safe_load(f"{session_path}/step-2-1-agents.json", [])
    listings_data = safe_load(f"{session_path}/step-2-2-listings.json", {})

    sale_listings = listings_data.get("sale_listings", [])
    rent_listings = listings_data.get("rent_listings", [])
    all_listings = listings_data.get("all_listings", [])

    # 유망 판정
    promising = [s for s in sales if s.get("is_promising")]
    verdict = "유망" if promising else "매출 미달"

    # 리포트 생성
    lines = []
    lines.append(f"# {region} 상가 매물 조사 리포트")
    lines.append("")
    lines.append(f"> 조사일: {time.strftime('%Y-%m-%d')} | 생성: /store-scout v1.0")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 지역 개요
    lines.append("## 1. 지역 개요")
    lines.append("")
    lines.append(f"- **조사 지역**: {region}")
    lines.append(f"- **매출 기준**: 월 {threshold_display} 이상")
    lines.append(f"- **판정 결과**: {verdict} ({len(promising)}개 마트 기준 충족)")
    lines.append(f"- **발견 마트**: {len(marts)}개")
    lines.append(f"- **상가 매물**: {len(all_listings)}건")
    lines.append(f"- **부동산 중개**: {len(agents)}곳")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 2. 마트별 매출 데이터
    if sales:
        lines.append("## 2. 마트별 매출 데이터")
        lines.append("")
        lines.append("| # | 업소명 | 월매출 | 판정 |")
        lines.append("|---|--------|--------|------|")
        for i, s in enumerate(sales, 1):
            status = "✅ 유망" if s.get("is_promising") else "❌ 미달"
            name = s.get("name", "?")
            sales_display = s.get("monthly_sales_display", "데이터 없음")
            lines.append(f"| {i} | {name} | {sales_display} | {status} |")
        lines.append("")

        total_credits = sum(s.get("credit_used", 0) for s in sales)
        lines.append(f"> 출처: 오픈업(openub.com) 추정 매출 | 크레딧 {total_credits}건 사용")
        lines.append("")
    elif marts:
        lines.append("## 2. 마트 목록 (매출 미확인)")
        lines.append("")
        lines.append("| # | 업소명 | 주소 |")
        lines.append("|---|--------|------|")
        for i, m in enumerate(marts, 1):
            lines.append(f"| {i} | {m.get('name', '?')} | {m.get('address', '')} |")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 3. 상가 매물 리스트
    lines.append("## 3. 상가 매물 리스트")
    lines.append("")

    if sale_listings:
        lines.append("### 매매")
        lines.append("")
        lines.append("| # | 매물명 | 가격 | 면적 | 층 | 링크 |")
        lines.append("|---|--------|------|------|---|------|")
        for i, l in enumerate(sale_listings, 1):
            title = l.get("title", "?")
            price = l.get("price", "")
            area = l.get("area", "")
            floor = l.get("floor", "")
            url = l.get("url", "")
            link = f"[보기]({url})" if url else ""
            lines.append(f"| {i} | {title} | {price} | {area} | {floor} | {link} |")
        lines.append("")

    if rent_listings:
        lines.append("### 임대 (전세/월세)")
        lines.append("")
        lines.append("| # | 매물명 | 보증금 | 월세 | 면적 | 층 | 링크 |")
        lines.append("|---|--------|--------|------|------|---|------|")
        for i, l in enumerate(rent_listings, 1):
            title = l.get("title", "?")
            deposit = l.get("deposit", "")
            rent = l.get("rent", "")
            area = l.get("area", "")
            floor = l.get("floor", "")
            url = l.get("url", "")
            link = f"[보기]({url})" if url else ""
            lines.append(f"| {i} | {title} | {deposit} | {rent} | {area} | {floor} | {link} |")
        lines.append("")

    if not all_listings:
        lines.append("*해당 지역에 등록된 상가 매물이 없습니다.*")
        lines.append("")

    lines.append("> 출처: 네이버 부동산 (new.land.naver.com)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 4. 부동산 중개업소
    lines.append("## 4. 부동산 중개업소")
    lines.append("")
    if agents:
        lines.append("| # | 업소명 | 전화번호 | 주소 |")
        lines.append("|---|--------|----------|------|")
        for i, a in enumerate(agents, 1):
            name = a.get("name", "?")
            phone = a.get("phone", "")
            address = a.get("address", "")
            lines.append(f"| {i} | {name} | {phone} | {address} |")
        lines.append("")
    else:
        lines.append("*부동산 중개업소 정보 없음*")
        lines.append("")

    lines.append("---")
    lines.append("")

    # 5. 참고사항
    lines.append("## 5. 참고사항")
    lines.append("")
    lines.append("- 매출 데이터는 오픈업 추정치이며, 실제와 차이가 있을 수 있습니다.")
    lines.append("- 매물 정보는 조사 시점 기준이며, 변동될 수 있습니다.")
    lines.append("- 확인매물(✓)은 중개업소에서 매물 존재를 확인한 건입니다.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*이 리포트는 /store-scout 자동화 파이프라인으로 생성되었습니다.*")

    report_content = "\n".join(lines)

    # 세션 내 저장
    report_path = f"{session_path}/report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    # Downloads에 복사
    downloads_path = os.path.expanduser(f"~/Downloads/{region}-store-scout-{time.strftime('%Y%m%d')}.md")
    shutil.copy2(report_path, downloads_path)

    log(session_path, f"리포트 저장: {downloads_path}")
    log(session_path, f"=== Step 3-1 완료 ===")

    return report_content, downloads_path


def safe_load(path, default):
    """파일 안전 로드"""
    try:
        return load_json(path)
    except (FileNotFoundError, Exception):
        return default


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python step_3_1_report.py <session_path> <region> [threshold_display]")
        sys.exit(1)

    session_path = sys.argv[1]
    region = sys.argv[2]
    threshold_display = sys.argv[3] if len(sys.argv) > 3 else "4억"

    content, path = generate_report(session_path, region, threshold_display)
    print(f"\n리포트 생성 완료: {path}")
    print(f"\n{'='*60}")
    print(content[:500])
    print("...")
