"""Build 엔티티의 계약을 잠근다 (#67, 사용자 승인 2026-08-11).

이 엔티티의 값어치는 레코드가 있다는 게 아니라 **역방향 조회가 된다**는 데 있다 —
「이 스킬을 쓰는 메타 빌드는?」. 그게 되려면 세 가지가 동시에 참이어야 하고, 셋 중
하나만 어긋나도 **조용히** 쓸모가 없어진다:

1. 레코드가 `knowledge/game-data/` 안에 있어야 한다 — `store.load()`가 거기만 스캔한다.
   (제안 원안은 `knowledge/builds/`였는데, 거기 두면 로더가 못 봐서 도구에 안 보인다.)
2. `uses` 관계가 어휘에 있어야 한다.
3. `uses` 대상이 **실존 id**여야 한다 — 참조 무결성이 깨지면 KB 로드 자체가 실패한다.
"""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.kb.store import load


@pytest.fixture(scope="module")
def builds() -> list:
    return [r for r in load().records.values() if r.type == "Build"]


def test_builds_live_where_the_loader_can_see_them(builds: list) -> None:
    """`game-data/` 밖이면 `search_kb`·`related`가 통째로 못 본다."""
    assert builds, "Build 레코드가 하나도 로드되지 않았다 — 배치를 확인할 것"
    game_data = knowledge_dir() / "game-data"
    for record in builds:
        assert game_data in record.path.parents, (
            f"{record.id}가 game-data/ 밖에 있다({record.path}) — store.load()가 못 본다"
        )


def test_uses_edges_point_at_real_records(builds: list) -> None:
    """`uses` 대상이 실존해야 역방향 조회가 성립한다 (참조 무결성은 로더도 검사한다)."""
    known = set(load().records)
    for record in builds:
        targets = [e["target"] for e in record.raw.get("relations", []) if e["rel"] == "uses"]
        assert targets, f"{record.id}에 uses 간선이 없다 — 역방향 조회가 안 된다"
        missing = [t for t in targets if t not in known]
        assert not missing, f"{record.id}의 uses 대상이 KB에 없다: {missing}"


def test_every_build_declares_its_coupling(builds: list) -> None:
    """⑧ 공수 결합은 **분류가 목적**이라 비워 두면 축이 죽는다.

    4유형은 실측 분류다 — 0.5 메타 8종에서 넷 다 관찰됐고, 그 분포가
    "상위 빌드는 자원을 공유한다"는 초기 가설을 기각했다.
    """
    kinds = {r.raw["data"]["coupling"]["kind"] for r in builds}
    assert kinds <= {
        "shared-resource",
        "separate",
        "offense-feeds-defense",
        "defense-action-feeds-offense",
    }


def test_transfer_axis_is_recorded(builds: list) -> None:
    """③ 전달 장치가 이 모델의 핵심이다 — 스택과 딜 사이의 다리.

    담체·스택만 적으면 「무엇을 쌓나」는 알아도 **「그게 왜 딜이 되나」**를 잃는다.
    다리가 없는 빌드(중독처럼 히트가 곧 강도)는 그 사실을 명시하게 한다.
    """
    for record in builds:
        transfer = record.raw["data"]["offense"].get("transfer")
        assert transfer, f"{record.id}에 transfer 축이 비어 있다 — 없으면 없다고 적을 것"
