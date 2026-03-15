"""
Article Scorer Script
역할: raw_articles_{날짜}.json을 읽어 AI 관련도 점수화 후 scored_articles_{날짜}.json 저장
호출: Analyzer Agent
실행: python .claude/skills/article-scorer/scripts/score_articles.py --date YYYY-MM-DD
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from Levenshtein import ratio as lev_ratio

ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = ROOT / "config" / "rss_sources.yaml"
OUTPUT_DIR = ROOT / "output"

TOP_N = 5
CANDIDATE_N = 5
TITLE_DUP_THRESHOLD = 0.85   # 제목 유사도 85% 이상 → 중복
MAX_SAME_SOURCE_IN_TOP = 3   # 동일 출처 top5 상한

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_trust_map(sources):
    """소스명 → trust_weight 딕셔너리"""
    return {s["name"]: s.get("trust_weight", 1.0) for s in sources}


def build_source_type_map(sources):
    """소스명 → source_type 딕셔너리"""
    return {s["name"]: s.get("type", "기타") for s in sources}


def is_within_hours(published_at_str, hours=24):
    if not published_at_str:
        return False
    try:
        dt = datetime.fromisoformat(published_at_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return dt >= cutoff
    except Exception:
        return False


def calc_score(article, keywords_high, keywords_medium, trust_map, source_type_map):
    """AI 관련도 점수 계산 (0~100 기준, trust_weight 적용)"""
    title = article.get("title", "").lower()
    snippet = (article.get("content_snippet") or "").lower()
    source = article.get("source", "")
    source_type = source_type_map.get(source, article.get("source_type", "기타"))

    score = 0

    # 제목 키워드
    for kw in keywords_high:
        if kw.lower() in title:
            score += 40
            break
    for kw in keywords_medium:
        if kw.lower() in title:
            score += 20
            break

    # 본문 snippet 키워드
    for kw in keywords_high + keywords_medium:
        if kw.lower() in snippet:
            score += 20
            break

    # 출처 보너스 (국내 언론 대상)
    if source_type == "국내":
        score += 10

    # 최신성 (+10: 24시간 이내)
    if is_within_hours(article.get("published_at"), hours=24):
        score += 10

    # 신뢰도 가중치
    trust = trust_map.get(source, 1.0)
    score = round(score * trust)

    return min(score, 130)  # 상한 캡 (trust로 130까지 가능)


def classify_topic(article, source_type_map):
    """토픽 분류 (규칙 기반)"""
    text = (
        (article.get("title") or "") + " " +
        (article.get("content_snippet") or "")
    ).lower()

    bigtech_kw = ["openai", "anthropic", "google", "deepmind", "meta ai", "microsoft",
                  "gpt", "claude", "gemini", "llama", "copilot"]
    newtech_kw = ["model", "모델", "research", "연구", "benchmark", "발표", "출시",
                  "multimodal", "멀티모달", "rag", "agent", "에이전트"]
    market_kw = ["investment", "투자", "acquisition", "인수", "funding", "ipo",
                 "revenue", "매출", "startup", "스타트업"]
    issue_kw = ["ethics", "윤리", "bias", "편향", "lawsuit", "소송", "controversy",
                "논란", "accident", "사고", "safety", "안전"]
    policy_kw = ["regulation", "규제", "policy", "정책", "법", "law", "legislation",
                 "government", "정부", "eu ai act", "ai act"]

    for kw in policy_kw:
        if kw in text:
            return "정책규제"
    for kw in issue_kw:
        if kw in text:
            return "AI이슈"
    for kw in market_kw:
        if kw in text:
            return "시장동향"
    for kw in bigtech_kw:
        if kw in text:
            return "빅테크동향"
    for kw in newtech_kw:
        if kw in text:
            return "신기술트렌드"
    return "기타"


def dedup_by_title(articles):
    """제목 유사도 85% 이상 중복 제거 (높은 점수 기사 유지)"""
    kept = []
    for article in articles:
        title = article["title"].lower()
        is_dup = False
        for k in kept:
            if lev_ratio(title, k["title"].lower()) >= TITLE_DUP_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            kept.append(article)
    return kept


def apply_diversity(ranked, top_n):
    """동일 출처가 top_n 내에 MAX_SAME_SOURCE_IN_TOP 초과 시 뒤로 밀기"""
    source_count = {}
    result = []
    deferred = []

    for article in ranked:
        src = article["source"]
        count = source_count.get(src, 0)
        if count < MAX_SAME_SOURCE_IN_TOP:
            result.append(article)
            source_count[src] = count + 1
        else:
            deferred.append(article)

        if len(result) >= top_n:
            break

    return result + deferred


def run(date_str):
    input_path = OUTPUT_DIR / f"raw_articles_{date_str}.json"
    if not input_path.exists():
        log.error(f"입력 파일 없음: {input_path}")
        sys.exit(1)

    config = load_config()
    sources = config.get("sources", [])
    keywords_high = config.get("ai_keywords", {}).get("high_weight", [])
    keywords_medium = config.get("ai_keywords", {}).get("medium_weight", [])
    trust_map = build_trust_map(sources)
    source_type_map = build_source_type_map(sources)

    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)

    articles = raw.get("articles", [])
    log.info(f"입력 기사 수: {len(articles)}")

    # 점수 계산 + 토픽 분류
    for a in articles:
        a["score"] = calc_score(a, keywords_high, keywords_medium, trust_map, source_type_map)
        a["topic"] = classify_topic(a, source_type_map)
        a["duplicate_of"] = None

    # 점수 내림차순 정렬
    articles.sort(key=lambda a: a["score"], reverse=True)

    # 제목 유사도 중복 제거
    articles = dedup_by_title(articles)
    log.info(f"중복 제거 후: {len(articles)}개")

    # 다양성 보정 후 순위 부여
    articles = apply_diversity(articles, top_n=TOP_N + CANDIDATE_N)

    if len(articles) < TOP_N + CANDIDATE_N:
        log.warning(f"기사 부족: {len(articles)}개 (필요: {TOP_N + CANDIDATE_N}개)")
        if len(articles) < TOP_N:
            log.error("top5 확보 실패 → 에스컬레이션 필요")
            sys.exit(1)

    top5 = []
    for i, a in enumerate(articles[:TOP_N]):
        a["rank"] = i + 1
        top5.append(a)

    candidates = []
    for i, a in enumerate(articles[TOP_N:TOP_N + CANDIDATE_N]):
        a["rank"] = TOP_N + i + 1
        candidates.append(a)

    # 결과 출력
    log.info(f"TOP 5:")
    for a in top5:
        log.info(f"  #{a['rank']} [{a['score']}점] [{a['topic']}] {a['title'][:60]}")
    log.info(f"후보 {len(candidates)}개 선정 완료")

    output_path = OUTPUT_DIR / f"scored_articles_{date_str}.json"
    result = {
        "scored_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone(__import__("datetime").timedelta(hours=9))
        ).isoformat(),
        "source_date": date_str,
        "top5": top5,
        "candidates": candidates,
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log.info(f"저장 완료: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="기사 점수화·선별 스크립트")
    parser.add_argument("--date", required=True, help="처리 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
