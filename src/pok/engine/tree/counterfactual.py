"""반사실(counterfactual) 측정 — 「빼면·바꾸면 얼마나 나빠지나」.

래더 코퍼스 300벌은 전부 **채택된 것**만 담고 있다(positive only). 「이 노드가
실제로 얼마를 벌어 주나」를 코퍼스에서 배우려면 negative가 필요한데, 기존 델타
측정(`deltas.py`)에는 **더하기 방향만** 있었다 — 제거 경로 0건.

⚠ **제거는 트리 연결성을 깨뜨리고, PoB는 그것을 오류로 내지 않는다.** 중간 노드를
빼면 하위가 고아가 되는데 PoB는 조용히 잘라낸 뒤 값을 낸다(철칙 4 — 계산기이지
검증기가 아니다). 그래서 여기서는 두 겹으로 막는다:

1. 후보 열거를 **그래프 연결성으로** 먼저 거른다 — PoB에 묻지 않는다.
2. 측정마다 `PobResult.pruned_nodes`를 확인한다. 비어 있지 않으면 값을 **쓰지 않고**
   「측정 실패」로 사유와 함께 낸다 — 조용히 버리지도 않는다. 버리면 표본이 몇 건
   왜 빠졌는지 읽는 쪽이 알 방법이 없고, 그 사유가 반사실에서는 결과의 절반이다.

⛔ **순서가 중요하다: 1이 본 게이트이고 2는 보조다.** `pruned_nodes`는 연결성
검출기가 **아니다** — 실측 2026-08-13(래더 `class-Lich` 1번 빌드, 127노드): 시작점에
할당 노드로 닿지 않는 3노드 군집(Warlord Leader 14761 · 45215 · 45586)을 PoB가
**전부 할당하고 pruned를 비워서** 냈다. 같은 3노드만 따로 요청하면 잘라낸다. 즉
`pruned`가 비었다는 것은 「끊긴 노드가 없다」가 아니다(`PobResult.is_tree_legal`의
설명은 이 지점에서 과대 약속이다 — 백로그 #74).

그래서 이 모듈은 연결성을 **KB 그래프에서** 판정한다. 방향이 안전한 쪽인 것도 실측으로
확인했다: KB 간선은 PoB 간선의 부분집합이다(2026-08-13 전수 대조 — PoB 5,154개 중
KB에 없는 것 4개, KB에만 있는 것 **0개**). 간선이 모자라면 트리가 더 부서지기 쉬워
보이므로 후보 판정은 **보수적으로** 틀린다 — 뺄 수 있는 것을 막을 뿐, 못 뺄 것을
통과시키지 않는다.

⛔ **무엇을 빼볼지는 여기서 고르지 않는다**(철칙 3 — 엔진=결정적). 후보 열거는
연결성·해금 조건이라는 결정적 규칙뿐이고, 우선순위·표본 선택은 호출자 몫이다.
`corpus_counterfactuals`가 선택 함수를 **인자로 받는** 이유가 그것이다.

⛔ **아무것도 저장하지 않는다.** 데이터셋을 어디에 어떤 꼴로 쌓을지는 구조 결정이라
사용자 합의 전에는 만들지 않는다(철칙 1). 반환값을 어디에 쌓을지는 호출자가 정한다.
"""

from __future__ import annotations

import collections
import dataclasses
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec
from pok.pob.daemon import PobDaemon

_DEFAULT_STATS = ("CombinedDPS", "Life", "TotalEHP")

_ROOT_REASON = "뿌리 — 포인트를 안 쓰고 항상 켜져 있다(클래스 시작·전직 시작·기본 할당)"


# ────────────────────── 후보 열거 (그래프만 본다) ──────────────────────


@dataclass(frozen=True)
class RemovalCandidates:
    """제거 후보 열거 결과. **뺀 것에는 사유가 붙는다** — 조용한 제외 금지.

    `blocked`가 없으면 "후보가 12개다"만 남아, 나머지 100개가 왜 빠졌는지(고아가
    생긴다? 뿌리다? KB가 모른다?) 읽는 쪽이 되짚을 수 없다.
    """

    nodes: tuple[int, ...]  # 제거해도 나머지 트리의 연결성이 유지되는 노드 (오름차순)
    blocked: dict[int, str]  # 할당돼 있지만 후보가 아닌 노드 → 사유
    # 뿌리에서 **할당 노드만 밟아** 닿지 않는 노드. 기준 빌드가 이미 그 상태라는 뜻이고,
    # PoB는 이것을 `pruned`로 알려주지 않는다(머리주석 실측). 래더 복원본에 실제로
    # 흔하다 — 실측 2026-08-13: 116벌 16,725노드 중 1,916개(11.5%) · 75/116벌.
    orphans: tuple[int, ...]
    roots: tuple[int, ...]


