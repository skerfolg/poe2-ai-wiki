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

# PoB 실효 반경 (표기의 1.2배 — `Misc.lua:36` PassiveTreeJewelDistanceMultiplier).
# **`Data.lua:657`의 12개를 그대로** 옮긴다. 키는 PoB의 `radiusIndex`(1부터)다 —
# 아이템이 "only affects passives in massive ring" 같은 문구로 **이 번호를 지목**한다
# (`ModParser.lua:5512-5524`). 번호를 우리 이름으로 바꾸면 대조가 끊기므로 안 바꾼다.
#
# ⚠ 1~4는 원(inner=0), **5~12는 도넛**이다 — inner보다 가까운 노드는 **안 덮는다**.
# 원으로 모델링하면 덮는 노드를 과대평가한다(BACKLOG #71).
JEWEL_RADIUS_BY_INDEX: dict[int, tuple[float, float]] = {
    1: (0.0, 1200.0),  # Small        (표기 1000)
    2: (0.0, 1380.0),  # Medium       (1150)
    3: (0.0, 1560.0),  # Large        (1300)
    4: (0.0, 1800.0),  # Very Large   (1500)
    5: (780.0, 1140.0),  # Variable — very small ring   (650~950)
    6: (960.0, 1320.0),  # Variable — small ring        (800~1100)
    7: (1140.0, 1500.0),  # Variable — medium-small ring (950~1250)
    8: (1320.0, 1680.0),  # Variable — medium ring       (1100~1400)
    9: (1500.0, 1860.0),  # Variable — medium-large ring (1250~1550)
    10: (1680.0, 2040.0),  # Variable — large ring        (1400~1700)
    11: (1980.0, 2340.0),  # Variable — very large ring   (1650~1950)
    12: (2160.0, 2520.0),  # Variable — massive ring      (1800~2100)
}

# 밀집도 **스캔 밴드** — 위 표와 쓰임이 다르다. 저건 「이 주얼의 반경이 얼마인가」이고
# 이건 「어느 크기로 훑어볼까」다. 도넛 8개를 전부 훑으면 겹치는 뭉치가 쏟아져 신호가
# 묻히므로, 원 4종 + 가장 큰 도넛만 쓴다.
JEWEL_RADII: tuple[tuple[str, float, float], ...] = (
    ("Small", *JEWEL_RADIUS_BY_INDEX[1]),
    ("Medium", *JEWEL_RADIUS_BY_INDEX[2]),
    ("Large", *JEWEL_RADIUS_BY_INDEX[3]),
    ("Very Large", *JEWEL_RADIUS_BY_INDEX[4]),
    ("Variable(최대)", *JEWEL_RADIUS_BY_INDEX[12]),
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
        # 두 축을 **둘 다** 봐야 한다 (백로그 #35):
        #   `locked_to`  = 「다른 전직 **전용 해금**」 — 조건을 만족하면 찍을 수 있다
        #   `ascendancy` = 「다른 어센던시 **트리 소속**」 — **애초에 못 들어간다**
        # 후자가 더 명백한 배제 대상인데 안 걸러졌다. 실측 2026-08-09:
        # `26383 살점 가르기`(`ascendancy: "Witch2"`, `unlock_constraint: None`)가
        # 인퍼널리스트 호출에 나와 **치명타 병목의 해법으로 채택 직전까지** 갔다.
        # 기계가 못 잡은 것을 사용자가 잡았다("살점 가르기는 블러드메이지 전용이잖아").
        #
        # `for_ascendancy`를 안 주면 어센던시 노드를 **전부** 뺀다 — 어느 전직인지
        # 모르면서 그 트리 노드를 후보로 내면 못 찍는 것을 권하는 셈이다(B-13).
        if node.locked_to and node.locked_to != wanted:
            continue
        # ⚠ **두 이름 공간이다.** `node.ascendancy`는 **코드**("Witch2")이고
        # `wanted`(=`resolve_ascendancy`)는 **표시명**("Blood Mage")이다. 그대로
        # 비교하면 항상 불일치라 **자기 어센던시 노드까지 전부 막힌다** — 만들다 실제로
        # 그랬다(§0 ⑤ 게이트가 정상을 막으면 신호가 죽는다). 노드 쪽도 해소해서 잰다.
        node_ascendancy = graph.resolve_ascendancy(node.ascendancy)
        if node_ascendancy and node_ascendancy != wanted:
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
