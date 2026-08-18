"""트리 최적화 루프 — P4 Phase 3 (BLUEPRINT §10.3).

그리디: 매 라운드 후보를 현재 빌드 문맥에서 델타 실측하고, 정책(Objective)
점수가 가장 높은 노드를 채택한다. 채택된 모든 스텝에 실측 델타가 남는다
(= Exit 기준 "포인트마다 델타로 정당화"). 전역 최적은 보장하지 않는다 —
근접-최적 + 근거를 목표로 한다(§10.3 한계 인정).

정책(무엇을 가중할지)은 호출자(에이전트/사용자)의 몫 — 엔진은 점수 계산과
탐색 대행만 한다(AD-3). 단일 축 금지(RC3): Objective는 다축 가중이 기본.
"""

from __future__ import annotations

import dataclasses
import functools
import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol

from pok.engine.jewel_placement import Placement, place_jewels
from pok.engine.objective import Target, TargetResult, evaluate_targets
from pok.engine.tree.clusters import Cluster, find_clusters, relevance
from pok.engine.tree.deltas import BundleDelta, NodeDelta, evaluate_bundles, evaluate_node_deltas
from pok.engine.tree.graph import ASCENDANCY_POINTS, TreeGraph
from pok.pob.buildxml import BuildSpec, JewelSpec
from pok.pob.daemon import PobDaemon
from pok.pob.runner import PobResult

# 마른 라운드에서 넓힐 상한. 트리 지름을 넘겨 봐야 무의미하고, 라운드 비용이
# 후보 수에 비례해 늘어난다(후보 하나 = PoB 계산 1회).
_MAX_REACH = 24
_MAX_SLICE = 160

# 사전식 목표가 있을 때 **부차 축**에 남기는 몫. 0으로 두면 병목에 기여하지
# 않는 수가 전부 점수 0이 되어(그리디는 s>0만 채택) 예산이 남은 채 멈춘다.
_TIEBREAK = 1e-3


class Measured(Protocol):
    """점수를 매길 수 있는 실측 결과 — **노드 하나든 묶음이든** 이 둘만 있으면 된다.

    긴 점프(#70)가 뭉치를 노드 후보와 **같은 저울**에 올리려면 `Objective`가 둘 다
    받아야 한다. 타입을 `NodeDelta`로 좁혀 두면 뭉치를 재는 순간 mypy가 막는다.
    """

    @property
    def deltas(self) -> dict[str, float]: ...

    @property
    def points(self) -> int: ...


@dataclass(frozen=True)
class Objective:
    """다차원 목적 가중 (RC3). 점수 = Σ w_s x (델타_s / max(기준_s, floor_s)) / 포인트.

    상대화(기준 대비 %)로 스탯 간 스케일 차이를 흡수한다. floor는 기준값이
    0에 가까울 때의 폭주 방지(예: ES 0인 빌드에서 ES 델타).

    **`targets`를 주면 가중 합산이 아니라 사전식(D28)으로 돈다.** 가중 합산은
    한 축이 지배한다 — DPS 가중치가 크면 EHP가 바닥이어도 DPS를 계속 올리는 수가
    항상 이긴다. "한쪽으로 쏠리지 않게"는 가중치를 손으로 맞춰서가 아니라
    **경계를 채우면 다음 축으로 넘어가게** 해서 얻는다(사용자 정리 2026-08-12).

    - 매 수마다 **현재 실측값**으로 병목을 다시 잡는다(고정이 아니다).
    - **이미 충족한 목표를 깨뜨리는 수는 배제한다** — 이게 없으면 그리디가
      EHP 경계를 헐어 DPS로 옮기는 짓을 한다.
    - 병목 축을 **못 재면**(measured None) 그 목표로는 그리디를 몰 수 없다 —
      건너뛰고 다음 목표를 본다. 안 그러면 델타가 전부 0이라 즉시 멈춘다
      (BACKLOG 형태 ②: 축이 측정에 없으면 점수 0).
    """

    weights: dict[str, float]  # 예: {"CombinedDPS": 1.0, "Life": 0.7, "TotalEHP": 0.5}
    floors: dict[str, float] = field(default_factory=dict)
    targets: tuple[Target, ...] = ()

    def _relative(self, stat: str, value: float, base_stats: dict[str, float]) -> float:
        denom = max(abs(base_stats.get(stat, 0.0)), self.floors.get(stat, 1.0))
        return value / denom

    def _weighted(self, delta: Measured, base_stats: dict[str, float]) -> float:
        return sum(
            w * self._relative(stat, delta.deltas.get(stat, 0.0), base_stats)
            for stat, w in self.weights.items()
        )

    def focus(self, base_stats: dict[str, float]) -> TargetResult | None:
        """지금 몰아야 할 목표 — 첫 미충족이되 **잴 수 있는** 것."""
        if not self.targets:
            return None
        report = evaluate_targets(self.targets, base_stats)
        for result in report.results:
            if not result.satisfied and result.measured is not None:
                return result
        return None

    def _breaks_floor(self, delta: Measured, base_stats: dict[str, float]) -> bool:
        """이미 충족한 경계를 이 수가 무너뜨리는가."""
        for result in evaluate_targets(self.targets, base_stats).results:
            if not result.satisfied or result.measured is None:
                continue
            after = result.measured + delta.deltas.get(result.metric, 0.0)
            if (result.op == ">=" and after < result.value) or (
                result.op == "<=" and after > result.value
            ):
                return True
        return False

    def score(self, delta: Measured, base_stats: dict[str, float]) -> float:
        if not self.targets:
            return self._weighted(delta, base_stats) / max(delta.points, 1)
        if self._breaks_floor(delta, base_stats):
            return float("-inf")  # 채택 조건이 s > 0이라 확실히 배제된다
        target = self.focus(base_stats)
        if target is None:
            # 전부 충족했거나 남은 목표를 못 잰다 → 원래 가중 합산으로 돌아간다
            return self._weighted(delta, base_stats) / max(delta.points, 1)
        sign = 1.0 if target.op == ">=" else -1.0
        primary = sign * self._relative(
            target.metric, delta.deltas.get(target.metric, 0.0), base_stats
        )
        return (primary + _TIEBREAK * self._weighted(delta, base_stats)) / max(delta.points, 1)


@dataclass(frozen=True)
class Step:
    """채택된 한 수 — 실측 근거 포함."""

    node_delta: NodeDelta
    score: float


@dataclass(frozen=True)
class Pruned:
    """가지치기로 제거된 가지 하나 — 끝단(죽은 노터블)+막다른 소노드.

    끝단의 단독 기여 ~0이 확인되면 막다른 가지를 환급한다: 막다른 길에 포인트를
    쓰는 건 유저 관점에서 비합리적이므로(사용자 지적 2026-07-31), 환급 후 재투자
    결과와 실측 비교해 나은 쪽을 취한다.

    **`nodes`의 모든 노드는 개별 검증을 통과한 것이다.** 예전엔 끝단만 재고 안쪽
    연쇄를 무검증으로 함께 지웠는데, 실측에서 -478 DPS가 났다(2026-08-04 빌드
    테스트). 끝단이 죽었다고 그 안쪽까지 죽었다는 보장이 없다 — 막다른 길에도
    생명력·피해 소노드가 앉아 있다.
    """

    endpoint_id: int
    endpoint_name: str
    nodes: tuple[int, ...]  # 제거된 노드 — **각각 개별 검증 통과** (끝단 포함)
    endpoint_removal_deltas: dict[str, float]  # 끝단 단독 제거 델타 (~0 = 죽음의 증거)
    chain_removal_deltas: dict[str, float]  # **가지 전체** 제거 후 델타 — 손실 판정은 이것
    chain_truncated: bool = False  # 살아 있는 노드를 만나 도중에 멈췄는가


