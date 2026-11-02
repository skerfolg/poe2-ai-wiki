"""Whole-tree selection must preserve the caller's target priorities."""

import pytest

from pok.engine.objective import Target
from pok.engine.tree.optimize import Objective, _better
from pok.pob.buildxml import BuildSpec
from pok.pob.runner import PobResult


def solution(node, stats):
    return (
        BuildSpec(class_name="fixture", ascendancy="", tree_nodes=(node,)),
        PobResult(stats, {}, (node,), (), False),
    )


@pytest.mark.parametrize(
    "targets, previous, candidate, expected",
    [
        (
            (Target("Life", ">=", 3000),),
            {"Life": 2000, "CombinedDPS": 20000},
            {"Life": 3000, "CombinedDPS": 19000},
            2,
        ),
        (
            (Target("Life", ">=", 3000),),
            {"Life": 3000, "CombinedDPS": 19000},
            {"Life": 2000, "CombinedDPS": 20000},
            1,
        ),
        (
            (Target("Life", ">=", 3000),),
            {"Life": 2000, "CombinedDPS": 20000},
            {"Life": 2500, "CombinedDPS": 19000},
            2,
        ),
        (
            (Target("ManaCost", "<=", 100),),
            {"ManaCost": 150, "CombinedDPS": 20000},
            {"ManaCost": 100, "CombinedDPS": 19000},
            2,
        ),
        (
            (Target("Life", ">=", 3000), Target("EnergyShield", ">=", 5000)),
            {"Life": 2500, "EnergyShield": 4000, "CombinedDPS": 20000},
            {"Life": 2600, "EnergyShield": 3000, "CombinedDPS": 19000},
            2,
        ),
        (
            (Target("Life", ">=", 3000), Target("EnergyShield", ">=", 5000)),
            {"Life": 2500, "EnergyShield": 5000, "CombinedDPS": 20000},
            {"Life": 2600, "EnergyShield": 4000, "CombinedDPS": 21000},
            1,
        ),
        (
            (Target("Life", ">=", 3000),),
            {"Life": 3000, "CombinedDPS": 20000},
            {"Life": 4000, "CombinedDPS": 19000},
            1,
        ),
        ((Target("unmeasured", ">=", 1),), {"CombinedDPS": 20000}, {"CombinedDPS": 19000}, 1),
        (
            (Target("Life", ">=", 3000),),
            {"Life": 3000, "CombinedDPS": 19000},
            {"CombinedDPS": 20000},
            1,
        ),
        (
            (Target("Life", ">=", 3000),),
            {"CombinedDPS": 20000},
            {"Life": 3000, "CombinedDPS": 19000},
            2,
        ),
        (
            (Target("Life", ">=", 3000), Target("EnergyShield", ">=", 5000)),
            {"Life": 4000, "EnergyShield": 4000, "CombinedDPS": 20000},
            {"Life": 3000, "EnergyShield": 5000, "CombinedDPS": 19000},
            2,
        ),
        ((), {"CombinedDPS": 20000}, {"CombinedDPS": 19000}, 1),
    ],
)
def test_whole_tree_selection_respects_targets(targets, previous, candidate, expected):
    objective = Objective(weights={"CombinedDPS": 1.0}, targets=targets)
    selected = _better(objective, solution(1, previous), solution(2, candidate))
    assert selected[0].tree_nodes == (expected,)
