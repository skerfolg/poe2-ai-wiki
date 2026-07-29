"""ingest 소스 설정 (KB_INGEST §1).

poe2db: 정중한 스크래핑 — 패치당 1회, 레이트리밋, 원시 전량 캐시(재요청 금지).
"""

from __future__ import annotations

from dataclasses import dataclass

POE2DB_BASE = "https://poe2db.tw"

USER_AGENT = "poe2-ai-wiki-ingest/0.1 (personal KB project; contact: sk.erfolg@gmail.com)"

# 기본 요청 간격(초) — robots엔 제한이 없지만 정중함 정책으로 자체 부과
DEFAULT_RATE_SECONDS = 1.0

LANGS = ("us", "kr")  # en/ko 쌍 수집 (D7: 한/영 용어)


@dataclass(frozen=True)
class Category:
    """poe2db 카테고리 = 목록 페이지 1장 + 상세 N장."""

    key: str
    listing_path: str  # 예: /us/Skill_Gems
    count_prefix: str  # 헤더의 개수 표기 접두 (예: "Skill Gems /427")
    extractor: str = "tables"  # tables | cards (목록 페이지 구조)


# P1b 1차 범위: 젬 4종 (uniques·modifiers·passives는 파서와 함께 확장)
# lineage-supports: 위키형 페이지(카드 구조), 보스/장소 페이지 혼입 → parse가 젬만 판별
CATEGORIES: dict[str, Category] = {
    "skill-gems": Category("skill-gems", "/us/Skill_Gems", "Skill Gems"),
    "support-gems": Category("support-gems", "/us/Support_Gems", "Support Gems"),
    "spirit-gems": Category("spirit-gems", "/us/Spirit_Gems", "Spirit Gems"),
    "lineage-supports": Category(
        "lineage-supports", "/us/Lineage_Supports", "lineage GemTags", extractor="cards"
    ),
}
