# HTML Renderer Skill

## 역할
summaries JSON을 HTML 뉴스레터로 렌더링하고 링크 유효성을 검사한다.

## 호출 에이전트
- Publisher Agent

## 스크립트
- `scripts/render_newsletter.py` — HTML 뉴스레터 생성 스크립트
- `scripts/template.html` — 뉴스레터 HTML 템플릿

## 실행
```bash
python .claude/skills/html-renderer/scripts/render_newsletter.py --date YYYY-MM-DD
```

## 입력
`output/summaries_{YYYY-MM-DD}.json`

## 출력
- `output/newsletter_{YYYY-MM-DD}.html` — 검토용
- `docs/index.html` — 최신 배포본
- `docs/archive/{YYYY-MM-DD}.html` — 아카이브
