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


def test_기준이_없는_빌드는_세지_않는_방식으로_빠진다(tmp_path: Path) -> None:
    """⛔ 조용히 절대 델타로 넘어가지 않는다 — 척도가 섞인 값이 정본에 가면 안 된다.

    옛 동작은 사이드카가 없으면 즉사였는데, 재측정본(2026-08-19~)은 행과 함께
    기준(`baseline`)을 실으므로 사이드카 없이도 돈다. 둘 다 없는 빌드만
    `builds_measured`에 안 잡히는 방식으로 빠진다 — coverage가 손실을 드러낸다."""
    (tmp_path / "counterfactual" / "9-9" / agg.REMOVALS).mkdir(parents=True)
    nodes, cov, _commit = agg.collect("9-9", None, raw_root=tmp_path, base=tmp_path)  # type: ignore[arg-type]
    assert nodes == {} and cov["builds_measured"] == 0


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


def test_KB_ref가_실려야_두_층이_곱해진다() -> None:
    """⚠ **조인 키다.** `UsageProfile`의 채택률은 `passive.<슬러그>` ref로 실려 있어
    node_id로는 못 잇는다. 이 층의 존재 이유가 「채택률 곱하기 손실률」로 메타 습관을
    드러내는 것이라(#62), 키가 없으면 두 층이 나란히 놓여 있기만 하고 안 곱해진다.
    """
    node = agg._Node(kind="keystone", label="조인용")
    node.points = [1]
    node.axes["CombinedDPS"] = [3.0]
    (rec,) = agg.build_records(
        "0-5",
        {45202: node},
        {"builds_measured": 1, "rows_kept": 1, "rows_total": 1},
        pob_commit="abc",
        tree_nodes=4553,
        refs={45202: ("passive.ancestral-bond-45202", "keystone")},
    )
    assert rec["data"]["node"]["ref"] == "passive.ancestral-bond-45202"


def test_KB에_없는_노드는_ref_없이_낸다() -> None:
    """⛔ 지어내지 않는다 — 트리 수집 갭이면 node_id로만 잡고 ref는 비운다.
    가짜 ref를 넣으면 조인이 조용히 어긋난다."""
    node = agg._Node(kind="small", label="KB에 없음")
    node.points = [1]
    (rec,) = agg.build_records(
        "0-5",
        {999999: node},
        {"builds_measured": 1, "rows_kept": 1, "rows_total": 1},
        pob_commit="abc",
        tree_nodes=4553,
        refs={},
    )
    assert "ref" not in rec["data"]["node"]


def test_조건부와_쓸모없음이_갈린다() -> None:
    """⛔ 전 빌드를 뭉친 중앙값은 둘을 **같은 0**으로 낸다(#88).

    실측 2026-08-18: Mind Over Matter는 전체 중앙 거의 0인데 작동률 1.4%·작동시
    36.6%다. Gathering Winds는 어느 빌드에서도 안 움직인다. 스키마가 이 둘을
    구별하지 못하면 「빼도 된다」는 정반대 결론이 나온다.
    """
    conditional = agg._Node(kind="keystone", label="조건부")
    conditional.points = [1] * 10
    conditional.axes["CombinedDPS"] = [0.0] * 9 + [36.6]

    useless = agg._Node(kind="notable", label="안 움직임")
    useless.points = [1] * 10
    useless.axes["CombinedDPS"] = [0.0] * 10

    recs = agg.build_records(
        "0-5",
        {1: conditional, 2: useless},
        {"builds_measured": 10, "rows_kept": 20, "rows_total": 20},
        pob_commit="abc",
        tree_nodes=4553,
        refs={},
    )
    cond_ax = recs[0]["data"]["axes"]["CombinedDPS"]
    dead_ax = recs[1]["data"]["axes"]["CombinedDPS"]
    assert cond_ax["loss_pct"]["median"] == dead_ax["loss_pct"]["median"] == 0.0, "뭉치면 같다"
    assert cond_ax["when_active"]["median"] == 36.6, "작동할 땐 큰 것이 안 보인다"
    assert dead_ax["n_active"] == 0 and cond_ax["n_active"] == 1
    assert cond_ax["active_share"] == 10.0 and dead_ax["active_share"] == 0.0


def test_대조군_없이는_그룹을_붙이지_않는다() -> None:
    """⛔ 실측 2026-08-18: 대조군을 안 봤더니 **노드마다 16~18개가 전부 붙었다**.
    「작동한 빌드가 이 그룹을 썼다」는 그 그룹이 넓으면(마나는 젬 55종) 늘 참이다.
    그룹이 **없을 때도** 똑같이 작동했다면 조건이 아니다."""
    node = agg._Node(kind="notable", label="그룹 판정")
    node.n_rows["CombinedDPS"] = 40
    node.n_fired["CombinedDPS"] = 20
    # 저주: 있을 때 18/20 작동, 없을 때 2/20 → 조건이다
    # 마나: 있을 때 10/20, 없을 때 10/20 → 아무것도 설명 못 한다
    node.seen_groups["CombinedDPS"].update({"저주": 20, "마나": 20})
    node.fired_groups["CombinedDPS"].update({"저주": 18, "마나": 10})
    assert set(node.groups_for("CombinedDPS")) == {"저주"}


