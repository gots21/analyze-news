import OpenDartReader
from google import genai
import urllib.request
import urllib.parse
import json
import time
import re
import sys
import os
from datetime import datetime
import yfinance as yf

# 0. 환경 설정
DART_KEY = '404b9d03b607c3e08b6e815ae12b4a3a31226177'
GEMINI_KEY = 'AIzaSyD_JWG9LPrwuH4vvBkCyZ95H07nSUvEhek'
NAVER_ID = 'UJDYIqP9J6qH36B9rR4c'
NAVER_SECRET = 'lLONMXN69W'

MODEL_ID = "gemma-4-26b-a4b-it"
client = genai.Client(api_key=GEMINI_KEY)
dart = OpenDartReader(DART_KEY)

def get_performance_price_trend(corp_name, stock_code):
    try:
        current_year = datetime.now().year
        # 1. DART에서 최근 3개년 결산 데이터 추출
        df_annual = dart.finstate(corp_name, current_year - 1)
        
        # 2. 거래소(KS/KQ) 확인 및 티커 설정 (폴백 구조 적용)
        ticker = yf.Ticker(f"{stock_code}.KS")
        if ticker.history(period="1d").empty:
            ticker = yf.Ticker(f"{stock_code}.KQ")
            
        trend_summary = f"\n[3개년 실적 및 주가 동향 연동]"
        
        if df_annual is not None and not df_annual.empty:
            # 매출액과 영업이익 행 추출
            rev_row = df_annual[df_annual['account_nm'].str.contains('매출액', na=False)]
            op_row = df_annual[df_annual['account_nm'].str.contains('영업이익', na=False)]
            
            # 데이터 누락 시 에러 방지
            if rev_row.empty or op_row.empty:
                return "\n[트렌드 분석 데이터 수집 실패]: 주요 계정(매출/영업이익) 누락"
                
            rev_row = rev_row.iloc[0]
            op_row = op_row.iloc[0]
            
            years = [current_year-3, current_year-2, current_year-1]
            amounts = {
                years[0]: (int(rev_row['bfrmtrm_amount']), int(op_row['bfrmtrm_amount'])),
                years[1]: (int(rev_row['frmtrm_amount']), int(op_row['frmtrm_amount'])),
                years[2]: (int(rev_row['thstrm_amount']), int(op_row['thstrm_amount']))
            }

            for yr in years:
                # 해당 연도 마지막 거래일 근처 주가 가져오기
                price_hist = ticker.history(start=f"{yr}-12-20", end=f"{yr}-12-31")
                end_price = int(price_hist['Close'].iloc[-1]) if not price_hist.empty else 0
                
                rev, op = amounts[yr]
                trend_summary += (
                    f"\n- {yr}년 말: 매출 {rev/1e8:,.0f}억 / 영업익 {op/1e8:,.0f}억 / "
                    f"기말 주가 {end_price:,}원"
                )
                
            return trend_summary
    except Exception as e:
        return f"\n[트렌드 분석 데이터 수집 실패]: {e}"
    return ""

def get_market_and_finance_data(stock_code):
    if not stock_code: 
        return "\n[실시간 시장 데이터] 비상장 기업이거나 종목코드 없음."
        
    try:
        ticker = yf.Ticker(f"{stock_code}.KS")
        hist = ticker.history(period="1d")
        if hist.empty:
            ticker = yf.Ticker(f"{stock_code}.KQ")
            hist = ticker.history(period="1d")
            
        if not hist.empty:
            price = int(hist['Close'].iloc[-1])
            info = ticker.fast_info
            # fast_info는 dict가 아니라 속성 접근 방식임
            try:
                mcap = info.market_cap / 100000000
            except:
                mcap = 0
            
            # 시총 0원 방지 보루
            if mcap == 0:
                return f"\n[실시간 시장/재무 데이터]\n- 현재 주가: {price:,}원\n- 시가총액: [데이터 누락/추가 확인 필요]"
            
            return f"\n[실시간 시장/재무 데이터]\n- 현재 주가: {price:,}원\n- 시가총액: 약 {int(mcap):,}억 원"
    except Exception as e:
        return f"\n[실시간 시장 데이터 수집 실패]: {e}"
    return ""

