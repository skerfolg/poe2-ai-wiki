"""트리 밀집도 스캔 — 후보 반경 밖의 노터블 뭉치를 찾는다 (백로그 제안 A).

## 왜 필요한가

`optimize_tree`는 현재 트리에서 **반경 안**의 후보만 본다. 그래서 멀리 있는 뭉치를
구조적으로 못 본다 — 실측: 예산 87로 돌렸더니 **43포인트에서 조기 종료 · 9포인트 낭비 ·
치명타 12.16%(목표 80%)**였고, 손으로 밀집도를 분석하니 병목을 정면으로 푸는 노터블
(인화성 강도 80% 등)이 나왔는데 **전부 후보 반경 밖**이었다.

## ⚠ 관련성 필터가 결정적이다

필터 없이 돌리면 결과가 쓰레기다 — 실측: "반경 1000에 노터블 9개"가 나왔는데 그중
**3개가 도리깨 노드**였다. 뭉쳐 있다는 사실 자체는 아무 뜻이 없다. `include`(가중치
있는 키워드)로 **무엇을 찾는지 말해야** 한다.

## 반경은 실측 목록에서 온다

주얼 반경은 `Data.lua`의 표기값의 **1.2배**(`PassiveTreeJewelDistanceMultiplier`)다.
실효 최대는 **2,520**(= 2,100의 1.2배)이고, `Variable` 계열은 `inner`가 있는 **도넛**이라
가까운 노드는 안 덮는다. 임의의 큰 반경을 넣으면 "주얼 하나로 덮인다"는 **틀린 결론**이
나온다 — 실측: 발의 세션이 3,800을 가정해 「42포인트 절약」을 두 번 보고했다가 철회했고,
실제로 덮이는 관련 노터블은 **2개 남짓**이었다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from pok.engine.tree.graph import TreeGraph

# PoB 실효 반경 (표기의 1.2배). `Data.lua:657-672` + `Misc.lua` gameConstants.
# 도넛(Variable)은 inner가 있어 가까운 노드를 안 덮는다 — 원으로 모델링하면 틀린다.
JEWEL_RADII: tuple[tuple[str, float, float], ...] = (
    ("Small", 0.0, 1200.0),
    ("Medium", 0.0, 1380.0),
    ("Large", 0.0, 1560.0),
    ("Very Large", 0.0, 1800.0),
    ("Variable(최대)", 2160.0, 2520.0),
)


@dataclass(frozen=True)
class ClusterHit:
    """반경 안에 든 노터블 하나 — **효과 문구째로** 낸다.

    점수만 내면 「힘 소진」(집정관 버프로 치명타 30%)과 「지배」 성유(그 페널티 무효화)
    같은 **두 축을 동시에 봐야 보이는 조합**을 영원히 못 찾는다.
    """

    node_id: int
    name_ko: str
    name_en: str
    score: float
    stats_en: tuple[str, ...]
    # 트리 좌표 — **이게 없으면 세션이 파일을 뒤진다**(제안 C). 클러스터 중심만으로는
    # "이 노터블이 내 트리에서 얼마나 먼가"를 못 재고, 그 질문이 실제로 나온다.
    position: tuple[float, float]
    locked_to: str | None = None


@dataclass(frozen=True)
class Cluster:
    """한 중심·반경의 스캔 결과."""

    center: tuple[float, float]
    radius: float
    inner: float
    label: str
    hits: tuple[ClusterHit, ...] = field(default=())

    @property
    def total_score(self) -> float:
        return round(sum(h.score for h in self.hits), 3)


def relevance(
    stats: Sequence[str], include: Sequence[tuple[str, float]], exclude: Sequence[str]
) -> float:
    """효과 문구가 찾는 축에 얼마나 걸리는가. `exclude`에 걸리면 **0**.

    가중치 합으로 낸다 — 한 노드가 여러 축을 건드리면 그만큼 값이 크다.
    """
    blob = " ".join(stats).lower()
    if any(word.lower() in blob for word in exclude):
        return 0.0
    return round(sum(weight for word, weight in include if word.lower() in blob), 3)


def find_clusters(
    graph: TreeGraph,
    *,
    include: Sequence[tuple[str, float]],
    exclude: Sequence[str] = (),
    radii: Sequence[float] | None = None,
    min_score: float = 0.0,
    top: int = 5,
    centers_per_band: int = 3,
    for_ascendancy: str | None = None,
) -> list[Cluster]:
    """관련 노터블이 가장 촘촘한 중심들을 찾는다.

    전 노터블의 좌표를 **중심 후보**로 놓고 각 반경 안의 관련 노터블 점수합이 최대인
    곳을 고른다. O(n²)이지만 노터블 1,193개라 즉시 끝난다.

    `for_ascendancy`를 주면 **다른 전직 전용 해금 노드를 뺀다** — 안 빼면 인게임에서
    못 찍는 노드가 클러스터 점수를 부풀린다(B-13에서 실제로 그렇게 「힘 소진」이
    설계 근거로 올라갔다). 판정은 `TreeGraph.resolve_ascendancy`가 표기를 맞춰 준다.
    """
    if not include:
        raise ValueError(
            "include가 비었다 — 관련성 필터 없는 밀집도는 쓰레기다"
            "(실측: 반경 1000의 노터블 9개 중 3개가 도리깨 노드였다)"
        )
    wanted = graph.resolve_ascendancy(for_ascendancy)
    pool: list[tuple[int, tuple[float, float], float]] = []
    for node in graph.nodes.values():
        if node.kind != "notable" or node.position is None:
            continue
        if node.locked_to and node.locked_to != wanted:
            continue
        score = relevance(node.stats_en, include, exclude)
        if score > 0:
            pool.append((node.node_id, node.position, score))
    if not pool:
        return []

    bands = [(f"r{int(r)}", 0.0, float(r)) for r in radii] if radii else list(JEWEL_RADII)
    out: list[Cluster] = []
    for label, inner, outer in bands:
        ranked: list[tuple[float, tuple[float, float], list[tuple[int, float]]]] = []
        for _, center, _ in pool:
            members = [
                (nid, score) for nid, pos, score in pool if inner <= math.dist(center, pos) <= outer
            ]
            total = sum(s for _, s in members)
            if total > min_score:
                ranked.append((total, center, members))
        ranked.sort(key=lambda x: -x[0])
        # **중심을 여럿 낸다.** 밴드마다 1등만 내면 대안이 통째로 가려진다 — 실측
        # 2026-08-09: 점화 가중을 조금 바꾸자 「부싯돌」(인화성 강도 80%) 뭉치가
        # 1등에서 밀려 결과에서 사라졌다. 겹치는 중심은 반경 절반 기준으로 솎는다.
        picked: list[tuple[float, tuple[float, float], list[tuple[int, float]]]] = []
        for entry in ranked:
            if len(picked) >= centers_per_band:
                break
            if any(math.dist(entry[1], other[1]) < outer / 2 for other in picked):
                continue
            picked.append(entry)
        for _, center, members in picked:
            out.append(
                Cluster(
                    center=center,
                    radius=outer,
                    inner=inner,
                    label=label,
                    hits=tuple(
                        ClusterHit(
                            node_id=nid,
                            name_ko=graph.nodes[nid].name_ko,
                            name_en=graph.nodes[nid].name_en,
                            score=score,
                            stats_en=graph.nodes[nid].stats_en,
                            position=graph.nodes[nid].position or (0.0, 0.0),
                            locked_to=graph.nodes[nid].locked_to,
                        )
                        for nid, score in sorted(members, key=lambda m: -m[1])[:top]
                    ),
                )
            )
    return out
