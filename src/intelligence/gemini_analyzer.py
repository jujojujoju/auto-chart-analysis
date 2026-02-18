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
[분석 대상 - 아래 각 줄은 "symbol 이름: C=현재가 s5=sma5 s20=sma20 s60=sma60 rsi=RSI v=거래량 | 10d=최근10일종가" 형식입니다]
{compressed_text}

위 모든 종목을 검토하여, [참고 정답 패턴]에 부합하는 종목만 선별하세요.
(하락/횡보 오래 하다가 갑자기 튀었다가 0.3~0.6 되돌림 후 횡보, 저점 상승이 최근 1번 이하인 "역배열→정배열 전환 초입"만 적합. 이미 정배열 오래 유지·저점 상승 여러 번 반복된 종목은 부적합)

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


def analyze_top_stocks_with_rss(
    top_tickers: list[tuple[str, str]],
    rss_texts: list[str],
    api_key: Optional[str],
) -> list[dict]:
    """매수세 Top 10 종목에 대한 애널리스트 분석. RSS 헤드라인 기반.

    Returns:
        [{"ticker":"005930.KS","name":"삼성전자","analysis":"..."}, ...]
    """
    if not top_tickers or not rss_texts or not api_key or not HAS_GENAI:
        return []

    _ensure_genai(api_key)
    model = genai.GenerativeModel(MODEL_NAME)

    ticker_str = ", ".join(f"{t} ({n})" for t, n in top_tickers)
    block = "\n".join(rss_texts[:60])

    prompt = f"""아래는 거래량(매수세) 상위 10종목입니다: {ticker_str}

아래 RSS 헤드라인에서 위 종목들이 언급된 경우, 해당 종목에 대한 애널리스트 의견·분석을 1~2문장으로 요약하세요.
언급이 없으면 "최근 RSS 언급 없음"으로 표시.

[헤드라인]
{block}

JSON 배열만 출력:
[{{"ticker":"005930.KS","name":"삼성전자","analysis":"요약"}}, ...]
"""

    try:
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.2, max_output_tokens=2048),
        )
        text = (resp.text or "").strip()
        start = text.find("[")
        if start < 0:
            return []
        end = text.rfind("]") + 1
        if end <= start:
            return []
        arr = json.loads(text[start:end])
        out = []
        for x in (arr or []):
            if isinstance(x, dict) and x.get("ticker"):
                out.append({
                    "ticker": str(x.get("ticker", "")).strip(),
                    "name": str(x.get("name", x.get("ticker", ""))).strip(),
                    "analysis": str(x.get("analysis", ""))[:250],
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