def _roots(spec: BuildSpec, graph: TreeGraph) -> frozenset[int]:
    """포인트를 안 쓰고 **항상 켜져 있는** 노드 — 연결성의 출발점이자 제거 불가 집합.

    셋이다:
    - 클래스 시작(`graph.start_of`) — KB에 레코드조차 없는 트리의 뿌리다.
    - **전직 시작** — PoB가 전직 선택으로 자동 할당한다. 스펙에 넣으면 오히려 잘리고
      (`graph.connect_anchors` 말미 주석), 그 트리의 측정이 통째로 무효가 된다.
      링크 표(graph 모듈의 `_START_LINKS`)에 빠진 전직도 있으므로 **링크가 아니라
      종류로** 찾는다 — 링크에 의존하면 그 전직의 노터블이 전부 고아로 보인다.
    - 기본 할당 노드(블러드 메이지 혈액술 — `GRANTED_ASCENDANCY_NODES`).
    """
    want = graph.resolve_ascendancy(spec.ascendancy) if spec.ascendancy else None
    starts = {
        nid
        for nid, node in graph.nodes.items()
        if node.kind == "ascendancy-start"
        and node.ascendancy
        and graph.resolve_ascendancy(node.ascendancy) == want
    }
    return frozenset(
        {graph.start_of(spec.class_name), *graph.granted_nodes(spec.ascendancy), *starts}
    )


def _reachable(
    graph: TreeGraph, universe: frozenset[int], roots: Iterable[int], *, without: int | None = None
) -> set[int]:
    """`universe`(=할당 노드 + 뿌리) 안에서만 이동하는 BFS. `without`은 없는 것으로 본다.

    할당되지 않은 노드를 지나갈 수 없다는 것이 핵심이다 — 트리의 연결성은 **찍은
    노드들끼리**의 연결이고, 그래프 전체의 연결성이 아니다.
    """
    seen = {r for r in roots if r in universe and r != without}
    q = collections.deque(seen)
    while q:
        cur = q.popleft()
        for nb in graph.adj[cur]:
            if nb in universe and nb != without and nb not in seen:
                seen.add(nb)
                q.append(nb)
    return seen


