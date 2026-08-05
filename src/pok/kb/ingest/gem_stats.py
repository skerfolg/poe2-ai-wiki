"""젬 효과 문구 전수 수록 (오프라인 재파싱) — 이관 건 2026-08-05.

빌드 세션이 **보조 젬 배율을 단 한 건도 인용하지 못했다.** `support.incision`의
`data`에 효과 수치가 하나도 없었기 때문인데, 전수를 보니 절개 하나가 아니라
**Support 537건 전량**이 그랬다. `description`(산문)·`tier`·`color`뿐이었다.

## 원인

파서가 설명을 `og:description`(SEO 메타)에서 가져왔다. 실제 수치는 `.Stats` 블록의
`.explicitMod`에 있고, 파서는 그 블록을 **읽기는 했지만** 비용·점유·시전시간만
뽑고 **효과 문구 줄은 버렸다**.

B-4와 같은 뿌리의 변종이다. B-4는 그 블록을 *안 읽은* 것이라 스캔 **범위**를
넓혀 고쳤는데, 이번은 읽고도 **추출 대상**에 없던 것이다. 범위만 고치고 대상은
손대지 않아서 축을 바꿔 재발했다(B-6→B-7이 파일 층 → 필드 층으로 재발한 것과 같다).

Passive는 이미 `stats`/`stats_en`으로 효과 문구를 100% 담고 있었다 — **규약은
있었고 젬 경로에만 적용되지 않았다.** 그래서 필드 이름도 `stats`로 맞춘다.

## 이 모듈

재수집 없이 원시 스냅샷(`artifacts/ingest-raw/<patch>/poe2db/us/*.html`)을 다시
파싱해 기존 레코드에 붙인다. 재수집 경로(parse→process→merge)도 함께 고쳤으므로
다음 패치부터는 자동으로 들어온다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir
from pok.kb.ingest.parse import parse_detail
from pok.kb.store import load as store_load
from pok.kb.store import patch_records

_STAT_KEYS = ("stats", "implicit_stats", "quality_stats")
# 효과 문구를 가질 만한 타입 — 아이템·모드는 다른 경로로 이미 수록돼 있다
_GEM_TYPES = frozenset({"Skill", "Support"})


def _slug_of(record: dict[str, Any]) -> str | None:
    for src in record.get("sources", []):
        ref = str(src.get("ref", ""))
        if src.get("src") == "poe2db" and "/us/" in ref:
            return ref.rsplit("/us/", 1)[1]
    return None


def apply_gem_stats(
    raw_dir: Path,
    knowledge: Path | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """젬 레코드에 효과 문구를 붙이고 **커버리지를 리포트로 낸다**.

    누락을 조용히 넘기지 않는 게 요점이다 — `missing`이 0이 아니면 그건 파서가
    못 뽑았거나 원시가 없다는 신호다.
    """
    pages = raw_dir / "poe2db" / "us"
    root = (knowledge or knowledge_dir()).parent
    store = store_load(root)

    updates: dict[str, dict[str, Any]] = {}
    missing_page: list[str] = []
    no_mods: list[str] = []
    total = 0

    for record in store.records.values():
        if record.type not in _GEM_TYPES:
            continue
        total += 1
        slug = _slug_of(record.raw)
        page_path = pages / f"{slug}.html" if slug else None
        if page_path is None or not page_path.exists():
            missing_page.append(record.id)
            continue
        page = parse_detail(page_path.read_text(encoding="utf-8", errors="replace"))
        patch = {k: getattr(page, k) for k in _STAT_KEYS if getattr(page, k)}
        if patch:
            updates[record.id] = patch
        else:
            # 원시는 있는데 문구가 안 나왔다 — 정말 없는 젬일 수도, 파서 갭일 수도
            no_mods.append(record.id)

    if write and updates:
        patch_records(updates, root=root)

    return {
        "gem_records": total,
        "with_stats": len(updates),
        "coverage_pct": round(len(updates) / total * 100.0, 1) if total else 0.0,
        "missing_raw_page": sorted(missing_page),
        "no_mod_lines": sorted(no_mods),
    }
