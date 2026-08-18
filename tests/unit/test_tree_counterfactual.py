"""반사실 측정 — 제거·교체 (#73).

여기서 잠그는 것은 **두 가지**다:

1. 후보 열거가 연결성을 그래프에서 판정한다 — PoB에 물으면 안 된다. PoB는 끊긴
   노드를 오류로 내지 않고 조용히 해제한 뒤 값을 낸다(철칙 4).
2. `pruned`가 선 표본을 **버리지도, 쓰지도 않는다.** 사유를 달아 낸다. 조용히 버리면
   "몇 건이 왜 빠졌는가"를 읽는 쪽이 알 방법이 없고, 반사실 데이터셋에서는 그 사유가
   신뢰도 그 자체다.

PoB 없이 돌리려고 계산만 가짜로 세운다(연결성·경로는 진짜 그래프에서 나온다) —
`tests/unit/test_tree_corpus.py`의 가짜 데몬 패턴과 같다.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree.counterfactual import (
    RemovalCandidates,
    corpus_counterfactuals,
    evaluate_removals,
    evaluate_swaps,
    removable_nodes,
)
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, JewelSpec

_graph = TreeGraph(knowledge_dir())

# Monk 시작(44683)에서 뻗는 실제 사슬 — 10364 → 55342 → 17248 (KB 인접 실측).
# 사슬이라 잎(17248)만 빼도 되고 중간을 빼면 뒤가 고아가 된다.
_CHAIN = (10364, 55342, 17248)
_MONK = BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=_CHAIN)


class _Result:
    def __init__(self, stats: dict[str, float], pruned: tuple[int, ...] = ()) -> None:
        self.stats = stats
        self.pruned_nodes = pruned


class _Daemon:
    """가짜 PoB — stats가 트리 크기에 선형이다(노드 1개 제거 = CombinedDPS -100).

    ⚠ `loaded_spec`·`compute_tree`는 **데몬 계약의 일부**다(#70 후속). 제거·교체는
    트리만 바뀌므로 측정기가 `TREE` 명령 쪽으로 보낸다 — 가짜가 그걸 안 흉내 내면
    계약이 어긋난 채로 시험만 통과한다. `pruned` 훅은 두 경로에 **똑같이** 건다.
    """

    def __init__(self, pruned: Callable[[BuildSpec], tuple[int, ...]] | None = None) -> None:
        self.seen: list[tuple[int, ...]] = []
        self._pruned = pruned or (lambda _spec: ())
        self.loaded_spec: BuildSpec | None = None

    def _stats(self, nodes: tuple[int, ...]) -> dict[str, float]:
        n = len(nodes)
        return {"CombinedDPS": 100.0 * n, "Life": 10.0 * n}

    def compute_build(self, spec: BuildSpec) -> _Result:
        self.seen.append(tuple(spec.tree_nodes))
        self.loaded_spec = spec
        return _Result(self._stats(tuple(spec.tree_nodes)), self._pruned(spec))

    def compute_tree(self, nodes: tuple[int, ...]) -> _Result:
        self.seen.append(tuple(nodes))
        base = self.loaded_spec
        assert base is not None, "compute_tree는 로드된 빌드가 있어야 한다"
        variant = dataclasses.replace(base, tree_nodes=tuple(nodes))
        return _Result(self._stats(tuple(nodes)), self._pruned(variant))

    def close(self) -> None:
        pass


def _stats() -> tuple[str, ...]:
    return ("CombinedDPS", "Life")


# ────────────────────── 후보 열거 ──────────────────────


def test_잎_노드만_제거_후보다() -> None:
    """중간 노드를 빼면 하위가 고아가 되는데 **PoB는 그것을 오류로 내지 않는다.**

    그래서 후보 단계에서 걸러야 한다 — 여기가 뚫리면 "빼 보니 나빠졌다"가 실은
    끊겨서 잘린 트리를 잰 값이 된다.
    """
    out = removable_nodes(_MONK, _graph)
    assert out.nodes == (17248,), "잎이 아닌 노드가 후보에 들어왔다"
    assert "고아" in out.blocked[10364] and "고아" in out.blocked[55342]
    assert out.orphans == ()


def test_제외된_노드에는_사유가_붙는다() -> None:
    """사유가 없으면 「후보 1개」만 남아 나머지가 왜 빠졌는지 되짚을 수 없다."""
    out = removable_nodes(_MONK, _graph)
    assert set(out.blocked) | set(out.nodes) == set(_CHAIN)
    assert all(reason for reason in out.blocked.values())


def test_기본_할당_노드는_후보가_아니다() -> None:
    """블러드 메이지 혈액술(8415)은 포인트를 안 쓰고 켜져 있다 — 뺄 수 있는 것이 아니다."""
    spec = BuildSpec(class_name="Witch", ascendancy="Witch2", tree_nodes=(8415,))
    out = removable_nodes(spec, _graph)
    assert out.nodes == ()
    assert "뿌리" in out.blocked[8415]
    assert 54447 in out.roots and 8415 in out.roots, "클래스 시작·기본 할당이 뿌리에서 빠졌다"


def test_전직_시작_노드는_후보가_아니고_사유도_구체적이다() -> None:
    """PoB가 자동 할당하므로 스펙에 있으면 오히려 잘린다 — 그 사실을 사유로 남긴다."""
    spec = BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=(11495, *_CHAIN))
    out = removable_nodes(spec, _graph)
    assert 11495 not in out.nodes
    assert "자동 할당" in out.blocked[11495]


def test_선행_노드를_요구하는_노드가_있으면_그_선행은_후보가_아니다() -> None:
    """`requires_nodes`는 전직 제약이 아니라 「먼저 찍어야 열린다」다 — PoB는 안 본다.

    빼면 값은 나오지만 인게임에서 못 찍는 트리가 된다(철칙 4: 값이 나온다 ≠ 만들 수 있다).
    """
    # 탈주자의 길(51850)은 50239·9535·61309를 선행으로 요구한다 (KB 실측 3건 중 하나)
    allocated, _paths = _graph.connect_anchors("Ranger", [50239, 9535, 61309, 51850])
    spec = BuildSpec(class_name="Ranger", ascendancy="Ranger1", tree_nodes=tuple(allocated))
    out = removable_nodes(spec, _graph)
    assert 50239 not in out.nodes
    assert "선행 노드" in out.blocked[50239] and "51850" in out.blocked[50239]


def test_주얼이_박힌_소켓은_후보가_아니다() -> None:
    """소켓을 빼면 주얼 기여까지 사라져 **소켓 하나의 값으로 오인된다.**"""
    path = _graph.shortest_path({_graph.start_of("Monk")}, 21984)
    assert path and path[-1] == 21984
    spec = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        tree_nodes=tuple(path),
        jewels=(JewelSpec(socket_node_id=21984, text="Rarity: RARE\nPok Jewel\nSapphire"),),
    )
    out = removable_nodes(spec, _graph)
    assert 21984 not in out.nodes
    assert "주얼" in out.blocked[21984]


def test_뿌리에서_닿지_않는_노드는_판정하지_않는다() -> None:
    """복원한 래더 빌드에 실제로 흔하다(실측 116벌 중 75벌).

    ⚠ 이걸 **PoB에 물어서는 알 수 없다** — 실측 2026-08-13: 127노드 리치 빌드의
    3노드 고아 군집을 PoB가 전부 할당하고 `pruned`를 비워서 냈다(#74). 그래서
    후보 열거가 그래프에서 판정하는 것이 유일한 감지 지점이다.
    """
    spec = BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=(10364, 10131))
    out = removable_nodes(spec, _graph)
    assert out.orphans == (10131,)
    assert "닿지 않는다" in out.blocked[10131]


# ────────────────────── 제거 측정 ──────────────────────


def test_제거_측정이_회수_포인트와_델타를_낸다() -> None:
    d = _Daemon()
    (row,) = evaluate_removals(_MONK, _graph, [17248], stats=_stats(), daemon=d)
    assert row.measured is True and row.failed == ""
    assert row.removed == (17248,) and row.points == 1 and row.pool == "passive"
    assert row.deltas["CombinedDPS"] == -100.0, "제거는 음수 델타 = negative 표본이다"
    assert row.per_point("CombinedDPS") == -100.0
    assert d.seen == [_CHAIN, (10364, 55342)], "기준 1회 + 변경안 1회여야 한다"


def test_pruned가_서면_값을_쓰지_않고_사유를_낸다() -> None:
    """이 레포의 핵심 함정 — PoB는 잘라낸 뒤의 값을 정상값처럼 낸다(철칙 4)."""
    d = _Daemon(pruned=lambda spec: (999,) if len(spec.tree_nodes) < len(_CHAIN) else ())
    (row,) = evaluate_removals(_MONK, _graph, [17248], stats=_stats(), daemon=d)
    assert row.measured is False
    assert row.pruned == (999,) and row.deltas == {}, "잘린 측정의 값을 실었다"
    assert "값을 쓰지 않는다" in row.failed


def test_제거_불가_노드를_요청해도_결과에서_사라지지_않는다() -> None:
    """조용히 건너뛰면 호출자는 **재지 않은 것을 쟀다고 믿는다.**"""
    d = _Daemon()
    rows = evaluate_removals(_MONK, _graph, [17248, 10364, 999999], stats=_stats(), daemon=d)
    assert [r.node_id for r in rows] == [17248, 10364, 999999], "요청과 결과의 건수가 다르다"
    assert rows[0].measured and not rows[1].measured and not rows[2].measured
    assert "고아" in rows[1].failed
    assert rows[2].failed, "할당돼 있지도 않은 노드를 사유 없이 통과시켰다"
    assert d.seen == [_CHAIN, (10364, 55342)], "실패 표본에 PoB를 부르지 않는다"


def test_실패_표본은_적용된_것이_없다고_적는다() -> None:
    """「1포인트 회수」가 남아 있으면 **재지 못한 것이 잰 것처럼 집계된다.**

    실측 2026-08-13(`class-Witchhunter` 8벌): 교체 4건이 전부 풀 불일치로 실패했는데
    `points`에 -1이 적혀 나왔다 — 데이터셋에 넣으면 포인트 예산이 어긋난다.
    """
    d = _Daemon()
    rows = evaluate_removals(_MONK, _graph, [10364], stats=_stats(), daemon=d)
    assert rows[0].removed == () and rows[0].points == 0 and rows[0].deltas == {}
    (swap,) = evaluate_swaps(_MONK, _graph, [(17248, 8415)], stats=_stats(), daemon=d)
    assert swap.removed == () and swap.added == () and swap.points == 0


def test_기준_빌드가_이미_잘렸으면_전_표본이_실패다() -> None:
    d = _Daemon(pruned=lambda _spec: (10131,))
    spec = BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=(*_CHAIN, 10131))
    rows = evaluate_removals(spec, _graph, [17248], stats=_stats(), daemon=d)
    assert not rows[0].measured and "기준 빌드" in rows[0].failed
    assert rows[0].deltas == {}


def test_택1_선택도_함께_빠진다() -> None:
    """없는 노드의 택1 선택을 남기면 스펙이 거짓이 된다."""
    spec = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        tree_nodes=_CHAIN,
        attribute_choices=((17248, "str"), (10364, "dex")),
    )
    seen: list[tuple[tuple[int, str], ...]] = []

    class _Spy(_Daemon):
        def compute_build(self, spec: BuildSpec) -> _Result:
            seen.append(spec.attribute_choices)
            return super().compute_build(spec)

    evaluate_removals(spec, _graph, [17248], stats=_stats(), daemon=_Spy())
    assert seen[-1] == ((10364, "dex"),)


# ────────────────────── 교체 측정 ──────────────────────


def test_교체는_한_빌드에서_제거와_추가를_동시에_잰다() -> None:
    """따로 재서 더하면 교체가 아니다 — 임계를 넘겨야 열리는 축에서 어긋난다."""
    d = _Daemon()
    (row,) = evaluate_swaps(_MONK, _graph, [(17248, 42857)], stats=_stats(), daemon=d)
    assert row.measured is True, row.failed
    assert row.added == (42857,) and row.removed == (17248,)
    assert row.points == 0, "1개 빼고 1개 넣었으면 순증 0이다"
    assert row.deltas["CombinedDPS"] == 0.0
    assert d.seen[-1] == (10364, 55342, 42857), "제거와 추가가 한 계산에 들어가지 않았다"


def test_교체_경로가_제거한_노드를_되짚으면_교체가_아니다() -> None:
    """뺀 노드를 다시 경유하는 「교체」는 실은 제거가 없다 — 조용히 재면 안 된다."""
    d = _Daemon()
    (row,) = evaluate_swaps(_MONK, _graph, [(17248, 53960)], stats=_stats(), daemon=d)
    assert row.measured is False and "다시 지나간다" in row.failed
    assert d.seen == [_CHAIN], "성립하지 않는 교체에 PoB를 불렀다"


def test_남의_전직_노드로는_교체하지_않는다() -> None:
    """PoB는 다른 전직 노드의 스탯도 그대로 더한다(실측 2026-08-06 오라클 전용 7개 혼입)."""
    d = _Daemon()
    (row,) = evaluate_swaps(_MONK, _graph, [(17248, 8415)], stats=_stats(), daemon=d)
    assert row.measured is False and "다른 전직" in row.failed


def test_포인트_풀이_다른_교체는_재지_않는다() -> None:
    """전직 포인트와 일반 패시브는 별도 예산이다 — 섞으면 #68을 그대로 옮겨 심는다."""
    spec = BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=(20437, 10364))
    (row,) = evaluate_swaps(spec, _graph, [(20437, 42857)], stats=_stats(), daemon=_Daemon())
    assert row.pool == "ascendancy"
    assert row.measured is False and "포인트 풀" in row.failed


def test_이미_트리에_있는_노드로는_교체하지_않는다() -> None:
    (row,) = evaluate_swaps(_MONK, _graph, [(17248, 10364)], stats=_stats(), daemon=_Daemon())
    assert row.measured is False and "이미 트리에 있다" in row.failed


# ────────────────────── 코퍼스 입구 ──────────────────────


def _write_corpus(folder: Path, nodes: str) -> None:
    """원시 코퍼스 한 벌 — `artifacts/ingest-raw/ladder/<시즌>/<컨셉>/*.json`과 같은 꼴."""
    from pok.pob.codec import encode

    folder.mkdir(parents=True, exist_ok=True)
    xml = (
        '<?xml version="1.0"?>\n<PathOfBuilding2>\n'
        ' <Build level="90" className="Monk" ascendClassName="Martial Artist"/>\n'
        f' <Tree><Spec nodes="{nodes}" ascendancyInternalId="Monk1" masteryEffects=""/></Tree>\n'
        "</PathOfBuilding2>\n"
    )
    (folder / "a.json").write_text(
        json.dumps({"pob_export": encode(xml), "raw": {"level": 100}}),
        encoding="utf-8",
        newline="\n",
    )


def _select_all(_spec: BuildSpec, candidates: RemovalCandidates) -> Sequence[int]:
    return candidates.nodes


def test_코퍼스_입구가_복원_노트를_함께_싣는다(tmp_path: Path) -> None:
    """반쯤 복원된 스펙의 측정을 온전한 것으로 읽으면 안 된다 — 노트가 결과에 있어야 한다."""
    _write_corpus(tmp_path / "0-5" / "class-Monk", f"44683,11495,{','.join(map(str, _CHAIN))}")
    (row,) = corpus_counterfactuals(
        _graph,
        "0-5",
        "class-Monk",
        _select_all,
        base=tmp_path,
        stats=_stats(),
        daemon=_Daemon(),
    )
    assert row["restored"]["notes"], "못 되돌린 것을 싣지 않았다"
    assert row["restored"]["faithful"] is False
    assert row["tree"] == {
        "class_name": "Monk",
        "ascendancy": "Monk1",
        "allocated": 3,
        "removable": 1,
        "graph_orphans": [],
    }
    (removal,) = row["removals"]
    assert removal["node_id"] == 17248 and removal["deltas"]["CombinedDPS"] == -100.0


def test_코퍼스_입구는_뽑을_노드를_스스로_고르지_않는다(tmp_path: Path) -> None:
    """표본 선택은 호출자 몫이다(철칙 3) — 선택 함수가 비면 아무것도 재지 않는다."""
    _write_corpus(tmp_path / "0-5" / "class-Monk", f"44683,11495,{','.join(map(str, _CHAIN))}")
    d = _Daemon()
    (row,) = corpus_counterfactuals(
        _graph, "0-5", "class-Monk", lambda _s, _c: [], base=tmp_path, stats=_stats(), daemon=d
    )
    assert row["removals"] == []


def test_못_되돌린_빌드는_조용히_빠지지_않는다(tmp_path: Path) -> None:
    folder = tmp_path / "0-5" / "class-Monk"
    folder.mkdir(parents=True)
    (folder / "a.json").write_text(
        json.dumps({"pob_export": "이건 코드가 아니다"}), encoding="utf-8", newline="\n"
    )
    (row,) = corpus_counterfactuals(
        _graph, "0-5", "class-Monk", _select_all, base=tmp_path, stats=_stats(), daemon=_Daemon()
    )
    assert "skipped" in row and "ValueError" in row["skipped"]
    assert "removals" not in row


def test_수집분이_없으면_멈춘다(tmp_path: Path) -> None:
    from pok.artifacts.ladder import LadderError

    with pytest.raises(LadderError):
        corpus_counterfactuals(
            _graph, "0-5", "없는-컨셉", _select_all, base=tmp_path, daemon=_Daemon()
        )


def test_저장_규약을_발명하지_않았다() -> None:
    """데이터셋을 어디에 어떤 꼴로 쌓을지는 **구조 결정**이다(철칙 1 — 사용자 합의 사항).

    기본 출력 경로가 슬그머니 생기면 그게 곧 규약이 된다. 서명에 쓰기 대상이 없음을
    잠근다 — 나중에 합의되면 이 시험을 고치면서 들어온다.
    """
    import inspect

    from pok.engine.tree import counterfactual as mod

    sig = inspect.signature(mod.corpus_counterfactuals)
    assert "out" not in sig.parameters and "dest" not in sig.parameters
    writes = [
        line.strip()
        for line in inspect.getsource(mod).splitlines()
        if any(w in line for w in ("write_text(", "mkdir(", "json.dump("))
    ]
    assert not writes, f"엔진 모듈이 쓰기를 한다 — 저장 규약은 합의 사항이다: {writes}"


# ── 연결 불요 주얼(#87): 길 없이 성립하는 노드가 측정에 들어온다 ──
#
# From Nothing류는 반경 안 노드의 연결 요건을 없앤다. 코퍼스의 48.8%가 보유하고,
# 하필 길 제약 없이 **옵션만 보고 고른** — 의도가 가장 분명한 — 표본인데, 그래프
# 연결성만 보면 고아로 잡혀 측정에서 통째로 빠졌다(보유 빌드 39/40에서 발생).

# 실측 픽스처: Witch 시작과 안 이어진 소켓 2491, 반경(Small=1200) 안의 인접 사슬
_ZK_SOCKET = 2491
_ZK_CHAIN = (37276, 52373)
_FROM_NOTHING = (
    "Rarity: UNIQUE\nFrom Nothing\nDiamond\nRadius: Small\nLimited to: 1\n"
    "Passives in Radius of Wildsurge Incantation can be Allocated\n"
    "without being connected to your tree"
)
_NO_RADIUS = _FROM_NOTHING.replace("Radius: Small\n", "")


def _witch(jewel_text: str | None) -> BuildSpec:
    jewels = (JewelSpec(socket_node_id=_ZK_SOCKET, text=jewel_text),) if jewel_text else ()
    return BuildSpec(
        class_name="Witch",
        ascendancy="Witch1",
        tree_nodes=(_ZK_SOCKET, *_ZK_CHAIN),
        jewels=jewels,
    )


def test_연결_불요_반경_안은_고아가_아니라_후보다() -> None:
    """주얼이 없으면 셋 다 고아 — 있으면 살아나되 **제거 후보로 남는다**.

    ⚠ 뿌리로 넣으면 안 된다: 뿌리는 제거 불가 집합이라, 살리려던 표본이 「측정
    제외」로 또 빠진다(만들다 실제로 그랬다). 이 노드들은 포인트를 쓰는 선택이라
    제거 반사실의 정당한 대상이다.
    """
    bare = removable_nodes(_witch(None), _graph)
    assert set(_ZK_CHAIN) <= set(bare.orphans), "픽스처가 애초에 고아가 아니다"

    got = removable_nodes(_witch(_FROM_NOTHING), _graph)
    assert not (set(_ZK_CHAIN) & set(got.orphans)), "반경 안이 여전히 고아다"
    assert set(_ZK_CHAIN) <= set(got.no_path_zone), "후보 자격의 근거가 안 남았다"
    # 잎(52373)은 제거 가능해야 한다 — 측정에 들어온다
    assert 52373 in got.nodes, "살린 노드가 측정 후보에 없다"


def test_다리_노드를_빼면_뒤가_고아가_되는_판정은_유지된다() -> None:
    """씨앗이 됐다고 공짜 제거가 되면 안 된다 — 37276을 빼면 52373이 어디서도
    안 닿는가? 아니다: 52373도 반경 안(씨앗)이라 살아남는다. 즉 **같은 반경 안**
    끼리는 서로 다리가 아니다. 그것까지가 인게임 규칙 그대로다."""
    got = removable_nodes(_witch(_FROM_NOTHING), _graph)
    assert 37276 in got.nodes, "반경 안 이웃이 다리로 오판됐다"


def test_소켓이_안_찍혔으면_아무것도_안_살린다() -> None:
    spec = dataclasses.replace(_witch(_FROM_NOTHING), tree_nodes=tuple(_ZK_CHAIN))
    got = removable_nodes(spec, _graph)
    assert got.no_path_zone == ()
    assert set(_ZK_CHAIN) <= set(got.orphans)


def test_반경을_못_읽으면_안_살리고_고아로_남긴다() -> None:
    """⛔ 추측 금지 — 반경 선언이 없으면 어디까지가 「불요」인지 모른다.
    조용히 최대 반경을 가정하면 오류 고아가 후보로 둔갑한다."""
    got = removable_nodes(_witch(_NO_RADIUS), _graph)
    assert got.no_path_zone == ()
    assert set(_ZK_CHAIN) <= set(got.orphans)
