"""
Hallucination Checker Script
역할: 기사 원문 URL을 fetch하여 요약문과 비교, 착시 여부를 LLM으로 검증
호출: Summarizer Agent
실행: python .claude/skills/hallucination-checker/scripts/check_alignment.py
      --url "https://..." --summary '["줄1","줄2","줄3","줄4","줄5"]'
출력: {"validation_passed": true/false, "reason": ""}
"""

import argparse
import io
import json
import logging
import os
import sys
from pathlib import Path

# Windows 콘솔 UTF-8 출력
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

import requests
from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parents[4]
load_dotenv(ROOT / ".env")

TIMEOUT = 10
CONTENT_MAX = 3000   # LLM에 넘길 원문 최대 길이
MODEL = "llama-3.3-70b-versatile"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def fetch_article(url):
    """원문 URL에서 텍스트 추출. 실패 시 None 반환."""
    try:
        resp = requests.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": "AI-Newsletter-Bot/1.1"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        # HTML 태그 제거 (간단한 방식)
        text = resp.text
        # <script>, <style> 제거
        import re
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        # HTML 태그 제거
        text = re.sub(r"<[^>]+>", " ", text)
        # 연속 공백 정리
        text = re.sub(r"\s+", " ", text).strip()
        return text[:CONTENT_MAX]
    except Exception as e:
        log.warning(f"URL fetch 실패 ({url}): {e}")
        return None


def verify_with_llm(article_content, summary_lines, fallback_used=False):
    """LLM으로 요약-원문 착시 여부 검증. {"validation_passed": bool, "reason": str} 반환."""
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    summary_text = "\n".join(
        f"{i+1}. {line}" for i, line in enumerate(summary_lines)
    )

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
        message = client.chat.completions.create(
            model=MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.choices[0].message.content.strip()
        # JSON 파싱
        result = json.loads(raw)
        return {
            "validation_passed": bool(result.get("validation_passed", False)),
            "reason": result.get("reason", ""),
        }
    except json.JSONDecodeError:
        log.warning(f"LLM 응답 JSON 파싱 실패: {raw}")
        return {"validation_passed": False, "reason": "LLM 응답 파싱 오류"}
    except Exception as e:
        log.error(f"LLM 호출 오류: {e}")
        return {"validation_passed": False, "reason": f"LLM 호출 오류: {e}"}


def run(url, summary_lines, fallback_snippet=None):
    article_content = fetch_article(url)
    fallback_used = False

    if not article_content:
        if fallback_snippet:
            log.info("원문 fetch 실패 → fallback(RSS snippet) 사용")
            article_content = fallback_snippet[:CONTENT_MAX]
            fallback_used = True
        else:
            log.error("원문 fetch 실패, fallback 없음 → 검증 불가")
            return {"validation_passed": False, "reason": "원문 fetch 실패, fallback 없음"}

    return verify_with_llm(article_content, summary_lines, fallback_used)


def main():
    parser = argparse.ArgumentParser(description="요약-원문 착시 검증 스크립트")
    parser.add_argument("--url", required=True, help="기사 원문 URL")
    parser.add_argument(
        "--summary",
        required=True,
        help='5줄 요약 (JSON 배열 문자열, 예: \'["줄1","줄2","줄3","줄4","줄5"]\')',
    )
    parser.add_argument(
        "--fallback",
        default="",
        help="원문 fetch 실패 시 대체할 RSS snippet 텍스트",
    )
    args = parser.parse_args()

    summary_lines = json.loads(args.summary)
    if not isinstance(summary_lines, list) or len(summary_lines) != 5:
        print(json.dumps({"validation_passed": False, "reason": "요약이 정확히 5줄이 아님"}, ensure_ascii=False))
        sys.exit(1)

    result = run(args.url, summary_lines, fallback_snippet=args.fallback or None)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