def removable_nodes(spec: BuildSpec, graph: TreeGraph) -> RemovalCandidates:
    """제거해도 **나머지 트리의 연결성이 유지되는** 노드를 결정적으로 열거한다.

    연결성 판정은 그래프에서 한다 — PoB에 묻지 않는다. PoB는 끊긴 노드를 오류로
    내지 않고, 잘라내지 않는 경우조차 있어서(머리주석 실측) 물어보면 "측정은 됐지만
    다른 트리를 잰" 수치를 정상값으로 받는다(철칙 4).

    연결성 외에 **인게임에서 못 만들게 되는 제거**도 뺀다. PoB는 이것들도 검사하지
    않으므로(값이 나온다 ≠ 만들 수 있다) 후보 단계가 유일한 강제 지점이다:
    - **선행 노드**(`requires_nodes`) — 다른 할당 노드가 「먼저 찍어야 열린다」고
      지목한 노드. 빼면 그 노터블이 인게임에서 안 열린다(KB 3건).
    - **주얼이 박힌 소켓** — 빼면 주얼 기여까지 함께 사라져 소켓 하나의 값으로
      오인된다. 게다가 할당 안 된 소켓의 주얼은 조립이 거부하는 구성이다
      (`pob/restore.py`의 orphan 소켓 주석과 같은 사유).

    비용: 후보마다 BFS 1회 = O(V·(V+E)). 빌드당 V≈130이라 5만 스텝 안쪽이고, PoB
    계산 1회(0.1초)에 비하면 무료다. 관절점(Tarjan) 1패스로 줄일 수 있지만 「뿌리
    여럿 + 할당 부분집합만 관심」 조건에서 변형이 필요해 검증이 어렵다 — 데이터가
    요구하지 않는 최적화는 넣지 않는다.
    """
    alloc = frozenset(spec.tree_nodes)
    roots = _roots(spec, graph)
    universe = alloc | roots
    reachable = _reachable(graph, universe, roots)
    orphans = tuple(sorted(alloc - reachable))

    prerequisite_of: dict[int, list[int]] = {}
    for nid in alloc:
        node = graph.nodes.get(nid)
        if node is None:
            continue
        for need in node.requires_nodes:
            if need in alloc:
                prerequisite_of.setdefault(need, []).append(nid)
    socketed = {j.socket_node_id for j in spec.jewels}

    ok: list[int] = []
    blocked: dict[int, str] = {}
    for nid in sorted(alloc):
        node = graph.nodes.get(nid)
        # 전직 시작을 뿌리보다 **먼저** 본다 — 같은 전직이면 뿌리 집합에도 들어 있어서
        # 순서를 바꾸면 "뿌리다"만 남고 「스펙에 실으면 잘린다」는 사유가 사라진다.
        if node is not None and node.kind == "ascendancy-start":
            blocked[nid] = "전직 시작 — PoB가 자동 할당한다(스펙에 있으면 오히려 잘린다)"
        elif nid in roots:
            blocked[nid] = _ROOT_REASON
        elif node is None:
            blocked[nid] = "KB가 모르는 노드 — 연결성을 판정할 수 없다(트리 수집 갭)"
        elif nid in orphans:
            blocked[nid] = (
                "뿌리에서 할당 노드만 밟아 닿지 않는다 — 빼도 잃는 것이 무엇인지 "
                "판정할 수 없다(PoB는 이 상태를 pruned로 알려주지 않는다)"
            )
        elif dependents := prerequisite_of.get(nid):
            blocked[nid] = (
                f"할당 노드 {sorted(dependents)}의 **선행 노드**다 — 빼면 PoB는 그대로 "
                "계산하지만 인게임에서 못 찍는 트리가 된다"
            )
        elif nid in socketed:
            blocked[nid] = "주얼이 박힌 소켓 — 빼면 주얼 기여까지 사라져 소켓 값으로 오인된다"
        else:
            lost = (reachable - {nid}) - _reachable(graph, universe, roots, without=nid)
            if lost:
                blocked[nid] = f"빼면 {len(lost)}개가 고아가 된다(예: {sorted(lost)[:5]})"
            else:
                ok.append(nid)
    return RemovalCandidates(
        nodes=tuple(ok), blocked=blocked, orphans=orphans, roots=tuple(sorted(roots))
    )


def _pool(graph: TreeGraph, node_id: int) -> str:
    """그 노드가 먹는 포인트 풀 — 전직 포인트와 일반 패시브는 **다른 예산**이다.

    섞어 세는 것이 백로그 #68이다(전직 노드가 `point_budget`을 갉아먹는다). 회수
    포인트에 풀을 안 붙이면 같은 결함을 반사실 데이터셋에 그대로 옮겨 심는다.
    """
    node = graph.nodes.get(node_id)
    return "ascendancy" if node is not None and node.ascendancy else "passive"


def _target_problem(spec: BuildSpec, graph: TreeGraph, target: int, tree: frozenset[int]) -> str:
    """추가 대상이 **인게임에서 찍을 수 있는 노드인가** — 아니면 사유. 규칙은 그래프에 있다.

    `graph.candidates`(후보 압축)와 `connect_anchors`(소유권 검사)가 이미 거는 규칙과
    같은 것을 교체 대상에도 건다. PoB는 이 중 아무것도 검사하지 않아서(다른 전직의
    노드도 스탯을 그대로 더한다 — 실측 2026-08-06 오라클 전용 7개 혼입) 여기서
    거르지 않으면 「나빠졌다/좋아졌다」가 만들 수 없는 트리 위에서 나온다.
    """
    node = graph.nodes.get(target)
    if node is None:
        return "KB가 모르는 노드다 — 무엇을 넣는지 확인할 수 없다"
    want = graph.resolve_ascendancy(spec.ascendancy) if spec.ascendancy else None
    if node.ascendancy and graph.resolve_ascendancy(node.ascendancy) != want:
        return f"다른 전직({node.ascendancy})의 노드다 — 인게임에서 할당 불가"
    if node.kind == "ascendancy-start":
        return "전직 시작 노드는 스펙에 싣지 않는다(PoB가 잘라낸다)"
    if node.locked_to not in (None, want):
        return f"해금 전직이 다르다({node.locked_to}) — PoB는 검사하지 않는다"
    if missing := [n for n in node.requires_nodes if n not in tree]:
        return f"선행 노드 {missing}가 트리에 없다 — 인게임에서 열리지 않는다"
    return ""