def get_dart_business_content(corp_name):
    stock_code = ""
    try:
        corp_codes = dart.corp_codes
        matched = corp_codes[corp_codes['corp_name'] == corp_name]
        
        if matched.empty:
            matched = corp_codes[corp_codes['corp_name'].str.contains(corp_name, na=False)]
            matched = matched[matched['stock_code'].str.strip() != '']
            
        if matched.empty:
            print(f"⚠️ DART 마스터 리스트에서 '{corp_name}'을 찾을 수 없음.")
            return None, ""  # 💡 빈 문자열로 튜플 짝맞추기
            
        corp_code = matched.iloc[0]['corp_code']
        official_name = matched.iloc[0]['corp_name']
        stock_code = matched.iloc[0]['stock_code'].strip().replace('$', '')
        print(f"✅ 종목코드 확인: {official_name} (DART 고유번호: {corp_code}, 종목코드: {stock_code})")

        start_year = datetime.now().year - 2
        start_date = f"{start_year}0101"
        df = dart.list(corp_code, start=start_date)
        
        if df is None or df.empty or (isinstance(df, dict) and df.get('status') == '013'):
            return None, stock_code  # 💡 튜플 통일
            
        report_df = df[df['report_nm'].str.contains('사업보고서|반기보고서|분기보고서')]
        if not report_df.empty:
            target_rcept_no = report_df.iloc[0]['rcept_no']
            target_report_nm = report_df.iloc[0]['report_nm']
        else:
            target_rcept_no = df.iloc[0]['rcept_no']
            target_report_nm = df.iloc[0]['report_nm']
            
        print(f"🔍 공시 확보: {target_report_nm} (접수번호: {target_rcept_no})")
        
        doc = dart.document(target_rcept_no)
        clean = re.sub(r'<[^>]+>', '', doc)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        key_sections = []
        for keyword in ["주요 제품", "매출 및 수주", "연구개발활동", "사업의 개요"]:
            idx = clean.find(keyword)
            if idx != -1 and idx < len(clean) - 500: 
                key_sections.append(clean[idx:idx+1500]) 
                
        if key_sections:
            clean = " ".join(key_sections)
        else:
            start_idx = clean.find('사업의 내용')
            clean = clean[start_idx:] if start_idx != -1 else clean[2000:]
            
        if len(clean) < 500:
            print("⚠️ 공시 본문 내용이 너무 짧아 뉴스 분석으로 대체합니다.")
            return None, stock_code  # 💡 튜플 통일
            
        return clean[:3000], stock_code
        
    except Exception as e:
        print(f"⚠️ DART 검색 중 에러 발생: {e}")
        return None, stock_code  # 💡 튜플 통일

def get_naver_news(query, display=5, sort='sim'):
    encText = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={encText}&display={display}&sort={sort}"
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", NAVER_ID)
    req.add_header("X-Naver-Client-Secret", NAVER_SECRET)
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read().decode('utf-8'))['items']
    except: return []

# 💡 model 파라미터 추가
def run_agent(prompt, max_retries=5, target_model=MODEL_ID):
    for attempt in range(max_retries):
        try:
            res = client.models.generate_content(model=target_model, contents=prompt)
            return res.text.strip()
        except Exception as e:
            if '503' in str(e) or '429' in str(e):
                time.sleep(2 ** attempt)
            else: return None
    return None

