"""트리 문구 파싱 갭 — PoB 실측과 정본 표기가 어긋나지 않는지 (제안 D).

두 축을 본다:

① **표기가 최신인가** — 정본의 `pob_modeling.kind == "tree-line-unparsed"` 집합이
   지금 PoB가 내는 판정과 같은가. 스냅샷을 올리고 감사를 다시 돌리지 않으면 여기서
   깨진다. 규율을 문서에 적는 대신 **도구가 잡게** 하는 지점이다(철칙 5).

② **표기가 실제로 0을 뜻하는가** — 갭이 붙은 노드를 할당해도 스탯이 안 변하고,
   안 붙은 노드는 변하는가. 이게 성립하지 않으면 플래그는 잡음이다.
   실측 2026-08-07: 집정관 지속시간(5695) 델타 **0개**, 대조군 생명력의 차크라
   (35031) **57개**. 세션이 전자를 "값어치 없음"으로 읽은 것이 백로그 #3이다.
"""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir, project_root
from pok.engine.tree.graph import TreeGraph
from pok.kb.store import load as store_load
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.parse_gaps import _KIND, dump_tree_parse_gaps, scan_parse_gaps
from pok.pob.runner import run_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


needs_pob_run = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

# 전 줄이 미파싱인 집정관 노터블 — 백로그 #3의 원인이 된 계열
_GAP_NODE = 5695  # passive.archon-duration-5695
# 갭이 없는 대조군 — 조건절 없는 순수 생명력 노터블
_CONTROL_NODE = 35031  # passive.chakra-of-life-35031


@pytest.fixture(scope="module")
def dump():  # type: ignore[no-untyped-def]
    return dump_tree_parse_gaps()


@needs_pob_run
def test_정본_표기가_지금_PoB_판정과_같다(dump) -> None:  # type: ignore[no-untyped-def]
    """스냅샷을 올리고 감사를 안 돌리면 여기서 깨진다 — 그게 이 테스트의 목적이다."""
    found, summary = scan_parse_gaps(dump=dump)
    expected = {item.record_id for item in found}
    recorded = {
        record.id
        for record in store_load().records.values()
        if ((record.raw.get("data") or {}).get("pob_modeling") or {}).get("kind") == _KIND
    }
    assert expected == recorded, (
        f"정본 표기가 낡았다 — 누락 {sorted(expected - recorded)[:5]} / "
        f"잔존 {sorted(recorded - expected)[:5]}. "
        "`pok.pob.parse_gaps.apply_parse_flags()`를 다시 돌릴 것"
    )
    # 갭 노드는 전부 KB에 이어져야 한다 — 조용히 버려지면 "전부 표시했다"가 거짓이 된다
    assert summary["unmatched_nodes"] == []


@needs_pob_run
def test_스냅샷_각인이_현재_PoB와_일치(dump) -> None:  # type: ignore[no-untyped-def]
    """어느 PoB 기준 판정인지 레코드가 들고 있어야 낡음을 판별할 수 있다."""
    snap = resolve_snapshot().short
    recorded = {
        ((record.raw.get("data") or {}).get("pob_modeling") or {}).get("snapshot")
        for record in store_load().records.values()
        if ((record.raw.get("data") or {}).get("pob_modeling") or {}).get("kind") == _KIND
    }
    assert recorded == {snap}, f"각인된 스냅샷 {recorded} ≠ 현재 {snap}"


@needs_pob_run
def test_집정관_노터블은_델타가_0이고_대조군은_아니다() -> None:
    """플래그가 실제로 '측정 안 됨'을 뜻하는지 — 양방향으로 확인한다.

    한쪽만 보면 안 된다: 갭 노드가 0인 것만으로는 "원래 효과가 없는 노드"와
    구분되지 않고, 대조군이 변하는 것만으로는 갭의 의미가 서지 않는다.
    """
    graph = TreeGraph(knowledge_dir())
    start = graph.start_of("Warrior")

    def changed_stats(target: int) -> int:
        path = graph.shortest_path({start}, target)
        assert path, f"노드 {target}로 가는 경로가 없다"

        def run(nodes: tuple[int, ...]):  # type: ignore[no-untyped-def]
            spec = BuildSpec(
                class_name="Warrior", ascendancy="Warrior1", level=90, tree_nodes=nodes
            )
            return run_xml(to_xml(spec), requested_nodes=nodes)

        before = run(tuple(path[:-1]))
        after = run(tuple(path))
        assert after.is_tree_legal, f"{target}: PoB가 노드를 잘라냈다 {after.pruned_nodes}"
        return sum(1 for k, v in before.stats.items() if abs(after.stats.get(k, 0.0) - v) > 1e-9)

    assert changed_stats(_GAP_NODE) == 0, (
        "갭 노드인데 스탯이 변했다 — 플래그 의미가 무너졌거나 PoB가 이제 이 문구를 읽는다"
    )
    assert changed_stats(_CONTROL_NODE) > 0, "대조군이 0이면 측정 방법 자체가 틀렸다"


@needs_pob_run
def test_덤프_스크립트가_경로대로_있다() -> None:
    assert (project_root() / "scripts" / "pob_parse_gaps.lua").exists()
