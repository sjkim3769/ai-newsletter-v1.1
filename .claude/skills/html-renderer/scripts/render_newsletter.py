"""
HTML Renderer Script
역할: summaries_{날짜}.json → HTML 뉴스레터 생성 + 링크 유효성 검사
호출: Publisher Agent
실행: python .claude/skills/html-renderer/scripts/render_newsletter.py --date YYYY-MM-DD
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "output"
DOCS_DIR = ROOT / "docs"
TEMPLATE_PATH = Path(__file__).parent / "template.html"

KST = timezone(timedelta(hours=9))
LINK_TIMEOUT = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── 품질 게이트 ──────────────────────────────────────────────────────────────

def quality_gates(articles):
    """5개 기사, 5줄 요약, 모두 validation_passed 확인. 실패 시 예외 발생."""
    if len(articles) != 5:
        raise ValueError(f"기사 수 오류: {len(articles)}개 (필요: 5개)")

    for a in articles:
        summary = a.get("summary", [])
        if len(summary) != 5:
            raise ValueError(f"요약 줄 수 오류: {a['title'][:40]} → {len(summary)}줄")
        if not a.get("validation_passed", False):
            raise ValueError(f"착시 검증 미통과: {a['title'][:40]}")

    urls = [a["url"] for a in articles]
    if len(set(urls)) != len(urls):
        raise ValueError("중복 URL 발견")

    log.info("품질 게이트 통과")


# ── 링크 유효성 검사 ─────────────────────────────────────────────────────────

def check_links(articles):
    """각 기사 URL HTTP 200 확인. 실패 기사 목록 반환."""
    failed = []
    for a in articles:
        url = a["url"]
        try:
            resp = requests.head(url, timeout=LINK_TIMEOUT,
                                 headers={"User-Agent": "AI-Newsletter-Bot/1.1"},
                                 allow_redirects=True)
            if resp.status_code == 200:
                log.info(f"[OK] {url[:60]}")
            else:
                log.warning(f"[FAIL {resp.status_code}] {url[:60]}")
                failed.append(a)
        except Exception as e:
            log.warning(f"[FAIL] {url[:60]} → {e}")
            failed.append(a)
    return failed


# ── HTML 생성 ─────────────────────────────────────────────────────────────────

ARROW_SVG = (
    '<svg width="12" height="12" viewBox="0 0 12 12" fill="none">'
    '<path d="M2 6h8M6 2l4 4-4 4" stroke="currentColor" '
    'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)


def render_article_card(article):
    rank = article.get("rank", "?")
    topic = article.get("topic", "기타")
    title = article.get("title", "")
    source = article.get("source", "")
    published_at = article.get("published_at", "")
    url = article.get("url", "#")
    summary_lines = article.get("summary", [])
    replaced = article.get("replaced_from_candidate", False)

    # 날짜 포맷
    pub_display = ""
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at)
            pub_display = dt.strftime("%Y.%m.%d")
        except Exception:
            pub_display = published_at[:10]

    # 태그
    tags_html = f'<span class="rank-badge">#{rank}</span>'
    tags_html += f'<span class="topic-tag">{topic}</span>'
    if replaced:
        tags_html += '<span class="replaced-tag">후보 대체</span>'

    # 요약
    summary_items = "".join(f"<li>{line}</li>" for line in summary_lines)
    source_dot = '<span class="source-dot"></span>'

    return f"""  <article class="card">
    <div class="card-meta">
      {tags_html}
    </div>
    <h2>{title}</h2>
    <p class="source-line">{source}{source_dot}{pub_display}</p>
    <ul class="summary">
      {summary_items}
    </ul>
    <a class="read-btn" href="{url}" target="_blank" rel="noopener">
      원문 읽기 {ARROW_SVG}
    </a>
  </article>"""


def get_archive_links():
    """docs/archive/ 에 있는 날짜별 HTML 파일 목록 → li 태그 반환."""
    archive_dir = DOCS_DIR / "archive"
    if not archive_dir.exists():
        return ""
    files = sorted(archive_dir.glob("*.html"), reverse=True)[:12]
    if not files:
        return ""
    items = []
    for f in files:
        date_str = f.stem  # YYYY-MM-DD
        items.append(f'    <li><a href="archive/{f.name}">{date_str}</a></li>')
    return "\n".join(items)


def format_date_kr(date_str):
    """YYYY-MM-DD → YYYY년 MM월 DD일"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.year}년 {dt.month}월 {dt.day}일"
    except Exception:
        return date_str


