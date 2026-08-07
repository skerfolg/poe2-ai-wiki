"""소환수 스탯 분리 — "이 줄은 누구의 것인가"를 **레코드 쪽에서** 잠근다 (#8-b).

poe2db 스킬 페이지는 그 스킬이 소환하는 실체의 스탯 카드를 같은 페이지에 싣는다.
파서가 페이지의 전 `.Stats`를 훑는 바람에 그 줄들이 플레이어 스킬의 `stats`로
들어왔다 — 실측 2026-08-07: 오라인 `skill.malice`가 "Fires 5 additional Projectiles"를
달고 있었고, KB **22건**이 그렇게 오염됐다.

B-11(모디파이어)과 같은 뿌리다: **누구의 줄인지 구분하지 않는 집계.** 그래서 고치는
방식도 같다 — 집계 축을 "페이지 전체"에서 "실체별"로 바꾼다. 증상(특정 문구)만
검사하면 축을 바꿔 재발하므로, 여기서는 **원시에서 다시 유도해 대조**한다: 파서를
어떻게 고치든 몬스터 카드의 줄이 `stats`에 있으면 걸린다.
"""

from __future__ import annotations

import pathlib

import pytest
from bs4 import BeautifulSoup

from pok.common.paths import knowledge_dir
from pok.kb.ingest.parse import _mod_lines, _monster_owner, parse_detail
from pok.kb.store import load as store_load

RAW = pathlib.Path("artifacts/ingest-raw/0.5.4b/poe2db/us")

# 원시 스냅샷은 gitignore되는 파생물이라 CI에 없다 (test_gem_stats와 같은 규약).
pytestmark = pytest.mark.skipif(
    not RAW.is_dir(), reason="artifacts/ingest-raw 스냅샷 없음 (수집 후에만 검증 가능)"
)


def _page(slug: str) -> object:
    return parse_detail((RAW / f"{slug}.html").read_text(encoding="utf-8", errors="replace"))


def _monster_only_lines(slug: str) -> set[str]:
    """원시 페이지에서 **몬스터 카드에만** 있는 줄 — 플레이어 `stats`에 있으면 오염이다."""
    soup = BeautifulSoup(
        (RAW / f"{slug}.html").read_text(encoding="utf-8", errors="replace"), "html.parser"
    )
    player: set[str] = set()
    monster: set[str] = set()
    for block in soup.select(".Stats"):
        bucket = monster if _monster_owner(block) is not None else player
        for node in block.select(".explicitMod, .implicitMod, .qualityMod, .secondaryQualityMod"):
            bucket.update(_mod_lines(node))
    return monster - player


def _slug_of(record: dict) -> str | None:
    for src in record.get("sources", []):
        ref = str(src.get("ref", ""))
        if src.get("src") == "poe2db" and "/us/" in ref:
            return ref.rsplit("/us/", 1)[1]
    return None


def test_no_kb_gem_carries_monster_card_lines() -> None:
    """**전수 대조** — 젬 레코드의 효과 문구에 몬스터 카드의 줄이 하나도 없어야 한다.

    수록 22건이 여기서 걸렸었다. 특정 문구가 아니라 원시에서 유도한 집합과 대조하므로
    새 패치에서 새 페이지가 오염돼도 잡힌다.
    """
    store = store_load(knowledge_dir().parent)
    dirty: dict[str, list[str]] = {}
    for record in store.records.values():
        if record.type not in ("Skill", "Support"):
            continue
        slug = _slug_of(record.raw)
        if not slug or not (RAW / f"{slug}.html").exists():
            continue
        foreign = _monster_only_lines(slug)
        if not foreign:
            continue
        data = record.raw.get("data", {})
        for key in ("stats", "implicit_stats", "quality_stats"):
            hit = [line for line in data.get(key, []) if line in foreign]
            if hit:
                dirty.setdefault(record.id, []).extend(hit)
    assert not dirty, f"몬스터 카드의 줄이 플레이어 효과 문구에 섞였다: {list(dirty)[:5]}"


def test_minion_stats_keep_the_data_under_the_entity_name() -> None:
    """버리지 않는다 — 소환수 수치는 **실체 이름과 함께** 남는다.

    해골 서리 마법사의 Ice Armour 수치는 이 카드에만 있다. 통째로 버리면 소환수
    빌드를 설계할 때 원시 페이지를 다시 뒤져야 한다(사용자 판정 2026-08-07).
    """
    page = _page("Skeletal_Frost_Mage")
    entities = {e["entity"]: e["stats"] for e in page.minion_stats}  # type: ignore[attr-defined]
    assert "Skeletal Frost Mage" in entities, f"실체 이름이 없다: {list(entities)}"
    joined = " ".join(entities["Skeletal Frost Mage"])
    assert "Ice Armour" in joined and "Cold Damage" in joined
    # 그리고 그 줄들은 플레이어 `stats`엔 없다
    assert not [s for s in page.stats if "Ice Armour" in s]  # type: ignore[attr-defined]


def test_unrelated_monsters_sharing_a_name_are_dropped() -> None:
    """`Malice`(오라)의 몬스터 탭은 **이름만 같은 딜리리움 몬스터**다 — 버린다.

    탭 id로는 못 가른다: 그 탭도 `MaliceDeliriumMinion4`처럼 "Minion"을 달고 있다.
    가르는 것은 **스킬 자신의 문구가 그 실체를 Minion이라 부르는가**이다.
    """
    page = _page("Malice")
    assert page.minion_stats == []  # type: ignore[attr-defined]
    joined = " ".join(page.stats)  # type: ignore[attr-defined]
    assert "Fires 5 additional Projectiles" not in joined
    assert "Physical Damage" not in joined, "오라가 물리 피해를 가질 리 없다"
    # 정상 줄은 그대로 남는다 — 오염 제거가 본문을 깎으면 안 된다
    assert any("Critical Weakness" in s for s in page.stats)  # type: ignore[attr-defined]


def test_summoner_skills_declare_their_minion() -> None:
    """소환수 스킬 20건은 전부 `minion_stats`를 받는다 (분류가 과잉 배제하지 않는다)."""
    for slug in ("Skeletal_Warrior", "Raise_Zombie", "Azmerian_Wolf", "Ravenous_Swarm"):
        assert _page(slug).minion_stats, f"{slug}: 소환수 스탯이 비었다"  # type: ignore[attr-defined]


def test_minion_stats_are_searchable() -> None:
    """수록만으로는 부족하다 — **찾을 수 있어야** 한다.

    분리 전에는 (주인이 틀렸을 뿐) `stats`에 있어서 검색은 됐다. 색인하지 않고
    옮기면 "찾을 수 없는 곳으로 치운" 셈이 되고, 세션은 파일 탐색으로 도피한다
    (철칙 5 따름정리 — 금지하려면 대안 경로를 먼저 만든다).
    """
    from pok.index.search import search

    assert any(h.id == "skill.skeletal-frost-mage" for h in search(query="Ice Armour", limit=8))
    assert any(
        h.id == "skill.azmerian-wolf" for h in search(query="Summons 7 Spirit Wolves", limit=8)
    )


def test_minion_stats_is_registered_as_machine_generated() -> None:
    """새 data 키는 `_MACHINE_DATA_KEYS`에 등록해야 재수집이 갱신한다."""
    from pok.kb.ingest.merge import _MACHINE_DATA_KEYS

    assert "minion_stats" in _MACHINE_DATA_KEYS
