"""반사실 캠페인 P1~P3 계약 (M3, BACKLOG #73).

여기서 잠그는 것은 **조용히 틀리는 것들**이다: 계획이 완전성 기준인데 표본이 줄어드는
것, 부분 데이터셋이 전량으로 읽히는 것, 다른 계산기로 잰 값이 섞이는 것.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pok.engine import counterfactual_campaign as cc


def _doc(account: str, name: str, updated: str = "2026-08-01T00:00:00Z") -> dict[str, Any]:
    """저장된 래더 payload 꼴 — poe.ninja 원본을 `raw`로 감싸고 계보를 얹는다."""
    return {
        "source": "poe.ninja",
        "concept": "class-Lich",
        "pob_export": "x",
        "raw": {"account": account, "name": name, "updatedUtc": updated},
    }


def _seed(root: Path, season: str, concept: str, docs: list[dict[str, Any]]) -> None:
    folder = root / season / concept
    folder.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (folder / f"{cc.build_id(doc)}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )


def test_빌드_id는_raw_안을_본다() -> None:
    """⚠ 이게 틀리면 **모든 빌드가 한 id로 뭉친다.**

    `_record_path`는 poe.ninja **원본 문서**를 받는데 저장 payload는 그걸 `raw`로
    감싼다. 감싼 쪽을 넘기면 계정·이름이 None이 되고, 실측 2026-08-17에 계획의
    `total`이 2,689이어야 할 자리에 **1**이 나왔다. 계획은 완전성 기준이라 그 한 줄이
    캠페인 전체를 1벌로 축소시킨다.
    """
    a = cc.build_id(_doc("acc-1", "Zed"))
    b = cc.build_id(_doc("acc-2", "Wye"))
    assert a != b, "서로 다른 캐릭터가 같은 id로 뭉쳤다"
    assert a.startswith("acc-1__Zed__"), a


def test_계획은_고유_캐릭터_수와_같다(tmp_path: Path) -> None:
    """같은 캐릭터가 여러 컨셉 폴더에 겹친다 — 파일 수로 세면 같은 빌드를 두 번 잰다."""
    zed, wye = _doc("acc-1", "Zed"), _doc("acc-2", "Wye")
    _seed(tmp_path, "0-5", "class-Lich", [zed, wye])
    _seed(tmp_path, "0-5", "keypassives-CI", [zed])  # 겹침

    plan = cc.make_plan("0-5", base=tmp_path)
    assert plan["total"] == 2, "파일 3개지만 캐릭터는 2명이다"
    assert {u["build"] for u in plan["units"]} == {cc.build_id(zed), cc.build_id(wye)}


def test_계획에_계보를_박는다(tmp_path: Path) -> None:
    """계획이 어느 전제에서 만들어졌는지가 없으면 재개 판정을 못 한다."""
    _seed(tmp_path, "0-5", "class-Lich", [_doc("acc-1", "Zed")])
    plan = cc.make_plan("0-5", base=tmp_path)
    assert "pob_commit" in plan["provenance"]
    assert "fidelity_usable" in plan["provenance"]
    assert plan["axis"] == "removals", "교체 축은 전수 46일이라 이 계획에 없다"


def test_스냅샷이_다르면_이어가지_않는다() -> None:
    """서로 다른 계산기로 잰 값이 한 데이터셋에 섞이면 나중에 갈라낼 수 없다.
    겉보기가 정상이라 사람이 못 잡는다 — 코드가 막는다(철칙 5)."""
    assert cc.check_resumable({"provenance": {"pob_commit": "다른커밋"}})
    assert cc.check_resumable({"provenance": {}}), "계획에 커밋이 없으면 막아야 한다"


def test_완료분은_건너뛴다() -> None:
    plan = {"units": [{"build": "a"}, {"build": "b"}, {"build": "c"}]}
    assert cc.pending(plan, {"done": ["b"]}) == ["a", "c"]
    assert cc.pending(plan, {}) == ["a", "b", "c"]


def test_결과_파일이_있으면_상태에_없어도_건너뛴다(tmp_path: Path) -> None:
    """상태 파일은 소유자가 하나뿐이라 **다른 실행이 만든 결과를 모른다.**

    규약이 「빌드당 파일 1개 · 파일 있으면 건너뛴다」인 이유가 이것이다 — 실측
    2026-08-17: 상태 파일만 믿던 실행이 다른 프로세스가 이미 잰 97벌을 끝에서 다시
    재려 했다. 파일이 진짜 기록이다.
    """
    (tmp_path / "0-5").mkdir(parents=True)
    cc.write_result("0-5", {"build": "b", "coverage": {}}, base=tmp_path)
    assert cc.completed("0-5", base=tmp_path) == {"b"}

    plan = {"units": [{"build": "a"}, {"build": "b"}, {"build": "c"}]}
    assert cc.pending(plan, {}, done_files=cc.completed("0-5", base=tmp_path)) == ["a", "c"]


def test_결과는_빌드당_파일_하나로_원자적으로_쓴다(tmp_path: Path) -> None:
    """중단이 반쪽 파일을 남기면 재개가 「완료」로 오판한다."""
    (tmp_path / "0-5").mkdir(parents=True)
    path = cc.write_result("0-5", {"build": "acc__Zed__t", "coverage": {}}, base=tmp_path)
    assert path.name == "acc__Zed__t.json"
    assert path.parent.name == cc.REMOVALS
    assert not list(path.parent.glob("*.tmp")), "임시 파일이 남았다"


def test_후보에서_빠진_이유가_결과에_남는다(monkeypatch: Any) -> None:
    """⛔ 조용한 제외 금지 — 「할당 130개 중 21개를 쟀다」만 남으면 나머지 109개가
    왜 빠졌는지 알 수 없다.

    특히 `graph_orphans`는 **연결 불요 주얼**(From Nothing 등, 코퍼스 48.8%) 때문에
    길 없이 할당된 정상 노드일 수 있다. 우리 그래프는 그걸 고아로 판정해 후보에서
    빼는데, 그 사실이 안 남으면 **없는 값이 0으로 읽힌다**(BACKLOG #87).
    실측 2026-08-18: 연결 불요 주얼 보유 빌드 39/40에서 고아 발생, 중앙 7개.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.counterfactual import removable_nodes
    from pok.engine.tree.graph import TreeGraph
    from pok.pob.buildxml import spec_from_dict
    from pok.pob.restore import spec_from_pob

    raw = Path("artifacts/ingest-raw/ladder/0-5")
    docs = sorted(raw.glob("*/*.json"))[:1] if raw.exists() else []
    if not docs:
        pytest.skip("래더 원시가 없다 — 데이터 repo 미연결 환경")
    doc = json.loads(docs[0].read_text(encoding="utf-8"))

    # 측정은 이 시험의 관심이 아니다(PoB가 필요하다) — 열거와 보고만 본다
    monkeypatch.setattr(cc, "evaluate_removals", lambda *a, **k: [])

    class _FakeDaemon:
        def compute_build(self, spec: Any) -> Any:
            class _R:
                stats: ClassVar[dict] = {"CombinedDPS": 123_456.0}

            return _R()

    graph = TreeGraph(knowledge_dir())
    out = cc.measure_build(graph, doc, pob_commit="x", daemon=_FakeDaemon(), stats=("CombinedDPS",))
    # 기준이 행과 함께 실린다 — 델타만 실으면 손실을 비율로 못 만든다(M4에서 데임)
    assert out["baseline"] == {"CombinedDPS": 123_456.0}

    spec = spec_from_dict(spec_from_pob(str(doc["pob_export"])).spec, validate_catalog=False)
    want = removable_nodes(spec, graph)
    cov = out["coverage"]
    assert cov["allocated"] == len(spec.tree_nodes)
    assert cov["candidates"] == len(want.nodes)
    assert cov["excluded"]["graph_orphans"] == len(want.orphans)
    assert cov["excluded"]["blocked"] == len(want.blocked)
