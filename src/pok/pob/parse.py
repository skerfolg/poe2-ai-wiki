"""PoB 공유 코드 → 구조 요약 (parse_pob, D30 앵커 수집의 해석기).

역방향(코드→구조)만 담당한다 — 정방향(BuildSpec→XML)은 buildxml.to_xml.
앵커 빌드(poe.ninja 등 외부 검증 빌드)를 KB id 공간과 비교 가능한 요약으로
내리는 것이 목적: 클래스·어센던시·스킬 그룹·트리 노드·아이템·저장 스탯.

판단 없음(AD-3): 요약은 사실 추출이며, 앵커의 가치 평가·델타 설계는 에이전트 몫.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from pok.pob.codec import decode


@dataclass(frozen=True)
class SkillGroupSummary:
    """소켓 그룹 하나 — 젬 이름 나열 (액티브/보조 구분은 XML에 없다: KB 대조 몫)."""

    gems: tuple[str, ...]
    slot: str = ""
    enabled: bool = True
    label: str = ""


@dataclass(frozen=True)
class ItemSummary:
    rarity: str
    name: str
    base: str


@dataclass(frozen=True)
class PobSummary:
    class_name: str
    ascendancy: str
    level: int
    main_socket_group: int  # 1-based (PoB 관례)
    skill_groups: tuple[SkillGroupSummary, ...]
    tree_nodes: tuple[int, ...]
    tree_version: str
    ascendancy_internal_id: str
    items: tuple[ItemSummary, ...]
    player_stats: dict[str, float] = field(default_factory=dict)  # 코드에 저장된 표시 스탯

    @property
    def main_skill_gems(self) -> tuple[str, ...]:
        idx = self.main_socket_group - 1
        if 0 <= idx < len(self.skill_groups):
            return self.skill_groups[idx].gems
        return ()


def parse_pob_xml(xml_text: str) -> PobSummary:
    """PoB XML → 요약. 루트는 PathOfBuilding2(PoE2) 또는 PathOfBuilding."""
    root = ET.fromstring(xml_text)
    build = root.find("Build")
    if build is None:
        raise ValueError("PoB XML에 Build 요소가 없음")
    stats: dict[str, float] = {}
    for ps in build.findall("PlayerStat"):
        name, value = ps.get("stat"), ps.get("value")
        if not name or value is None:
            continue
        try:
            stats[name] = float(value)
        except ValueError:
            continue  # 숫자 아닌 표시값은 요약에서 제외
    groups: list[SkillGroupSummary] = []
    skills = root.find("Skills")
    if skills is not None:
        skill_set = skills.find("SkillSet")
        for g in (skill_set if skill_set is not None else skills).findall("Skill"):
            groups.append(
                SkillGroupSummary(
                    gems=tuple(gm.get("nameSpec") or "" for gm in g.findall("Gem")),
                    slot=g.get("slot") or "",
                    enabled=(g.get("enabled") or "true").lower() == "true",
                    label=g.get("label") or "",
                )
            )
    nodes: tuple[int, ...] = ()
    tree_version = asc_internal = ""
    tree = root.find("Tree")
    spec = tree.find("Spec") if tree is not None else None
    if spec is not None:
        raw_nodes = (spec.get("nodes") or "").strip()
        nodes = tuple(int(n) for n in raw_nodes.split(",") if n.strip().isdigit())
        tree_version = spec.get("treeVersion") or ""
        asc_internal = spec.get("ascendancyInternalId") or ""
    items: list[ItemSummary] = []
    items_el = root.find("Items")
    if items_el is not None:
        for it in items_el.findall("Item"):
            lines = [ln.strip() for ln in (it.text or "").strip().splitlines() if ln.strip()]
            if not lines or not lines[0].lower().startswith("rarity:"):
                continue
            rarity = lines[0].split(":", 1)[1].strip().lower()
            name = lines[1] if len(lines) > 1 else ""
            base = lines[2] if rarity in ("rare", "unique") and len(lines) > 2 else name
            items.append(ItemSummary(rarity=rarity, name=name, base=base))
    return PobSummary(
        class_name=build.get("className") or "",
        ascendancy=build.get("ascendClassName") or "",
        level=int(build.get("level") or 1),
        main_socket_group=int(build.get("mainSocketGroup") or 1),
        skill_groups=tuple(groups),
        tree_nodes=nodes,
        tree_version=tree_version,
        ascendancy_internal_id=asc_internal,
        items=tuple(items),
        player_stats=stats,
    )


def parse_pob(build_code: str) -> PobSummary:
    """공유 코드(base64+zlib) → 요약. 손상 코드는 ValueError (codec.decode)."""
    return parse_pob_xml(decode(build_code))
