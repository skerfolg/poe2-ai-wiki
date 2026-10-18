"""Limited unique templates cannot inflate the value of every new jewel socket."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from pok.engine.tree.deltas import _jewel_limit_rejection, evaluate_node_deltas
from pok.pob.buildxml import BuildSpec, JewelSpec

PRISM = (
    "Rarity: UNIQUE\nPrism of Belief\nDiamond\nLimited to: 1\n"
    "+3 to Level of all Perfect Strike Skills\nCorrupted"
)
RUBY = "Rarity: RARE\nMeasured Ruby\nRuby\n10% increased Ignite Magnitude"


def _spec(*jewels: JewelSpec) -> BuildSpec:
    return BuildSpec(
        class_name="Mercenary", ascendancy="Mercenary3", tree_nodes=(1, 2, 4), jewels=jewels
    )


@pytest.mark.parametrize(
    ("existing", "candidate", "socket", "rejected"),
    [
        ((JewelSpec(2, PRISM),), PRISM, 3, True),
        ((JewelSpec(2, PRISM),), PRISM, 2, False),
        ((JewelSpec(99, PRISM),), PRISM, 3, False),
        ((JewelSpec(2, PRISM),), RUBY, 3, False),
        ((JewelSpec(2, PRISM),), PRISM.replace("Limited to: 1\n", ""), 3, True),
        (
            (JewelSpec(2, PRISM.replace("Limited to: 1", "Limited to: 2")),),
            PRISM.replace("Limited to: 1", "Limited to: 2"),
            3,
            False,
        ),
        (
            (
                JewelSpec(2, PRISM.replace("Limited to: 1", "Limited to: 2")),
                JewelSpec(4, PRISM.replace("Limited to: 1", "Limited to: 2")),
            ),
            PRISM.replace("Limited to: 1", "Limited to: 2"),
            3,
            True,
        ),
    ],
)
def test_declared_unique_limit_excludes_the_replaced_socket(
    existing: tuple[JewelSpec, ...], candidate: str, socket: int, rejected: bool
) -> None:
    reason = _jewel_limit_rejection(_spec(*existing), candidate, socket)
    assert bool(reason) is rejected
    if reason:
        assert "Prism of Belief" in reason and "Limited to:" in reason


class _Daemon:
    def __init__(self) -> None:
        self.loaded_spec: BuildSpec | None = None
        self.measured: list[BuildSpec] = []

    def compute_build(self, spec: BuildSpec) -> SimpleNamespace:
        self.loaded_spec = spec
        self.measured.append(spec)
        score = sum(100 if "Prism of Belief" in j.text else 10 for j in spec.jewels)
        return SimpleNamespace(stats={"CombinedDPS": score}, pruned_nodes=())

    def compute_tree(self, nodes: tuple[int, ...]) -> SimpleNamespace:
        assert self.loaded_spec is not None
        return self.compute_build(dataclasses.replace(self.loaded_spec, tree_nodes=nodes))


def _graph() -> SimpleNamespace:
    return SimpleNamespace(
        start_of=lambda _: 1,
        shortest_path=lambda base, candidate, *, exclude_nodes=frozenset(): (
            None if candidate in exclude_nodes else (candidate,)
        ),
        nodes={3: SimpleNamespace(kind="jewel-socket", name_en="Socket", name_ko="소켓")},
    )


def test_limited_prism_is_never_measured_twice_and_ruby_is_still_considered() -> None:
    daemon = _Daemon()
    rejected: list[str] = []
    rows = evaluate_node_deltas(
        _spec(JewelSpec(2, PRISM)),
        _graph(),
        [3],
        daemon=daemon,
        stats=("CombinedDPS",),
        jewel_templates=(PRISM, RUBY),
        jewel_rejections=rejected,
    )
    assert rows[0].jewel_text == RUBY
    assert rows[0].deltas == {"CombinedDPS": 10}
    assert len(rejected) == 1 and "Limited to: 1" in rejected[0]
    assert all(sum("Prism of Belief" in j.text for j in s.jewels) <= 1 for s in daemon.measured)


def test_template_replaces_an_existing_entry_for_the_candidate_socket() -> None:
    daemon = _Daemon()
    rows = evaluate_node_deltas(
        _spec(JewelSpec(3, RUBY)),
        _graph(),
        [3],
        daemon=daemon,
        stats=("CombinedDPS",),
        jewel_templates=(PRISM,),
    )
    assert rows[0].jewel_text == PRISM
    variants = [s for s in daemon.measured if any(j.text == PRISM for j in s.jewels)]
    assert variants and all(len(s.jewels) == 1 for s in variants)
