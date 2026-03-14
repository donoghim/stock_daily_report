# 📈 미국 증시 마감 시황 리포트 자동화 (Gemini 1.5 Pro)

이 프로젝트는 매일 아침 미국 증시 마감 데이터를 정확하게 수집하고, 최신 경제 기사를 종합하여 **Google Gemini 1.5 Pro** AI를 통해 완성된 시황 분석 보고서를 **PDF 형식으로 이메일 자동 발송**하는 파이썬 기반의 GitHub Actions 자동화 시스템입니다.

---

## 🏗️ 시스템 아키텍처 및 동작 흐름 (Workflow)

본 스크립트는 매일 약속된 시간(KST 아침 6시 30분)에 GitHub 서버에서 자동으로 동작하며 아래의 순서로 실행됩니다.

### 1. 📅 개장일 판단 및 환경 변수 체크 (`pandas_market_calendars`)
- 미국 시간(EST/EDT) 기준으로 오늘이 뉴욕증시 개장일인지 확인합니다.
- **휴장일(주말/공휴일)인 경우**: 스크립트 실행을 중단하고 "오늘 미국 증시는 휴장입니다"라는 안내 메일만 텍스트로 보냅니다.
- **예외 (수동 실행 시)**: GitHub Actions에서 `Run workflow` 버튼을 직접 누른 경우(수동 실행), 오늘이 휴장일이더라도 **가장 최근의 과거 개장일(ex: 금요일)** 데이터를 찾아서 보고서 생성을 강제로 진행합니다.

### 2. 📊 정확한 수치 데이터 수집 (`yfinance`)
- 가장 큰 문제였던 LLM의 '수치 조작(할루시네이션)'을 원천 차단하기 위해, 실제 주가 데이터는 파이썬이 직접 긁어옵니다.
- 3대 지수(다우지수, S&P 500, 나스닥), 10년물 국채 금리, 금 선물, 원/달러 환율 종가와 등락률을 계산합니다.

### 3. 📰 실시간 주요 뉴스 수집 (`feedparser`)
- Yahoo Finance 등 공신력 있는 경제 매체의 RSS 피드에서 가장 최신 주요 기사 5건(제목과 링크)을 수집해 옵니다.

### 4. 🤖 AI 리포트 생성 (`google-generativeai`)
- 위 2번과 3번에서 수집한 **정확한 숫자 데이터**와 **기사 목록**만 프롬프트 안에 넣어서(Inject) Gemini 1.5 Pro에게 보냅니다.
- 프롬프트에 "주어진 데이터만 사용할 것"이라는 제약을 걸어 숫자는 정확하게, 분석과 요약은 월스트리트 전문가 톤(Tone)으로 유려하게 작성된 Markdown 리포트를 반환받습니다.

### 5. 📄 HTML 변환 및 PDF 렌더링 (`markdown`, `pdfkit`)
- Gemini가 넘겨준 Markdown 텍스트에 기본적인 폰트, 여백, 선 등 깔끔한 CSS 스타일을 덧입혀 HTML로 변환합니다.
- 리눅스 내장 도구(`wkhtmltopdf`)를 활용하여 최종적으로 PDF 파일(`report_YYYY-MM-DD.pdf`)로 저장합니다.

### 6. 📧 이메일 자동 전송 (`smtplib`)
- 완성된 PDF 파일을 첨부하여, GitHub Secrets에 미리 저장해 둔 본인의 Gmail 계정을 통해 지정된 수신처로 이메일을 최종 발송하고 프로세스를 종료합니다.

---

## 🛠️ GitHub Actions 설정 방법

이 프로젝트가 완전 무인 자동화로 매일 1회 동작하기 위해서, 레포지토리의 **Settings ➔ Secrets and variables ➔ Actions** 에 다음 4개의 비밀 변수를 등록해야 합니다.

1. **`GEMINI_API_KEY`**: 구글 AI Studio에서 발급받은 Gemini 1.5 API 키
2. **`SENDER_EMAIL`**: 메일을 보낼 구글(Gmail) 계정 주소
3. **`SENDER_PASSWORD`**: 메일을 보낼 구글 계정의 **16자리 앱 비밀번호**
4. **`RECEIVER_EMAIL`**: 시황 보고서를 매일 수신할 이메일 주소

## ⏰ 스케줄러 수정 안내
현재 `.github/workflows/daily_report.yml` 파일 내에 Cron이 설정되어 있습니다.
- `cron: '30 21 * * *'` (UTC 기준)
- 한국(KST) 시간으로는 9시간을 더한 **오전 6시 30분**에 매일 실행됩니다. 
- (시간을 변경하고 싶다면 위 cron 표현식을 수정하시면 됩니다.)

---

## 💻 로컬 디버깅 모드 테스트 방법

GitHub에 코드를 올리지 않고 내 PC에서 즉시 결과물을 확인하고 싶을 때 사용하는 방법입니다.

### 1. `.env` 파일 설정
프로젝트 최상단 폴더에 `.env` 파일을 생성하고 아래 양식에 맞게 내용을 채워 넣습니다.
(이 파일은 `.gitignore`에 등록되어 있어 GitHub에 절대 업로드되지 않으니 안심하세요!)
```env
GEMINI_API_KEY="여기에_발급받은_API_키를_넣으세요"
SENDER_EMAIL="본인_이메일@gmail.com"
SENDER_PASSWORD="앱_비밀번호_16자리"
RECEIVER_EMAIL="수신할_이메일_주소@naver.com"
```

### 2. 가상환경 활성화 및 패키지 설치
```bash
python -m venv venv
# Windows
.\venv\Scripts\Activate.ps1
# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 디버그 모드로 스크립트 실행
터미널에서 아래 명령어를 실행합니다.
```bash
python main.py --debug
```
- **기능**: `--debug` 옵션을 주면 번거로운 이메일 발송과 PDF 변환 작업을 생략합니다.
- **결과**: 대신 터미널 화면에 시원하게 Markdown 텍스트로 보고서를 즉시 출력해주며, 동일 폴더 내에 `debug_report_오늘날짜.md` 파일로도 저장해 줍니다. 프롬프트를 수정하거나 테스트할 때 매우 유용합니다.
