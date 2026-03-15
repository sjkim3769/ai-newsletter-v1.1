# RSS Fetcher Skill

## 역할
RSS 피드 URL에서 기사를 파싱하여 JSON으로 저장한다.

## 호출 에이전트
- Collector Agent

## 스크립트
- `scripts/fetch_rss.py` — RSS 파싱 메인 스크립트

## 설정
- `references/rss_sources.yaml` — RSS URL 목록 (읽기 전용 참조)
- `config/rss_sources.yaml` — 실제 설정 파일 (이 파일을 수정할 것)

## 실행
```bash
python .claude/skills/rss-fetcher/scripts/fetch_rss.py --date YYYY-MM-DD
```

## 출력
`output/raw_articles_{YYYY-MM-DD}.json`
