"""
Prefetch Script
역할: scored_articles의 top5+candidates URL을 병렬로 fetch하여 prefetched_{날짜}.json 저장
실행: python .claude/skills/summarizer/scripts/prefetch.py --date YYYY-MM-DD

Summarizer Agent가 이 파일을 읽어 URL fetch를 건너뛰고 LLM 작업에만 집중한다.
"""

import argparse
import io
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "output"

FETCH_TIMEOUT = 10
CONTENT_MAX = 3000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def fetch_article(url):
    try:
        resp = requests.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "AI-Newsletter-Bot/1.1"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:CONTENT_MAX]
    except Exception as e:
        log.warning(f"fetch 실패 ({url[:60]}): {e}")
        return None


def run(date_str):
    input_path = OUTPUT_DIR / f"scored_articles_{date_str}.json"
    if not input_path.exists():
        log.error(f"입력 파일 없음: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        scored = json.load(f)

    articles = scored.get("top5", []) + scored.get("candidates", [])
    urls = [a["url"] for a in articles]

    log.info(f"병렬 fetch 시작: {len(urls)}개 URL")

    results = {}
    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        futures = {executor.submit(fetch_article, url): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            content = future.result()
            results[url] = content
            status = "OK" if content else "FAIL"
            log.info(f"[{status}] {url[:60]}")

    ok = sum(1 for v in results.values() if v)
    log.info(f"fetch 완료: {ok}/{len(urls)} 성공")

    output_path = OUTPUT_DIR / f"prefetched_{date_str}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info(f"저장 완료: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="기사 URL 병렬 prefetch")
    parser.add_argument("--date", required=True, help="처리 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