def parse_queries_with_score(raw_text, target_corp):
    RELEVANCE_MAP = {3: 10, 2: 5, 1: 2}
    parsed = []
    
    # 줄바꿈 기준으로 쪼개기
    lines = raw_text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # 1. LLM이 맘대로 붙인 '1. ', '- ', '*' 같은 글머리 기호 싹 청소
        line = re.sub(r'^[\d\.\-\*\s]+', '', line)
        
        # 2. 파이프(|) 기준으로 키워드와 점수 분리 (뒤에서부터 찾기)
        if '|' in line:
            parts = line.rsplit('|', 1)
            query = parts[0].strip().strip('"').strip("'")
            try:
                # 점수 부분에 글자가 섞여 있어도 숫자만 쏙 빼옴
                score = int(re.sub(r'\D', '', parts[1]))
                if score not in [1, 2, 3]: score = 2
            except:
                score = 2
        else:
            # 파이프를 빼먹었을 경우 최후의 수단
            query = line.strip().strip('"').strip("'")
            score = 2 
            
        if len(query) >= 2:
            # 💡 대상 기업명이 없으면 강제로 붙임
            if target_corp not in query:
                query = f"{target_corp} {query}"
            
            parsed.append((query, RELEVANCE_MAP.get(score, 5), score))
            
    return parsed

# 💡 [개선] 뉴스 텍스트와 원본 URL을 함께 저장하는 구조
def fetch_and_dedup_news(queries, limit=15):
    pool = []
    for q, display_count, score in sorted(queries, key=lambda x: x[1], reverse=True):
        sort_type = 'date' if score == 3 else 'sim'
        raw_news = get_naver_news(q, display=display_count, sort=sort_type)
        for n in raw_news:
            clean_title = n['title'].replace('<b>','').replace('</b>','')
            clean_desc = n['description'].replace('<b>','').replace('</b>','')
            pool.append({
                "title": clean_title,
                "content": f"{clean_title}: {clean_desc}",
                "url": n['link']  # 💡 원본 뉴스 링크 보존
            })
    
    seen_urls = set()
    deduped = []
    for item in pool:
        if item['url'] not in seen_urls:
            seen_urls.add(item['url'])
            deduped.append(item)
    return deduped[:limit]

def generate_dynamic_experts(corp_name, sectors, business_report):
    # 💡 공시 핵심 내용 500자 추가
    prompt = f"""기업명: {corp_name}
    사업분야: {sectors}
    공시 핵심 내용: {business_report[:500] if business_report else '없음'}

    이 기업의 핵심 사업을 가장 깊이 이해하는 실무 전문가 1명을 JSON [{{"name":"..","persona":".."}}] 형식으로만 추천해.
    전문가 이름은 실제 인물 이름이 아닌 역할명으로 작성해 (예: 'IT 서비스 전략 애널리스트')"""
    raw = run_agent(prompt)
    try:
        clean_raw = raw.replace("```json", "").replace("```", "").strip()
        experts = json.loads(clean_raw)
        return {e['name']: e['persona'] for e in experts}
    except: return {
    f"{corp_name} 산업 분석가": 
    f"{corp_name}의 핵심 사업 경쟁력, 시장 점유율, 주요 제품/서비스의 성장성을 분석하는 전문가."
}

# --- 실행부 ---
target_corp = "삼성에스디에스"

insights_log = []
used_experts = []

print(f"🕵️ [{target_corp}] 에이전트 심층 분석 시작...")

business_report, stock_code = get_dart_business_content(target_corp)
if business_report:
    print("📄 공시 데이터 확보 완료. 본문 기반 분석 병행.")
else:
    print("⚠️ 공시 데이터 없음. 실시간 뉴스 데이터 중심으로 분석 진행.")
    business_report = "해당 기업의 최신 공시 데이터를 찾을 수 없어 실시간 뉴스 정보를 바탕으로 분석함."

# 💡 실시간 주가 및 재무 지표 병합
market_data = get_market_and_finance_data(stock_code)
trend_data = get_performance_price_trend(target_corp, stock_code)
business_report = market_data + "\n" + trend_data + "\n" + business_report