@dataclass(frozen=True)
class OptimizeResult:
    spec: BuildSpec  # 최적화 후
    result: PobResult  # 최종 실측
    steps: tuple[Step, ...]  # 채택 순서대로 (각각 델타 근거)
    pruned: tuple[Pruned, ...]  # 가지치기로 회수된 죽은 노드들
    rejected_rounds: int  # 양의 점수 후보가 없어 중단됐으면 1
    # 후보 반경 **밖**의 관련 노터블 뭉치 — 그리디는 구조적으로 못 본다(제안 A).
    # `cluster_include`를 줘야 채워진다(관련성 필터 없는 밀집도는 쓰레기라서).
    far_clusters: tuple[Cluster, ...] = ()
    notes: tuple[str, ...] = ()
    # 앵커가 쓴 **전직** 포인트 — `point_budget`(일반 패시브)과 별도 풀이다(#68).
    # 합쳐 세면 전직 노드를 앵커로 넣을수록 일반 트리가 작아진다.
    ascendancy_points: int = 0
    # 스냅샷 주얼을 새 트리에 되배치한 내역 — **왜 거기인지**가 각각 붙어 있다.
    jewel_placements: tuple[Placement, ...] = ()

    @property
    def wasted_points(self) -> int:
        """**채택했다가 회수한** 포인트 — 예산을 태우고 아무것도 못 산 몫.

        실측 2026-08-05: 마지막 8스텝이 3~4포인트씩 썼는데 그중 7개가 가지치기에서
        델타 0으로 잡혔다. 회수 자체는 되지만 "이 지출이 무효였다"가 신호로 읽히지
        않아, 세션은 예산을 다 쓴 트리를 정상 산출물로 받았다.
        """
        return sum(len(p.nodes) for p in self.pruned)

    @property
    def waste_notes(self) -> tuple[str, ...]:
        """헛돈 예산을 문장으로 — 보이지 않으면 판단할 수도 없다(AD-3, 룬 소켓과 같은 성격)."""
        if not self.pruned:
            return ()
        out = [
            f"⚠ 채택 후 회수 {self.wasted_points}포인트 / 스텝 {len(self.pruned)}개 — "
            f"**그만큼의 예산이 순 효과 없이 소모됐다.** 후보 반경"
            f"(`candidate_radius`)이나 라운드당 후보 수를 늘려 더 먼 노드를 보게 하라"
        ]
        truncated = [p for p in self.pruned if p.chain_truncated]
        if truncated:
            out.append(
                f"그중 {len(truncated)}건은 살아 있는 노드를 만나 **가지 일부만** "
                f"회수됐다 — 남은 통행 노드는 그대로 예산을 점유한다"
            )
        return tuple(out)


def _power_ranked(
    daemon: PobDaemon,
    graph: TreeGraph,
    current: BuildSpec,
    tree_now: set[int],
    budget: int,
    banned: set[int],
    slice_size: int,
) -> list[int]:
    """PoB `POWER`로 **트리 전체**를 훑어 포인트당 상위 후보를 낸다 (#77 대응).

    그리디의 구조적 한계는 「반경 안만 본다」였다 — #70 재검증 실측: 예산 82포인트를
    더 쓰고 폭을 **0.4%**만 넓혔고, 대각선이 정답지의 75%·DPS가 53%에서 멈췄다.
    `POWER`는 미할당 노드 전량(3,793개)을 한 번에 재므로 반경 개념이 없다.

    ⚠ **값이 아니라 순위만 쓴다.** `POWER`는 노드 하나만 더한 값이라 **경로 비용이
    빠져 있다**(PoB 자신이 "Estimate"라 부른다). 전직 8종 실측: 값 오차 중앙 16.9%,
    순위 상관은 총량 상관 0.808인데 **포인트당 0.954**다. 그래서 여기서도 포인트당으로
    줄 세운다 — 그 보정이 곧 빠진 경로 비용의 근사다.

    ⚠ **얕게 자르면 놓친다.** 실제 상위 5를 담으려면 추정 상위 **25위**까지 필요한
    전직이 있었다(Witch3b). `slice_size`를 그대로 쓰는 이유이고, 줄이지 말 것.
    """
    power, _meta = daemon.node_power(("CombinedDPS", "TotalEHP"))
    scored: list[tuple[float, int]] = []
    for nid, deltas in power.items():
        if nid in tree_now or nid in banned or nid not in graph.nodes:
            continue
        path = graph.shortest_path(tree_now, nid)
        if not path or len(path) > budget:
            continue
        gain = max(deltas.get("CombinedDPS", 0.0), 0.0)
        if gain <= 0:
            continue
        scored.append((gain / len(path), nid))
    scored.sort(reverse=True)
    return [nid for _, nid in scored[:slice_size]]


def _with_free_zones(
    candidates: Iterable[tuple[int, Any, int]], cost: Callable[[int, int], int]
) -> list[tuple[int, Any, int]]:
    """후보의 거리(=포인트 비용)를 비연결 영역 규칙으로 다시 매긴다 (제안 A)."""
    return [(nid, meta, cost(nid, dist)) for nid, meta, dist in candidates]


