"""PoB 코드 → 우리 `BuildSpec` 사전 (#67 6차, 사용자 지시 2026-08-12).

`parse.py`는 **요약**을 낸다(무엇이 들어 있나). 여기는 **되돌린다**(다시 계산할 수
있게). 둘은 목적이 달라 합치지 않았다 — 요약은 아이템 이름만 알면 되지만 복원은
raw 텍스트·주얼·능력치 선택까지 전부 필요하다.

**왜 필요한가**: 래더 코퍼스에 PoB 코드가 40벌 넘게 쌓였는데 우리 엔진에 넣을 수
없었다. 「실제 빌드를 다시 최적화」·「우리 산출물 대 래더 A/B」가 전부 여기서 막혔다.
실측 2026-08-12: 복원기 없이 손으로 시도하니 10벌 중 1벌만 됐고, 그 1벌도 EHP가
원본과 4,214 대 5,990으로 어긋났다 — **주얼 소켓과 능력치 택1을 빠뜨려서**였다.

⚠ **못 되돌린 것은 반드시 말한다.** 조용히 빼면 "복원했다"고 믿은 채 다른 빌드를
재게 된다. `RestoredBuild.notes`가 그 자리다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pok.pob.codec import decode

# PoB 슬롯명 그대로 쓴다. 주얼은 슬롯이 아니라 `Spec/Sockets`에 있어 따로 처리한다.
_SKIP_SLOTS = frozenset({"Weapon 1 Swap", "Weapon 2 Swap"})

# 속성값 안의 공백문자 → 문자 참조. **표준 XML 리더는 속성 안 개행·탭을 공백 하나로
# 정규화한다**(XML 1.0 §3.3.3 attribute-value normalization). 문자 참조는 그 정규화를
# 받지 않으므로, 파싱 **전에** 바꿔 두면 ElementTree가 원래 문자를 그대로 돌려준다.
_ATTR_WS = {"\n": "&#10;", "\r": "&#13;", "\t": "&#9;"}


def _keep_attr_whitespace(xml_text: str) -> str:
    """속성값의 개행을 살려서 돌려준다 (#134).

    PoB는 여러 줄 config(`customMods`)를 **리터럴 개행이 든 속성값**으로 적는다 —
    자기 파서가 `&#10;` 같은 수치 참조를 모르기 때문이다(`runtime/lua/xml.lua:11`,
    `buildxml._pob_attr` 참조). 그 표기를 표준 리더로 읽으면 개행이 공백이 되어
    두 줄이 한 줄로 붙고, PoB의 `modLib.parseMod`는 줄 단위로 돌므로
    **전부 파싱 실패한다 — 결과는 델타 0이라 「효과 없음」과 구별되지 않는다**
    (실측 2026-08-28: 두 줄짜리 customMods가 원시 XML 직접 계산에서는 DPS +14.8% ·
    EHP +65.5%인데 복원 왕복 뒤엔 ±0).

    태그 **안**에서만 바꾼다 — 아이템 raw 텍스트는 원소 text라 정규화 대상이 아니고,
    거기 든 따옴표·개행을 건드리면 안 된다.
    """
    if not any(ch in xml_text for ch in _ATTR_WS):
        return xml_text
    out: list[str] = []
    i, n = 0, len(xml_text)
    while True:
        start = xml_text.find("<", i)
        if start < 0:
            out.append(xml_text[i:])
            return "".join(out)
        out.append(xml_text[i:start])  # 태그 밖은 통째로 (아이템 텍스트가 여기다)
        j, quote = start, ""
        while j < n:
            ch = xml_text[j]
            if quote:
                out.append(ch if ch == quote else _ATTR_WS.get(ch, ch))
                if ch == quote:
                    quote = ""
            else:
                out.append(ch)
                if ch in "\"'":
                    quote = ch
                elif ch == ">":
                    j += 1
                    break
            j += 1
        i = j


@dataclass(frozen=True)
class RestoredBuild:
    """복원 결과 + **못 되돌린 것들**."""

    spec: dict[str, Any]
    notes: tuple[str, ...] = ()
    # 게이트가 요구하는데 코드에 없는 값 — 호출자가 채워야 계산이 정직해진다
    needs_decision: tuple[str, ...] = ()
    # 아이템이 부여해 뺀 스킬 그룹 (스킬명, 함께 빠진 보조 젬 수). **문자열 note로만
    # 두면 걸러낼 수 없다** — 딜을 비교하려면 이게 빈 빌드만 써야 한다(실측
    # 2026-08-12: 복원 256벌 중 203벌이 여기 걸리고, 그쪽 DPS는 원본보다 낮게 나온다).
    dropped_item_granted: tuple[tuple[str, int], ...] = ()

    @property
    def damage_comparable(self) -> bool:
        """딜 수치를 원본과 견줄 수 있나 — 부여 그룹을 뺐으면 보조가 빠져 낮게 나온다."""
        return not self.dropped_item_granted

    @property
    def faithful(self) -> bool:
        """빠뜨린 것 없이 되돌렸나. False여도 계산은 되지만 **원본과 다르다**."""
        return not self.notes and not self.needs_decision


@lru_cache(maxsize=1)
def _known_nodes() -> tuple[frozenset[int], frozenset[int]]:
    """(KB가 아는 트리 노드, 그중 전직 시작 노드).

    PoB가 **자동 할당**하는 노드를 스펙에서 빼려는 것이다 — 넣으면 PoB가 잘라내고
    (`pruned_nodes`), 델타 측정기는 pruned가 있는 결과를 통째로 버린다.

    자동 할당은 둘이다: **전직 시작**(KB에 `kind`로 있다)과 **클래스 시작**(KB에
    레코드가 아예 없다 — 고를 수 있는 패시브가 아니라 뿌리다). 후자는 열거할 표가
    이 층에 없으므로 "KB가 모르는 노드"로 판별한다. 그래서 **뺀 개수를 반드시
    보고한다** — KB 수집 갭이 생기면 멀쩡한 노드가 조용히 빠질 수 있다.

    ⛔ `engine.tree.graph.CLASS_START`를 쓰지 않는다: `pob`는 `engine`을 import할 수
    없다(의존 방향 단방향, import-linter가 강제).
    """
    from pok.kb.store import load

    known: set[int] = set()
    starts: set[int] = set()
    for record in load().records.values():
        data = record.raw.get("data") or {}
        node_id = data.get("node_id")
        if record.type != "Passive" or node_id is None:
            continue
        try:
            nid = int(node_id)
        except (TypeError, ValueError):
            continue
        known.add(nid)
        if data.get("kind") == "ascendancy-start":
            starts.add(nid)
    return frozenset(known), frozenset(starts)


def _int(value: str | None, default: int) -> int:
    """PoB는 빈 값을 문자열 `"nil"`로 적는다 — 그대로 float()에 넣으면 터진다.

    실측 2026-08-12: 코퍼스 300벌 중 **291벌**이 이 한 줄 때문에 복원 실패했다.
    """
    if value is None:
        return default
    text = value.strip()
    if not text or text == "nil":
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _items_by_id(items_el: ET.Element) -> dict[str, str]:
    # ⚠ `.text`만 읽으면 안 된다 — `<ModRange>` 자식이 끼면 그 뒤 줄이 잘려
    #   옵션 없는 유니크가 되고, PoB는 아무 효과도 안 붙인 채 계산한다.
    return {it.get("id", ""): "".join(it.itertext()).strip() for it in items_el.findall("Item")}


def _stat_set_index(gem: ET.Element, gem_id: str) -> int | None:
    """이 젬이 **어느 모드(statSet)로 계산됐는지** — 코드에 있으면 그 값, 없으면 None.

    ⛔ 예전 주석은 "PoB 코드는 어느 모드로 계산했는지 남기지 않는다"였고, 그래서
    **있는 값을 버리고 무조건 1번을 가정**했다 (#134). 원본을 읽으면 틀렸다 —
    `SkillsTab.lua:508`이 `statSet`을 grantedEffect별 `<StatSetIndex>` 자식 원소로
    저장한다(속성 `statSetIndex`도 쓰지만 로드 쪽 370행이 즉시 `{}`로 덮어써 **자식이
    정본**이다. 그래서 자식을 먼저 보고 속성은 뒤로 둔다).

    버리면 복원본이 **원본과 다른 모드로 계산된다** — 실측 2026-08-10: 구형 번개의
    파트 1/2/3이 2,387 / 32,231 / 47,329로 20배 갈렸다. 오류도 경고도 없다.
    """
    by_effect: dict[str, int] = {}
    for child in gem.findall("StatSetIndex"):
        effect = child.get("grantedEffect") or ""
        index = (child.get("index") or "").strip()
        if effect and index.isdigit():
            by_effect[effect] = int(index)
    if not by_effect:
        attr = (gem.get("statSetIndex") or "").strip()
        return int(attr) if attr.isdigit() else None
    if len(by_effect) == 1:
        return next(iter(by_effect.values()))
    # 젬 하나가 부여 효과를 여럿 가지면(녹아내린 폭발 = 주 + 파편) **주 효과** 것을 쓴다.
    # 못 짚으면 가정으로 떨어뜨린다 — 아무 값이나 고르면 조용히 틀린 모드가 된다.
    from pok.kb.skill_facts import primary_effect

    candidates = [primary_effect(gem_id)]
    try:  # 래더 코드는 **게임 id**로 적혀 있다. 별칭표는 PoB 스냅샷을 읽으므로 없으면 건너뛴다
        from pok.pob.catalog import canonical_gem_id

        candidates.append(primary_effect(canonical_gem_id(gem_id)))
    except (OSError, RuntimeError):
        pass
    for candidate in candidates:
        if candidate in by_effect:
            return by_effect[candidate]
    return None


def _skills(
    root: ET.Element, assume_first_stat_set: bool, assume_stages: int | None
) -> tuple[list[dict[str, Any]], list[str], int, list[tuple[str, int]]]:
    holder = root.find("Skills")
    if holder is None:
        return [], [], 0, []
    sset = holder.find("SkillSet")
    groups: list[dict[str, Any]] = []
    assumed: list[str] = []
    from_items = 0
    granted_groups: list[tuple[str, int]] = []
    for skill in (sset if sset is not None else holder).findall("Skill"):
        # PoB는 **아이템이 준 스킬 그룹**에 `source`를 붙인다. 그걸 젬으로 다시 실으면
        # 이중 계산이고, 우리 게이트도 "젬으로 못 켠다"며 막는다. 아이템을 장착하면
        # PoB가 알아서 되살리므로 여기서는 싣지 않는다.
        if skill.get("source"):
            from_items += 1
            continue
        # ⛔ 예전엔 여기서 **젬 이름**으로 한 번 더 걸러 냈다 — `source`가 없어도 KB가
        #    아이템 부여로 아는 스킬이 들어 있으면 그룹째 뺐다. **그게 결함이었다.**
        #    `source` 없는 그룹은 PoB가 만든 것이 아니라 **플레이어가 구성한 것**이고,
        #    아이템이 준 스킬에 주얼러 오브로 보조를 붙인 바로 그 구성이다.
        #    실측 2026-08-13(블러드 메이지 래더 코드): 그 그룹을 빼자 같은 빌드가
        #    **DPS 1,935,569 → 12,334**(157배)가 됐다. 주력 스킬 그룹이었다.
        #    이중 계산도 아니다 — 원본 XML은 `source` 있는 그룹과 없는 그룹을 **둘 다**
        #    들고 저 수치를 낸다. 우리가 `source` 있는 것만 빼면 PoB가 그것을 되만들어
        #    원본과 같은 구조가 된다.
        gems = []
        for gem in skill.findall("Gem"):
            gem_id = gem.get("gemId") or ""
            if not gem_id:
                continue
            entry: dict[str, Any] = {
                "gem_id": gem_id,
                "name": gem.get("nameSpec") or "",
                "level": _int(gem.get("level"), 20),
                "quality": _int(gem.get("quality"), 0),
                "enabled": (gem.get("enabled") or "true") != "false",
                # 부패는 젬 레벨을 올린다 — 버리면 딜이 조용히 빠진다(실측 74.4%).
                "corrupted": (gem.get("corrupted") or "nil") == "true",
                "corrupt_level": _int(gem.get("corruptLevel"), 0),
            }
            # 모드(statSet)는 **코드에 적혀 있으면 그것을 쓴다** (#134). 없을 때만
            # 1번을 가정하고, 가정했다는 사실을 반드시 남긴다 — 조용히 1번을 쓰면
            # 실측 2026-08-10처럼 20배 차이가 난다.
            found = _stat_set_index(gem, gem_id)
            if found is not None:
                entry["stat_set_index"] = found
            elif assume_first_stat_set:
                entry["stat_set_index"] = 1
                assumed.append(entry["name"] or gem_id)
            # 단계 수는 **어느 코드에도 없다**(실측: 코퍼스 300벌 전부 skillStageCount
            # 미포함). 유지 단계는 설계 판단이라 기본값을 두지 않는다 — 필요하면
            # 호출자가 정해서 넘긴다.
            if assume_stages is not None:
                entry["stages"] = assume_stages
            gems.append(entry)
        if gems:
            groups.append(
                {
                    "gems": gems,
                    "slot": skill.get("slot") or "Weapon 1",
                    "enabled": (skill.get("enabled") or "true") != "false",
                    "main_active_skill": _int(skill.get("mainActiveSkill"), 1),
                }
            )
    return groups, assumed, from_items, granted_groups


def _config(root: ET.Element) -> list[list[Any]]:
    """`Config/ConfigSet/Input` → 계산 조건.

    ⚠ 이걸 빼면 **버프·충전·적 상태가 전부 꺼진 채** 계산된다. 실측 2026-08-12:
    config 없이 복원하니 EHP가 원본 대비 14~44% 낮았다. 오류도 경고도 없이 낮게
    나오므로 "복원했다"고 믿으면 그대로 틀린 수치를 쓴다.
    """
    holder = root.find("Config")
    if holder is None:
        return []
    cfg_set = holder.find("ConfigSet")
    out: list[list[Any]] = []
    for item in (cfg_set if cfg_set is not None else holder).findall("Input"):
        name = item.get("name")
        if not name:
            continue
        if item.get("boolean") is not None:
            out.append([name, item.get("boolean") == "true"])
        elif item.get("number") is not None:
            out.append([name, _int(item.get("number"), 0)])
        elif item.get("string") is not None:
            out.append([name, item.get("string")])
    return out


def _attribute_choices(spec_el: ET.Element) -> list[list[Any]]:
    """`Overrides/AttributeOverride` → 택1 노드의 선택.

    실측 2026-08-05: 앵커에서 택1 35개를 빼자 Str 184→79 · Dex 165→104 · Int 137→27.
    **한 빌드의 능력치 절반 이상이 여기서 나온다** — 빠뜨리면 요구치도 스탯 스태킹도
    전부 어긋난다.
    """
    out: list[list[Any]] = []
    overrides = spec_el.find("Overrides")
    if overrides is None:
        return out
    for attr in overrides.findall("AttributeOverride"):
        for key, choice in (("strNodes", "str"), ("dexNodes", "dex"), ("intNodes", "int")):
            for raw in (attr.get(key) or "").split(","):
                if raw.strip().isdigit():
                    out.append([int(raw), choice])
    return out


def spec_from_pob_xml(
    xml_text: str, *, assume_first_stat_set: bool = True, assume_stages: int | None = None
) -> RestoredBuild:
    """PoB XML → `spec_from_dict`가 받는 사전. 못 되돌린 것은 notes에."""
    root = ET.fromstring(_keep_attr_whitespace(xml_text))
    build = root.find("Build")
    tree_el = root.find("Tree")
    if build is None or tree_el is None:
        raise ValueError("PoB XML에 <Build>/<Tree>가 없다 — 코드가 손상됐거나 형식이 다르다")
    spec_el = tree_el.find("Spec")
    if spec_el is None:
        raise ValueError("PoB XML에 <Tree><Spec>이 없다")

    notes: list[str] = []
    items_el = root.find("Items")
    by_id = _items_by_id(items_el) if items_el is not None else {}

    items: list[dict[str, str]] = []
    if items_el is not None:
        itemset = items_el.find("ItemSet")
        for slot in (itemset if itemset is not None else items_el).findall("Slot"):
            name, iid = slot.get("name") or "", slot.get("itemId") or "0"
            if iid in ("0", "") or iid not in by_id:
                continue
            if name in _SKIP_SLOTS:
                # 교체 무기는 우리 스펙에 자리가 없다. 조용히 버리면 "무기 없는
                # 빌드"가 되어 DPS 0이 나오고, 원인을 짚을 수 없다.
                notes.append(f"교체 무기 슬롯 '{name}'를 싣지 못했다 — 스펙에 자리가 없다")
                continue
            items.append({"slot": name, "text": by_id[iid]})

    # 주얼은 슬롯이 아니라 트리 소켓에 박힌다 — `Items`만 보면 통째로 빠진다.
    # ⚠ PoB는 **할당하지 않은 소켓의 매핑도 남겨 둔다**(예전에 꽂았던 주얼). 그대로
    #   실으면 "소켓이 tree_nodes에 없다"로 조립이 거부된다 — 할당된 것만 싣는다.
    allocated = {int(n) for n in (spec_el.get("nodes") or "").split(",") if n.strip().isdigit()}
    jewels: list[dict[str, Any]] = []
    orphan = 0
    for socket in spec_el.findall("./Sockets/Socket"):
        node_id, iid = socket.get("nodeId"), socket.get("itemId") or "0"
        if not (node_id and node_id.isdigit() and iid in by_id):
            continue
        if int(node_id) in allocated:
            jewels.append({"socket_node_id": int(node_id), "text": by_id[iid]})
        else:
            orphan += 1
    if orphan:
        notes.append(f"할당 안 된 소켓의 주얼 {orphan}개는 뺐다 — 트리에 없는 소켓이다")

    # 0.5의 무기 세트별 할당 — 우리 스펙은 트리를 하나만 들고 있다.
    for tag in ("WeaponSet1", "WeaponSet2"):
        el = spec_el.find(tag)
        if el is not None and len(el):
            notes.append(
                f"{tag}에 세트 전용 할당 {len(el)}건이 있는데 스펙에 자리가 없다 — "
                "그만큼 원본보다 약하게 계산된다"
            )
    if (spec_el.get("masteryEffects") or "").strip():
        notes.append("masteryEffects가 있는데 스펙에 자리가 없다 — 그만큼 빠진 채 계산된다")

    groups, assumed, from_items, granted_groups = _skills(
        root, assume_first_stat_set, assume_stages
    )
    if granted_groups:
        lost = sum(s for _, s in granted_groups)
        notes.append(
            f"아이템 부여 스킬 그룹 {len(granted_groups)}개를 뺐다"
            f"({', '.join(n for n, _ in granted_groups[:4])}) — 장착 아이템이 PoB에서 "
            f"다시 부여한다. ⚠ 그 그룹의 **보조 젬 {lost}개는 함께 빠진다**"
            "(주얼러 오브로 늘린 소켓) — 그만큼 원본보다 약하게 계산된다"
        )
    if from_items:
        notes.append(
            f"아이템이 준 스킬 그룹 {from_items}개는 싣지 않았다 — 장착 아이템이 "
            "PoB에서 다시 부여한다(젬으로 실으면 이중 계산이다)"
        )
    # 원본 `nodes`에는 **클래스·전직 시작 노드가 들어 있다.** 그대로 실으면 PoB가
    # 잘라내고(`pruned_nodes`), 델타 측정기는 pruned가 있는 결과를 통째로 버린다 —
    # 복원한 빌드로는 아무것도 못 재게 된다(실측 2026-08-12: 전 빌드에서 2개씩).
    known, asc_starts = _known_nodes()
    raw_nodes = [int(n) for n in (spec_el.get("nodes") or "").split(",") if n.strip().isdigit()]
    nodes = [n for n in raw_nodes if n in known and n not in asc_starts]
    dropped = len(raw_nodes) - len(nodes)
    if dropped:
        notes.append(
            f"자동 할당 노드 {dropped}개를 뺐다(클래스·전직 시작) — 스펙에 넣으면 PoB가 "
            "잘라내고 그 트리의 측정이 전부 무효가 된다. KB에 없는 노드도 여기 섞이므로 "
            "개수가 예상(빌드당 2)보다 크면 트리 수집 갭을 의심할 것"
        )
    spec: dict[str, Any] = {
        "class_name": build.get("className") or "",
        # 전직은 **내부 코드**여야 한다("Monk1") — 실명은 카탈로그가 거부한다.
        "ascendancy": spec_el.get("ascendancyInternalId") or build.get("ascendClassName") or "",
        "level": _int(build.get("level"), 90),
        "main_socket_group": _int(build.get("mainSocketGroup"), 1),
        "tree_nodes": nodes,
        "items": items,
        "skills": groups,
        "jewels": jewels,
        "attribute_choices": _attribute_choices(spec_el),
        "config": _config(root),
    }
    needs: list[str] = []
    if assume_stages is not None:
        needs.append(
            f"단계형 스킬에 `stages={assume_stages}`를 **가정했다** — PoB 코드에는 단계 "
            "수가 없다(코퍼스 300벌 전부). 유지 단계가 다르면 수치가 크게 달라진다"
        )
    if assumed:
        needs.append(
            f"젬 {len(assumed)}개에 `stat_set_index=1`을 **가정했다** — PoB 코드는 어느 "
            f"모드로 계산했는지 남기지 않는다. 모드가 둘 이상인 젬이면 수치가 크게 "
            f"달라진다(실측 20배). 대상: {assumed[:6]}{' …' if len(assumed) > 6 else ''}"
        )
    # ⛔ **복원본이라는 표식을 남긴다** (#129). 조립 게이트는 「손으로 지은 희귀 접사」를
    #    거부하는데, 복원본에는 `derived_from`이 있을 수 없다 — 표식이 없으면 **남의 빌드를
    #    읽는 것 자체가 막힌다**(§0 ⑪ 거짓 거부). 실측 2026-08-27에 그렇게 막혔다.
    spec["restored_from"] = "pob-code"
    return RestoredBuild(
        spec=spec,
        notes=tuple(notes),
        needs_decision=tuple(needs),
        dropped_item_granted=tuple(granted_groups),
    )


def spec_from_pob(
    build_code: str, *, assume_first_stat_set: bool = True, assume_stages: int | None = None
) -> RestoredBuild:
    """PoB 공유 코드(base64) → 스펙 사전."""
    return spec_from_pob_xml(
        decode(build_code),
        assume_first_stat_set=assume_first_stat_set,
        assume_stages=assume_stages,
    )