def render_html(summaries, date_str):
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    articles_html = "\n".join(render_article_card(a) for a in summaries["articles"])
    archive_html = get_archive_links()
    generated_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # 수집 기사 수: raw_articles 파일에서 읽기
    total_collected = "?"
    raw_path = OUTPUT_DIR / f"raw_articles_{date_str}.json"
    if raw_path.exists():
        try:
            with open(raw_path, encoding="utf-8") as f:
                raw = json.load(f)
            total_collected = str(raw.get("total_count", "?"))
        except Exception:
            pass

    html = (template
            .replace("{{publish_date}}", date_str)
            .replace("{{publish_date_kr}}", format_date_kr(date_str))
            .replace("{{generated_at}}", generated_at)
            .replace("{{validation_passed}}", "true")
            .replace("{{articles}}", articles_html)
            .replace("{{archive_links}}", archive_html)
            .replace("{{total_collected}}", total_collected))
    return html


# ── 저장 및 배포 ──────────────────────────────────────────────────────────────

def write_publish_log(date_str, status, replaced_count=0, skip_reason=""):
    log_path = OUTPUT_DIR / "publish_log.jsonl"
    entry = {
        "date": date_str,
        "published_at": datetime.now(KST).isoformat() if status == "success" else None,
        "articles_count": 5 if status == "success" else 0,
        "replaced_count": replaced_count,
        "status": status,
    }
    if skip_reason:
        entry["skip_reason"] = skip_reason

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run(date_str):
    input_path = OUTPUT_DIR / f"summaries_{date_str}.json"
    if not input_path.exists():
        log.error(f"입력 파일 없음: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        summaries = json.load(f)

    articles = summaries.get("articles", [])

    # 1. 품질 게이트
    try:
        quality_gates(articles)
    except ValueError as e:
        log.error(f"품질 게이트 실패: {e}")
        write_publish_log(date_str, "failed", skip_reason=str(e))
        sys.exit(1)

    # 2. 링크 유효성 검사
    failed_links = check_links(articles)
    if len(failed_links) >= 2:
        msg = f"링크 유효성 실패 {len(failed_links)}개 → 배포 중단"
        log.error(msg)
        write_publish_log(date_str, "failed", skip_reason=msg)
        sys.exit(1)
    elif failed_links:
        log.warning(f"링크 1개 실패 (계속 진행): {failed_links[0]['url']}")

    # 3. HTML 렌더링
    html = render_html(summaries, date_str)

    # 4. 저장
    OUTPUT_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "archive").mkdir(exist_ok=True)

    # 검토용
    review_path = OUTPUT_DIR / f"newsletter_{date_str}.html"
    review_path.write_text(html, encoding="utf-8")
    log.info(f"검토용 저장: {review_path}")

    # 최신본
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    log.info(f"배포본 저장: {DOCS_DIR / 'index.html'}")

    # 아카이브
    archive_path = DOCS_DIR / "archive" / f"{date_str}.html"
    if archive_path.exists():
        log.warning(f"아카이브 파일 이미 존재 — 덮어쓰기 금지: {archive_path}")
    else:
        archive_path.write_text(html, encoding="utf-8")
        log.info(f"아카이브 저장: {archive_path}")

    # 5. 로그
    replaced_count = sum(1 for a in articles if a.get("replaced_from_candidate"))
    write_publish_log(date_str, "success", replaced_count=replaced_count)
    log.info("발행 완료")


def main():
    parser = argparse.ArgumentParser(description="HTML 뉴스레터 렌더링 스크립트")
    parser.add_argument("--date", required=True, help="발행 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