def _drop(spec: BuildSpec, node_id: int, added: tuple[int, ...] = ()) -> BuildSpec:
    """노드 하나를 뺀(+경로를 더한) 변형 스펙.

    `attribute_choices`도 함께 뺀다 — 빼 버린 노드의 택1 선택을 남겨 두면 없는
    노드에 대한 주장이 스펙에 남는다(PoB가 무시하든 말든 스펙이 거짓이 된다).
    """
    return dataclasses.replace(
        spec,
        tree_nodes=tuple(n for n in spec.tree_nodes if n != node_id) + added,
        attribute_choices=tuple((n, c) for n, c in spec.attribute_choices if n != node_id),
    )


def _pruned_reason(pruned: tuple[int, ...], what: str) -> str:
    return (
        f"{what}에서 PoB가 노드 {len(pruned)}개를 잘랐다{list(pruned)[:5]} — "
        "요청한 트리가 반영되지 않았으므로 값을 쓰지 않는다"
    )


def _head(graph: TreeGraph, node_id: int) -> dict[str, Any]:
    node = graph.nodes.get(node_id)
    return {
        "name_en": node.name_en if node else "",
        "name_ko": node.name_ko if node else "",
        "kind": node.kind if node else "",
    }


# ────────────────────── 제거 측정 ──────────────────────


@dataclass(frozen=True)
class NodeRemoval:
    """노드 하나를 뺐을 때의 실측. **`measured`가 False면 `deltas`는 비어 있다.**"""

    node_id: int
    name_en: str
    name_ko: str
    kind: str
    removed: tuple[int, ...]
    points: int  # 회수 포인트 (제거로 되돌려받는 양)
    pool: str  # 그 포인트가 어느 예산인가 — passive|ascendancy (#68)
    deltas: dict[str, float]  # stat → (변경안 - 기준). **음수 = 나빠졌다** = negative 표본
    pruned: tuple[int, ...] = ()
    failed: str = ""  # 측정 실패 사유 (비어 있으면 유효)

    @property
    def measured(self) -> bool:
        """값을 써도 되는가 — 실패 사유가 없고 잘린 노드도 없어야 한다."""
        return not self.failed and not self.pruned

    def per_point(self, stat: str) -> float:
        return self.deltas.get(stat, 0.0) / max(self.points, 1)


def evaluate_removals(
    spec: BuildSpec,
    graph: TreeGraph,
    targets: Sequence[int],
    *,
    stats: tuple[str, ...] = _DEFAULT_STATS,
    daemon: PobDaemon | None = None,
) -> list[NodeRemoval]:
    """`targets`를 하나씩 빼서 각각의 델타를 실측한다 — 데몬 1개로 N회.

    **표본을 버리지 않는다.** 제거 불가·pruned 발생은 결과에 `failed` 사유로 실려
    나온다. `evaluate_node_deltas`(추가)는 pruned 표본을 `continue`로 버리는데,
    거기서는 "그 후보를 안 쓴다"로 끝나지만 반사실에서는 **몇 건이 왜 빠졌는가**가
    데이터셋의 신뢰도 그 자체다.

    `evaluate_node_deltas`를 재사용할 수 없는 이유: ①`graph.shortest_path`로 **더하는**
    경로만 만든다(제거 경로가 없다) ②위의 표본 폐기 방침이 반대다. 기준·변형 계산과
    델타 산술은 이 모듈 안에서 `evaluate_swaps`와 공유한다(중복 없음).
    """
    candidates = removable_nodes(spec, graph)
    allowed = set(candidates.nodes)
    own = daemon is None
    d = daemon or PobDaemon()
    out: list[NodeRemoval] = []
    try:
        base = d.compute_build(spec)
        base_failed = _pruned_reason(base.pruned_nodes, "기준 빌드") if base.pruned_nodes else ""
        for nid in targets:
            failed = base_failed or (
                ""
                if nid in allowed
                else candidates.blocked.get(nid, "할당돼 있지 않다 — 뺄 것이 없다")
            )
            pruned: tuple[int, ...] = ()
            deltas: dict[str, float] = {}
            if not failed:
                result = d.compute_build(_drop(spec, nid))
                pruned = result.pruned_nodes
                if pruned:
                    failed = _pruned_reason(pruned, f"노드 {nid} 제거안")
                else:
                    deltas = {
                        k: round(result.stats.get(k, 0.0) - base.stats.get(k, 0.0), 4)
                        for k in stats
                    }
            out.append(
                NodeRemoval(
                    node_id=nid,
                    removed=(nid,),
                    points=1,
                    pool=_pool(graph, nid),
                    deltas=deltas,
                    pruned=pruned,
                    failed=failed,
                    **_head(graph, nid),
                )
            )
    finally:
        if own:
            d.close()
    return out


