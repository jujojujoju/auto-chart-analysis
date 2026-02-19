"""Gemini 2.0 Flash API를 활용한 차트 패턴 분석.

10개의 정답 샘플(선호하는 차트 패턴)과 현재 차트를 비교하여
기준에 부합하는 종목 선정.
"""

import json
from pathlib import Path
from typing import Any, Optional

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


# Gemini (무료 티어) - list_models()로 확인된 사용 가능 모델 사용
MODEL_NAME = "gemini-2.5-flash"


def _ensure_genai(api_key: Optional[str]) -> None:
    if not HAS_GENAI:
        raise ImportError("pip install google-generativeai")
    if not api_key:
        raise ValueError("GEMINI_API_KEY가 필요합니다. .env에 설정하세요.")
    genai.configure(api_key=api_key)


# 정답 차트 패턴 설명 (사용자 정의)
PATTERN_DESCRIPTION = """
[찾고자 하는 정답 패턴 - 반드시 이 조건만]
- "하락이나 횡보를 오래 하다가" 갑자기 이평선 정배열이 되려고 팍 튀었다가, 0.3~0.6 수준의 되돌림이 온 뒤 횡보하는 차트.
- 이평선 역배열에서 정배열로 전환하려는 "막 전환 초입" 구간.
- 저점이 높아지는 현상이 최근에 1번 이하로 나타난 차트만 적합 (저점 상승이 여러 번 반복된 이미 확정된 상승 추세는 제외).
- 즉: 오랜 하락/횡보 → 갑자기 튀어오름 → 30~60% 되돌림 후 횡보. 아직 저점 상승이 1회 이하.

[반드시 제외할 패턴 - 이런 종목은 부적합]
- 이미 이평선 정배열이 오래 유지된 종목 (저점이 높아지는 구간이 여러 번 반복된 상승 추세).
- 주가가 이평선과 이격이 많이 벌어진 "강한 상승 중" 종목 (과열 구간).
- 저점이 최근에 2번 이상 연속으로 높아진, 이미 상승 추세가 확정된 종목.
- RSI 70 근처 과매수, 상단 볼린저밴드 근처.
참고: 카카오·네이버·다올투자증권·CJ CGV (2021.7~ 하락/횡보 후 돌파 직후 눌림목).
"""


def load_sample_charts(sample_dir: Path) -> list[dict[str, Any]]:
    """samples/ 에서 정답 샘플 로드. answer_*.json 우선."""
    samples: list[dict[str, Any]] = []
    if not sample_dir.exists():
        return samples

    paths = sorted(sample_dir.glob("answer_*.json"))
    if not paths:
        paths = sorted(sample_dir.glob("*.json"))[:10]
    for path in paths[:10]:
        try:
            with open(path, encoding="utf-8") as f:
                samples.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue

    return samples


def _build_system_prompt(samples: list[dict[str, Any]]) -> str:
    """정답 샘플 + 패턴 설명 기반 시스템 프롬프트."""
    base = """당신은 감정을 배제한 기계적 차트·재무 분석 전문가입니다.
일봉 OHLCV, 이평선(5·20·60), RSI, 볼린저밴드, OBV(거래량) 등 보조지표와 재무제표를 종합해 판단합니다.
""" + PATTERN_DESCRIPTION

    if not samples:
        return base + "\n(정답 샘플이 없으면 위 패턴 설명만으로 판단하세요.)"

    samples_text = "\n\n--- 정답 차트 샘플 (참고용) ---\n"
    for i, s in enumerate(samples[:10], 1):
        sym = s.get("symbol", "?")
        rows = s.get("rows", 0)
        cols = s.get("columns", [])
        samples_text += f"\n[샘플 {i}] {sym} (일수: {rows}, 지표: {cols})"
        ohlcv = s.get("ohlcv", {})
        if ohlcv:
            last = list(ohlcv.values())[-1] if ohlcv else {}
            samples_text += f" 마지막 봉: {last}"

    return base + samples_text


