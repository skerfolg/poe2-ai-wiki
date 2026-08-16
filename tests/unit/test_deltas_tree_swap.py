"""트리만 바뀌면 `compute_tree`로 잰다 — 그리고 **토대를 틀리지 않는다** (#70 후속).

데몬의 `TREE` 명령은 로드된 빌드의 트리만 갈아 끼워 스킬 재구성(+3.16초/호출)을
건너뛴다(3.15초 → 0.29초, 10.8배). 문제는 **무엇이 올라가 있는지**다 — 중간에 다른
스펙을 통째로 올리면 그 뒤의 `compute_tree`는 엉뚱한 빌드 위에서 재는데, 값이
그럴듯해서 조용히 틀린다. 여기서 잠그는 것이 그 경계다.
"""

from __future__ import annotations

import dataclasses

from pok.engine.tree.deltas import _Measurer, _tree_only
from pok.pob.buildxml import BuildSpec, ItemSpec, JewelSpec


class _Result:
    def __init__(self, stats: dict[str, float]) -> None:
        self.stats = stats
        self.pruned_nodes: tuple[int, ...] = ()


class _Daemon:
    """호출 종류를 그대로 기록하는 가짜 데몬. 로드 상태는 **자기가** 들고 있다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []
        self._loaded: BuildSpec | None = None

    @property
    def loaded_spec(self) -> BuildSpec | None:
        return self._loaded

    def compute_build(self, spec: BuildSpec) -> _Result:
        self.calls.append(("build", tuple(spec.tree_nodes)))
        self._loaded = spec
        return _Result({"CombinedDPS": 100.0 * len(spec.tree_nodes)})

    def compute_tree(self, nodes: tuple[int, ...]) -> _Result:
        self.calls.append(("tree", tuple(nodes)))
        return _Result({"CombinedDPS": 100.0 * len(nodes)})


def _spec(**kw) -> BuildSpec:
    return BuildSpec(class_name="Witch", ascendancy="Witch1", tree_nodes=(1, 2), **kw)


def test_트리만_바뀌면_트리_명령으로_잰다() -> None:
    base = _spec()
    d = _Daemon()
    m = _Measurer(d, base)
    m.base()
    m.measure(dataclasses.replace(base, tree_nodes=(1, 2, 3)))

    assert d.calls == [("build", (1, 2)), ("tree", (1, 2, 3))]


def test_아이템이_바뀌면_통째로_올린다() -> None:
    """주얼을 꽂는 변형은 아이템이 바뀐다 — `compute_tree`로는 반영되지 않는다."""
    base = _spec()
    d = _Daemon()
    m = _Measurer(d, base)
    m.base()
    with_jewel = dataclasses.replace(
        base, tree_nodes=(1, 2, 3), jewels=(JewelSpec(socket_node_id=3, text="x"),)
    )
    m.measure(with_jewel)

    assert d.calls[-1][0] == "build"


def test_다른_빌드가_올라가_있으면_기준을_다시_올린다() -> None:
    """⚠ 이게 조용히 틀리던 자리다. 주얼 변형을 잰 **직후** 트리 변형을 재면
    토대가 그 주얼 빌드다 — 기준을 다시 올린 뒤에 트리를 갈아 끼워야 한다."""
    base = _spec()
    d = _Daemon()
    m = _Measurer(d, base)
    m.base()
    m.measure(dataclasses.replace(base, tree_nodes=(1, 2, 3), jewels=(JewelSpec(3, "x"),)))
    m.measure(dataclasses.replace(base, tree_nodes=(1, 2, 4)))

    assert [c[0] for c in d.calls] == ["build", "build", "build", "tree"], (
        "기준 재로드 없이 tree를 부르면 주얼 빌드 위에서 잰다"
    )
    assert d.calls[-2] == ("build", (1, 2)), "다시 올린 것은 기준 스펙이어야 한다"
    assert d.calls[-1] == ("tree", (1, 2, 4))


def test_속성_선택이_다르면_트리_명령을_쓰지_않는다() -> None:
    """`attribute_choices`는 XML `hashOverrides`가 되는데, `TREE`는 **로드된 빌드의**
    hashOverrides를 그대로 넘긴다. 그 차이로 조용히 틀린 전력이 있다
    (2026-08-13: Accuracy 846 → 636, DPS 1.4%)."""
    base = _spec()
    variant = dataclasses.replace(base, tree_nodes=(1, 2, 3), attribute_choices=((3, "str"),))
    assert not _tree_only(base, variant)

    d = _Daemon()
    m = _Measurer(d, base)
    m.base()
    m.measure(variant)
    assert d.calls[-1][0] == "build"


def test_장비가_다르면_트리만_바뀐_것이_아니다() -> None:
    base = _spec()
    variant = dataclasses.replace(
        base, tree_nodes=(1, 2, 3), items=(ItemSpec(slot="Weapon 1", text="Foo"),)
    )
    assert not _tree_only(base, variant)


def test_트리가_같아도_판정은_성립한다() -> None:
    """노드가 그대로면 `_tree_only`는 참이다 — 자기 자신과의 비교가 무너지면
    기준 재로드 판정이 통째로 어긋난다."""
    base = _spec()
    assert _tree_only(base, base)