def test_모든_빌드가_쓰는_그룹은_비교_자체가_안_된다() -> None:
    """대조군이 없으면(전원 보유) 리프트를 못 낸다 — 조용히 붙이지 않는다."""
    node = agg._Node(kind="notable", label="전원 보유")
    node.n_rows["CombinedDPS"] = 30
    node.n_fired["CombinedDPS"] = 15
    node.seen_groups["CombinedDPS"].update({"마나": 30})
    node.fired_groups["CombinedDPS"].update({"마나": 15})
    assert node.groups_for("CombinedDPS") == {}


def test_그룹을_축마다_따로_센다() -> None:
    """⛔ DPS 조건을 정하는데 EHP가 움직인 것까지 「작동」으로 세면 **다른 축의
    상관이 조건으로 둔갑한다.** (그룹끼리 겹치는 것 자체는 정상이다 — 빌드는 여러
    그룹의 합이고, 고르는 용도로는 상관된 그룹이 해롭지 않다.)"""
    node = agg._Node(kind="notable", label="축 분리")
    for stat, hit in (("CombinedDPS", 18), ("TotalEHP", 10)):
        node.n_rows[stat] = 40
        node.n_fired[stat] = 20
        node.seen_groups[stat].update({"저주": 20})
        node.fired_groups[stat].update({"저주": hit})
    assert set(node.groups_for("CombinedDPS")) == {"저주"}
    assert node.groups_for("TotalEHP") == {}, "EHP에선 조건이 아닌데 붙었다"


def test_오염_행도_함께_낸다() -> None:
    """⛔ 제외만 하면 신호가 통째로 사라지는 경우가 있다(#99).

    실측 2026-08-20: `Zealot's Oath`는 EHP가 움직인 35행이 **전부** 오염 제외에
    걸렸고, 남은 40행이 전부 0이라 집계가 「어느 빌드에서도 안 움직임」으로 냈다 —
    「측정 0」이 실측이 아니라 **집계의 산물**이었다.
    """
    node = agg._Node(kind="keystone", label="오염이 신호를 가린 노드")
    node.points = [1] * 3
    node.axes["TotalEHP"] = [0.0, 0.0, 0.0]  # 깨끗한 행은 전부 0
    node.axes_all["TotalEHP"] = [0.0, 0.0, 0.0, 45.0, 60.0]  # 오염 행에 신호가 있다
    node.tainted = 2
    (rec,) = agg.build_records(
        "0-5",
        {52: node},
        {"builds_measured": 5, "rows_kept": 3, "rows_total": 5},
        pob_commit="abc",
        tree_nodes=4553,
        refs={},
    )
    ax = rec["data"]["axes"]["TotalEHP"]
    assert ax["active_share"] == 0.0, "제외본은 여전히 0이어야 한다(대조)"
    assert ax["with_tainted"]["active_share"] > 0, "오염 포함 신호가 안 실렸다"
    assert ax["with_tainted"]["kept_pct"] == 60.0, "잔존율이 안 맞는다"
    assert ax["with_tainted"]["loss_pct"]["p90"] > 0


def test_오염이_없으면_잔존율_100() -> None:
    node = agg._Node(kind="notable", label="깨끗")
    node.points = [1, 1]
    node.axes["CombinedDPS"] = [5.0, 7.0]
    node.axes_all["CombinedDPS"] = [5.0, 7.0]
    (rec,) = agg.build_records(
        "0-5",
        {9: node},
        {"builds_measured": 2, "rows_kept": 2, "rows_total": 2},
        pob_commit="abc",
        tree_nodes=4553,
        refs={},
    )
    assert rec["data"]["axes"]["CombinedDPS"]["with_tainted"]["kept_pct"] == 100.0


def test_안_실린_축은_안_쟀다가_아니라_재서_0이다() -> None:
    """#108의 함정 — 분모를 `deltas`에서 뽑으면 **작동률이 정의상 100%**가 된다.

    관측에 움직인 축만 싣게 바꾼 뒤 집계기가 `deltas`를 훑으면, 안 움직인 축은 아예
    세어지지 않아 「채택되는데 안 움직인다」는 신호가 통째로 사라진다 — 판정 큐를
    만드는 근거가 바로 그 신호다.
    """
    from pok.engine.counterfactual_aggregate import _measured_axes

    base = {"CombinedDPS": 100.0, "Life": 50.0, "EHPSurvivalTime": 20.0}
    row = {"deltas": {"Life": -5.0}, "unmeasured": ["EHPSurvivalTime"]}

    axes = _measured_axes(base, row)
    assert axes == ["CombinedDPS", "Life"], "결측 축(#109)은 분모에서 빠진다"
    assert "CombinedDPS" in axes, "안 실린 축도 **잰 축**이므로 0으로 세어야 한다"

    # 결측 표기가 없던 예전 데이터(13축 시절)는 기준선 그대로가 잰 축이다
    assert _measured_axes(base, {"deltas": {"Life": -5.0}}) == list(base)