def analyze_with_gemini(
    chart_json: dict[str, Any],
    samples: list[dict[str, Any]],
    api_key: Optional[str],
) -> str:
    """차트 JSON을 Gemini에 전달하여 분석 결과(텍스트) 반환."""
    _ensure_genai(api_key)

    model = genai.GenerativeModel(MODEL_NAME)
    system = _build_system_prompt(samples)

    # 현재 차트 요약 + 재무제표 (전체 전송 시 토큰 제한 고려)
    symbol = chart_json.get("symbol", "?")
    period = chart_json.get("period", "")
    rows = chart_json.get("rows", 0)
    cols = chart_json.get("columns", [])
    ohlcv = chart_json.get("ohlcv", {})
    last_5 = dict(list(ohlcv.items())[-5:]) if len(ohlcv) >= 5 else ohlcv
    financials = chart_json.get("financials_summary", {})

    fin_block = ""
    if financials:
        fin_block = f"""
[재무제표 요약] (최신 연도, 단위: USD)
{json.dumps(financials, ensure_ascii=False, indent=2)}
"""

    user_content = f"""
[현재 분석 대상]
symbol: {symbol}
period: {period}
rows: {rows}
columns: {cols}

최근 5일 봉 데이터:
{json.dumps(last_5, ensure_ascii=False, indent=2)}
{fin_block}
위 차트를 보고, 반드시 [찾고자 하는 정답 패턴]과 [제외할 패턴]을 구분하세요.
이평선 정배열 완성·이격 과대·강한 상승 중인 종목은 반드시 '부적합'입니다. '추세 돌파 직후 눌림목'만 적합.
JSON이나 코드블록 없이, 아래 형식으로만 답하세요 (각 1~2문장, 근거 명확히):

[판정] 적합 또는 부적합
[차트] 기술적 분석 (추세·이평선·거래량·보조지표 근거)
[재무] 재무제표 분석 근거
[종합] 정답 패턴과의 유사성·종합 판단
[권고] 매수 또는 관망 또는 매도
"""
    response = model.generate_content(
        system + "\n\n" + user_content,
        generation_config=genai.types.GenerationConfig(
            temperature=0.2,
            max_output_tokens=1536,
        ),
    )
    return response.text


def analyze_all_charts_single_call(
    compressed_text: str,
    samples: list[dict[str, Any]],
    api_key: Optional[str],
) -> tuple[list[dict], Optional[str]]:
    """전체 차트를 1회 호출로 분석.

    Returns:
        (pattern_matches, api_error_message)
        pattern_matches: [{"symbol","name","chart_reason","reason","action"}, ...]
        api_error_message: RPM/RPD/TPM 등 사용량 제한 오류 시 오류 메시지
    """
    _ensure_genai(api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    system = _build_system_prompt(samples)

    user_content = f"""
[분석 대상 - 아래 각 줄은 정규화된 데이터입니다. 절대 가격이 아니라 이격도·변동률로 표기]
- symbol 이름: C/s20=종가/20일선비율 C/s60=종가/60일선비율 rsi=RSI | 10d_pct=[전일대비 변동률%] 10d_c/s20=[종가/20일선 비율 시계열]
- 1.0 = 이평선 위, 1.05 = 5% 위, 0.95 = 5% 아래. 이격도가 너무 벌어진(예: 1.2 이상) 종목은 부적합.
{compressed_text}

위 모든 종목을 검토하여, [참고 정답 패턴]에 부합하는 종목만 선별하세요.
(하락/횡보 오래 하다가 갑자기 튀었다가 0.3~0.6 되돌림 후 횡보, 저점 상승이 최근 1번 이하인 "역배열→정배열 전환 초입"만 적합. 이미 정배열 오래 유지·이격도 과대·저점 상승 여러 번 반복된 종목은 부적합)

아래 형식으로만 답하세요. 적합 종목이 없으면 "적합 없음"만 출력.

1. symbol | 이름 | 차트 근거 (1~2문장)
2. symbol | 이름 | 차트 근거
...
"""
    try:
        response = model.generate_content(
            system + "\n\n" + user_content,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=8192,
            ),
        )
    except Exception as e:
        err = str(e).strip()
        if any(k in err.lower() for k in ("rate", "resource_exhausted", "429", "rpm", "rpd", "tpm", "quota")):
            return [], "Gemini API 사용량 제한(RPM/RPD/TPM) 초과: %s" % err
        return [], "Gemini API 오류: %s" % err

    text = (response.text or "").strip()
    matches = _parse_batch_response(text)
    return matches, None


