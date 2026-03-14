import os
import sys
import datetime
import yfinance as yf
import feedparser
import pandas_market_calendars as mcal
import pytz
import google.generativeai as genai
import markdown
import pdfkit
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

def check_market_open():
    """
    오늘(미국 시간 기준)이 미국 증시 개장일인지 확인합니다.
    """
    tz = pytz.timezone('America/New_York')
    # 현재 한국시간 아침 6시 30분경 실행된다면, 미국은 전날 오후 4시 30분경임
    # 정확한 판별을 위해 현재 뉴욕 시간 기준 날짜를 가져옴
    now_ny = datetime.datetime.now(tz)
    today_str = now_ny.strftime('%Y-%m-%d')
    
    nyse = mcal.get_calendar('NYSE')
    # 오늘이 개장일인지 확인
    schedule = nyse.schedule(start_date=today_str, end_date=today_str)
    
    if schedule.empty:
        # GitHub Actions 환경변수를 확인하여 수동 실행 여부 판단
        # github event name에 공백 등이 붙어있을 수 있으므로 strip 처리
        event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
        is_manual = (event_name == "workflow_dispatch") or not os.environ.get("GITHUB_ACTIONS")
        
        if is_manual:
            # 과거 10일 중 마지막 개장일을 찾음
            past_date = (now_ny - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
            valid_days = nyse.valid_days(start_date=past_date, end_date=today_str)
            if len(valid_days) > 0:
                last_open_date = valid_days[-1].strftime('%Y-%m-%d')
                print(f"[{today_str}] 휴장일이지만 수동 실행이므로 직전 개장일({last_open_date}) 기준으로 리포트를 작성합니다.")
                return True, last_open_date
                
        print(f"[{today_str}] 미국 증시 휴장일입니다.")
        return False, today_str
    
    print(f"[{today_str}] 미국 증시 정상 개장일입니다.")
    return True, today_str

def fetch_market_data():
    """
    yfinance를 사용하여 주요 지표들의 종가와 등락률을 스크래핑합니다.
    """
    tickers = {
        '다우존스': '^DJI',
        'S&P 500': '^GSPC',
        '나스닥': '^IXIC',
        '10년물 국채': '^TNX',
        '금': 'GC=F',
        '원/달러 환율': 'KRW=X'
    }
    
    data_summary = {}
    
    for name, ticker in tickers.items():
        try:
            t = yf.Ticker(ticker)
            # 최근 2일 데이터 가져오기 (전일 대비 등락률 계산 위함)
            hist = t.history(period='5d')
            if len(hist) >= 2:
                current_price = hist['Close'].iloc[-1]
                prev_price = hist['Close'].iloc[-2]
                change_pct = ((current_price - prev_price) / prev_price) * 100
                
                # 포맷팅
                if name in ['10년물 국채', '원/달러 환율']:
                    data_summary[name] = f"{current_price:.3f} (전일대비 {change_pct:+.2f}%)"
                else:
                    data_summary[name] = f"{current_price:,.2f} (전일대비 {change_pct:+.2f}%)"
            else:
                 data_summary[name] = "데이터 부족"
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            data_summary[name] = "수집 실패"
            
    return data_summary

def fetch_news():
    """
    주요 매체의 RSS 피드를 통해 최근 기사 5개를 수집합니다.
    """
    # Yahoo Finance Top News RSS
    rss_url = "https://finance.yahoo.com/rss/topstories"
    feed = feedparser.parse(rss_url)
    
    news_items = []
    
    # 상위 5개 기사만 추출
    for entry in feed.entries[:5]:
        news_items.append({
            'title': entry.title,
            'link': entry.link,
            # 'summary': entry.summary if hasattr(entry, 'summary') else ''
        })
        
    return news_items

def generate_report(market_data, news_data, today_str):
    """
    수집된 정확한 데이터를 제미나이 프롬프트에 주입하여 보고서를 생성합니다.
    """
    # 제미나이 API 키 설정 (GitHub Actions Secrets에서 가져옴)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
        return "보고서 생성 실패: API 키 누락"
        
    genai.configure(api_key=api_key)
    
    # 모델 설정 (최신 gemini-1.5-pro 사용)
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    # 프롬프트 구성
    market_text = "\n".join([f"- {k}: {v}" for k, v in market_data.items()])
    news_text = "\n".join([f"- {n['title']} ({n['link']})" for n in news_data])
    
    prompt = f"""
    너는 월스트리트의 수석 시황 분석가이자, 나의 개인 은퇴 자산 관리 비서야.
    다음 제공된 **정확한 실제 데이터**만을 바탕으로 '일일 시황 보고서'를 작성해줘. 
    (절대 임의로 수치를 지어내지 말고, 제공된 데이터만 사용할 것!)
    
    [실제 시장 데이터]
    {market_text}
    
    [오늘의 주요 기사]
    {news_text}
    
    아래 양식에 맞춰서 Markdown 형식으로 작성해줘:
    
    # [{today_str}] 미국 증시 마감시황 보고서
    
    ## [1. 시장요약]
    (제공된 시장 데이터를 바탕으로 핵심 요약)
    
    ## [2. 오늘의 시장 하이라이트]
    (제공된 주요 기사 5개를 종합 분석)
    
    ## [3. 오늘의 투자 인사이트]
    (전략 요약 및 단기 제언)
    
    ## [4. 오늘의 한마디]
    (멘탈 관리 멘트)
    
    ## [5. 참고자료]
    (기사 제목과 링크 리스트)
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"제미나이 API 호출 중 에러 발생: {e}")
        return f"보고서 생성 에러: {e}"

def create_pdf(markdown_text, output_filename="report.pdf"):
    """
    Markdown 텍스트를 HTML로 변환한 후 PDF 파일로 저장합니다.
    """
    try:
        html_content = markdown.markdown(markdown_text, extensions=['tables', 'fenced_code'])
        
        # 간단한 CSS 추가 (인코딩 명시 포함)
        styled_html = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; line-height: 1.6; color: #333; padding: 20px; }}
                h1 {{ color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 5px; }}
                h2 {{ color: #202124; margin-top: 20px; border-bottom: 1px solid #ddd; padding-bottom: 3px; }}
                ul {{ margin-bottom: 15px; }}
                li {{ margin-bottom: 5px; }}
                a {{ color: #1a73e8; text-decoration: none; }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
        
        # Windows 로컬 테스트용 경로(wkhtmltopdf 설치 필요) 또는 GitHub Actions 리눅스 기본 경로
        # 보통 Linux(GitHub Actions)에서는 pdfkit이 wkhtmltopdf를 자동 인식하므로 기본 설정 사용
        options = {
            'encoding': "UTF-8",
            'no-outline': None
        }
        
        try:
            pdfkit.from_string(styled_html, output_filename, options=options)
            print(f"PDF 파일 생성 완료: {output_filename}")
            return True
        except Exception as e:
            print(f"PDF 변환 에러 (wkhtmltopdf가 설치되어 있는지 확인): {e}")
            return False
            
    except Exception as e:
        print(f"문서 처리 중 에러 발생: {e}")
        return False

def send_email(subject, body, attachment_path=None):
    """
    지정된 이메일로 메일을 발송합니다.
    """
    sender_email = os.environ.get("SENDER_EMAIL")
    sender_password = os.environ.get("SENDER_PASSWORD")
    receiver_email = os.environ.get("RECEIVER_EMAIL")
    
    if not all([sender_email, sender_password, receiver_email]):
        print("이메일 발송 실패: 환경변수(SENDER_EMAIL, SENDER_PASSWORD, RECEIVER_EMAIL) 누락")
        return False
        
    msg = MIMEMultipart()
    msg['From'] = sender_email or ""
    msg['To'] = receiver_email or ""
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(
                f.read(),
                Name=os.path.basename(attachment_path)
            )
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
        msg.attach(part)
        
    try:
        # Gmail SMTP 서버 설정 (앱 비밀번호 필요)
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email or "", sender_password or "")
        server.send_message(msg)
        server.quit()
        print(f"이메일 발송 성공: {receiver_email}")
        return True
    except Exception as e:
        print(f"이메일 발송 에러: {e}")
        return False

if __name__ == "__main__":
    is_open, today_str = check_market_open()
    
    if not is_open:
        print("휴장일이므로 프로세스를 종료합니다. (필요시 알림 메일 발송 로직 추가)")
        send_email(
            subject=f"[{today_str}] 미국 증시 휴장 안내",
            body="오늘 미국 증시는 휴장입니다. 시황 보고서가 발행되지 않습니다."
        )
        sys.exit(0)
        
    print("시장 데이터 수집 중...")
    market_data = fetch_market_data()
    
    print("\n뉴스 데이터 수집 중...")
    news_data = fetch_news()
    
    print("\n시황 보고서 생성 중 (Gemini)...")
    report_md = generate_report(market_data, news_data, today_str)
    
    print("\nPDF 생성 중...")
    pdf_filename = f"report_{today_str}.pdf"
    is_pdf_created = create_pdf(report_md, pdf_filename)
    
    print("\n이메일 발송 중...")
    if is_pdf_created:
        send_email(
            subject=f"미국 증시 마감시황 보고서 ({today_str})",
            body="오늘의 미국 증시 마감 시황 보고서 PDF가 첨부되었습니다.",
            attachment_path=pdf_filename
        )
    else:
        # PDF 생성 실패 시 텍스트로 대체 전송
        send_email(
            subject=f"미국 증시 마감시황 보고서 ({today_str}) [PDF 오류 - 텍스트 대체]",
            body=report_md
        )


