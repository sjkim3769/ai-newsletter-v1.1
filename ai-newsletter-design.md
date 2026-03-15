# AI Newsletter Agent - 통합 설계서

> **문서 목적**: Claude Code 구현 시 참조하는 계획서  
> **프로젝트**: ai-newsletter-v1.1  
> **작성 기준**: 4인 전문가 팀 (품질담당자 / Orchestrator / Efficiency / Quality / Facilitator)

---

## 1. 작업 컨텍스트 문서

### 1.1 배경 및 목적

AI 산업의 빠른 변화 속에서 국내외 주요 언론사 및 빅테크 공식 채널의 AI 관련 기사를 매일 자동 수집·요약하여, 관리자가 승인 후 정적 웹페이지로 발행하는 뉴스레터 에이전트 시스템을 구축한다.

### 1.2 범위

| 구분 | 내용 |
|------|------|
| **수집 대상** | 해외 영문 (TechCrunch, VentureBeat, Wired, MIT Tech Review 등), 국내 (지디넷, 블로터, 전자신문), 빅테크 공식 블로그 (Google AI, Anthropic, OpenAI) |
| **수집 주기** | 1일 1회 (GitHub Actions 스케줄) |
| **대상 토픽** | 빅테크 기업 동향, 신기술 트렌드, 시장 동향, AI 이슈, 정책 |
| **발행 채널** | GitHub Pages (정적 HTML, 관리자 승인 후 배포) |
| **언어** | 수집은 한/영 혼재, 요약 출력은 한국어 |

### 1.3 입출력 정의

**입력**
- RSS 피드 URL 목록 (설정 파일로 관리)
- 수집 실행 트리거 (GitHub Actions cron 또는 수동)

**중간 산출물**
- `output/raw_articles_{날짜}.json` — 수집된 원문 기사 목록
- `output/scored_articles_{날짜}.json` — 점수 및 분류 완료 기사
- `output/summaries_{날짜}.json` — 검증 완료 요약 결과
- `output/newsletter_{날짜}.html` — 발행 준비 완료 HTML

**최종 출력**
- GitHub Pages에 배포된 정적 HTML 뉴스레터 (날짜별 아카이브)
- 상위 5개 기사, 기사별 5줄 요약, 원문 링크 포함

### 1.4 제약조건

| 구분 | 제약사항 |
|------|----------|
| **품질 (품질담당자)** | 요약 내용과 원문 링크 간 착시 현상 발생 시 해당 기사 즉시 제외, 후보 기사로 대체 |
| **비용 (Efficiency)** | LLM API 호출은 최종 선별된 5개 기사에만 적용 (수집·분류는 코드 처리) |
| **보안 (Quality)** | 관리자만 배포 가능 (GitHub Actions 수동 승인 단계 포함) |
| **환경** | VS Code + GitHub, Python 3.10+, Node.js 18+ |
| **스케줄** | 매일 오전 8시 KST (UTC 23:00 전일) 자동 수집 |

### 1.5 용어 정의

| 용어 | 정의 |
|------|------|
| **착시 현상** | 요약 기사 내용이 원문 URL의 실제 기사 내용과 다르게 읽히는 현상 |
| **후보 기사** | 상위 5개 선정에서 탈락했으나 대체 가능한 6~10위 기사 |
| **발행 승인** | 관리자가 GitHub Actions workflow_dispatch로 배포를 최종 확인하는 단계 |
| **점수화** | 수집된 기사의 AI 관련도, 출처 신뢰도, 중복 여부를 기반으로 산출되는 우선순위 점수 |

---

## 2. 워크플로우 정의

### 2.1 전체 흐름도

