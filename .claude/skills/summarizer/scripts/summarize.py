"""
Summarizer Script
역할: scored_articles_{날짜}.json → 5줄 요약 생성 + 착시 검증 → summaries_{날짜}.json 저장
실행: python .claude/skills/summarizer/scripts/summarize.py --date YYYY-MM-DD

개선사항:
- Agent 오버헤드 제거 (LLM이 지시서 읽고 도구 선택하는 시간 없음)
- 5개 기사 URL fetch 병렬화 (ThreadPoolExecutor)
- fetch 결과를 요약·검증에 공유 (이중 fetch 제거)
"""

import argparse
import io
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from groq import Groq

# Windows 콘솔 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
load_dotenv(ROOT / ".env")
OUTPUT_DIR = ROOT / "output"

KST = timezone(timedelta(hours=9))
FETCH_TIMEOUT = 10
CONTENT_MAX = 3000
SUMMARY_MODEL = "llama-3.3-70b-versatile"
VALIDATION_MODEL = "llama-3.3-70b-versatile"
MAX_RETRIES = 1        # 요약 형식 오류 시 재생성 횟수
MAX_CANDIDATES = 5     # 착시 실패 시 후보 대체 최대 횟수

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── URL Fetch ──────────────────────────────────────────────────────────────────

def fetch_article(url):
    """원문 URL에서 텍스트 추출. 실패 시 None 반환."""
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
        log.warning(f"URL fetch 실패 ({url[:60]}): {e}")
        return None


def fetch_all_parallel(articles):
    """여러 기사 URL을 병렬로 fetch. {url: content or None} 반환."""
    results = {}
    with ThreadPoolExecutor(max_workers=len(articles)) as executor:
        futures = {executor.submit(fetch_article, a["url"]): a["url"] for a in articles}
        for future in as_completed(futures):
            url = futures[future]
            results[url] = future.result()
    return results


# ── 요약 생성 ──────────────────────────────────────────────────────────────────

