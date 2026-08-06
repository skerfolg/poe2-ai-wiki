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
_START_LINKS: dict[int, tuple[int, ...]] = {
    54447: (22147, 32699, 4739, 23710, 40721, 8305, 44871),  # 59822(asc) 제외
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

    @property
    def locked_to(self) -> str | None:
        """이 노드를 해금할 수 있는 어센던시 (없으면 None = 누구나)."""
        if not self.unlock_constraint:
            return None
        value = self.unlock_constraint.get("ascendancy")
        return str(value) if value else None


class TreeGraph:
    """본 트리 무방향 그래프 + 어센던시 서브그래프. 로드 1회, 질의 N회."""

    def __init__(self, knowledge: Path) -> None:
        from pok.kb.store import load as store_load

        # 샤드만 읽으면 시드 승격된 큐레이션 Passive(개별 JSON)가 빠진다 — store로 전량
        kb = store_load(knowledge.parent if knowledge.name == "knowledge" else knowledge)
        self.nodes: dict[int, TreeNode] = {}
        raw_conn: dict[int, list[int]] = {}
        for r in kb.records.values():
            d = r.raw.get("data", {})
            if r.type != "Passive" or "node_id" not in d:
                continue
            nid = int(d["node_id"])
            self.nodes[nid] = TreeNode(
                node_id=nid,
                name_en=r.raw["name"]["en"],
                name_ko=r.raw["name"]["ko"],
                kind=d.get("kind", "small"),
                stats_en=tuple(d.get("stats_en") or ()),
                ascendancy=d.get("ascendancy"),
                unlock_constraint=d.get("unlock_constraint") or None,
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

    def connect_anchors(
        self, class_name: str, targets: collections.abc.Iterable[int]
    ) -> tuple[list[int], dict[int, list[int]]]:
        """그리디 슈타이너: 시작점에서 타깃들을 최소 포인트로 연결.

        매 라운드 '기존 트리에서 가장 싼 타깃'을 최단 경로로 붙인다(근사 —
        전역 최적 비보장, §10.3 한계 인정). 반환: (할당 노드 전체, 타깃별 경로).
        """
        tree: set[int] = {self.start_of(class_name)}
        remaining = set(targets)
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
        allocated = sorted(tree - {self.start_of(class_name)})
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
        `ascendancy_name`은 실명("Blood Mage")이며, 주지 않으면 잠긴 노드를 **전부** 뺀다
        (모르는 채 넣는 것보다 빼고 알리는 쪽이 안전하다).
        """
        dist = self.distances_from(near, max_dist)
        out = [
            (nid, self.nodes[nid], d)
            for nid, d in dist.items()
            if d > 0
            and nid in self.nodes
            and self.nodes[nid].kind in kinds
            and self.nodes[nid].ascendancy is None
            and self.nodes[nid].locked_to in (None, ascendancy_name)
        ]
        return sorted(out, key=lambda x: (x[2], x[0]))
