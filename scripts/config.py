"""store-scout 공통 설정"""
import os
import json
import time
import tempfile
import platform

# 디렉토리
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION_DIR = os.path.join(PROJECT_DIR, "session")
SCREENSHOT_DIR = None  # 세션별 동적 설정

# 기본값
DEFAULT_THRESHOLD = 400000000  # 4억
DEFAULT_CREDIT_LIMIT = 10
DEFAULT_SEARCH_CATEGORIES = ["슈퍼마켓", "마트"]

# Anti-bot 딜레이 (초)
DELAY_SHORT = (2, 4)    # 일반 페이지 이동
DELAY_MEDIUM = (4, 6)   # 검색 간
DELAY_LONG = (8, 12)    # 크레딧 차감 조회 간
DELAY_BURST_PAUSE = 30  # 연속 10건 후 대기

# 오픈업
OPENUP_URL = "https://www.openub.com"
OPENUP_COOKIES_PATH = os.path.join(SESSION_DIR, "openup-cookies.json")

# 네이버
NAVER_MAP_URL = "https://map.naver.com"
NAVER_LAND_URL = "https://new.land.naver.com"

# Playwright 공통 설정
BROWSER_ARGS = {
    "headless": False,  # 디버그 시 False, 프로덕션 시 True
    "slow_mo": 100,
}
VIEWPORT = {"width": 1920, "height": 1080}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    if platform.system() == "Windows"
    else "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 크로스플랫폼 임시 디렉토리
TEMP_BASE = os.path.join(tempfile.gettempdir(), "store-scout")
SIGNAL_FILE = os.path.join(TEMP_BASE, "login-done")


def create_session(region):
    """세션 디렉토리 생성 및 반환"""
    session_id = f"{region}_{time.strftime('%Y%m%d_%H%M%S')}"
    session_path = os.path.join(TEMP_BASE, session_id)
    screenshots_path = os.path.join(session_path, "screenshots")
    os.makedirs(screenshots_path, exist_ok=True)

    global SCREENSHOT_DIR
    SCREENSHOT_DIR = screenshots_path

    return session_id, session_path


def save_json(data, filepath):
    """JSON 파일 저장"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(filepath):
    """JSON 파일 로드"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def log(session_path, message):
    """세션 로그 기록"""
    log_path = os.path.join(session_path, "log.txt")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
    print(f"[{timestamp}] {message}")


def random_delay(delay_range):
    """랜덤 딜레이"""
    import random
    delay = random.uniform(delay_range[0], delay_range[1])
    time.sleep(delay)
    return delay