def generate_summary(client, article_content):
    """Groq LLM으로 5줄 요약 생성. 리스트[5] 반환. 실패 시 None."""
    prompt = f"""다음 기사를 읽고 한국어로 정확히 5줄로 요약하라.

[기사 내용]
{article_content}

규칙:
- 반드시 한국어로 작성
- 정확히 5줄 (번호 없이 줄바꿈으로 구분)
- 기사의 본문내용을 맥락을 이해하고 하이라이트 형태로 5줄로 요약한다
- 원문에 없는 내용 추가 금지
- 줄당 50~100자"""

    try:
        resp = client.chat.completions.create(
            model=SUMMARY_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        return lines if len(lines) == 5 else None
    except Exception as e:
        log.error(f"요약 LLM 호출 오류: {e}")
        return None


def generate_summary_with_retry(client, content, snippet, url):
    """fetch 본문 우선, 실패 시 snippet 폴백. 형식 오류 시 1회 재시도."""
    fallback_used = content is None
    input_text = content if content else snippet

    if not input_text:
        log.error(f"요약 입력 없음: {url[:60]}")
        return None, True

    for attempt in range(MAX_RETRIES + 1):
        lines = generate_summary(client, input_text)
        if lines:
            return lines, fallback_used
        log.warning(f"요약 형식 오류 (시도 {attempt+1}/{MAX_RETRIES+1}): {url[:60]}")

    log.error(f"요약 생성 실패: {url[:60]}")
    return None, fallback_used


# ── 착시 검증 ──────────────────────────────────────────────────────────────────

def validate_summary(client, article_content, summary_lines, fallback_used=False):
    """Groq LLM으로 착시 검증. {"validation_passed": bool, "reason": str} 반환."""
    summary_text = "\n".join(f"{i+1}. {l}" for i, l in enumerate(summary_lines))
    fetch_note = "(※ 원문 fetch 실패로 RSS 설명 텍스트로 대체)" if fallback_used else ""

    prompt = f"""아래 [원문 내용]과 [요약문]을 비교하라. {fetch_note}

[원문 내용]
{article_content}

[요약문]
{summary_text}

다음 기준으로 착시 여부를 판정하라:
1. 요약에 원문에 없는 사실이 포함되어 있는가?
2. 요약의 주어/주체가 원문과 다른가?
3. 요약의 수치/날짜/고유명사가 원문과 다른가?
4. 요약을 읽은 독자가 원문과 다른 내용을 기대하게 되는가?

판정 결과를 JSON으로만 응답하라 (다른 텍스트 없이):
{{"validation_passed": true 또는 false, "reason": "실패 시 사유, 통과 시 빈 문자열"}}"""

    try:
        resp = client.chat.completions.create(
            model=VALIDATION_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
        result = json.loads(raw)
        return {
            "validation_passed": bool(result.get("validation_passed", False)),
            "reason": result.get("reason", ""),
        }
    except json.JSONDecodeError:
        log.warning(f"검증 LLM JSON 파싱 실패: {raw[:100]}")
        return {"validation_passed": False, "reason": "LLM 응답 파싱 오류"}
    except Exception as e:
        log.error(f"검증 LLM 호출 오류: {e}")
        return {"validation_passed": False, "reason": f"LLM 호출 오류: {e}"}


# ── 기사 1개 처리 ──────────────────────────────────────────────────────────────

def process_article(client, article, prefetched_content):
    """단일 기사에 대해 요약 생성 + 착시 검증 수행. 결과 dict 반환."""
    url = article["url"]
    snippet = article.get("content_snippet", "")
    content = prefetched_content  # 미리 fetch된 내용 재사용 (이중 fetch 제거)

    summary_lines, fallback_used = generate_summary_with_retry(client, content, snippet, url)
    if not summary_lines:
        return None

    input_for_validation = content if content else snippet
    validation = validate_summary(client, input_for_validation, summary_lines, fallback_used)

    log.info(f"[{'PASS' if validation['validation_passed'] else 'FAIL'}] {article['title'][:50]}")

    return {
        "rank": article["rank"],
        "title": article["title"],
        "source": article["source"],
        "source_type": article.get("source_type", ""),
        "url": url,
        "published_at": article.get("published_at"),
        "topic": article.get("topic", "기타"),
        "summary": summary_lines,
        "validation_passed": validation["validation_passed"],
        "validation_reason": validation.get("reason", ""),
        "replaced_from_candidate": False,
        "original_rank": article["rank"],
    }


# ── 메인 파이프라인 ────────────────────────────────────────────────────────────

def run(date_str):
    input_path = OUTPUT_DIR / f"scored_articles_{date_str}.json"
    if not input_path.exists():
        log.error(f"입력 파일 없음: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        scored = json.load(f)

    top5 = scored.get("top5", [])
    candidates = list(scored.get("candidates", []))

    if len(top5) < 5:
        log.error(f"top5 기사 부족: {len(top5)}개")
        sys.exit(1)

    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    # ── STEP A: 전체 URL 병렬 fetch (top5 + candidates 모두) ──────────────────
    all_articles = top5 + candidates
    log.info(f"URL 병렬 fetch 시작: {len(all_articles)}개")
    prefetched = fetch_all_parallel(all_articles)
    log.info("URL 병렬 fetch 완료")

    # ── STEP B: 기사별 요약·검증 (순차 — 후보 대체 로직 보존) ────────────────
    results = []
    excluded = []
    queue = list(top5)
    candidate_iter = iter(candidates)
    candidate_used = 0

    while len(results) < 5:
        if not queue:
            if candidate_used >= MAX_CANDIDATES:
                log.error("후보 기사 소진 → 에스컬레이션 필요")
                sys.exit(2)
            try:
                next_candidate = next(candidate_iter)
                queue.append(next_candidate)
                candidate_used += 1
            except StopIteration:
                log.error("candidates 목록 소진")
                sys.exit(2)

        article = queue.pop(0)
        content = prefetched.get(article["url"])
        result = process_article(client, article, content)

        if result is None:
            log.warning(f"요약 생성 실패 → 제외: {article['title'][:50]}")
            excluded.append({"id": article.get("id"), "title": article["title"], "reason": "요약 생성 실패"})
            continue

        if result["validation_passed"]:
            # 후보 대체 기사인 경우 rank 재조정
            if article not in top5:
                result["replaced_from_candidate"] = True
                result["rank"] = len(results) + 1
            results.append(result)
        else:
            log.warning(f"착시 감지 → 제외: {article['title'][:50]} / {result['validation_reason']}")
            excluded.append({
                "id": article.get("id"),
                "title": article["title"],
                "reason": f"착시 감지: {result['validation_reason']}",
            })

    # ── STEP C: 저장 ──────────────────────────────────────────────────────────
    output = {
        "published_date": date_str,
        "generated_at": datetime.now(KST).isoformat(),
        "articles": results,
        "excluded_articles": excluded,
    }

    output_path = OUTPUT_DIR / f"summaries_{date_str}.json"
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"저장 완료: {output_path}")
    log.info(f"결과: {len(results)}개 통과 / {len(excluded)}개 제외")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="기사 요약·검증 스크립트")
    parser.add_argument("--date", required=True, help="처리 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