# ────────────────────── 교체 측정 ──────────────────────


@dataclass(frozen=True)
class SwapDelta:
    """빼고 넣기를 **한 빌드에서 동시에** 잰 실측. `measured`가 False면 `deltas`는 비어 있다."""

    out_node: int
    in_node: int
    name_out: str
    name_in: str
    removed: tuple[int, ...]
    added: tuple[int, ...]  # 실제로 더해진 노드 전량 (연결 경로 포함)
    points: int  # 순증 포인트 = len(added) - len(removed). 음수면 포인트가 남는다
    pool: str
    deltas: dict[str, float]
    pruned: tuple[int, ...] = ()
    failed: str = ""

    @property
    def measured(self) -> bool:
        return not self.failed and not self.pruned


def _swap_problem(
    spec: BuildSpec,
    graph: TreeGraph,
    candidates: RemovalCandidates,
    reduced: frozenset[int],
    out_node: int,
    in_node: int,
) -> str:
    """교체가 성립하지 않는 사유 (없으면 빈 문자열) — PoB를 부르기 전에 거는 결정적 검사."""
    if out_node not in set(candidates.nodes):
        return candidates.blocked.get(out_node, "할당돼 있지 않다 — 뺄 것이 없다")
    if problem := _target_problem(spec, graph, in_node, reduced):
        return problem
    if (out_pool := _pool(graph, out_node)) != (in_pool := _pool(graph, in_node)):
        return (
            f"포인트 풀이 다르다({out_pool} → {in_pool}) — 전직 포인트와 일반 패시브는 "
            "별도 예산이라 교체가 성립하지 않는다(#68)"
        )
    return ""


def evaluate_swaps(
    spec: BuildSpec,
    graph: TreeGraph,
    swaps: Sequence[tuple[int, int]],
    *,
    stats: tuple[str, ...] = _DEFAULT_STATS,
    daemon: PobDaemon | None = None,
) -> list[SwapDelta]:
    """`(빼는 노드, 넣는 노드)` 쌍을 **한 빌드에서 동시에** 재고 델타를 낸다.

    교체 = 제거 1 + 추가 1이지만 **따로 재서 더한 값이 아니다.** 임계를 넘겨야 열리는
    축에서는 둘을 합친 결과가 개별 합과 어긋난다(`evaluate_bundles` 머리주석의
    곱연산 축과 같은 이유 — 실측 2026-08-05: 단독 델타 0인 둘이 함께 1.44배).

    추가 쪽 경로는 `graph.shortest_path`를 재사용하되 **제거한 뒤의 트리**에서 잡는다.
    제거 전 트리에서 잡으면 방금 뺀 노드를 경유하는 경로가 나와 교체가 성립하지
    않는다 — 그 경우는 조용히 통과시키지 않고 사유를 붙여 낸다.

    **풀이 다른 교체는 재지 않는다** — 전직 포인트로 본 트리 노드를 찍을 수 없다(#68).
    """
    candidates = removable_nodes(spec, graph)
    roots = frozenset(candidates.roots)
    own = daemon is None
    d = daemon or PobDaemon()
    out: list[SwapDelta] = []
    try:
        base = d.compute_build(spec)
        base_failed = _pruned_reason(base.pruned_nodes, "기준 빌드") if base.pruned_nodes else ""
        for out_node, in_node in swaps:
            reduced = (frozenset(spec.tree_nodes) - {out_node}) | roots
            added: tuple[int, ...] = ()
            pruned: tuple[int, ...] = ()
            deltas: dict[str, float] = {}
            failed = base_failed or _swap_problem(
                spec, graph, candidates, reduced, out_node, in_node
            )
            if not failed:
                path = graph.shortest_path(set(reduced), in_node)
                if not path:
                    failed = (
                        "도달 불가 — 제거 후 트리에서 이 노드로 가는 길이 없다"
                        if path is None
                        else "이미 트리에 있다 — 넣을 것이 없다"
                    )
                elif out_node in path:
                    failed = f"추가 경로가 제거한 노드 {out_node}를 다시 지나간다 — 교체가 아니다"
                else:
                    added = tuple(path)
                    result = d.compute_build(_drop(spec, out_node, added))
                    pruned = result.pruned_nodes
                    if pruned:
                        failed = _pruned_reason(pruned, f"{out_node}→{in_node} 교체안")
                    else:
                        deltas = {
                            k: round(result.stats.get(k, 0.0) - base.stats.get(k, 0.0), 4)
                            for k in stats
                        }
            removed = (out_node,)
            out.append(
                SwapDelta(
                    out_node=out_node,
                    in_node=in_node,
                    name_out=str(_head(graph, out_node)["name_en"]),
                    name_in=str(_head(graph, in_node)["name_en"]),
                    removed=removed,
                    added=added,
                    points=len(added) - len(removed),
                    pool=_pool(graph, out_node),
                    deltas=deltas,
                    pruned=pruned,
                    failed=failed,
                )
            )
    finally:
        if own:
            d.close()
    return out