sectors_raw = run_agent(f"'{target_corp}' 주요 사업 3개 콤마 구분 출력.")
sectors = [s.strip() for s in sectors_raw.split(',')] if sectors_raw else ["바이오"]

# 💡 클로드의 안전장치 적용
sector_name = sectors[0] if sectors else "핵심 사업"

BASE_EXPERTS = {
    "산업 거시경제": f"매크로 지표가 '{target_corp}' 및 {sector_name} 산업(수출, 소비심리)에 미치는 영향을 분석하는 전문가.",
    "재무/밸류에이션": (
        f"'{target_corp}'의 분기 실적, 재무지표, 영업현금흐름(OCF), CAPEX 투자 부담, 그리고 현재 주가 밸류에이션(PER/PBR)의 적정성을 분석하는 재무 전문가."
        f"'{target_corp}'의 3개년 실적 추이와 주가 동향의 상관관계를 분석하는 전문가. 현재에서 4년 이전의 재무 지표 관련 기사는 검색에서 제외해"
        f"실적과 주가가 따로 노는 '디커플링' 구간이 있는지, 있다면 그 이유(신작 기대감, 매크로 등)를 뉴스 데이터와 연동해서 밝혀내라."
    ),
    "비평가": (
        f"{target_corp}의 비즈니스 모델 지속성과 수익 구조의 구조적 취약점을 집중 분석하는 전문가. "
        f"긍정적 뉴스에 반드시 반론을 제시하고, 시장이 간과하는 리스크를 발굴한다. "
        f"특히 현재 수익 모델의 지속 가능성(예: 패키지 게임의 출시 후 매출 급감 곡선, "
        f"구독/라이브 서비스 전환 가능성과 그 비용)을 냉정하게 분석하고 "
        f"경쟁사 위협, 산업 구조적 변화를 파헤친다."
    )
}

print("🧠 동적 전문가 페르소나 섭외 중...")
dynamic_experts = generate_dynamic_experts(target_corp, sectors, business_report)
ALL_EXPERTS = {**BASE_EXPERTS, **dynamic_experts}
# 💡 전문가 풀 출력 복구
print(f"✅ 투입 확정 전문가: {list(ALL_EXPERTS.keys())}")

step1_prompt = f"""
대상 기업: {target_corp}
공시 핵심 본문: {business_report[:1000]}
사업 분야: {sectors}

위 공시 데이터를 읽고 네이버 뉴스 검색어 5개를 무조건 꽉 채워서 만들어. 

[출력 절대 규칙]
1. '사업보고서', '주소지', '대표이사' 등 행정 단어 절대 금지. 신작, 파이프라인, 본업 위주로 작성.
2. 무조건 '{target_corp} '로 시작해.
3. 💡 반드시 줄바꿈(Enter)으로 구분해서 딱 5줄만 출력해. 번호(1. 2.) 붙이지 마.
4. 각 줄의 끝에는 '|관련도(1~3)'을 붙여. (예: {target_corp} 붉은사막 해외 매출|3)
"""
step1_res = run_agent(step1_prompt)
base_queries = parse_queries_with_score(step1_res, target_corp)
# 💡 1차 검색어 출력 복구
print(f"✅ [1차 검색어]: {[q[0] for q in base_queries]}")

base_news_pool = fetch_and_dedup_news(base_queries)
insights_log.append({"step": "초기 세팅", "data": business_report[:500], "news": base_news_pool})
current_context = f"공시: {business_report[:500]}\n뉴스: {[n['content'] for n in base_news_pool[:3]]}"

