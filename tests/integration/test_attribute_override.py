"""능력치 택1 노드의 선택을 PoB에 전달한다 (이관 5 C13').

`+N to any Attribute` 노드는 PoB 트리에 `isAttribute=true` + `options[]`로 있고
(293개, KB `attribute_choice`와 정확히 일치) `<Tree><Spec><Overrides>`에 저장된다.
그 자리가 없어서 **선택을 표현할 수 없었다** — 전부 기본값으로 계산됐다.

실측: 앵커에서 택1 35개를 빼자 Str 184→79·Dex 165→104·Int 137→27. 한 빌드의
능력치 절반 이상이 이 노드들에서 나온다.
"""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.compute import compute_pob
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import spec_from_dict, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


# PoB를 **실행**하는 테스트다 — LuaJIT과 전체 스냅샷이 필요하다. CI는 카탈로그
# 파일만 sparse-checkout하므로 여기선 skip된다(기존 통합 테스트와 같은 규약).
pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


@pytest.fixture(scope="module")
def connected_attribute_node() -> tuple[int, list[int]]:
    """시작점과 연결된 택1 노드 하나 — 비연결이면 계산에 아예 안 들어간다."""
    graph = TreeGraph(knowledge_dir())
    start = graph.start_of("Warrior")
    for node_id, node in graph.nodes.items():
        if "attribute" not in (node.name_en or "").lower():
            continue
        path = graph.shortest_path({start}, node_id)
        if path and len(path) <= 4:
            return node_id, list(path)
    pytest.skip("연결된 택1 노드를 못 찾았다")


def test_choice_changes_the_measured_attribute(
    connected_attribute_node: tuple[int, list[int]],
) -> None:
    """선택이 실제 계산에 반영돼야 한다 — 표현만 되고 안 먹으면 의미가 없다."""
    node_id, path = connected_attribute_node
    base = {
        "class_name": "Warrior",
        "ascendancy": "Warrior1",
        "level": 90,
        "tree_nodes": path,
    }
    plain = compute_pob(spec_from_dict(base))
    assert not plain.pruned_nodes, "비연결이면 측정 자체가 무효다"

    picked = {
        choice: compute_pob(
            spec_from_dict({**base, "attribute_choices": {str(node_id): choice}})
        ).stats
        for choice in ("str", "dex", "int")
    }
    assert picked["str"]["Str"] == plain.stats["Str"] + 5
    assert picked["dex"]["Dex"] == plain.stats["Dex"] + 5
    assert picked["int"]["Int"] == plain.stats["Int"] + 5


def test_unspecified_node_grants_nothing(
    connected_attribute_node: tuple[int, list[int]],
) -> None:
    """미지정 기본 동작 — 택1 노드는 **아무 능력치도 주지 않는다**(실측 2026-08-05).

    이관 노트가 물은 것이다. 기본이 힘이라고 가정하면 요구치 판정이 어긋난다.
    """
    node_id, path = connected_attribute_node
    with_node = compute_pob(
        spec_from_dict(
            {"class_name": "Warrior", "ascendancy": "Warrior1", "level": 90, "tree_nodes": path}
        )
    ).stats
    without = compute_pob(
        spec_from_dict(
            {
                "class_name": "Warrior",
                "ascendancy": "Warrior1",
                "level": 90,
                "tree_nodes": [n for n in path if n != node_id],
            }
        )
    ).stats
    assert (with_node["Str"], with_node["Dex"], with_node["Int"]) == (
        without["Str"],
        without["Dex"],
        without["Int"],
    )


def test_all_three_attributes_are_always_emitted() -> None:
    """`PassiveSpec.lua:203`이 nil 검사 없이 `strNodes:gmatch(…)`를 부른다.

    빈 축을 생략하면 파싱이 깨져 선택이 엉뚱하게 들어간다 — 실측 2026-08-05에
    세 선택이 전부 같은 결과를 냈다. PoB 자신도 저장할 때 항상 셋을 쓴다(309행).
    """
    xml = to_xml(
        spec_from_dict(
            {
                "class_name": "Warrior",
                "ascendancy": "Warrior1",
                "attribute_choices": {"6744": "str"},
            }
        )
    )
    assert 'strNodes="6744"' in xml
    assert 'dexNodes=""' in xml and 'intNodes=""' in xml


def test_unknown_choice_is_rejected() -> None:
    with pytest.raises(ValueError, match="알 수 없다"):
        spec_from_dict(
            {
                "class_name": "Warrior",
                "ascendancy": "Warrior1",
                "attribute_choices": {"6744": "wisdom"},
            }
        )
