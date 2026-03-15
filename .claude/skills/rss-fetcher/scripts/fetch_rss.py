"""
RSS Fetcher Script
역할: config/rss_sources.yaml의 RSS 피드를 파싱하여 raw_articles_{날짜}.json 저장
호출: Collector Agent
실행: python .claude/skills/rss-fetcher/scripts/fetch_rss.py --date YYYY-MM-DD
"""

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests
import yaml

# 프로젝트 루트 기준 경로
ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = ROOT / "config" / "rss_sources.yaml"
OUTPUT_DIR = ROOT / "output"

KST = timezone(timedelta(hours=9))
TIMEOUT = 10          # 소스당 HTTP 타임아웃 (초)
MIN_ARTICLES = 20     # 최소 수집 기사 수
SNIPPET_LENGTH = 500  # content_snippet 최대 길이

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_date(entry):
    """feedparser entry에서 published datetime 추출 → ISO 8601 문자열 반환"""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                dt = datetime(*t[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return None


def is_recent(published_at_str, hours=48):
    """발행일이 최근 N시간 이내인지 확인 (None이면 포함)"""
    if not published_at_str:
        return True
    try:
        dt = datetime.fromisoformat(published_at_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return dt >= cutoff
    except Exception:
        return True


def fetch_feed(source):
    """단일 RSS 소스를 파싱하여 article 목록 반환"""
    articles = []
    name = source["name"]
    url = source["url"]

    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "AI-Newsletter-Bot/1.1"})
        resp.raise_for_status()
        # 국내 언론사 한국어 인코딩 명시
        content = resp.content
        feed = feedparser.parse(content)
    except Exception as e:
        log.warning(f"[SKIP] {name} 접근 실패: {e}")
        return articles

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        url_entry = entry.get("link", "").strip()
        if not title or not url_entry:
            continue

        published_at = parse_date(entry)

        # content_snippet: RSS 본문 앞 SNIPPET_LENGTH자만 저장
        raw = entry.get("summary", "")
        if not raw and entry.get("content"):
            raw = entry["content"][0].get("value", "")
        snippet = raw.strip()[:SNIPPET_LENGTH]

        articles.append({
            "id": str(uuid.uuid4()),
            "title": title,
            "url": url_entry,
            "source": name,
            "source_type": source.get("type", "기타"),
            "language": source.get("language", "ko"),
            "published_at": published_at,
            "content_snippet": snippet,
        })

    log.info(f"[OK] {name}: {len(articles)}개 수집")
    return articles


def validate_article(article):
    """필수 필드 존재 + URL 형식 확인"""
    required = ["id", "title", "url", "source", "published_at"]
    for field in required:
        if not article.get(field):
            return False
    if not article["url"].startswith(("http://", "https://")):
        return False
    return True


def dedup(articles):
    """URL 기준 중복 제거"""
    seen = set()
    result = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            result.append(a)
    return result


def run(date_str, retry=0):
    config = load_config()
    sources = config.get("sources", [])

    all_articles = []
    sources_attempted = len(sources)
    sources_succeeded = 0

    for source in sources:
        fetched = fetch_feed(source)
        if fetched:
            sources_succeeded += 1
        all_articles.extend(fetched)

    # 유효성 검증 + 중복 제거
    valid = [a for a in all_articles if validate_article(a)]
    valid = dedup(valid)

    # 최근 48시간 기사 우선 정렬 (최신순)
    valid.sort(key=lambda a: a["published_at"] or "", reverse=True)

    log.info(f"수집 완료: 전체 {len(all_articles)}개 → 유효 {len(valid)}개")

    if len(valid) < MIN_ARTICLES:
        if retry < 2:
            log.warning(f"기사 {MIN_ARTICLES}개 미달 ({len(valid)}개). 재시도 {retry + 1}/2")
            return run(date_str, retry=retry + 1)
        else:
            log.error(f"재시도 2회 후에도 {MIN_ARTICLES}개 미달. 에스컬레이션 필요.")
            sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"raw_articles_{date_str}.json"

    result = {
        "collected_at": datetime.now(KST).isoformat(),
        "date": date_str,
        "total_count": len(valid),
        "sources_attempted": sources_attempted,
        "sources_succeeded": sources_succeeded,
        "articles": valid,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"저장 완료: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="RSS 피드 수집 스크립트")
    parser.add_argument("--date", required=True, help="수집 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()

    # 멱등성: 오늘 파일이 이미 존재하면 스킵
    output_path = OUTPUT_DIR / f"raw_articles_{args.date}.json"
    if output_path.exists():
        log.info(f"이미 존재: {output_path} — 수집 스킵")
        sys.exit(0)

    run(args.date)


if __name__ == "__main__":
    main()
