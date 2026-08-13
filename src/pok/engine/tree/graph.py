"""패시브 트리 그래프 — 결정적 경로 도구 (P4 Phase 1, D23).

정본(`knowledge/game-data/tree/*.ndjson`)에서 무방향 인접을 구성한다.
엣지는 단방향 저장·무방향 의미(tree_merge 머리주석) — 여기서 양방향으로 펼친다.

클래스 시작 노드는 KB 밖의 구조 데이터라 PoB 실측 상수로 둔다
(실측 2026-07-30, PoB 5d173cb latestTree.classes[..].startNodeId):
Witch/Sorceress·Ranger/Huntress는 시작점을 공유한다.

여기는 **연결 비용**(가산적·순수 그래프)만 다룬다 — 노드의 **가치**는
PoB 델타 실측(deltas.py)의 몫 (BLUEPRINT §10.3 분리 원칙).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from pathlib import Path

# PoB 실측 (5d173cb): 클래스명 → (시작 노드, 시작 인접 — 어센던시 시작 제외 전)
CLASS_START: dict[str, int] = {
    "Witch": 54447,
    "Sorceress": 54447,
    "Ranger": 50459,
    "Huntress": 50459,
    "Warrior": 47175,
    "Mercenary": 50986,
    "Monk": 44683,
    "Druid": 61525,
}
# **기본 할당되는 전직 노드** — 포인트를 안 쓰고 처음부터 켜져 있다.
# 사용자 판정 2026-08-12: "블러드 메이지는 기본으로 혈액술(Sanguimancy) 어센던시가
# 할당되어 있다. 블러드 메이지만 유일하게 하나를 기본 할당하고 시작해 총 9포인트가 된다."
# 실측이 뒷받침한다 — 래더 표본에서 블러드 메이지만 전직 **노터블 5개**(다른 전직 4개)이고
# Sanguimancy는 10/10 보유다.
GRANTED_ASCENDANCY_NODES: dict[str, tuple[int, ...]] = {
    "Witch2": (8415,),  # Blood Mage → Sanguimancy
}

# 전직별 어센던시 포인트 상한 (#68 · 사용자 판정 2026-08-13).
#
# ⚠ **게임 문서가 아니라 래더 관측이다** — 0-5 코퍼스 230벌(전직 23종 × 10벌)에서
#    실제로 쓴 전직 포인트의 최대치다. 분포: 8포인트 173벌 · 9포인트 48벌 · 7 이하 9벌.
#    아래 6종에서만 9가 관측됐고 나머지 17종은 10/10이 8 이하였다(우연이라기엔 너무
#    치우쳤다 — 9 사용률 21%면 10벌 전부 8일 확률이 종당 9%라 17종은 설명이 안 된다).
#
# ⛔ **왜 6종만 9인지는 규명되지 않았다.** 숨은 공짜 노드일 수도(블러드 메이지의
#    혈액술처럼 `GRANTED_ASCENDANCY_NODES`에 빠진 것), 포인트를 부여하는 노드일 수도
#    있다. 그래서 이 표는 **판정이 아니라 관측 기록**이고, 반증이 쉽다: 여기 8인
#    전직에서 9포인트 빌드가 관측되면 그 값이 틀린 것이다. 초과를 **거부하지 않고
#    경고만** 하는 이유가 이것이다 — 틀린 상한으로 정상 빌드를 막으면 안 된다.
ASCENDANCY_POINT_CAP: dict[str, int] = {
    "Monk3": 9,  # 애컬라이트 오브 차율라 — 9/10벌
    "Ranger1": 9,  # 데드아이 — 7/10벌
    "Ranger3": 9,  # 패스파인더 — 8/10벌
    "Mercenary3": 9,  # 젬링 리저네어 — 6/10벌
    "Warrior3": 9,  # 스미스 오브 키타바 — 9/10벌
    "Huntress2": 9,  # 스피릿 워커 — 9/10벌
}
DEFAULT_ASCENDANCY_POINTS = 8

_START_LINKS: dict[int, tuple[int, ...]] = {
    # ⚠ 59822(블러드 메이지)를 빼 뒀었는데 **그게 결함이었다**(실측 2026-08-12).
    #    형제 전직 5종(인퍼널리스트·리치·스톰위버·크로노맨서·바라시타)은 전부 링크돼
    #    있는데 블러드 메이지만 없어서, 그 전직 노터블(Sanguimancy·Sunder the Flesh·
    #    Grasping Wounds)이 **클래스 시작에서 아예 닿지 않았다** — `connect_anchors`가
    #    「연결 불가 타깃」으로 터진다. 0.5 실가동 22종 중 닿지 않는 것은 이것뿐이었다
    #    (나머지 미연결 13종은 0.5에 없는 PoE1 잔재라 무해하다).
    54447: (22147, 32699, 4739, 23710, 40721, 8305, 44871, 59822),
    50459: (56651, 1583, 63493, 13828, 46990, 41736, 36365),
    47175: (38646, 33812, 3936, 5852, 32534),
    50986: (59779, 7120, 59915, 36252, 55536),
    44683: (10364, 9994, 52980, 11495, 74),
    61525: (42761, 13855, 35535, 50084),
}


@dataclass(frozen=True)
class TreeNode:
    node_id: int
    name_en: str
    name_ko: str
    kind: str  # keystone|notable|small|mastery|jewel-socket|ascendancy-start
    stats_en: tuple[str, ...]
    ascendancy: str | None  # "Witch2" 등 — None이면 본 트리
    # 해금 조건 — 특정 어센던시에서만 찍히는 노드({"ascendancy": "Oracle", "nodes": [...]}).
    # PoB 계산기는 이걸 **검사하지 않아** 스탯을 그대로 더한다. 그래서 후보 단계에서
    # 걸러야 한다(실측 2026-08-06: 블러드 메이지 빌드에 오라클 전용 7개가 섞였다).
    unlock_constraint: dict[str, object] | None = None
    # 트리 좌표 (PoB 반경 판정과 같은 공간). 밀집도 스캔·주얼 반경이 이걸 쓴다.
    # KB 4,553개 중 4,540개 보유 — 없는 것(시작 노드 등)은 None이다.
    position: tuple[float, float] | None = None

    @property
    def locked_to(self) -> str | None:
        """이 노드를 해금할 수 있는 어센던시 (없으면 None = 전직 제약 없음)."""
        if not self.unlock_constraint:
            return None
        value = self.unlock_constraint.get("ascendancy")
        return str(value) if value else None

    @property
    def requires_nodes(self) -> tuple[int, ...]:
        """먼저 할당해야 열리는 **선행 노드** (전직 제약과 별개 축).

        `unlock_constraint`에 `ascendancy` 없이 `nodes`만 있는 꼴이 있다 — 실측
        2026-08-07 Passive 3건(탈주자의 길·동혈수호자·신성한 합일). 이건 "다른
        전직 전용"이 아니라 "저 노터블들을 먼저 찍어야 열린다"이므로 `locked_to`가
        None이고, 전직 대조만 하던 검사에서는 **그냥 통과했다**. 그중 2건은 본
        트리 노드라 후보에도 샜다.
        """
        if not self.unlock_constraint or self.unlock_constraint.get("ascendancy"):
            return ()
        nodes = self.unlock_constraint.get("nodes")
        return tuple(int(n) for n in nodes) if isinstance(nodes, list) else ()


class TreeGraph:
    """본 트리 무방향 그래프 + 어센던시 서브그래프. 로드 1회, 질의 N회."""

    def __init__(self, knowledge: Path) -> None:
        from pok.kb.store import load as store_load

        # 샤드만 읽으면 시드 승격된 큐레이션 Passive(개별 JSON)가 빠진다 — store로 전량
        kb = store_load(knowledge.parent if knowledge.name == "knowledge" else knowledge)
        self.nodes: dict[int, TreeNode] = {}
        raw_conn: dict[int, list[int]] = {}
        # 표기 → 실명. 빌드 스펙은 코드("Witch1")를 들고 `unlock_constraint`는
        # 실명("Oracle")으로 적혀 있어, 잇는 표가 없으면 대조 자체가 성립하지 않는다.
        self._asc_names: dict[str, str] = {}
        for r in kb.records.values():
            d = r.raw.get("data", {})
            if r.type != "Passive" or "node_id" not in d:
                continue
            code = d.get("ascendancy")
            names = d.get("ascendancy_name") or {}
            real = str(names.get("en") or "") if isinstance(names, dict) else ""
            if code and real:
                for notation in (str(code), real, *(str(v) for v in names.values() if v)):
                    self._asc_names[notation.casefold()] = real
            nid = int(d["node_id"])
            self.nodes[nid] = TreeNode(
                node_id=nid,
                name_en=r.raw["name"]["en"],
                name_ko=r.raw["name"]["ko"],
                kind=d.get("kind", "small"),
                stats_en=tuple(d.get("stats_en") or ()),
                ascendancy=d.get("ascendancy"),
                unlock_constraint=d.get("unlock_constraint") or None,
                position=(
                    (float(pos["x"]), float(pos["y"]))
                    if isinstance(pos := d.get("position"), dict)
                    else None
                ),
            )
            raw_conn[nid] = [int(c) for c in d.get("connections", [])]
        self.adj: dict[int, set[int]] = collections.defaultdict(set)
        for nid, conns in raw_conn.items():
            a = self.nodes[nid].ascendancy
            for c in conns:
                if c in self.nodes and self.nodes[c].ascendancy == a:
                    self.adj[nid].add(c)
                    self.adj[c].add(nid)
        # 클래스 시작 (가상 노드 — KB 밖이라 TreeNode 없음)
        for start, links in _START_LINKS.items():
            for nb in links:
                if nb in self.nodes:
                    self.adj[start].add(nb)
                    self.adj[nb].add(start)
        # 어센던시 시작 → 첫 노터블 (예: 59822→8415는 KB에 단방향으로만 존재)
        for nid, node in self.nodes.items():
            if node.kind == "ascendancy-start":
                for c in raw_conn.get(nid, []):
                    if c in self.nodes:
                        self.adj[nid].add(c)
                        self.adj[c].add(nid)

    def resolve_ascendancy(self, name: str | None) -> str | None:
        """코드("Witch1")·영문("Blood Mage")·한글 아무 표기나 → 실명. 모르면 원문 그대로.

        원문 폴백은 의도적이다 — 모르는 표기를 None으로 떨구면 "제약 없음"으로
        읽혀 잠긴 노드가 통과한다(조용한 폴백은 이 프로젝트가 반복해 데인 꼴이다).
        """
        if not name:
            return None
        return self._asc_names.get(name.casefold(), name)

    def start_of(self, class_name: str) -> int:
        if class_name not in CLASS_START:
            raise ValueError(f"알 수 없는 클래스: {class_name!r}")
        return CLASS_START[class_name]

    def shortest_path(self, sources: set[int], target: int) -> list[int] | None:
        """다중 소스 → target 최단 경로 (소스 자신은 제외한 새 노드들만 반환)."""
        if target in sources:
            return []
        prev: dict[int, int | None] = {s: None for s in sources}
        q = collections.deque(sources)
        while q:
            cur = q.popleft()
            for nb in self.adj[cur]:
                if nb not in prev:
                    prev[nb] = cur
                    if nb == target:
                        path: list[int] = []
                        walk: int | None = nb
                        while walk is not None and walk not in sources:
                            path.append(walk)
                            walk = prev[walk]
                        return path[::-1]
                    q.append(nb)
        return None

    def granted_nodes(self, ascendancy: str | None) -> frozenset[int]:
        """그 전직이 **공짜로 들고 시작하는** 노드 (없으면 빈 집합)."""
        if not ascendancy:
            return frozenset()
        want = self.resolve_ascendancy(ascendancy)
        out: set[int] = set()
        for code, nodes in GRANTED_ASCENDANCY_NODES.items():
            if self.resolve_ascendancy(code) == want:
                out.update(nodes)
        return frozenset(out)

    def ascendancy_point_cap(self, ascendancy: str | None) -> int:
        """그 전직이 쓸 수 있는 어센던시 포인트 — **관측 상한**이다(`ASCENDANCY_POINT_CAP`).

        전직을 모르면 기본값을 준다. 상한을 모른다고 무제한으로 두면 예산 판단이
        조용히 사라진다(이 레포가 반복해 데인 꼴).
        """
        want = self.resolve_ascendancy(ascendancy)
        for code, cap in ASCENDANCY_POINT_CAP.items():
            if self.resolve_ascendancy(code) == want:
                return cap
        return DEFAULT_ASCENDANCY_POINTS

    def connect_anchors(
        self,
        class_name: str,
        targets: collections.abc.Iterable[int],
        *,
        ascendancy: str | None = None,
    ) -> tuple[list[int], dict[int, list[int]]]:
        """그리디 슈타이너: 시작점에서 타깃들을 최소 포인트로 연결.

        매 라운드 '기존 트리에서 가장 싼 타깃'을 최단 경로로 붙인다(근사 —
        전역 최적 비보장, §10.3 한계 인정). 반환: (할당 노드 전체, 타깃별 경로).

        `ascendancy`를 주면 **남의 전직 노드를 거부한다.** 그래프는 본 트리를 빙 돌아
        다른 전직 권역으로 들어갈 수 있는데(실측 2026-08-12: `connect_anchors("Witch",
        [11495])`가 마셜 아티스트 시작 노드에 성공한다) 인게임에서는 불가능하다.
        후보 선정과 출고 게이트가 막고 있었지만 **이 함수를 직접 부르는 경로는
        뚫려 있었다** — 앵커 id를 잘못 주면 인게임에서 못 만드는 트리가 나온다.

        **안 주면 전직 노드 타깃 자체를 거부한다**(#69). 검사를 선택으로 두면 인자를
        빠뜨리는 것만으로 게이트가 꺼지는데, 호출자가 전직을 모르는 경로가 실재한다 —
        「모르면 통과」가 아니라 「모르면 못 쓴다」로 닫는다. 일반 패시브만 연결하는
        호출은 종전대로 전직 없이 쓸 수 있다.

        기본 할당 노드(블러드 메이지의 혈액술)는 **출발 시점에 이미 켜져 있는 것**으로
        놓는다 — 포인트를 안 쓰므로 경로 비용에서 빠진다.
        """
        want = self.resolve_ascendancy(ascendancy) if ascendancy else None
        remaining = set(targets)
        if want is None:
            # ⛔ 전직을 모르면 소유권을 **검사할 수 없다**. 예전엔 검사를 통째로 건너뛰어
            #    남의 전직 노드가 그대로 통과했다(#69) — 인자를 빠뜨리는 것만으로 게이트가
            #    꺼지는 구조였다. 모르면 통과가 아니라 **거부**다: 일반 패시브만 연결한다.
            asc_targets = sorted(
                t
                for t in remaining
                if (node := self.nodes.get(t)) is not None and node.ascendancy
            )
            if asc_targets:
                raise ValueError(
                    f"전직 노드를 연결하려면 ascendancy를 줘야 한다: {asc_targets} — "
                    "전직을 모르면 그것이 이 빌드 것인지 검사할 수 없고, "
                    "검사 없이 통과시키면 인게임에서 할당 불가한 트리가 나간다"
                )
        else:
            foreign = sorted(
                t
                for t in remaining
                if (node := self.nodes.get(t)) is not None
                and node.ascendancy
                and self.resolve_ascendancy(node.ascendancy) != want
            )
            if foreign:
                raise ValueError(
                    f"다른 전직의 노드는 연결할 수 없다: {foreign} — "
                    f"이 빌드는 {want!r}다. 인게임에서 할당 불가한 트리가 된다"
                )
        # 공짜로 켜져 있는 노드는 **이미 트리에 있는 것**으로 출발한다.
        tree: set[int] = {self.start_of(class_name), *self.granted_nodes(ascendancy)}
        paths: dict[int, list[int]] = {}
        while remaining:
            best_t, best_p = None, None
            for t in remaining:
                p = self.shortest_path(tree, t)
                if p is not None and (best_p is None or len(p) < len(best_p)):
                    best_t, best_p = t, p
            if best_t is None:
                raise ValueError(f"연결 불가 타깃: {sorted(remaining)}")
            assert best_p is not None
            tree.update(best_p)
            paths[best_t] = best_p
            remaining.discard(best_t)
        # ⚠ 전직 시작 노드는 **스펙에 넣으면 안 된다** — PoB가 전직 선택으로 자동
        # 할당하므로 tree_nodes에 있으면 `pruned_nodes`로 잘라낸다. 그러면 그 트리를
        # 쓰는 **모든 측정이 무효 처리**되어(deltas·bundles가 pruned 결과를 버린다)
        # 그리디가 한 수도 못 뽑는다 — 실측 2026-08-12 e2e에서 정확히 그렇게 멈췄고,
        # 원인은 노드 하나였다(11495). 통행은 시켜도 산출물에는 싣지 않는다.
        allocated = sorted(
            n
            for n in tree - {self.start_of(class_name)} - self.granted_nodes(ascendancy)
            if not (self.nodes.get(n) is not None and self.nodes[n].kind == "ascendancy-start")
        )
        return allocated, paths

    def distances_from(self, sources: set[int], max_dist: int) -> dict[int, int]:
        """소스 집합에서 각 노드까지의 BFS 거리 (연결 비용 추정용)."""
        dist = {s: 0 for s in sources}
        q = collections.deque(sources)
        while q:
            cur = q.popleft()
            if dist[cur] >= max_dist:
                continue
            for nb in self.adj[cur]:
                if nb not in dist:
                    dist[nb] = dist[cur] + 1
                    q.append(nb)
        return dist

    def candidates(
        self,
        near: set[int],
        max_dist: int,
        kinds: tuple[str, ...] = ("notable", "keystone", "jewel-socket"),
        ascendancy_name: str | None = None,
    ) -> list[tuple[int, TreeNode, int]]:
        """near 집합에서 max_dist 안의 후보 노드 (거리 오름차순). 가치 판단은 하지 않는다.

        **해금 조건이 맞지 않는 노드는 후보에서 뺀다** — PoB 계산기가 이 제약을 검사하지
        않아, 넣으면 인게임에서 못 찍는 스탯이 그대로 더해진다(실측 2026-08-06).
        `ascendancy_name`은 코드·영문·한글 아무 표기나 받는다. 주지 않으면 잠긴 노드를
        **전부** 뺀다 — 안전하지만 **과잉**이다(오라클 빌드가 자기 노드를 후보로 못
        받는다). 호출자는 빌드의 전직을 반드시 넘길 것(B-13).

        선행 노드 요구형(`requires_nodes`)은 **그 노드들이 이미 `near`에 있을 때만**
        후보다 — 전직 제약이 아니라서 `locked_to` 대조로는 걸러지지 않는다.
        """
        allowed = self.resolve_ascendancy(ascendancy_name)
        dist = self.distances_from(near, max_dist)
        out = [
            (nid, self.nodes[nid], d)
            for nid, d in dist.items()
            if d > 0
            and nid in self.nodes
            and self.nodes[nid].kind in kinds
            and self.nodes[nid].ascendancy is None
            and self.nodes[nid].locked_to in (None, allowed)
            and set(self.nodes[nid].requires_nodes) <= near
        ]
        return sorted(out, key=lambda x: (x[2], x[0]))