# ────────────────────── 코퍼스 순회 입구 ──────────────────────


def corpus_counterfactuals(
    graph: TreeGraph,
    season: str,
    concept: str,
    select: Callable[[BuildSpec, RemovalCandidates], Sequence[int]],
    *,
    base: Path | None = None,
    limit: int | None = None,
    stats: tuple[str, ...] = _DEFAULT_STATS,
    daemon: PobDaemon | None = None,
) -> list[dict[str, Any]]:
    """래더 코퍼스를 되돌려(`restore.spec_from_pob`) 제거 측정을 돌리는 **얇은** 입구.

    `select(spec, candidates) -> 뺄 노드들`은 **호출자가 준다**. 어느 노드를 뽑아볼지는
    판단이고(철칙 3), 여기 박으면 데이터셋 전체가 그 판단에 물든다.

    ⚠ 반쯤 복원된 스펙의 측정을 온전한 것으로 읽으면 안 된다 — `RestoredBuild.notes`·
    `needs_decision`·`damage_comparable`을 행마다 함께 싣는다(복원 300벌 중 203벌이
    아이템 부여 스킬 때문에 딜 비교 불가다). 못 되돌린 빌드도 `skipped` 사유로 남긴다.

    반환만 하고 **아무것도 쓰지 않는다** — 저장 규약은 구조 결정이다(철칙 1).
    """
    from pok.artifacts.ladder import LadderError, ladder_dir
    from pok.pob.buildxml import spec_from_dict
    from pok.pob.restore import spec_from_pob

    folder = (base or ladder_dir()) / season / concept
    files = sorted(folder.glob("*.json"))[:limit]
    if not files:
        raise LadderError(f"수집된 것이 없다: {folder}")

    own = daemon is None
    d = daemon or PobDaemon()
    out: list[dict[str, Any]] = []
    try:
        for path in files:
            row: dict[str, Any] = {"file": path.name}
            doc = json.loads(path.read_text(encoding="utf-8"))
            try:
                restored = spec_from_pob(str(doc.get("pob_export") or ""))
                # `validate_catalog=False`: 카탈로그 검증은 **우리가 스펙을 쓸 때**의
                # 게이트다. 남의 빌드를 재는 자리에서 켜면 젬 표기 차이 하나로 표본이
                # 조용히 줄어든다 — 대신 복원 노트를 행에 실어 판단을 넘긴다.
                spec = spec_from_dict(restored.spec, validate_catalog=False)
                candidates = removable_nodes(spec, graph)
            except (KeyError, ValueError) as exc:  # 코드 손상·알 수 없는 클래스 등
                row["skipped"] = f"{type(exc).__name__}: {exc}"
                out.append(row)
                continue
            row["restored"] = {
                "faithful": restored.faithful,
                "damage_comparable": restored.damage_comparable,
                "notes": list(restored.notes),
                "needs_decision": list(restored.needs_decision),
                "dropped_item_granted": [
                    {"skill": n, "lost_supports": k} for n, k in restored.dropped_item_granted
                ],
            }
            row["tree"] = {
                "class_name": spec.class_name,
                "ascendancy": spec.ascendancy,
                "allocated": len(spec.tree_nodes),
                "removable": len(candidates.nodes),
                # 우리 그래프가 본 비연결. PoB의 `pruned`와 어긋나면 KB 연결 수집 갭이다
                "graph_orphans": list(candidates.orphans),
            }
            row["removals"] = [
                dataclasses.asdict(r)
                for r in evaluate_removals(
                    spec, graph, [int(t) for t in select(spec, candidates)], stats=stats, daemon=d
                )
            ]
            out.append(row)
    finally:
        if own:
            d.close()
    return out