def optimize_tree(
    spec: BuildSpec,
    graph: TreeGraph,
    objective: Objective,
    *,
    point_budget: int,
    candidate_radius: int = 8,
    max_candidates_per_round: int = 40,
    power_candidates: bool = False,
    stats: tuple[str, ...] | None = None,
    jewel_templates: tuple[str, ...] = (),
    exclude_nodes: tuple[int, ...] = (),
    unconnected_regions: tuple[Mapping[str, Any], ...] = (),
    cluster_include: tuple[tuple[str, float], ...] = (),
    cluster_exclude: tuple[str, ...] = (),
    required_anchors: tuple[int, ...] = (),
    time_budget_s: float | None = None,
) -> OptimizeResult:
    """포인트 예산 안에서 정책 점수가 양수인 최선 수를 반복 채택한다.

    후보 = 현재 트리에서 candidate_radius 안의 notable/keystone/jewel-socket
    (거리순 상한 max_candidates_per_round — 초과분은 다음 라운드에서 트리가
    자라며 자연히 반경에 들어온다). 주얼 소켓의 가치는 장착 주얼이 있어야
    보인다(빈 소켓 델타 0) — jewel_templates(**가정 탐침**, 설계물이 아니다)를 주면
    소켓 후보를 템플릿별로 실측해 목적 점수 최고인 템플릿으로 평가하고,
    채택 시 spec.jewels에 해당 JewelSpec을 편입한다. 가지치기가 소켓을
    제거하면 주얼도 함께 제거된다.
    """
    # 목표 축이 측정 목록에 없으면 델타에 안 들어와 **병목을 밀 수단이 없다**.
    # 가중치 키만 재던 옛 코드에 targets를 얹으면 조용히 그렇게 된다.
    measure = tuple(
        dict.fromkeys(
            [*(stats or objective.weights.keys()), *(t.metric for t in objective.targets)]
        )
    )
    steps: list[Step] = []
    pruned: list[Pruned] = []
    # 죽음이 실증된 끝단(재채택 금지 — 종료 보장) + 호출자가 설계 판단으로 뺀 노드
    banned: set[int] = set(exclude_nodes)
    free_zones = [
        ((float(r["center"][0]), float(r["center"][1])), float(r["radius"]))
        for r in unconnected_regions
    ]

    def reachable_cost(node_id: int, walked: int) -> int:
        """비연결 주얼이 덮는 원 안이면 통행 비용이 없다 — 자기 1포인트만."""
        node = graph.nodes.get(node_id)
        if node is None or node.position is None or not free_zones:
            return walked
        for center, radius in free_zones:
            if math.dist(center, node.position) <= radius:
                return 1
        return walked

    # ── 필수 앵커 먼저 박는다 (점수 경쟁과 분리) ──
    #
    # 메커니즘에 반드시 필요한 노드에 **높은 가중치**를 주는 방식은 틀렸다 — 가중치는
    # 여전히 경쟁이라, 점수가 더 높은 다른 노드에 밀린다. 필수는 경쟁 대상이 아니라
    # **통과점**이다(사용자 정리 2026-08-12). 그리고 PoB가 못 재는 메커니즘 노드는
    # 델타가 0이라 그리디가 **절대** 안 뽑는다 — 여기서 박지 않으면 영영 안 들어온다.
    # 최적화 **전** 주얼을 스냅샷한다 — 끝나고 새 트리에 되배치할 원본이다.
    jewel_snapshot = tuple(j.text for j in spec.jewels if j.text)
    spec, anchor_notes, anchor_cost = _seed_anchors(spec, graph, required_anchors, point_budget)
    current = spec
    # 전직 포인트는 **빼지 않는다** — 인게임에서 별도 풀이라 일반 트리를 갉으면 안 된다(#68).
    budget = max(0, point_budget - anchor_cost.general)
    rejected = 0
    # 주얼 소켓은 **빈 채로는 델타 0**이다 — 템플릿이 없으면 그리디가 영영 안 찍는다.
    # 실측 2026-08-12: 같은 소켓이 템플릿 없이 0, 매직 주얼 +10.16 DPS, 레어 +21.07.
    # 래더 표본은 소켓을 중앙 5개 찍는데 우리 산출물은 앵커로 받은 것뿐이었다.
    # ⛔ 예전처럼 **고정 가중치를 가정하지 않는다**(AD-8 반프록시): 주얼 품질에 따라
    #    값이 2배 넘게 갈리므로 상수로는 표현할 수 없다. 재려면 템플릿을 줘야 하고,
    #    안 줬다면 **0으로 재고 있다는 사실을 말한다**.
    # 소켓이 트리에 들어갔을 때만 뜨면 되는 것과, **입력 결함이라 항상 떠야 하는 것**을
    # 가른다. 반경 선언 누락은 후자다 — 소켓을 하나도 안 찍었어도 템플릿이 망가진 건
    # 망가진 것이고, 다음 실행에서 그대로 또 0을 잰다.
    jewel_notes: list[str] = []
    template_notes: list[str] = []
    if not jewel_templates:
        jewel_notes.append(
            "주얼 템플릿이 없어 소켓을 **0으로 쟀다** — 빈 소켓은 델타가 0이라 "
            "그리디가 영영 안 찍는다(래더 표본은 중앙 5개를 찍는다). "
            "⚠ **모두에게 맞는 주얼은 없다**(사용자 지적 2026-08-12) — 손으로 짜지 말고 "
            '소켓을 먼저 할당한 뒤 `optimize_rare(slot="Jewel@<소켓 node_id>")`로 '
            "**이 빌드 전용** 주얼을 뽑아 그 text를 `jewel_templates`에 넣을 것. "
            "여기 템플릿은 설계물이 아니라 **소켓 값을 재기 위한 가정 탐침**이다"
        )
    else:
        from pok.engine.jewels import needs_radius_declaration

        bad = [
            (tpl.splitlines()[1] if len(tpl.splitlines()) > 1 else tpl[:30])
            for tpl in jewel_templates
            if needs_radius_declaration(tpl)
        ]
        if bad:
            # 반경 주얼(Time-Lost 계열)은 `Radius:` 선언이 없으면 **어느 소켓에서든
            # 델타 0**이다(실측: 선언하면 CritChance 10.44 → 15.84). 조용한 과소 계상.
            template_notes.append(
                f"⚠ 반경 선언(`Radius:`)이 없는 주얼 템플릿 {bad} — 반경이 안 정해져 "
                "**어느 소켓에서든 델타 0**이다. `engine.jewels.render_radius_jewel`로 "
                "그 주얼의 실제 반경 라벨을 붙일 것"
            )

    # ⏱ **시간 상한.** 후보 하나가 PoB 계산 1회(실측 0.16초)이고 라운드마다 후보
    # 수만큼 돈다 — 예산 156·후보 40이면 가지치기 재실행까지 합쳐 **40분을 넘긴다**
    # (실측 2026-08-12: 진행 표시도 없이 45분째 돌던 실행을 죽였다). 상한이 없으면
    # 세션이 통째로 멈추고, 그 사이 무엇이 되고 있는지 알 방법도 없다.
    started = time.monotonic()

    def out_of_time() -> bool:
        return time_budget_s is not None and (time.monotonic() - started) >= time_budget_s

    # 마른 라운드에서 **넓혀 보고** 멈춘다 — 아래 주석 참고.
    reach, slice_size = candidate_radius, max_candidates_per_round
    widened: list[str] = []
    # 긴 점프(#70) 채택 기록 — 노드 한 수와 섞여 있으면 「먼 축을 열었다」가 안 보인다.
    long_jumps: list[str] = []
    with PobDaemon() as daemon:
        best_solution: tuple[BuildSpec, PobResult] | None = None  # 단조성 안전장치
        while True:
            # ── 그리디 채택 ──
            rejected = 0
            while budget > 0:
                if out_of_time():
                    break
                tree_now = set(current.tree_nodes) | {graph.start_of(current.class_name)}
                if power_candidates:
                    # ⚠ 반경을 **안 본다.** 그리디의 구조적 한계가 「반경 안만 본다」였고
                    #   (#77 실측: 폭의 0.4%만 그리디가 더했다), PoB의 `POWER`는 트리
                    #   전체 3,793노드를 한 번에 잰다(25.6초). 값은 못 쓰고 **포인트당
                    #   순위**만 쓴다 — 경로 비용이 빠져 있어서다(전직 8종 실측:
                    #   총량 0.808 · 포인트당 0.954).
                    cands = _power_ranked(
                        daemon, graph, current, tree_now, budget, banned, slice_size
                    )
                else:
                    cands = [
                        nid
                        for nid, _, d in _with_free_zones(
                            graph.candidates(
                                tree_now,
                                max_dist=reach,
                                # 빌드의 전직을 넘겨야 **자기** 해금 노드를 후보로 받는다.
                                # 안 넘기면 기본 None → 잠긴 노드 전량 배제라 안전하되 과잉:
                                # 오라클 빌드가 오라클 전용 노터블 42개를 못 본다(B-13 실측).
                                ascendancy_name=current.ascendancy,
                            ),
                            reachable_cost,
                        )
                        if d <= budget and nid not in banned
                    ][:slice_size]
                if not cands:
                    break
                base = daemon.compute_build(current)
                deltas = evaluate_node_deltas(
                    current,
                    graph,
                    cands,
                    stats=measure,
                    daemon=daemon,
                    jewel_templates=jewel_templates,
                    # 템플릿 선택도 같은 정책으로 — 기준은 이번 라운드의 실측 스탯
                    jewel_score=functools.partial(objective.score, base_stats=base.stats),
                )
                scored = sorted(
                    ((objective.score(nd, base.stats), nd) for nd in deltas),
                    key=lambda x: -x[0],
                )
                affordable = [(s, nd) for s, nd in scored if nd.points <= budget and s > 0]

                # ── 긴 점프 (#70) — 매 라운드 노드와 **같은 저울**에서 겨룬다 ──
                # 먼 목적지로 가는 첫 걸음은 통행 소노드라 델타가 0에 가깝다. 포인트당
                # 으로 재는 그리디는 그 한 걸음을 절대 안 뽑고, 그래서 목적지의 값이
                # 아무리 커도 **출발 자체를 안 한다**. 반경을 넓혀도 안 고쳐진다 —
                # 반경 문제가 아니라 가격 매기는 방식의 문제다(BACKLOG #70).
                #
                # ⛔ 「마를 때만」 재면 안 된다 — 가까운 수가 계속 잡히는 동안에는
                #    영영 평가되지 않아, 먼 축이 끝까지 안 열린다. 매 라운드 재는 값은
                #    실측했다: PoB 1회 0.418초, (기준 1 + 뭉치 15)회면 라운드당 +6.7초로
                #    노드 40개(16.7초) 대비 **+40%**다(실측 2026-08-13, 사용자 판정).
                for score_bd, bd in _bundle_candidates(
                    current,
                    graph,
                    objective,
                    base,
                    budget,
                    daemon=daemon,
                    stats=measure,
                    include=cluster_include,
                    exclude=cluster_exclude,
                    limit=slice_size,
                ):
                    affordable.append((score_bd, _as_node_delta(bd)))
                affordable.sort(key=lambda x: -x[0])

                if not affordable:
                    # ⛔ 예전엔 여기서 그냥 멈췄다 — **예산을 남긴 채**. 그리디는 반경
                    # 안의 가까운 후보만 보므로, 근처가 빌드와 무관한 권역이면 한 수도
                    # 못 두고 끝난다. 독스트링은 "반경·후보 수를 늘려라"라고 안내했지만
                    # 그건 문서에만 있는 규율이라 안 지켜졌다(실측 2026-08-12 e2e:
                    # 예산 30 중 8만 쓰고 종료). **도구가 스스로 넓혀 보고** 그래도
                    # 없을 때만 멈춘다 — 넓힌 사실은 notes로 남긴다.
                    if budget > 0 and reach < _MAX_REACH:
                        reach = min(_MAX_REACH, reach * 2)
                        slice_size = min(_MAX_SLICE, slice_size * 2)
                        widened.append(f"반경 {reach}·후보 {slice_size}")
                        continue
                    rejected = 1
                    break
                best_score, best = affordable[0]
                jewels = current.jewels
                if best.jewel_text is not None:
                    jewels = (
                        *current.jewels,
                        JewelSpec(socket_node_id=best.node_id, text=best.jewel_text),
                    )
                current = dataclasses.replace(
                    current, tree_nodes=tuple(current.tree_nodes) + best.path, jewels=jewels
                )
                budget -= best.points
                steps.append(Step(node_delta=best, score=best_score))
                if best.kind == "bundle":
                    long_jumps.append(
                        f"긴 점프 「{best.name_ko}」 {best.points}포인트 — "
                        "노드 단위 점수로는 첫 걸음에서 탈락해 못 가던 곳이다"
                    )
            result_now = daemon.compute_build(current)
            best_solution = _better(objective, best_solution, (current, result_now))
            # ── 가지치기: 죽은 끝단이면 막다른 가지 전체 제거·환급 ──
            current, newly_pruned, refund, candidates = _prune_dead_branches(
                spec, current, steps, graph, daemon, measure
            )
            for cand in candidates:  # 끝단만 뺀 중간 해들 — 무료 개선 후보
                best_solution = _better(objective, best_solution, cand)
            pruned.extend(newly_pruned)
            banned.update(p.endpoint_id for p in newly_pruned)
            if refund == 0 or out_of_time():
                break  # 죽은 가지 없음 — 안정 (또는 시간 상한)
            budget += refund  # 환급 포인트를 온전한 묶음에 재투자 (다음 루프)
        # 실측으로 가장 나은 해 반환 (동가치면 포인트 적게 쓴 쪽 — 스텁·죽은 끝단 배제)
        final = daemon.compute_build(current)
        best_solution = _better(objective, best_solution, (current, final))
        assert best_solution is not None
        current, final = best_solution
        # ── 스냅샷 주얼 되배치 ──
        #
        # 트리를 다시 짜면 소켓 구성이 달라진다. 가지치기가 트리에서 빠진 소켓의
        # 주얼을 **동반 제거**하는 것은 **의도된 것이다**(사용자 확인 2026-08-18) —
        # 소켓을 안 찍은 채로 주얼 모드가 계산에 들어가면 **측정 자체가 거짓말**이
        # 된다. 탐색 중에는 그대로 두고, **끝에서** 새 트리의 빈 소켓에 되돌려
        # 놓는다. 잘못이었던 것은 제거가 아니라 **침묵**이다 — 자리를 옮겼는지
        # 아예 못 놓았는지가 산출물에 안 나왔다.
        current, jewel_rows, jewel_place_notes = _restore_jewels(graph, current, jewel_snapshot)
        if jewel_rows:
            # 주얼이 바뀌었으면 **다시 잰다** — 안 그러면 실측값이 옛 주얼 구성의 것이다.
            final = daemon.compute_build(current)
    # 후보 반경 **밖**의 뭉치를 함께 낸다 — 그리디가 구조적으로 못 보는 것이다(제안 A).
    far, notes = _scan_far_clusters(
        graph, current, cluster_include, cluster_exclude, candidate_radius
    )
    notes = (*anchor_notes, *notes, *_target_notes(objective, final.stats))
    # 템플릿 결함은 **입력의 문제**라 소켓을 하나도 안 찍었어도 알린다 — 안 그러면
    # 다음 실행에서 같은 템플릿으로 또 0을 잰다.
    notes = (*notes, *template_notes)
    # ⚠ 이 경고에 조건을 걸었다가 **조용해졌다** — "소켓이 반경 안에 있을 때만"으로
    #   좁혔더니 실제 실행에서 안 떴다. 침묵이 과잉보다 나쁘다(이 결함 자체가 조용해서
    #   여러 회차를 살아남았다). 템플릿이 없으면 무조건 알린다.
    notes = (*notes, *jewel_notes)
    notes = (*notes, *jewel_place_notes)
    # 긴 점프는 **드러나야** 한다 — 노드 한 수와 섞여 있으면 「먼 축을 열었다」는
    # 사실이 보이지 않고, 그게 안 보이면 #70이 고쳐졌는지도 알 수 없다.
    notes = (*notes, *long_jumps)
    if widened:
        notes = (
            *notes,
            f"후보가 말라 탐색을 넓혔다: {' → '.join(widened)} — "
            "시작 반경이 이 빌드에 좁았다는 뜻이다(다음엔 candidate_radius를 올려 시작할 것)",
        )
    if time_budget_s is not None and out_of_time():
        notes = (
            *notes,
            f"⏱ 시간 상한 {time_budget_s:.0f}초를 넘겨 **중단했다** — 예산 {budget}포인트가 "
            f"남았다. 후보 하나가 PoB 계산 1회(약 0.16초)라 예산·후보 수에 비례해 는다. "
            "덜 최적화된 트리이지 완성된 트리가 아니다",
        )
    elif budget > 0:
        notes = (
            *notes,
            f"⚠ 예산 {budget}포인트를 **쓰지 못하고 끝났다** — 최대 반경까지 넓혀도 "
            "점수가 양수인 후보가 없었다. 목적(weights·targets)이 이 빌드에서 오르지 "
            "않는 축이거나, 남은 예산으로 닿을 곳이 없다",
        )
    return OptimizeResult(
        current,
        final,
        tuple(steps),
        tuple(pruned),
        rejected_rounds=rejected,
        far_clusters=far,
        notes=notes,
        ascendancy_points=anchor_cost.ascendancy,
        jewel_placements=tuple(jewel_rows),
    )


