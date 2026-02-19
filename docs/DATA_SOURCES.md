# 리서치·애널리스트 데이터 출처 정리

직접 브라우저에서 확인할 수 있도록 **어느 페이지에서, 어떤 방식으로** 데이터를 가져오는지 정리했습니다.

---

## 1. Founders Fund (해외 펀드 포트폴리오)

| 항목 | 내용 |
|------|------|
| **URL** | https://foundersfund.com/portfolio/ |
| **방식** | 웹 크롤링 (REST API 아님) |
| **실제 동작** | 페이지 HTML 한 번 받아옴 → 정규식으로 `<h2>...</h2>` 안의 텍스트만 추출 → 회사명 리스트로 사용 |
| **가져오는 것** | 회사명만 (예: SpaceX, Palantir). **본문/PDF/링크 내용은 안 읽음** |
| **코드 위치** | `src/data/founders_fund.py` |

**확인 방법**: 브라우저에서 위 URL 접속 → 페이지에 보이는 회사명들이 그대로 리스트로 쓰인다고 보면 됨.

---

## 2. DART 전자공시 (한국 공시)

| 항목 | 내용 |
|------|------|
| **URL** | https://opendart.fss.or.kr/api/list.json |
| **방식** | **REST API** (공식 Open DART API). 쿼리: `crtfc_key`, `bgn_de`, `end_de`, `page_no`, `page_count` |
| **실제 동작** | 최근 3일 기준으로 공시 **목록**만 조회. JSON 응답에서 `corp_name`, `report_nm`, `stock_code` 등만 사용 |
| **가져오는 것** | 공시 제목·회사명·종목코드. **실제 공시 보고서(PDF/HTML) 내용은 안 가져옴** |
| **필요** | 회원가입 후 발급한 API 키 → `.env`의 `DART_API_KEY` |
| **코드 위치** | `src/data/dart_source.py` |

**확인 방법**:  
- Open DART 회원가입 후 API 신청  
- 문서: https://opendart.fss.or.kr/guide/main.do  
- 위 URL에 키와 날짜 넣어서 호출하면 “목록” JSON만 받는 구조임.

---

## 3. Finviz (해외 뉴스)

| 항목 | 내용 |
|------|------|
| **URL** | https://finviz.com/rss/news.ashx |
| **방식** | **RSS 2.0** (XML). `feedparser` 또는 `xml.etree`로 파싱 |
| **실제 동작** | RSS XML 받아서 `<item>`의 `<title>`, `<description>`, `<link>`만 추출 |
| **가져오는 것** | 제목 + 요약(description) + 링크. **기사 본문이나 링크 안의 페이지는 안 읽음** |
| **코드 위치** | `src/data/rss_sources.py` → `fetch_finviz_news()` |

**확인 방법**: 브라우저에서 위 URL 접속 → XML에 보이는 title/description/link가 그대로 사용됨.

---

## 4. Seeking Alpha (해외 주식 아이디어)

| 항목 | 내용 |
|------|------|
| **URL** | https://seekingalpha.com/stock-ideas.xml |
| **방식** | **RSS 2.0** (XML). Finviz와 동일하게 파싱 |
| **실제 동작** | RSS XML에서 title, summary, link만 추출 |
| **가져오는 것** | 제목 + 요약 + 링크. **기사 전문/PDF는 안 읽음** |
| **코드 위치** | `src/data/rss_sources.py` → `fetch_seeking_alpha()` |

**확인 방법**: 위 URL 접속 → XML 내용이 곧 우리가 쓰는 데이터.

---

## 5. 네이버 경제 뉴스

| 항목 | 내용 |
|------|------|
| **URL** | https://news.naver.com/main/rss/rss.naver?sid1=101 |
| **방식** | **RSS 2.0** (XML). 동일 파싱 |
| **실제 동작** | RSS에서 title, description, link만 추출 |
| **가져오는 것** | 제목 + 요약 + 링크. **뉴스 본문은 안 읽음** |
| **코드 위치** | `src/data/rss_sources.py` → `fetch_naver_economy()` |

**확인 방법**: 위 URL 접속 → 보이는 XML이 수집 대상.

---

## 6. 키움증권 리서치

| 항목 | 내용 |
|------|------|
| **URL** | https://www.kiwoom.com/h/invest/research/VMarketIMView |
| **방식** | **웹 크롤링** (REST API 아님). 페이지 HTML 한 번 받아옴 |
| **실제 동작** | HTML에서 정규식으로 `<a href="...">텍스트</a>` 찾기.  
  조건: `href`에 "research" 포함 **또는** 텍스트에 "리포트", "추천", "종목" 포함 → 그때만 제목·링크 저장 |
| **가져오는 것** | **제목 + 링크 URL만**. 요약(summary)은 비움.  
  **해당 링크가 PDF든 웹이든, 그 안의 내용(리포트 본문/PDF)은 전혀 안 읽음** |
| **코드 위치** | `src/data/kiwoom_research.py` (크롤링) → `src/data/rss_sources.py`의 `fetch_kiwoom_research()`에서 호출 |

**확인 방법**:  
1. 브라우저에서 위 URL 접속.  
2. 페이지가 JavaScript로 리스트를 그리면, 우리가 받는 HTML에는 리스트가 없을 수 있어서 **실제로는 0건일 수 있음**.  
3. 페이지 소스 보기(Ctrl+U)에서 `<a href="..."` 중에 "research" 또는 "리포트"/"추천"/"종목" 들어간 것만 우리가 쓰는 후보.

---

## 7. “Top 10 핫한 애널리스트” (RSS + Gemini)

| 항목 | 내용 |
|------|------|
| **데이터 출처** | 위 3~6번 **전부** (Finviz, Seeking Alpha, 네이버 경제, 키움 리서치)를 합친 RSS 항목들 |
| **방식** | 각 항목마다 `[출처] 제목 \| 요약 200자` 문자열 만들고 → **Gemini API 한 번 호출**해서 “추천/위험” 등으로 분류·요약 |
| **가져오는 것** | 원본은 **RSS의 제목+요약만**. 기사/리포트 본문이나 PDF는 계속 **안 읽음** |

---

## 요약 표

| 출처 | URL | 방식 | 실제 읽는 것 |
|------|-----|------|----------------|
| Founders Fund | foundersfund.com/portfolio/ | HTML 크롤링 | `<h2>` 회사명만 |
| DART | opendart.fss.or.kr/api/list.json | REST API | 공시 **목록** (제목·회사명·종목코드) |
| Finviz | finviz.com/rss/news.ashx | RSS XML | title + description + link |
| Seeking Alpha | seekingalpha.com/stock-ideas.xml | RSS XML | title + summary + link |
| 네이버 경제 | news.naver.com/.../rss.naver?sid1=101 | RSS XML | title + description + link |
| 키움 리서치 | kiwoom.com/.../VMarketIMView | HTML 크롤링 | 제목+링크만 (본문/PDF 미수집) |

**공통**:  
- **리포트/기사 본문, PDF, 링크 안 페이지 내용은 어디에서도 수집·분석하지 않습니다.**  
- “제대로 읽어오는지” 확인하시려면 위 URL들을 브라우저/API 문서대로 직접 열어보시면 됩니다.