def _parse_batch_response(text: str) -> list[dict]:
    """1회 호출 응답 파싱. '1. symbol | 이름 | 차트 근거' 형식."""
    import re
    out = []
    if not text or "적합 없음" in text[:50]:
        return out
    # 1. 005930.KS | 삼성전자 | 차트 근거...
    pattern = re.compile(r"^\s*\d+[.)]\s*([^\s|]+)\s*\|\s*([^|]+)\|?(.*)$", re.MULTILINE)
    for m in pattern.finditer(text):
        symbol = m.group(1).strip()
        name = m.group(2).strip()
        reason = m.group(3).strip()[:300] if m.group(3) else ""
        out.append({"symbol": symbol, "name": name, "chart_reason": reason, "reason": reason, "action": ""})
    return out


def filter_rss_with_gemini(
    rss_texts: list[str],
    api_key: Optional[str],
) -> dict:
    """RSS 헤드라인을 Gemini로 필터링. 추천 종목 + 위험신호 종목 분리 추출.

    Returns:
        {"recommended": [{"ticker","name","reason","source"}, ...], "warning": [...]}
    """
    out = {"recommended": [], "warning": []}
    if not rss_texts or not api_key:
        return out
    if not HAS_GENAI:
        return out

    _ensure_genai(api_key)
    model = genai.GenerativeModel(MODEL_NAME)

    block = "\n".join(rss_texts[:80])  # 토큰 제한
    prompt = f"""아래는 금융 뉴스/애널리스트 헤드라인입니다.
두 가지로 분류하세요:
1) 추천: Strong Buy, Upgrade, 목표가 상향, 매수 추천 등 긍정적 의견 (최대 10개)
2) 위험신호: Downgrade, Sell, 목표가 하향, 매도, 리스크 경고 등 부정적 의견 (최대 10개)

[헤드라인]
{block}

반드시 아래 JSON 형식만 출력 (다른 텍스트 없이):
{{"recommended":[{{"ticker":"AAPL","name":"Apple","reason":"목표가 상향","source":"Finviz"}}],"warning":[{{"ticker":"XYZ","name":"XYZ","reason":"목표가 하향","source":"Seeking Alpha"}}]}}
미국주: AAPL 등. 한국주: 005930.KS 등. 헤드라인에서 확인 가능한 종목만."""

    def _parse_list(arr):
        result = []
        for x in (arr or []):
            if isinstance(x, dict) and x.get("ticker"):
                result.append({
                    "ticker": str(x.get("ticker", "")).strip(),
                    "name": str(x.get("name", x.get("ticker", ""))).strip() or x.get("ticker", ""),
                    "reason": str(x.get("reason", ""))[:200],
                    "source": str(x.get("source", ""))[:50] or "RSS",
                })
        return result[:10]

    try:
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.1, max_output_tokens=2048),
        )
        text = (resp.text or "").strip()
        start = text.find("{")
        if start < 0:
            return out
        end = text.rfind("}") + 1
        if end <= start:
            return out
        obj = json.loads(text[start:end])
        if isinstance(obj, dict):
            out["recommended"] = _parse_list(obj.get("recommended"))
            out["warning"] = _parse_list(obj.get("warning"))
    except Exception:
        pass
    return out


def _parse_json_array_robust(text: str) -> list:
    """JSON 배열 파싱. 실패 시 trailing comma 제거 등 시도."""
    text = text.strip().replace("```json", "").replace("```", "").strip()
    start = text.find("[")
    if start < 0:
        return []
    end = text.rfind("]") + 1
    if end <= start:
        return []
    raw = text[start:end]
    for attempt in [raw, raw.replace(",]", "]").replace(",}", "}")]:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return []