def _restore_jewels(
    graph: TreeGraph, spec: BuildSpec, snapshot: tuple[str, ...]
) -> tuple[BuildSpec, list[Placement], list[str]]:
    """스냅샷 주얼 중 **자리를 잃은 것**만 되배치한다.

    ⛔ 탐색 중의 동반 제거를 되돌리는 게 아니다 — 그건 옳다(소켓 없이 주얼 모드가
    계산에 들어가면 측정이 거짓이 된다). 여기는 **탐색이 끝난 뒤**, 남은 소켓에
    다시 앉히는 자리다.

    ⚠ 정품(스냅샷)과 **가정 탐침**(`jewel_templates`로 들어온 것)을 가른다 — 탐침은
    소켓 값을 재려고 넣은 가짜라, 자리를 두고 다투면 **정품이 이긴다**. 탐침이 밀려
    자리를 잃으면 그 소켓은 빈 채로 남는다(빈 소켓은 델타 0이지만, 가짜 주얼을
    산출물에 남기는 것보다 낫다 — 산출물은 설계지 탐침이 아니다).
    """
    if not snapshot:
        return spec, [], []
    homeless = list(snapshot)
    kept: list[JewelSpec] = []
    for jewel in spec.jewels:
        if jewel.text in homeless:  # 살아남은 정품 — 그 자리를 지킨다
            homeless.remove(jewel.text)
            kept.append(jewel)
    if not homeless:
        return spec, [], []
    # 탐침은 전부 뗀 자리에서 되배치한다 — 정품이 먼저 고른다.
    base = dataclasses.replace(spec, jewels=tuple(kept))
    placed, rows, notes = place_jewels(graph, base, tuple(homeless))
    moved = [r for r in rows if r.socket_node_id is not None]
    if moved:
        notes.append(
            f"주얼 {len(moved)}개가 **자리를 옮겼다** — 원래 소켓이 새 트리에서 "
            "빠졌다(가지치기가 회수했거나 애초에 안 찍혔다). 어디로 왜 갔는지는 "
            "`jewel_placements`에 각각 붙어 있다"
        )
    probes = len(spec.jewels) - len(kept)
    if probes:
        notes.append(
            f"가정 탐침 주얼 {probes}개를 뺐다 — 소켓 값을 재려고 넣은 가짜라 "
            "산출물에 남기지 않는다(정품 스냅샷이 자리를 먼저 갖는다)"
        )
    return placed, rows, notes