for loop in range(len(ALL_EXPERTS)):
    print(f"\n🔄 [루프 {loop+1}/{len(ALL_EXPERTS)}] 리서치 중...")
    available = {k: v for k, v in ALL_EXPERTS.items() if k not in used_experts}
    if not available: break
    if loop == 0 and "재무/밸류에이션" in available:
        selected_sector = "재무/밸류에이션"
    else:
        router_prompt = f"""
        [이전 분석 요약]: {current_context[:500]}
        [대기 중인 전문가]: {list(available.keys())}
    
        위 컨텍스트를 보고 추가 분석이 필요한 전문가 1명의 이름만 출력해.
    
        [선택 규칙]
        1. '비평가' 전문가도 필수 투입.
        2. 비평가 분석이 끝났고 추가 분석 불필요 시 STOP.
        """
        selected_sector = run_agent(router_prompt)

    if not selected_sector or 'STOP' in selected_sector.upper(): 
        print("🛑 [라우터] 리서치 조기 종료.")
        break
    
    matched = next((k for k in available if k in selected_sector), list(available.keys())[0])
    used_experts.append(matched)
    
    expert_persona = ALL_EXPERTS[matched]
    print(f"🧙 [소환] {matched}")
    
    q_raw = run_agent(f"""
    페르소나: {expert_persona}
    분석 대상 기업: {target_corp}
    주요 사업 분야: {sectors}
    컨텍스트: {current_context}
    
    위 내용을 바탕으로, 오직 네 전문 분야 관점에서 '{target_corp}'의 핵심 사업({sectors})과 관련된 심층 추적 검색어 3개를 만들어.
    
    [출력 절대 규칙]
    1. 대상 기업의 주요 사업({sectors})과 직접적인 관련이 없는 타 산업 생태계 키워드(예: 분석 대상이 게임/엔터인데 반도체나 에너지 매크로를 언급하는 등)는 절대 금지.
    2. 반드시 네이버 검색이 가능하도록 '한글'로 작성해.
    3. 반드시 모든 검색어는 '{target_corp} '로 시작해야 해. (예: {target_corp} 신작 게임 매출)
    4. '키워드|관련도(1~3)' 형식으로 3줄 작성해. 다른 설명 절대 금지.
    """)

    expert_queries = parse_queries_with_score(q_raw, target_corp)
    
    # 💡 클로드의 예방주사 적용: 빈 리스트면 1차 뉴스(base_news) 재활용
    if expert_queries:
        print(f"✅ [{matched} 타겟 검색어]: {[q[0] for q in expert_queries]}")
        expert_news = fetch_and_dedup_news(expert_queries)
    else:
        print(f"⚠️ [{matched}] 검색어 파싱 실패. 1차 기본 뉴스 풀로 폴백 진행.")
        expert_news = base_news_pool
    
    # 💡 뉴스 분석 시 URL 구조 명확히 전달
    news_context = "\n".join([f"뉴스[{i+1}]: {n['content']} (URL: {n['url']})" for i, n in enumerate(expert_news)])
    analysis = run_agent(f"페르소나: {ALL_EXPERTS[matched]}\n{news_context}\n위 뉴스를 바탕으로 핵심 인사이트 분석.")

    # 💡 로그에 구조화된 데이터 저장
    insights_log.append({
        "expert": matched,
        "news": expert_news, # [{"title":.., "url":..}, ...]
        "analysis": analysis
    })
    current_context = analysis