def get_hottest_analyst_analyses(
    rss_texts: list[str],
    api_key: Optional[str],
) -> list[dict]:
    """RSS에서 최근 가장 핫한 애널리스트 분석 10건. 미국·한국 둘 다 포함."""
    if not rss_texts or not api_key or not HAS_GENAI:
        return []

    _ensure_genai(api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    block = "\n".join(rss_texts[:80])

    prompt = f"""아래 RSS 헤드라인에서 가장 화제인 종목 10개를 골라, 티커·종목명·요약·출처를 주세요.
미국주(AAPL,TSLA 등), 한국주(005930.KS 등) 모두 포함.

[헤드라인]
{block}

아래 형식의 JSON 배열만 출력:
[{{"ticker":"AAPL","name":"Apple","analysis":"한줄요약","source":"Finviz"}}, ...]
10개 출력."""

    try:
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=2048,
            ),
        )
        text = (resp.text or "").strip()
        arr = _parse_json_array_robust(text)
        out = []
        seen = set()
        for x in (arr or []):
            if isinstance(x, dict) and x.get("ticker"):
                t = str(x.get("ticker", "")).strip()
                if t and t not in seen:
                    seen.add(t)
                    out.append({
                        "ticker": t,
                        "name": str(x.get("name", t)).strip() or t,
                        "analysis": str(x.get("analysis", ""))[:250],
                        "source": str(x.get("source", ""))[:30] or "RSS",
                    })
        return out[:10]
    except Exception:
        return []


def parse_gemini_response(text: str) -> dict:
    """플레인 텍스트 응답 파싱. [판정], [차트], [재무], [종합], [권고] 형식."""
    import re
    t = text.strip().replace("```", "").replace("json", "")
    out = {"verdict": "?", "chart_reason": "", "financial_reason": "", "reason": "", "action": "?"}
    tags = ["[판정]", "[차트]", "[재무]", "[종합]", "[권고]"]
    keys = ["verdict", "chart_reason", "financial_reason", "reason", "action"]
    for tag, key in zip(tags, keys):
        pos = t.find(tag)
        if pos >= 0:
            start = pos + len(tag)
            end = len(t)
            for nxt in tags:
                if nxt != tag:
                    p = t.find(nxt, start)
                    if 0 <= p < end:
                        end = p
            val = t[start:end].strip().split("\n")[0][:250]
            out[key] = val
    if not out["reason"] and t:
        out["reason"] = t[:200].replace("\n", " ")
    return out


# --- 퀀트 전문가 배치 스코어링 (RPD 20 / RPM 5 대응) ---

QUANT_SYSTEM_PROMPT = """당신은 퀀트 기반 투자 분석 전문가입니다. 감정 배제, 수치·공식 기반으로만 판단합니다.

스코어 공식:
1. 목표가 괴리율(Gap) 30%: (목표가 - 현재가) / 현재가 × 100. 괴리 20% 이상이면 높은 점수.
2. 재무 건전성(Fundamental) 40%: 영업이익률(OPM) 10% 이상 또는 최근 분기 흑자 전환 시 가산.
3. 시장 심리(Sentiment) 30%: '역대급', 'Strong Buy', '상향', '매수' 등 긍정 단어 포함 시 가산.

각 종목에 대해 위 세 항목을 점수화(0~100)하고, 가중합으로 최종 Score를 계산한 뒤, 상위 종목만 선별하세요. 근거를 반드시 포함하세요."""