class AnchorCost(NamedTuple):
    """앵커 연결에 든 포인트 — **두 풀로 갈라서** 센다 (#68).

    인게임에서 어센던시 포인트는 일반 패시브 예산과 **별도 풀**이다. 예전엔 합쳐
    세서, 전직 노드를 앵커에 넣을수록 일반 트리 예산이 줄어 트리가 작아졌다 —
    포인트를 근거로 한 판단(예산 초과 경고·포인트당 효율)이 그만큼 틀렸다.
    """

    general: int  # 일반 패시브 — `point_budget`에서 뺀다
    ascendancy: int  # 전직 노드 — 별도 풀이라 일반 예산을 갉지 않는다


def _seed_anchors(
    spec: BuildSpec, graph: TreeGraph, anchors: tuple[int, ...], budget: int
) -> tuple[BuildSpec, tuple[str, ...], AnchorCost]:
    """필수 앵커를 트리에 먼저 연결하고, 그 결과를 **보호 대상 기준선**으로 만든다.

    반환한 스펙이 `optimize_tree`의 `spec`(= 가지치기가 건드리지 않는 원래 트리)이
    되므로, 앵커와 그 경로는 **델타가 0이어도 잘려 나가지 않는다.** 이게 핵심이다 —
    메커니즘 노드는 PoB가 못 재는 경우가 많아(트리거·일부 DoT) 델타 0으로 잡히고,
    보호하지 않으면 가지치기가 곧바로 회수해 버린다.
    """
    if not anchors:
        return spec, (), AnchorCost(0, 0)
    # 공짜로 켜져 있는 노드(블러드 메이지의 혈액술)는 출발 시점에 이미 트리에 있다.
    tree = (
        set(spec.tree_nodes)
        | {graph.start_of(spec.class_name)}
        | graph.granted_nodes(spec.ascendancy)
    )
    granted = graph.granted_nodes(spec.ascendancy)
    foreign = [
        n
        for n in anchors
        if (node := graph.nodes.get(n)) is not None
        and node.ascendancy
        and graph.resolve_ascendancy(node.ascendancy) != graph.resolve_ascendancy(spec.ascendancy)
    ]
    if foreign:
        # 남의 전직 노드는 인게임에서 못 찍는다 — 조용히 넣으면 거짓 트리가 나간다.
        return spec, (f"⛔ 다른 전직의 앵커 {foreign} — 빼고 진행했다",), AnchorCost(0, 0)
    added: list[int] = []
    asc_added: list[int] = []  # added의 부분집합 — 전직 노드만
    unreachable: list[int] = []
    for node_id in anchors:
        path = graph.shortest_path(tree, node_id)
        if path is None:
            unreachable.append(node_id)
            continue
        tree.update(path)
        # 전직 시작 노드는 통행만 하고 스펙에는 안 싣는다(위 graph.connect_anchors와 같은
        # 이유 — 넣으면 PoB가 잘라내고 그 트리의 측정이 전부 무효가 된다).
        for n in path:
            if n in granted:
                continue  # 공짜로 켜져 있다 — 어느 풀에서도 안 뺀다
            node = graph.nodes.get(n)
            if node is not None and node.kind == "ascendancy-start":
                continue
            added.append(n)
            # 전직 노드는 **별도 풀**이다 — 일반 예산에서 빼면 트리가 그만큼 작아진다(#68).
            if node is not None and node.ascendancy:
                asc_added.append(n)
    # 공짜 노드는 **스펙에는 남기고 포인트에서만** 뺀다 — 관문 하위·조건부 개방은
    # PoB가 자동 할당하지 않으므로 tree_nodes에서 빼면 그 트리가 재현되지 않는다.
    free = graph.free_nodes(spec.ascendancy, tree)
    paid_asc = [n for n in asc_added if n not in free]
    cost = AnchorCost(general=len(added) - len(asc_added), ascendancy=len(paid_asc))
    notes: list[str] = []
    if added:
        # 두 수를 **갈라서** 말한다 — 합쳐 말하면 일반 예산이 그만큼 줄었다고 읽힌다.
        asc_part = f" + 전직 {cost.ascendancy}포인트(별도 풀)" if cost.ascendancy else ""
        notes.append(
            f"필수 앵커 {len(anchors) - len(unreachable)}개를 먼저 연결했다 — "
            f"일반 {cost.general}포인트{asc_part}. "
            "점수 경쟁에서 제외되고 가지치기도 건드리지 않는다"
        )
    if unreachable:
        # 조용히 빼면 "앵커를 넣었다"고 믿은 채 없는 트리를 받는다.
        notes.append(f"⚠ 연결 불가 앵커 {unreachable} — 트리에 들어가지 않았다")
    if cost.general > budget:
        notes.append(
            f"⚠ 필수 앵커만으로 예산을 {cost.general - budget}포인트 **초과**했다 — "
            "그리디에 남은 예산이 없다. 앵커를 줄이거나 예산을 늘릴 것"
        )
    # 전직 풀도 상한이 있다(8 = 전직당 2포인트씩 4차). ⛔ 거부하지 않고 **경고만** 한다 —
    # 앵커를 빼는 판단은 해석 층의 몫이고, 여기서 자르면 근거 없이 트리가 바뀐다.
    if cost.ascendancy > ASCENDANCY_POINTS:
        notes.append(
            f"⚠ 전직 포인트 {cost.ascendancy}개는 상한 {ASCENDANCY_POINTS}을 넘는다 — "
            "인게임에서 못 찍는 트리다. 앵커에서 전직 노드를 줄일 것"
        )
    return (
        dataclasses.replace(spec, tree_nodes=tuple(spec.tree_nodes) + tuple(added)),
        tuple(notes),
        cost,
    )


