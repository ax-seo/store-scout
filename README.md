# store-scout

상가 매물 조사 자동화 도구. Playwright 기반으로 네이버 지도, 오픈업(OpenUp), 네이버 부동산을 자동 탐색하여 마크다운 리포트를 생성한다.

---

## 파이프라인 구조

```
Phase 1: 지역 탐색
  Step 1-1  네이버 지도 마트/슈퍼마켓 검색
  Step 1-2  오픈업 매출 검증 (크레딧 차감)

Phase 2: 매물 수집
  Step 2-1  네이버 지도 부동산 중개업소 검색
  Step 2-2  네이버 부동산 상가 매물 검색

Phase 3: 산출물
  Step 3-1  마크다운 리포트 생성
```

---

## Windows 설치 가이드

### 1. Python 설치

[python.org](https://www.python.org/downloads/)에서 Python 3.10 이상을 다운로드한다.

설치 시 반드시 **"Add Python to PATH"** 체크박스를 선택한다.

설치 확인:

```powershell
python --version
pip --version
```

### 2. 프로젝트 클론

```powershell
git clone https://github.com/ax-seo/store-scout.git
cd store-scout
```

또는 ZIP 다운로드 후 압축 해제.

### 3. 가상환경 생성 (권장)

```powershell
python -m venv .venv
.venv\Scripts\activate
```

활성화 후 프롬프트 앞에 `(.venv)`가 표시되면 정상.

### 4. 의존성 설치

```powershell
pip install playwright
playwright install chromium
```

`playwright install chromium`은 Chromium 브라우저를 자동 다운로드한다. 회사 프록시 환경에서 실패하면 아래 환경변수를 설정:

```powershell
$env:HTTPS_PROXY = "http://proxy.company.com:8080"
playwright install chromium
```

### 5. 오픈업 로그인 (최초 1회)

오픈업 매출 검증을 사용하려면 쿠키를 먼저 저장해야 한다.

```powershell
cd scripts
python openup_login.py
```

1. 브라우저가 열린다
2. 오픈업(openub.com)에 로그인한다
3. 로그인 완료 후 **별도 터미널**에서 시그널 파일을 생성한다:

```powershell
# PowerShell
echo. > "$env:TEMP\store-scout\login-done"
```

```cmd
:: CMD
echo. > "%TEMP%\store-scout\login-done"
```

4. 쿠키가 `session/openup-cookies.json`에 저장된다

> 쿠키 만료 시 위 과정을 반복한다.

---

## 사용법

### 기본 실행

```powershell
cd scripts
python main.py "강남역"
```

### 주요 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `region` | (필수) | 조사할 지역명. 복수 입력 가능 |
| `--threshold` | `4억` | 유망 판정 월매출 기준 |
| `--credit-limit` | `10` | 오픈업 크레딧 최대 사용량 |
| `--skip-openup` | 미사용 | 오픈업 매출 검증 생략 |
| `--headless` | 미사용 | 브라우저 숨김 모드 |
| `--slack` | 미사용 | 결과 전송 슬랙 채널 |
| `--viz` | 미사용 | HTML 대시보드 생성 |

### 실행 예시

```powershell
# 강남역 주변, 매출 기준 3억
python main.py "강남역" --threshold 3억

# 여러 지역 동시 조사
python main.py "강남역" "홍대입구" "잠실역"

# 오픈업 생략 (크레딧 소모 없음)
python main.py "역삼역" --skip-openup

# 브라우저 숨김 + 오픈업 생략
python main.py "강남역" --skip-openup --headless
```

> 오픈업 사용 시 `--headless` 불가. CloudFront 봇 차단으로 `headless=False`가 강제된다.

### 결과물 위치

- 세션 데이터: `%TEMP%\store-scout\<지역>_<시간>\`
- 스크린샷: `%TEMP%\store-scout\<지역>_<시간>\screenshots\`
- 최종 리포트: 세션 폴더 내 마크다운 파일

---

## 프로젝트 구조

```
store-scout/
├── scripts/
│   ├── config.py                   # 공통 설정, 경로, 딜레이
│   ├── main.py                     # CLI 엔트리포인트
│   ├── openup_login.py             # 오픈업 쿠키 저장 (수동 로그인)
│   ├── step_1_1_naver_map_marts.py # 네이버 지도 마트 검색
│   ├── step_1_2_openup_sales.py    # 오픈업 매출 검증
│   ├── step_2_1_realtors.py        # 부동산 중개업소 검색
│   ├── step_2_2_naver_land.py      # 네이버 부동산 매물 검색
│   └── step_3_1_report.py          # 마크다운 리포트 생성
├── session/                        # 오픈업 쿠키 저장
├── .gitignore
└── README.md
```

---

## 트러블슈팅

### Playwright 설치 실패

```powershell
# 시스템 의존성 설치
playwright install-deps chromium
```

Windows에서는 대부분 추가 의존성이 필요 없지만, 위 명령으로 확인 가능.

### PowerShell 실행 정책 오류

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 가상환경 활성화 오류 (PowerShell)

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.venv\Scripts\activate
```

### 오픈업 CloudFront 403 차단

- `--headless` 옵션 없이 실행 (기본값)
- 오픈업 사용 시 반드시 브라우저 창이 보여야 한다

### 네이버 지도 검색 결과 없음

- 검색어를 구체적으로 변경 (예: "강남역" 대신 "강남역 마트")
- 네이버 지도가 정상 접속되는지 브라우저에서 먼저 확인

### 인코딩 오류 (한글 깨짐)

PowerShell 인코딩 설정:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
```

CMD 인코딩 설정:

```cmd
chcp 65001
```