```
[GitHub Actions Cron] 
        ↓
[STEP 1] RSS 수집 에이전트 (Collector)
  - 전체 RSS 피드 파싱 → 원문 기사 목록 추출
  - 성공 기준: 최소 20개 이상 기사 수집
  - 실패 시: 재시도 2회 → 에스컬레이션 (이슈 생성)
        ↓
  output/raw_articles_{날짜}.json
        ↓
[STEP 2] 분류·선별 에이전트 (Analyzer)
  - AI 관련도 점수화, 중복 제거, 출처 신뢰도 반영
  - 상위 5개 + 후보 5개(6~10위) 선정
  - 성공 기준: 상위 5개 + 후보 5개 확보
  - 실패 시: 후보 부족 시 수집 범위 확장 재시도
        ↓
  output/scored_articles_{날짜}.json
        ↓
[STEP 3] 요약 에이전트 (Summarizer)
  - 기사별 5줄 요약 생성 (LLM 판단)
  - 요약-원문 착시 검증 (LLM 자기 검증)
  - 착시 감지 시 → 해당 기사 제외, 후보 기사 자동 대체
  - 성공 기준: 검증 통과한 5개 기사 요약 완성
  - 실패 시: 후보 기사 순차 대체 (최대 5회)
        ↓
  output/summaries_{날짜}.json
        ↓
[STEP 4] 발행 에이전트 (Publisher)
  - HTML 뉴스레터 생성
  - 관리자 승인 대기 (GitHub Actions 수동 트리거)
  - 승인 시 → GitHub Pages 배포
  - 성공 기준: HTML 유효성 검사 통과, 링크 5개 전부 유효
        ↓
  docs/index.html (GitHub Pages)
```

### 2.2 LLM 판단 영역 vs 코드 처리 영역

| 단계 | LLM 판단 (에이전트) | 코드 처리 (스크립트) |
|------|---------------------|---------------------|
| STEP 1 수집 | ✗ | RSS 파싱, HTTP 요청, JSON 저장 |
| STEP 2 분류 | AI 관련도 판단, 토픽 분류 | 점수 계산, 중복 제거, 정렬 |
| STEP 3 요약 | **5줄 요약 생성**, **착시 자기 검증** | 파일 입출력, 후보 대체 로직 |
| STEP 4 발행 | ✗ | HTML 렌더링, GitHub Pages 배포 |

### 2.3 분기 조건 및 상태 전이

```
수집 결과 < 20개
  → 재시도 (최대 2회)
  → 실패 시 GitHub Issue 자동 생성 후 중단

상위 5개 확보 실패
  → RSS 피드 범위 확장 후 재시도

착시 감지 (요약-원문 불일치)
  → 해당 기사 블랙리스트 등록
  → 후보 기사 중 다음 순위로 자동 대체
  → 후보 소진 시 에스컬레이션

관리자 미승인 (48시간 초과)
  → 해당 일자 발행 스킵 + 로그 기록
```

### 2.4 각 단계별 성공 기준 및 검증

| 단계 | 성공 기준 | 검증 방법 | 실패 처리 |
|------|----------|----------|----------|
| STEP 1 수집 | 기사 20개 이상, 필수 필드(title/url/date/source) 존재 | 스키마 검증 | 자동 재시도 2회 → 에스컬레이션 |
| STEP 2 분류 | 상위 5개 + 후보 5개 확보, 중복 없음 | 규칙 기반 (항목 수, 점수 범위) | 자동 재시도 (범위 확장) |
| STEP 3 요약 | 기사당 정확히 5줄, 요약-원문 착시 없음 | **LLM 자기 검증** | 자동 대체 (후보 기사) → 에스컬레이션 |
| STEP 4 발행 | HTML 유효성 통과, 5개 링크 200 응답 | 규칙 기반 (링크 체크) | 스킵 + 로그 |

---

## 3. 구현 스펙

### 3.1 폴더 구조