def _target_notes(objective: Objective, stats: dict[str, float]) -> tuple[str, ...]:
    """목표 충족 상태를 문장으로 — **못 잰 축은 반드시 말한다**.

    PoB가 못 재는 축(트리거 발동률·일부 DoT)을 목표로 걸면 델타가 전부 0이라
    그리디가 그 축을 **한 걸음도 못 민다**. 조용히 넘어가면 "최적화했는데 안
    올랐다"로 읽힌다 — 안 오른 게 아니라 안 재진 것이다(BACKLOG 형태 ②·#44).
    """
    if not objective.targets:
        return ()
    report = evaluate_targets(objective.targets, stats)
    out: list[str] = []
    if report.unmeasured:
        out.append(
            f"⚠ 목표 축 {list(report.unmeasured)}을 **재지 못했다** — 그 축으로는 "
            "그리디를 한 걸음도 못 밀었다(값이 0이 아니라 측정이 없다). "
            "PoB가 못 재는 축이면 별도 측정기(예: compute_trigger_rate)로 확인할 것"
        )
    unmet = [r for r in report.results if not r.satisfied and r.measured is not None]
    if unmet:
        out.append(
            "미충족 목표: "
            + " · ".join(
                f"{r.label or r.metric} {r.measured:.0f} {r.op} {r.value:.0f}" for r in unmet
            )
        )
        # ⚠ **미달로 끝났다는 것은 사전식이 퇴화했다는 뜻이다.** 사전식은 「경계를
        #   채운 뒤 다음 축」인데, 못 채우면 끝까지 첫 축만 민다 — 아래 축은 순서에
        #   **한 번도 들어오지 못한다**. 그래서 이 산출물의 DPS는 「DPS를 최적화한
        #   결과」가 아니라 첫 축을 밀다 딸려 온 값이다. 미달 사실만 말하고 이걸 안
        #   말하면, 세션은 두 축을 다 최적화한 결과로 읽는다.
        #   실측 2026-08-18(데드아이): 트리만으로 도달 가능한 EHP가 정답지의 59%라
        #   바닥 60·80·100%가 전부 미달 — 서로 다른 바닥이 아니라 **서로 다른 세기의
        #   가중치**로 작동했다(DPS 88·110·153%로 뒤죽박죽).
        first = unmet[0]
        out.append(
            f"⚠ 첫 목표({first.label or first.metric})를 **끝내 못 채웠다** — 사전식은 "
            "경계를 채운 뒤 다음 축으로 넘어가는데, 못 채우면 **아래 축은 순서에 한 번도 "
            "들어오지 않는다**. 이 결과의 나머지 축 값은 최적화한 값이 아니라 딸려 온 "
            "값이니 「두 축을 다 봤다」로 읽지 말 것. 목표가 이 구성에서 **도달 가능한지** "
            "먼저 확인할 것(트리만으로 재는 중이면 주얼·장비 몫이 빠져 있다)"
        )
    return tuple(out)


_DESTINATION_KINDS = ("notable", "keystone", "jewel-socket")


