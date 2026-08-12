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
from typing import Any

from pok.engine.objective import Target, TargetResult, evaluate_targets
from pok.engine.tree.clusters import Cluster, find_clusters
from pok.engine.tree.deltas import NodeDelta, evaluate_node_deltas
from pok.engine.tree.graph import TreeGraph
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

    def _weighted(self, delta: NodeDelta, base_stats: dict[str, float]) -> float:
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

    def _breaks_floor(self, delta: NodeDelta, base_stats: dict[str, float]) -> bool:
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

    def score(self, delta: NodeDelta, base_stats: dict[str, float]) -> float:
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
    spec, anchor_notes, anchor_cost = _seed_anchors(spec, graph, required_anchors, point_budget)
    current = spec
    budget = max(0, point_budget - anchor_cost)
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
    with PobDaemon() as daemon:
        best_solution: tuple[BuildSpec, PobResult] | None = None  # 단조성 안전장치
        while True:
            # ── 그리디 채택 ──
            rejected = 0
            while budget > 0:
                if out_of_time():
                    break
                tree_now = set(current.tree_nodes) | {graph.start_of(current.class_name)}
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
    )


def _seed_anchors(
    spec: BuildSpec, graph: TreeGraph, anchors: tuple[int, ...], budget: int
) -> tuple[BuildSpec, tuple[str, ...], int]:
    """필수 앵커를 트리에 먼저 연결하고, 그 결과를 **보호 대상 기준선**으로 만든다.

    반환한 스펙이 `optimize_tree`의 `spec`(= 가지치기가 건드리지 않는 원래 트리)이
    되므로, 앵커와 그 경로는 **델타가 0이어도 잘려 나가지 않는다.** 이게 핵심이다 —
    메커니즘 노드는 PoB가 못 재는 경우가 많아(트리거·일부 DoT) 델타 0으로 잡히고,
    보호하지 않으면 가지치기가 곧바로 회수해 버린다.
    """
    if not anchors:
        return spec, (), 0
    tree = set(spec.tree_nodes) | {graph.start_of(spec.class_name)}
    added: list[int] = []
    unreachable: list[int] = []
    for node_id in anchors:
        path = graph.shortest_path(tree, node_id)
        if path is None:
            unreachable.append(node_id)
            continue
        tree.update(path)
        # 전직 시작 노드는 통행만 하고 스펙에는 안 싣는다(위 graph.connect_anchors와 같은
        # 이유 — 넣으면 PoB가 잘라내고 그 트리의 측정이 전부 무효가 된다).
        added.extend(
            n
            for n in path
            if not (graph.nodes.get(n) is not None and graph.nodes[n].kind == "ascendancy-start")
        )
    notes: list[str] = []
    if added:
        notes.append(
            f"필수 앵커 {len(anchors) - len(unreachable)}개를 먼저 연결했다 — "
            f"{len(added)}포인트. 점수 경쟁에서 제외되고 가지치기도 건드리지 않는다"
        )
    if unreachable:
        # 조용히 빼면 "앵커를 넣었다"고 믿은 채 없는 트리를 받는다.
        notes.append(f"⚠ 연결 불가 앵커 {unreachable} — 트리에 들어가지 않았다")
    if len(added) > budget:
        notes.append(
            f"⚠ 필수 앵커만으로 예산을 {len(added) - budget}포인트 **초과**했다 — "
            "그리디에 남은 예산이 없다. 앵커를 줄이거나 예산을 늘릴 것"
        )
    return (
        dataclasses.replace(spec, tree_nodes=tuple(spec.tree_nodes) + tuple(added)),
        tuple(notes),
        len(added),
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
    return tuple(out)


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
