# 정답 차트 샘플 (패턴 매칭 기준)

이 폴더의 `answer_*.json` 파일이 Gemini 패턴 매칭의 기준이 됩니다.

## 4종목 정답 차트 생성

```bash
python scripts/generate_answer_samples.py
```

생성 파일: 카카오(035720.KS), 네이버(035420.KS), 다올투자증권(030210.KS), CJ CGV(079160.KS)  
→ `samples/answer_kakao.json`, `answer_naver.json`, `answer_daol.json`, `answer_cj_cgv.json`

## 패턴 설명 (코드 내 고정)

- 오랜 횡보/하락 후 저점 상승 → 고점 돌파 → 눌림목
- 이평선·RSI·볼린저·OBV(거래량) 참고

샘플이 없으면 위 패턴 설명만으로 Gemini가 판단합니다.
