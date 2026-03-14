import os
import sys
import datetime
import yfinance as yf
import feedparser
import pandas_market_calendars as mcal
import pytz
from google import genai
import markdown
import pdfkit
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

# 로컬 환경의 .env 파일에서 환경변수 불러오기 (GitHub Actions에서는 무시됨)
load_dotenv()

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
        # 매체명 파싱 노하우 (야후 RSS의 경우 source 태그에 주로 있음, 없으면 기본값)
        source_name = entry.source.title if hasattr(entry, 'source') else 'Yahoo Finance'
        
        news_items.append({
            'source': source_name,
            'title': entry.title,
            'link': entry.link,
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
        
    # 구글 최신 라이브러리 (google-genai) 클라이언트 생성
    client = genai.Client(api_key=api_key)
    
    # 시간 텍스트 생성
    kst = pytz.timezone('Asia/Seoul')
    est = pytz.timezone('America/New_York')
    now_utc = datetime.datetime.now(pytz.utc)
    
    time_kst = now_utc.astimezone(kst).strftime('%Y-%m-%d %H:%M:%S KST')
    time_est = now_utc.astimezone(est).strftime('%Y-%m-%d %H:%M:%S EST')
    
    # 프롬프트 구성
    market_text = "\n".join([f"- {k}: {v}" for k, v in market_data.items()])
    news_text = "\n".join([f"- [{n['source']}] {n['title']} (URL: {n['link']})" for n in news_data])
    
    prompt = f"""
    너는 월스트리트의 수석 시황 분석가이자, 나의 개인 은퇴 자산 관리 비서야.
    다음 제공된 **정확한 실제 데이터**만을 바탕으로 지정된 '7가지 형식'에 맞춰 시황 보고서를 작성해줘. 
    (절대 임의로 수치를 지어내지 말고, 제공된 데이터만 사용할 것!)
    
    [실제 시장 데이터]
    {market_text}
    
    [오늘의 주요 기사 피드]
    {news_text}
    
    아래 양식에 맞춰서 정확히 Markdown 형식으로 작성해줘:
    
    # {today_str} 미국 증시 마감시황 보고서
    
    **[보고서 헤더]**
    * 작성 시점: {time_kst}
    * 데이터 기준: {time_est} 마감 기준
    
    ## [1. 시장요약]
    (제공된 3대 지수 종가/변동률, 10년물 국채 금리, 금, 환율 등 수치를 정확히 나열하고 등락 원인을 요약)
    
    ## [2. 오늘의 시장 하이라이트]
    (제공된 {len(news_data)}개 기사를 종합 분석하여 오늘 시장의 핵심 흐름과 분위기를 서술)
    
    ## [3. 섹터별 이슈]
    (주요 기사 내용으로 미루어보아 AI, 반도체, 에너지, 로봇 중 특이 동향이 있는 섹터가 있다면 짚어주고 관련 전문가 또는 시장 반응 서술)
    
    ## [4. 내일의 일정]
    (오늘의 흐름을 바탕으로 단기적으로 시장이 주목할 만한 주요 지표 발표나 실적 일정이 예상된다면 간략히 브리핑. 특정 데이터가 없다면 '향후 주목할 점'으로 대체 가능)
    
    ## [5. 오늘의 투자 인사이트]
    (기사별 전략 요약 및 이를 종합한 단기적인 투자 제언)
    
    ## [6. 오늘의 한마디]
    (투자자의 멘탈 관리를 위한 힘이 되는 조언 또는 격언)
    
    ## [7. 참고자료]
    (제공된 기사의 매체명, 제목, URL을 반드시 누락 없이 모두 리스트업)
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
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
    is_debug = "--debug" in sys.argv
    
    is_open, today_str = check_market_open()
    
    if not is_open:
        print("휴장일이므로 프로세스를 종료합니다. (필요시 알림 메일 발송 로직 추가)")
        if not is_debug:
            send_email(
                subject=f"[{today_str}] 미국 증시 휴장 안내",
                body="오늘 미국 증시는 휴장입니다. 시황 보고서가 발행되지 않습니다."
            )
        else:
            print("[DEBUG] 휴장일 알림 메일 발송 생략")
        sys.exit(0)
        
    print("시장 데이터 수집 중...")
    market_data = fetch_market_data()
    
    print("\n뉴스 데이터 수집 중...")
    news_data = fetch_news()
    
    print("\n시황 보고서 생성 중 (Gemini)...")
    report_md = generate_report(market_data, news_data, today_str)
    
    if is_debug:
        print("\n" + "="*50)
        print("[DEBUG] 생성된 리포트 (Markdown)")
        print("="*50)
        print(report_md)
        print("="*50)
        
        # 파일로도 저장해서 편하게 볼 수 있게 함
        debug_filename = f"debug_report_{today_str}.md"
        with open(debug_filename, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"\n[DEBUG] 리포트를 {debug_filename} 파일로 저장했습니다.")
        print("[DEBUG] 디버그 모드이므로 PDF 변환 및 이메일 발송 작업을 생략하고 마칩니다.")
        sys.exit(0)
    
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


