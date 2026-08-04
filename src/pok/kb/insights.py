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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pok.common.paths import knowledge_dir
from pok.kb.store import atomic_write

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


def dump_front_matter(meta: Mapping[str, str]) -> str:
    """front matter 직렬화 — 만들 때도 고칠 때도 이 한 곳을 쓴다."""
    lines = [f"{k}: {v}" for k, v in meta.items() if v not in (None, "")]
    return _FENCE + "\n" + "\n".join(lines) + "\n" + _FENCE + "\n"


def patch_front_matter(
    path: Path,
    updates: Mapping[str, str | None],
    *,
    allow_drop: Iterable[str] = (),
) -> Path:
    """인사이트 front matter를 **부분 갱신**한다 — 정본 쓰기의 인사이트판 (B-8).

    `store.patch_records`와 같은 계약을 쓴다. 그 계약을 레코드에만 두니 같은 사고가
    인사이트 쪽에서 났다(실측 2026-08-04: `promoted_to` 계보 소실) — 층이 다르면
    다른 문제로 보이지만 원인은 하나, "부분 갱신"을 "전체 교체"로 하는 것이다.

      · 주지 않은 키는 **보존**한다 (전체 교체 아님)
      · `None`은 삭제 — 근거 있는 제거의 표현
      · 명시(None·`allow_drop`) 없이 키가 사라지면 **거부**한다
      · 본문은 건드리지 않고, 쓰기는 원자적이다

    쓰기 지점이 흩어져 있으면 각자 파싱·재작성을 재구현하고 한 곳만 빠뜨려도
    값이 날아간다 — B-6이 레코드에서 없앤 결함과 같다.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise ValueError(f"front matter 없음: {path.name} — 계보 없는 파일은 갱신 대상이 아니다")
    end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == _FENCE)

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()

    merged: dict[str, str] = dict(meta)
    for key, new_value in updates.items():
        if new_value is None:
            merged.pop(key, None)
        else:
            merged[key] = new_value

    lost = sorted(
        set(meta) - set(merged) - {k for k, v in updates.items() if v is None} - set(allow_drop)
    )
    if lost:
        raise ValueError(
            f"{path.name}: 갱신이 기존 항목 {len(lost)}건을 지운다 — 근거 없는 소실 거부: {lost}"
        )

    body = "\n".join(lines[end + 1 :]).strip("\n")
    atomic_write(path, dump_front_matter(merged) + "\n" + body + "\n")
    return path


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