```
/ai-newsletter-v1.1
  ├── CLAUDE.md                              # 메인 에이전트 지침 (오케스트레이터)
  │
  ├── /.claude
  │   ├── /agents
  │   │   ├── /collector
  │   │   │   └── AGENT.md                  # RSS 수집 에이전트 지침
  │   │   ├── /analyzer
  │   │   │   └── AGENT.md                  # 분류·선별 에이전트 지침
  │   │   ├── /summarizer
  │   │   │   └── AGENT.md                  # 요약·검증 에이전트 지침
  │   │   └── /publisher
  │   │       └── AGENT.md                  # 발행 에이전트 지침
  │   │
  │   └── /skills
  │       ├── /rss-fetcher
  │       │   ├── SKILL.md
  │       │   ├── /scripts
  │       │   │   └── fetch_rss.py          # RSS 파싱 스크립트
  │       │   └── /references
  │       │       └── rss_sources.yaml      # RSS URL 목록 설정
  │       ├── /article-scorer
  │       │   ├── SKILL.md
  │       │   └── /scripts
  │       │       └── score_articles.py     # 점수화·중복제거 스크립트
  │       ├── /hallucination-checker
  │       │   ├── SKILL.md
  │       │   └── /scripts
  │       │       └── check_alignment.py    # 요약-원문 정합성 검사
  │       └── /html-renderer
  │           ├── SKILL.md
  │           └── /scripts
  │               ├── render_newsletter.py  # HTML 뉴스레터 생성
  │               └── template.html        # 뉴스레터 HTML 템플릿
  │
  ├── /output                               # 중간 산출물 (날짜별)
  │   ├── raw_articles_{YYYY-MM-DD}.json
  │   ├── scored_articles_{YYYY-MM-DD}.json
  │   ├── summaries_{YYYY-MM-DD}.json
  │   └── newsletter_{YYYY-MM-DD}.html
  │
  ├── /docs                                 # GitHub Pages 배포 디렉토리
  │   ├── index.html                        # 최신 뉴스레터
  │   └── /archive                          # 날짜별 아카이브
  │
  ├── /.github
  │   └── /workflows
  │       ├── daily-collect.yml             # 매일 오전 8시 KST 수집 자동화
  │       └── manual-publish.yml            # 관리자 수동 승인 배포
  │
  ├── /config
  │   └── rss_sources.yaml                  # RSS 피드 URL 및 출처 메타데이터
  │
  └── requirements.txt                      # Python 의존성
```

### 3.2 CLAUDE.md 핵심 섹션 목록

| 섹션 | 내용 요약 |
|------|----------|
| `## Role` | 오케스트레이터 역할 정의 — 4개 서브에이전트 조율, 직접 처리 금지 |
| `## Workflow` | STEP 1~4 실행 순서 및 각 단계 트리거 조건 |
| `## Agent Routing` | 어떤 조건에서 어떤 서브에이전트를 호출하는지 명시 |
| `## Data Flow` | 단계별 파일 입출력 경로 규칙 |
| `## Error Handling` | 재시도 횟수, 에스컬레이션 기준, GitHub Issue 생성 조건 |
| `## Quality Gates` | 착시 감지 시 후보 대체 정책, 발행 금지 기준 |
| `## Constraints` | LLM 호출 범위 제한, 비용 최적화 지침 |

### 3.3 에이전트 구조 (서브에이전트 분리)

**분리 근거**: 각 단계가 독립적인 도메인 지식을 필요로 하며, 컨텍스트 윈도우 효율을 위해 필요한 시점에만 해당 에이전트 지침 로드.

| 에이전트 | 역할 | 입력 | 출력 | 트리거 조건 |
|---------|------|------|------|------------|
| **Collector** | RSS 피드 수집 및 파싱 | `rss_sources.yaml` | `raw_articles_{날짜}.json` | GitHub Actions cron 또는 수동 실행 |
| **Analyzer** | AI 관련도 분류, 점수화, 상위 10개 선정 | `raw_articles_{날짜}.json` | `scored_articles_{날짜}.json` | Collector 완료 후 |
| **Summarizer** | 5줄 요약 생성 + 착시 자기 검증 + 후보 대체 | `scored_articles_{날짜}.json` | `summaries_{날짜}.json` | Analyzer 완료 후 |
| **Publisher** | HTML 렌더링 + 관리자 승인 대기 + GitHub Pages 배포 | `summaries_{날짜}.json` | `docs/index.html` | 관리자 workflow_dispatch 승인 |

### 3.4 스킬 목록

| 스킬 | 역할 | 트리거 조건 | 호출 에이전트 |
|------|------|------------|-------------|
| `rss-fetcher` | RSS URL에서 기사 파싱, HTTP 요청, JSON 저장 | Collector 에이전트 실행 시 | Collector |
| `article-scorer` | AI 관련도 점수 계산, 중복 해시 비교, 정렬 | Analyzer 에이전트 실행 시 | Analyzer |
| `hallucination-checker` | 요약문과 원문 URL 내용 정합성 검사 | Summarizer 검증 단계 | Summarizer |
| `html-renderer` | summaries JSON → HTML 뉴스레터 렌더링, 링크 유효성 체크 | Publisher 에이전트 실행 시 | Publisher |