def _far_destination_bundles(
    spec: BuildSpec,
    graph: TreeGraph,
    include: tuple[tuple[str, float], ...],
    exclude: tuple[str, ...],
    budget: int,
    limit: int,
) -> list[dict[str, Any]]:
    """긴 점프의 후보 — **축마다 하나씩**, 반경 밖의 목적지를 모은 묶음 (#70).

    ⚠ 예전엔 `find_clusters`(→`_scan_far_clusters`)의 결과를 그대로 먹였는데 **틀렸다.**
    거기서 나오는 `Cluster.label`은 `JEWEL_RADII`의 **주얼 반경 밴드**(Small/Medium/…)다
    — 오래된 기억류 주얼이 소켓 주변 반경 안의 노드에 옵션을 부여하는 그 범위이지
    「먼 목적지」와 무관하다(사용자 정정 2026-08-13). 실측 결과 그리디가 16포인트를
    주얼 밀집 그룹에 쓰고 **대각선은 20,005 → 20,004로 그대로였다.**

    **묶는 기준은 호출자가 선언한 축(`cluster_include`)이다.** 엔진이 「무엇이 한
    묶음인가」를 새로 정하면 그게 곧 판단이고, 판단은 해석 층의 몫이다(AD-3). 축 이름은
    호출자가 준 것이므로 여기에 임의 상수가 끼지 않는다 — 묶음 수 = 축 수다.

    ⚠ **반경 안도 담는다.** 예전엔 「안쪽은 이미 노드 후보로 경쟁하니 중복」이라며
    잘라 냈는데 **틀렸다**(사용자 지적 2026-08-13). 뭉치가 존재하는 이유가 바로
    「하나씩 넣으면 각각의 델타가 작아 전부 버려지는」 시너지 축이고(`evaluate_bundles`
    독스트링), 그 문제는 **거리와 무관**하다 — 근거리에 붙어 있어도 둘을 같이 찍어야
    값이 나오는 노드는 개별 후보로는 영영 안 뽑힌다.
    실측: 반경 안을 포함하니 최고 점수가 **0.0033 → 0.0607(18배)**로 올랐다.
    1포인트짜리 목적지를 반경 때문에 잘라 내고 있었다. 중복은 해롭지 않다 —
    같은 값이면 같이 지거나 같이 이긴다.
    """
    tree = set(spec.tree_nodes) | {graph.start_of(spec.class_name)}
    far = graph.distances_from(tree, _MAX_REACH * 8)  # 거리 순서를 얻으려는 1회 BFS
    per_axis: list[list[dict[str, Any]]] = []
    for word, weight in include:
        cands = sorted(
            (
                nid
                for nid, node in graph.nodes.items()
                if nid in far
                and nid not in tree
                and node.kind in _DESTINATION_KINDS
                and relevance(node.stats_en, ((word, weight),), exclude) > 0
            ),
            key=lambda nid: far[nid],
        )
        # ⚠ 크기를 **하나로 정하면 안 된다**(실측 2026-08-13, 두 번 데였다):
        #   ① 축 전체를 담으면 트리 전역이라 항상 예산 초과 → 후보가 통째로 사라진다
        #      (Critical 105개·Attack Speed 47개).
        #   ② 「남은 예산이 닿는 만큼」으로 고치니 예산이 큰 빌드에서 비대해졌다 —
        #      블러드 메이지 예산 90에서 뭉치 하나가 **87포인트**를 먹고 ΔDPS **-24,573**.
        #      경로 74개가 대부분 통행 노드라 넣을수록 손해였고, 그래서 긴 점프 0회였다.
        #   그래서 **가까운 것부터 하나씩 늘려 가며 여러 크기를 낸다.** 작은 것은 경로가
        #   짧아 양수가 나오고, 큰 것은 정말 값어치가 있을 때만 이긴다 — 어느 크기가
        #   맞는지는 측정이 정하지 우리가 정하지 않는다(AD-3).
        grown, picked, spent = set(tree), [], 0
        sizes: list[dict[str, Any]] = []
        for nid in cands:
            path = graph.shortest_path(grown, nid)
            if path is None or spent + len(path) > budget:
                continue
            grown.update(path)
            picked.append(nid)
            spent += len(path)
            sizes.append({"name": f"먼 목적지: {word} ({len(picked)}개)", "nodes": list(picked)})
        per_axis.append(sizes)
    # 작은 것부터 라운드 로빈 — 한 축이 후보 자리를 독점하지 않게. 상한은 호출자의
    # `max_candidates_per_round`를 그대로 쓴다(새 상수를 만들지 않는다).
    out: list[dict[str, Any]] = []
    for i in range(max((len(s) for s in per_axis), default=0)):
        for sizes in per_axis:
            if i < len(sizes) and len(out) < limit:
                out.append(sizes[i])
    return out


def _as_node_delta(bd: BundleDelta) -> NodeDelta:
    """묶음을 채택 기록(`Step`)에 실을 수 있는 꼴로 — 델타 근거를 그대로 들고 간다.

    긴 점프도 「포인트마다 델타로 정당화」(Exit 기준)를 지켜야 한다. `kind="bundle"`
    이라 읽는 쪽이 노드 한 수와 구별할 수 있다.
    """
    return NodeDelta(
        node_id=bd.nodes[0] if bd.nodes else 0,
        name_en=f"[bundle] {bd.name}",
        name_ko=f"[묶음] {bd.name}",
        kind="bundle",
        points=bd.points,
        path=bd.path,
        deltas=bd.deltas,
    )


def _bundle_candidates(
    spec: BuildSpec,
    graph: TreeGraph,
    objective: Objective,
    base: PobResult,
    budget: int,
    *,
    daemon: PobDaemon,
    stats: tuple[str, ...],
    include: tuple[tuple[str, float], ...],
    exclude: tuple[str, ...],
    limit: int,
) -> list[tuple[float, BundleDelta]]:
    """이번 라운드의 **먼 뭉치 후보** — 노드 후보와 같은 저울에 올릴 (점수, 묶음) 목록.

    점수는 `Objective.score`를 그대로 쓴다. 엔진이 뭉치용 새 휴리스틱을 만들면 그게
    곧 판단이고, 판단은 해석 층의 몫이다(AD-3).

    ⛔ `evaluate_bundles`(deltas.py)는 **호출만** 한다 — 반사실 하네스 세션이 그 모듈을
       작업 중이라 인터페이스를 건드리지 않는다(2026-08-13 조율).

    이미 트리에 들어온 뭉치는 `_scan_far_clusters`가 걸러 낸다(닿는 것은 「먼 뭉치」가
    아니다) — 채택분을 따로 기억할 필요가 없다.
    """
    if not include:
        return []  # 관련성 필터 없는 밀집도는 쓰레기다 — 스캔하지 않는다
    bundles = _far_destination_bundles(spec, graph, include, exclude, budget, limit)
    if not bundles:
        return []
    measured = evaluate_bundles(spec, graph, bundles, stats=stats, daemon=daemon)
    return [
        (score, bd)
        for bd in measured
        if bd.points and bd.points <= budget and (score := objective.score(bd, base.stats)) > 0
    ]


def _scan_far_clusters(
    graph: TreeGraph,
    spec: BuildSpec,
    include: tuple[tuple[str, float], ...],
    exclude: tuple[str, ...],
    candidate_radius: int,
) -> tuple[tuple[Cluster, ...], tuple[str, ...]]:
    """지금 트리에서 **닿지 않는** 관련 뭉치만 남긴다.

    반경 안의 것은 그리디가 이미 봤다 — 그걸 또 실으면 신호가 묽어진다.
    `include`가 없으면 **스캔하지 않고 그 사실을 말한다**: 관련성 필터 없는 밀집도는
    쓰레기라서(실측: 반경 1000의 노터블 9개 중 3개가 도리깨 노드) 기본값을 지어내면
    안 된다.
    """
    if not include:
        return (), (
            "밀집도 스캔 안 함 — `cluster_include`를 주면 **후보 반경 밖**의 관련 노터블 "
            "뭉치를 `far_clusters`로 함께 낸다. 그리디는 반경 안만 보므로 먼 뭉치는 "
            "구조적으로 못 본다(실측: 예산 87에 43포인트 조기 종료, 병목을 푸는 노터블이 "
            "전부 반경 밖이었다)",
        )
    tree_now = set(spec.tree_nodes) | {graph.start_of(spec.class_name)}
    near = {nid for nid, _, _ in graph.candidates(tree_now, max_dist=candidate_radius)}
    clusters = find_clusters(
        graph,
        include=include,
        exclude=exclude,
        for_ascendancy=spec.ascendancy,
    )
    far = tuple(c for c in clusters if not all(h.node_id in near for h in c.hits))
    if not far:
        return (), ("밀집도 스캔: 후보 반경 밖에 관련 뭉치 없음 — 그리디가 이미 다 보고 있다",)
    return far, ()


