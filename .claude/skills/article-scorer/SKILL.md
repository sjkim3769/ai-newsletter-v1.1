# Article Scorer Skill

## 역할
수집된 기사를 AI 관련도 점수화, 중복 제거, 출처 신뢰도 반영으로 상위 10개를 선정한다.

## 호출 에이전트
- Analyzer Agent

## 스크립트
- `scripts/score_articles.py` — 점수화·중복제거 메인 스크립트

## 실행
```bash
python .claude/skills/article-scorer/scripts/score_articles.py --date YYYY-MM-DD
```

## 입력
`output/raw_articles_{YYYY-MM-DD}.json`

## 출력
`output/scored_articles_{YYYY-MM-DD}.json`
