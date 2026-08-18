"""2층 집계 계약 (M4).

1층은 「이 빌드에서」의 값이라 엔진이 못 읽는다. 여기서 노드별로 묶는데, 묶는 방식
자체가 규율이다 — 척도 불변으로 모으고, 축을 합치지 않고, **못 잰 것을 0으로 만들지
않는다**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pok.engine import counterfactual_aggregate as agg


def _row(node_id: int, deltas: dict[str, float], *, points: int = 1, kind: str = "notable"):
    return {
        "node_id": node_id,
        "name_en": f"노드{node_id}",
        "kind": kind,
        "points": points,
        "pool": "passive",
        "deltas": deltas,
        "pruned": [],
        "failed": "",
    }


def test_손실은_비율로_모은다() -> None:
    """⛔ 절대 델타를 더하지 않는다 — 빌드 규모가 100배씩 달라 큰 빌드 몇 벌이
    전부를 정한다. 손실률은 척도 불변이라 빌드를 넘어 합칠 수 있다."""
    # 규모가 10배 다른 두 빌드가 **같은 10% 손실**을 냈다
    assert agg._loss_pct(1_000_000.0, -100_000.0) == pytest.approx(10.0)
    assert agg._loss_pct(100_000.0, -10_000.0) == pytest.approx(10.0)


def test_기준이_0이면_비율이_없다() -> None:
    """딜이 0인 빌드에서 DPS 손실률은 정의되지 않는다 — 0으로 만들면 거짓이다."""
    assert agg._loss_pct(0.0, -5.0) is None


def test_분포는_평균을_안_쓴다() -> None:
    """한 벌이 평균을 끌고 간다 — UsageProfile이 min/median/max를 쓰는 것과 같은 이유."""
    got = agg._spread([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1_000.0])
    assert got["median"] == 1.0, "평균이면 100이 넘는다"
    assert got["p90"] >= got["median"] >= got["p10"]


def test_관측_0인_노드도_레코드를_만든다() -> None:
    """⛔ 「빼도 안 아프다」와 「재지 못했다」는 다른 말이다. 레코드가 없으면 후자가
    전자로 읽힌다(BACKLOG 형태 ① — 선언이 없으면 조용한 0). 실측 2026-08-18:
    주얼 오염 제외로 관측이 0이 된 노드가 67종이다."""
    node = agg._Node(kind="notable", label="오염된 노드")
    node.tainted = 5
    records = agg.build_records(
        "0-5",
        {123: node},
        {"builds_measured": 10, "rows_kept": 0, "rows_total": 5},
        pob_commit="abc",
        tree_nodes=4553,
    )
    (rec,) = records
    assert rec["data"]["sample"]["n"] == 0
    assert rec["data"]["sample"]["excluded"]["jewel_tainted"] == 5
    assert rec["data"]["axes"] == {}, "축이 있으면 잰 것처럼 읽힌다"


def test_축을_합치지_않는다() -> None:
    """아픔은 축마다 다르다. 하나로 접는 것은 **목적함수를 아는 쪽**만 할 수 있는
    판단이고 그건 호출 시점에 정해진다(철칙 3 · RC3 · 사용자 승인 2026-08-18)."""
    node = agg._Node(kind="keystone", label="두 축")
    node.points = [1, 1, 1]
    node.axes["CombinedDPS"] = [10.0, 20.0, 30.0]
    node.axes["TotalEHP"] = [0.0, 0.0, 0.0]
    (rec,) = agg.build_records(
        "0-5",
        {7: node},
        {"builds_measured": 3, "rows_kept": 3, "rows_total": 3},
        pob_commit="abc",
        tree_nodes=4553,
    )
    axes = rec["data"]["axes"]
    assert set(axes) == {"CombinedDPS", "TotalEHP"}
    assert axes["TotalEHP"]["zero_share"] == 100.0, "메타 습관의 신호가 사라졌다"
    assert axes["CombinedDPS"]["loss_pct"]["median"] == 20.0
    assert "value" not in rec["data"] and "score" not in rec["data"], "요약값을 만들면 판단이다"


def test_시즌_커버리지가_레코드마다_실린다() -> None:
    """`get_entry`는 레코드를 **하나만** 꺼내 준다 — 전체 그림이 거기 없으면
    읽는 쪽이 이 노드의 위치를 알 수 없다."""
    node = agg._Node(kind="small", label="작은 노드")
    node.points = [1]
    node.axes["CombinedDPS"] = [1.0]
    (rec,) = agg.build_records(
        "0-5",
        {9: node},
        {"builds_measured": 2689, "rows_kept": 57122, "rows_total": 67080},
        pob_commit="5d173cb",
        tree_nodes=4553,
    )
    cov = rec["data"]["sample"]["coverage"]
    assert cov["tree_nodes"] == 4553 and cov["builds_measured"] == 2689
    assert cov["rows_kept"] < cov["rows_total"], "거른 사실이 안 보인다"


def test_기준값이_없으면_거부한다(tmp_path: Path) -> None:
    """⛔ 조용히 절대 델타로 넘어가지 않는다 — 그러면 척도가 섞인 값이 정본에 간다."""
    (tmp_path / "counterfactual" / "9-9" / agg.REMOVALS).mkdir(parents=True)
    with pytest.raises(SystemExit, match="기준값이 없다"):
        agg.collect("9-9", None, raw_root=tmp_path, base=tmp_path)  # type: ignore[arg-type]


def test_레코드가_스키마를_통과한다() -> None:
    """정본에 들어갈 형태다 — 검증이 **쓴 뒤**에 터지면 남의 시험에서 터진다."""
    import json as _json

    from jsonschema import Draft202012Validator

    from pok.common.paths import knowledge_dir
    from pok.kb.store import _build_registry

    sdir = knowledge_dir() / "schema"
    schemas = {
        str(f.relative_to(sdir)).replace("\\", "/"): _json.loads(f.read_text(encoding="utf-8"))
        for f in sdir.rglob("*.json")
    }
    registry = _build_registry(schemas)

    node = agg._Node(kind="notable", label="검증용")
    node.points = [1, 2]
    node.axes["CombinedDPS"] = [5.0, 7.0]
    (rec,) = agg.build_records(
        "0-5",
        {11: node},
        {"builds_measured": 2, "rows_kept": 2, "rows_total": 2},
        pob_commit="abc",
        tree_nodes=4553,
    )
    Draft202012Validator(schemas["record.schema.json"], registry=registry).validate(rec)
    Draft202012Validator(schemas["node-value.schema.json"], registry=registry).validate(rec["data"])
    assert json.dumps(rec, ensure_ascii=False)