def batch_stock_analysis_with_scores(
    stocks_data_list: list[dict],
    api_key: Optional[str],
    batch_size: int = 10,
    sleep_sec: float = 12.0,
    market_label: str = "US",
) -> tuple[list[dict], Optional[str]]:
    """한 번에 batch_size개 종목 데이터를 Gemini에 보내 스코어·근거 수집. RPD 절약용.
    stocks_data_list: [{"ticker","name","current_price","target_price","opm_pct","headlines":[]}, ...]
    Returns: (top 10 list with score/reason, error_msg)
    """
    import time
    if not HAS_GENAI or not api_key or not stocks_data_list:
        return [], None
    _ensure_genai(api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    results: list[dict] = []
    err_msg: Optional[str] = None
    for i in range(0, len(stocks_data_list), batch_size):
        batch = stocks_data_list[i : i + batch_size]
        block = []
        for s in batch:
            gap = ""
            if s.get("current_price") and s.get("target_price"):
                try:
                    g = (float(s["target_price"]) - float(s["current_price"])) / float(s["current_price"]) * 100
                    gap = f"목표가괴리율={g:.1f}%"
                except (TypeError, ZeroDivisionError):
                    pass
            block.append(
                "[%s] %s | 현재가=%s 목표가=%s %s | OPM=%s%% | 헤드라인/리포트=%s"
                % (
                    s.get("ticker", "?"),
                    s.get("name", "?"),
                    s.get("current_price"),
                    s.get("target_price"),
                    gap,
                    s.get("opm_pct"),
                    str((s.get("headlines") or s.get("seeking_alpha_headlines") or s.get("headlines_or_reports"))[:5]),
                )
            )
        user = f"""[{market_label} 후보 종목 데이터 - 이미 계산된 수치 포함]
{chr(10).join(block)}

위 데이터를 바탕으로 Score = Gap 30% + Fundamental 40% + Sentiment 30% 로 점수화하고, 상위 10개만 골라 주세요.
각 종목마다 한 줄: ticker | name | Score(0~100) | 근거(한 줄). JSON 배열로만 출력:
[{{"ticker":"AAPL","name":"Apple","score":85,"reason":"괴리 25% 가산, OPM 15%"}}, ...]"""
        try:
            resp = model.generate_content(
                QUANT_SYSTEM_PROMPT + "\n\n" + user,
                generation_config=genai.types.GenerationConfig(temperature=0.2, max_output_tokens=2048),
            )
            text = (resp.text or "").strip()
            arr = _parse_json_array_robust(text)
            for x in (arr or []):
                if isinstance(x, dict) and x.get("ticker"):
                    results.append({
                        "ticker": str(x.get("ticker", "")).strip(),
                        "name": str(x.get("name", x.get("ticker", ""))).strip(),
                        "score": int(x.get("score", 0)) if x.get("score") is not None else 0,
                        "reason": str(x.get("reason", ""))[:300],
                        "market": market_label,
                    })
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "resource_exhausted" in err_msg.lower():
                break
        if i + batch_size < len(stocks_data_list):
            time.sleep(sleep_sec)
    results.sort(key=lambda x: -x.get("score", 0))
    return results[:10], err_msg


def batch_chart_analysis_top10(
    charts_summary_list: list[dict],
    api_key: Optional[str],
    batch_size: int = 10,
    sleep_sec: float = 12.0,
    market_label: str = "US",
) -> tuple[list[dict], Optional[str]]:
    """차트 요약(50/100/200 정배열, 골드크로스, 이격도, RSI) 배치로 Gemini에 보내 상위 10개 선별."""
    import time
    if not HAS_GENAI or not api_key or not charts_summary_list:
        return [], None
    _ensure_genai(api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    block = "\n".join(
        "[%s] %s | 정배열=%s 골드크로스=%s 이격도200=%s RSI=%s"
        % (
            c.get("symbol", "?"),
            c.get("name", "?"),
            c.get("alignment_50_100_200"),
            c.get("golden_cross_50_200"),
            c.get("displacement_200"),
            c.get("rsi"),
        )
        for c in charts_summary_list
    )
    user = f"""[{market_label} 차트 후보 - 50/100/200 이평선 정배열·골든크로스·200이격도·RSI]
{block}

조건: 50>100>200 정배열, 골든크로스, 200이평 이격도 적정, 정배열인데 RSI 30 이하 우선. 정답 차트와 유사한 패턴 우선.
상위 10개만 골라 한 줄씩: symbol | name | 근거(한 줄). JSON 배열만:
[{{"symbol":"005930.KS","name":"삼성전자","reason":"정배열+골드크로스, 이격도 1.02"}}, ...]"""
    try:
        resp = model.generate_content(
            PATTERN_DESCRIPTION + "\n\n" + user,
            generation_config=genai.types.GenerationConfig(temperature=0.2, max_output_tokens=2048),
        )
        text = (resp.text or "").strip()
        arr = _parse_json_array_robust(text)
        results = []
        for x in (arr or []):
            if isinstance(x, dict) and x.get("symbol"):
                results.append({
                    "symbol": str(x.get("symbol", "")).strip(),
                    "name": str(x.get("name", x.get("symbol", ""))).strip(),
                    "reason": str(x.get("reason", ""))[:300],
                    "market": market_label,
                })
        return results[:10], None
    except Exception as e:
        return [], str(e)