# --- 1단계: 수석 전략가의 초안 작성 ---
log_json = json.dumps(insights_log, ensure_ascii=False, indent=2)
final_report_prompt = f"""
너는 30년 경력 수석 투자 전략가야. 아래 로그를 기반으로 반말로 최종 보고서 초안을 작성해.

[데이터 로그]
{log_json}

[인용 및 각주 규칙]
1. 💡 보고서 맨 앞부분(서론 직후)에 반드시 [현재 주가 및 밸류에이션 분석] 섹션을 만들고, 로그에 있는 주가/시가총액/PER/PBR 데이터를 활용해 숫자 기반의 냉철한 분석을 먼저 깔아줘.
2. 💡 [재무-주가 동향 분석] 섹션을 별도로 만들 것. 과거 실적 대비 주가가 선행했는지, 혹은 실적 발표 후 주가가 후행했는지 분석 결과를 반드시 포함해.
3. 시가총액이 0원으로 되어 있다면 절대로 '0원'이라고 적지 말고 외부 검색을 통해 시가 총액을 다시 확인하여 기재하거나 확인할 수 있는 데이터 위주로 꼼꼼하게 분석해라. 예를 들어, "현재 주가는 15,000원으로, 매출과 영업이익이 전년 대비 각각 20%, 50% 증가했어." 이런 식으로 숫자와 함께 명확히 설명해라.
4. 재무 지표나 주가, 투자, 밸류에이션 관련 내용이 있다면 반드시 [현재 주가 및 밸류에이션 분석] 섹션에 구체적으로 서술하라. 예를 들어, "현재 주가는 15,000원으로, 시가총액은 약 1조 원이야. PER은 10배, PBR은 1.5배로, 동종업계 평균보다 저평가된 상태야." 이런 식으로 숫자와 함께 명확히 설명해라.
5. '로그상 0원' 같은 개발자용 멘트는 보고서에 절대 포함하지 마라.
6. 본문 인용 시 제공된 로그의 "news" 배열에 있는 기사에만 [1], [2] 각주를 달아라.
7. 보고서 최하단 [참고 문헌] 섹션에 기사 제목과 URL을 정리해라.
8. 투자 트리거 3개 포함.
9. 기사 제목에 '{target_corp}'가 없어도 삭제하지 마. 판단이 애매한 출처는 제목 뒤에 '⚠️' 표시만 달아.
10. 반드시 [리스크 및 주의사항] 섹션을 포함하고 비평가 관점의 분석 내용(수익 지속성, 구조적 취약점)을 구체적으로 서술하고 긍정적 내용과 균형을 맞춰라.
"""

draft_report = run_agent(final_report_prompt, target_model="gemini-3-flash-preview")

# --- 2단계: 수석 에디터의 팩트 체크 및 출처 세탁 ---
print("🕵️ [팩트 체크] 수석 에디터가 출처 교차 검증 중...")

# 💡 토큰 폭탄 방지: URL 목록만 가볍게 추출
valid_urls = []
for log in insights_log:
    for news in log.get("news", []):
        if isinstance(news, dict) and news.get("url"):
            valid_urls.append({"title": news["title"], "url": news["url"]})

verification_prompt = f"""
너는 피도 눈물도 없는 팩트 체커(수석 에디터)야.
아래 [수집된 실제 뉴스 URL 목록]과 [작성된 초안 보고서]를 비교해서 출처를 엄격하게 검증해.

[수집된 실제 뉴스 URL 목록]
{json.dumps(valid_urls, ensure_ascii=False, indent=2)}

[작성된 초안 보고서]
{draft_report}

[검증 규칙 - 절대 엄수]
1. 초안 보고서의 [참고 문헌]에 있는 모든 기사 제목과 URL이 [수집된 실제 뉴스 URL 목록]에 존재하는지 대조해.
2. 목록에 없는 가짜 URL이나 "(전문가 분석 기반)" 같은 허위 출처는 삭제해.
3. 허위 출처를 참조하던 본문의 각주 번호도 깔끔하게 지워.
4. 확인된 진짜 출처만 남기고 번호를 [1]번부터 다시 매겨.
5. 수정이 끝난 '최종 보고서 전문'만 출력해.
6. 최종 분석 보고서 본문에 미사용된 URL이나 출처는 절대 남기지 마.
"""

# 💡 전역 변수 건드리지 않고 여기서만 가벼운 모델 호출
final_report = run_agent(verification_prompt, target_model="gemini-3-flash-preview")

print("\n" + "★" * 50)
print(final_report if final_report else "보고서 생성 실패")
print("★" * 50)