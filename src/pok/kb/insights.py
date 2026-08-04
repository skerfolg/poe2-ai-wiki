"""인사이트 정본(`knowledge/insights/*.md`) 로드 — 학습 루프의 산출물 읽기.

인사이트는 KB 레코드가 아니다. 레코드는 게임 데이터(젬·모드·노드)의 *사실*이고,
인사이트는 그 사실들 위에서 얻은 **판단·규율**이다 — "무엇이 안 되는가", "왜
갈리는가" 같은 것들. 그래서 스키마도 저장 형식도 다르다(마크다운 + front matter).

읽는 쪽에서는 이 차이가 중요하다: 레코드는 조회해서 값을 쓰지만, 인사이트는
**설계 전에 통째로 읽어 판단의 전제로 삼는** 물건이었다. 건수가 적을 때는 그게
가능했지만 쌓일수록 토큰이 불어난다 — 그래서 검색 경로가 필요하다(P5 잔여, RAG).

front matter는 `promote_insight`가 박는 계보다(라벨·검증 주체·피드백 id·패치).
파싱은 의존성 없이 한다 — `key: value` 한 줄씩이고 값에 콜론이 들어갈 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pok.common.paths import knowledge_dir

_FENCE = "---"


@dataclass(frozen=True)
class Insight:
    """인사이트 1건. `meta`는 front matter 원본 그대로(계보를 잃지 않는다)."""

    id: str
    slug: str
    title: str
    label: str
    scope: str
    body: str
    meta: dict[str, str]
    path: Path

    @property
    def verified_by(self) -> str:
        return self.meta.get("verified_by", "")

    @property
    def promoted_to(self) -> list[str]:
        """이 인사이트의 사실이 반영된 canonical 레코드 id들 (사다리 2칸)."""
        raw = self.meta.get("promoted_to", "")
        return [x.strip() for x in raw.split(",") if x.strip()]

    @property
    def feedback_id(self) -> str:
        return self.meta.get("feedback_id", "")

    @property
    def patch(self) -> str:
        return self.meta.get("patch", "")


def parse_insight(text: str, path: Path) -> Insight:
    """마크다운 1건을 파싱한다. front matter가 없어도 본문은 살린다.

    id·title이 비면 파일명(slug)에서 채운다 — 손으로 쓴 문서가 섞여도 검색에서
    사라지지 않게 하는 게 맞다(누락보다 불완전한 수록이 낫다).
    """
    slug = path.stem
    meta: dict[str, str] = {}
    body = text

    lines = text.splitlines()
    if lines and lines[0].strip() == _FENCE:
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == _FENCE:
                body = "\n".join(lines[i + 1 :]).strip()
                break
            key, sep, value = line.partition(":")
            if sep:
                meta[key.strip()] = value.strip()

    title = ""
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    return Insight(
        id=meta.get("id") or f"insight.{slug}",
        slug=slug,
        title=title or slug,
        label=meta.get("label", "UNVERIFIED"),
        # scope가 없으면 시즌 한정으로 본다 — 검증 안 된 관찰이 항구적 지식
        # 행세를 하지 않게 하는 쪽이 안전한 기본값이다(3계층 사다리)
        scope=meta.get("scope", "season"),
        body=body,
        meta=meta,
        path=path,
    )


def insights_dir(root: Path | None = None) -> Path:
    return knowledge_dir(root) / "insights"


def load_insights(root: Path | None = None) -> tuple[Insight, ...]:
    """정본의 인사이트를 전부 읽는다 (slug 순 — 결정적)."""
    directory = insights_dir(root)
    if not directory.exists():
        return ()
    return tuple(
        parse_insight(path.read_text(encoding="utf-8"), path)
        for path in sorted(directory.glob("*.md"))
    )