_PRUNE_EPS = 1e-6  # PoB는 결정적 — 죽은 노드의 제거 델타는 정확히 0


def _value(objective: Objective, result: PobResult) -> float:
    """해 비교용 절대 가치 (가중 합 — 동일 목적끼리의 비교에만 사용)."""
    return sum(w * result.stats.get(s, 0.0) for s, w in objective.weights.items())


_Solution = tuple[BuildSpec, PobResult]


def _with_tree(spec: BuildSpec, nodes: tuple[int, ...]) -> BuildSpec:
    """tree_nodes 교체 + 트리에서 빠진 소켓의 주얼 동반 제거 (buildxml 계약:
    소켓이 tree_nodes에 없으면 주얼 직렬화가 거부된다)."""
    kept = set(nodes)
    return dataclasses.replace(
        spec, tree_nodes=nodes, jewels=tuple(j for j in spec.jewels if j.socket_node_id in kept)
    )


def _better(obj: Objective, a: _Solution | None, b: _Solution) -> _Solution:
    """가치 우선, 동가치면 트리 노드가 적은(포인트를 덜 쓴) 쪽."""
    if a is None:
        return b
    va, vb = _value(obj, a[1]), _value(obj, b[1])
    if abs(va - vb) > _PRUNE_EPS:
        return a if va > vb else b
    return b if len(b[0].tree_nodes) < len(a[0].tree_nodes) else a


def _prune_dead_branches(
    original: BuildSpec,
    current: BuildSpec,
    steps: list[Step],
    graph: TreeGraph,
    daemon: PobDaemon,
    measure: tuple[str, ...],
) -> tuple[BuildSpec, list[Pruned], int, list[_Solution]]:
    """끝단(채택 노터블)의 단독 기여가 ~0이면 **막다른 가지 전체**를 제거한다.

    발견 배경(2026-07-31 실증): 채택 단위가 "노터블+경로" 묶음이라 경로
    소노드 가치에 죽은 노터블이 무임승차한다. 1차 수정(끝단만 제거)은
    가치 있는 소노드 스텁을 남겼는데, 막다른 길에 포인트를 쓰는 건 유저
    관점에서 비합리적(사용자 지적) — 가지 전체를 환급하고 상위 루프가
    재투자한다. 원래 스펙의 노드·분기점(다른 가지가 걸린 노드)은 보존.
    """
    protected = set(original.tree_nodes) | {s.node_delta.node_id for s in steps}
    start = graph.start_of(current.class_name)
    removed: list[Pruned] = []
    candidates: list[_Solution] = []  # "끝단만 뺀" 중간 해 — 무료 개선이므로 후보 등록
    eo_current = current  # 누적 "끝단만 제거" 해 (스텁 유지 + 죽은 끝단 전부 제외)
    base = daemon.compute_build(current)
    for step in steps:
        endpoint = step.node_delta.node_id
        if endpoint not in current.tree_nodes:
            continue  # 이전 라운드에서 이미 제거됨
        alloc = set(current.tree_nodes)
        if len([n for n in graph.adj[endpoint] if n in alloc or n == start]) > 1:
            continue  # 분기점이 된 끝단은 다른 가지의 통로 — 건드리지 않는다
        # ① 끝단 단독 제거로 죽음 판정
        probe = _with_tree(current, tuple(n for n in current.tree_nodes if n != endpoint))
        probe_result = daemon.compute_build(probe)
        endpoint_deltas = {
            k: probe_result.stats.get(k, 0.0) - base.stats.get(k, 0.0) for k in measure
        }
        if any(abs(v) > _PRUNE_EPS for v in endpoint_deltas.values()):
            continue  # 끝단이 살아 있다 — 가지 유지
        eo_current = _with_tree(
            eo_current, tuple(n for n in eo_current.tree_nodes if n != endpoint)
        )
        candidates.append((eo_current, daemon.compute_build(eo_current)))
        # ② 막다른 가지 수집: 끝단에서 안쪽으로 차수 1 연쇄 (보호 노드 전까지)
        chain: list[int] = []
        cursor: int | None = endpoint
        alloc = set(current.tree_nodes)
        while cursor is not None:
            neighbors = [n for n in graph.adj[cursor] if n in alloc or n == start]
            if len(neighbors) > 1 or (cursor != endpoint and cursor in protected):
                break
            chain.append(cursor)
            alloc.discard(cursor)
            cursor = neighbors[0] if neighbors and neighbors[0] != start else None

        # ③ **연쇄를 한 노드씩 검증하며 제거한다.** 끝단이 죽었다고 그 안쪽까지
        # 죽었다는 보장이 없다 — 막다른 길에도 생명력·피해 소노드가 앉아 있다.
        # 무검증 일괄 제거는 실측에서 -478 DPS를 냈고, 보고(`endpoint_removal_deltas`)는
        # 끝단 1개 기준이라 0으로 보여 손실이 가려졌다(2026-08-04 빌드 테스트).
        candidate_chain = list(chain)
        verified: list[int] = []
        chain_deltas: dict[str, float] = {}
        probe_spec = current
        for chain_node in chain:
            trial = _with_tree(
                probe_spec, tuple(n for n in probe_spec.tree_nodes if n != chain_node)
            )
            trial_stats = daemon.compute_build(trial).stats
            deltas = {k: trial_stats.get(k, 0.0) - base.stats.get(k, 0.0) for k in measure}
            if any(abs(v) > _PRUNE_EPS for v in deltas.values()):
                break  # 이 노드는 살아 있다 — 여기서 멈추고 나머지는 남긴다
            probe_spec = trial
            verified.append(chain_node)
            chain_deltas = deltas
        if not verified:
            continue  # 끝단조차 되살아났다(경계 사례) — 이 가지는 건드리지 않는다
        chain = verified
        current = probe_spec
        base = daemon.compute_build(current)
        node = graph.nodes.get(endpoint)
        removed.append(
            Pruned(
                endpoint_id=endpoint,
                endpoint_name=(node.name_ko or node.name_en) if node else str(endpoint),
                nodes=tuple(chain),
                endpoint_removal_deltas=endpoint_deltas,
                chain_removal_deltas=chain_deltas,
                chain_truncated=len(verified) < len(candidate_chain),
            )
        )
    return current, removed, sum(len(p.nodes) for p in removed), candidates
