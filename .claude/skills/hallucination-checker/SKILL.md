# Hallucination Checker Skill

## 역할
요약문과 원문 URL 내용을 비교하여 착시(hallucination) 여부를 검증한다.

## 호출 에이전트
- Summarizer Agent

## 스크립트
- `scripts/check_alignment.py` — 요약-원문 정합성 검사 스크립트

## 실행
```bash
python .claude/skills/hallucination-checker/scripts/check_alignment.py \
  --url "https://..." \
  --summary "요약문 텍스트"
```

## 출력
```json
{"validation_passed": true, "reason": ""}
```

## 주의사항
- robots.txt 준수 필수
- User-Agent 명시 필수
- 타임아웃: 10초