### 3.5 주요 산출물 파일 형식

**`raw_articles_{날짜}.json`**
```json
{
  "collected_at": "2025-01-15T08:00:00+09:00",
  "total_count": 47,
  "articles": [
    {
      "id": "uuid",
      "title": "기사 제목",
      "url": "https://...",
      "source": "TechCrunch",
      "source_type": "해외영문|국내|빅테크공식",
      "published_at": "2025-01-15T06:30:00Z",
      "description": "RSS 피드 요약 (원문 그대로)",
      "content_snippet": "본문 앞 500자"
    }
  ]
}
```

**`scored_articles_{날짜}.json`**
```json
{
  "top5": [ { ...article, "score": 92, "topic": "빅테크동향", "duplicate_of": null } ],
  "candidates": [ { ...article, "score": 78, "rank": 6 } ]
}
```

**`summaries_{날짜}.json`**
```json
{
  "published_date": "2025-01-15",
  "articles": [
    {
      "rank": 1,
      "title": "기사 제목",
      "source": "TechCrunch",
      "url": "https://...",
      "topic": "빅테크동향",
      "summary": ["줄1", "줄2", "줄3", "줄4", "줄5"],
      "validation_passed": true,
      "replaced_from_candidate": false
    }
  ]
}
```

### 3.6 GitHub Actions 워크플로우 구조

**`daily-collect.yml`** (자동 실행)
- 트리거: `schedule: cron: '0 23 * * *'` (UTC 23:00 = KST 08:00)
- 실행 순서: Collector → Analyzer → Summarizer → 결과물 커밋
- 실패 시: GitHub Issue 자동 생성

**`manual-publish.yml`** (관리자 승인 배포)
- 트리거: `workflow_dispatch` (수동)
- 입력 파라미터: 발행할 날짜 선택
- 실행 순서: Publisher → GitHub Pages 배포
- 권한: 지정된 관리자만 실행 가능 (`environment: production`)

---

## 4. 품질 원칙 (4인 전문가 팀 합의)

### 품질담당자 — 착시 방지 정책
- 요약 생성 후 **반드시** 원문 URL 내용과 정합성 검증 실행
- 검증 실패(착시 감지) 시 해당 기사는 **그 날 발행 목록에서 영구 제외**
- 후보 기사 소진 전까지 자동 대체, 소진 시 에스컬레이션

### Orchestrator — 아키텍처 결정
- 서브에이전트 간 직접 호출 금지, 반드시 CLAUDE.md 오케스트레이터 경유
- 각 단계 산출물은 `/output/`에 날짜 포함 파일명으로 저장 (파일 기반 데이터 전달)

### Efficiency — 비용 최적화
- LLM API 호출은 **상위 5개 (+ 후보 대체 시 최대 5개 추가)** 기사에만 한정
- 수집·점수화·HTML 렌더링은 코드 처리
- 이미 수집된 날짜의 JSON이 존재하면 수집 단계 스킵 (멱등성 보장)

### Quality — 비즈니스 로직 안전성
- 링크 유효성 검사: 발행 전 5개 URL 모두 HTTP 200 확인
- 관리자 승인 없이 GitHub Pages 자동 배포 절대 금지
- 발행 HTML에 생성 타임스탬프 및 검증 통과 여부 메타데이터 포함

### Facilitator — 유지보수성
- RSS 피드 목록은 `config/rss_sources.yaml`에서만 관리 (코드 하드코딩 금지)
- 모든 스크립트는 단일 책임 원칙 준수
- 중간 산출물 파일 보존 (30일) — 디버깅 및 감사 추적 용도

---

## 5. 구현 시 주의사항

1. `hallucination-checker` 스킬은 원문 URL을 **실제로 fetch**하여 내용 비교 필요 — robots.txt 준수
2. 국내 언론사 RSS는 한국어 인코딩(UTF-8) 처리 명시적 지정
3. GitHub Pages 배포 디렉토리는 `/docs`로 설정 (레포지토리 Settings에서 확인)
4. `workflow_dispatch`의 `environment: production`에 Required reviewers 설정 필요
5. OpenAI, Anthropic 공식 블로그 RSS 주소는 변경될 수 있으므로 `rss_sources.yaml`에서 주기적 검증 필요
