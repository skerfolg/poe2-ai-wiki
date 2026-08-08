"""아이템 문구 파싱 갭 — PoB 실측과 정본 표기가 어긋나지 않는지 (제안 D 아이템 편).

트리판(`test_tree_parse_gaps.py`)과 같은 목적이다: 스냅샷을 올리고 감사를 다시 돌리지
않으면 표기가 낡는데, 그걸 **문서 규율이 아니라 테스트가** 잡는다(철칙 5).

⚠ 여기서는 **1단계(대표 베이스)만** 돌린다. 전체 감사는 베이스 20종 = PoB 부팅 20회라
테스트로 돌리기엔 무겁다. 대신 그 20종이 판정을 하나도 바꾸지 않았다는 사실을 함께
확인한다(`rescued_by_other_base == 0` — `parseMod`가 베이스와 무관하기 때문). 그 전제가
깨지면 1단계만으로는 부족해지므로, 그때는 이 테스트가 **과잉 검출**로 실패한다.
"""

from __future__ import annotations

import pytest

from pok.kb.store import load as store_load
from pok.pob.buildxml import BuildSpec, ItemSpec, to_xml
from pok.pob.item_parse_gaps import _KIND, _PRIMARY_BASE, _probe, scannable_lines
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

_PROBE_BASE = "Rarity: RARE\nPoK Probe\nAmber Amulet\nItem Level: 100"


@needs_pob_run
def test_정본_표기가_지금_PoB_판정과_같다() -> None:
    """스냅샷을 올리고 `python -m pok.pob.item_parse_gaps`를 안 돌리면 여기서 깨진다."""
    store = store_load()
    batch = {
        record.id: lines
        for record in store.records.values()
        if record.type in ("Modifier", "Item")
        and (lines := scannable_lines(record.raw.get("data") or {}))
    }
    found = _probe(batch, _PRIMARY_BASE, resolve_snapshot(), 1800.0)
    # 파싱 예외(별개 결함)와 다른 kind가 이미 붙은 것은 표기 대상이 아니다 — 빼고 본다.
    errored = {rid for rid, ls in found.items() if any(x.kind == "error" for x in ls)}
    other_kind = {
        rid
        for rid in found
        if ((store.records[rid].raw.get("data") or {}).get("pob_modeling") or {}).get("kind")
        not in (None, _KIND)
    }
    expected = set(found) - errored - other_kind
    recorded = {
        record.id
        for record in store.records.values()
        if ((record.raw.get("data") or {}).get("pob_modeling") or {}).get("kind") == _KIND
    }
    assert expected == recorded, (
        f"정본 표기가 낡았다 — 누락 {sorted(expected - recorded)[:5]} / "
        f"잔존 {sorted(recorded - expected)[:5]}. "
        "`python -m pok.pob.item_parse_gaps`를 다시 돌릴 것"
    )


@needs_pob_run
def test_표기된_접사는_델타가_0이고_대조군은_아니다() -> None:
    """플래그가 실제로 '측정 안 됨'을 뜻하는지 — 양방향으로 건다.

    ⚠ 대조군은 **이 더미 빌드에 실제로 효과가 있는 것**이어야 한다. "증가한 화염 피해"는
    화염 피해원이 없어 0으로 나온다 — 그건 파싱 실패가 아니라 **잴 것이 없는 것**이다.
    """

    def changed(mod: str | None) -> int:
        text = _PROBE_BASE + (f"\n{mod}" if mod else "")
        spec = BuildSpec(
            class_name="Warrior",
            ascendancy="Warrior1",
            level=90,
            items=(ItemSpec(slot="Amulet", text=text),),
        )
        after = run_xml(to_xml(spec))
        before = run_xml(
            to_xml(
                BuildSpec(
                    class_name="Warrior",
                    ascendancy="Warrior1",
                    level=90,
                    items=(ItemSpec(slot="Amulet", text=_PROBE_BASE),),
                )
            )
        )
        return sum(1 for k, v in before.stats.items() if abs(after.stats.get(k, 0.0) - v) > 1e-9)

    # 실측 2026-08-08: 셋 다 0개
    assert changed("40% increased Archon Buff duration") == 0
    assert changed("+50 to maximum Runic Ward") == 0
    # 실측 2026-08-08: 47개
    assert changed("+80 to maximum Life") > 0, "대조군이 0이면 측정 방법 자체가 틀렸다"
