"""패시브 트리 수집·정형화 (KB_INGEST §6-2 ②).

젬과 다른 점:
- 수집이 **일괄 엔드포인트 2회**(kr/us)로 끝난다 — 개별 페이지 스크래핑 불필요.
- 규모가 커서(5천여 노드) **종류별 청크**로 분할 처리한다 (keystone→notable→jewel→small).
- 연결(connections)은 P4 트리 최적화(Steiner)의 기반이라 **엣지를 보존**한다.

KI-8 신호 (트리판):
  A = 구현 증거: 이름에 DNT/UNUSED 표식 없음 AND (stats 있음 OR 키스톤/구조 노드)
  P = PoB tree.json 존재
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from pok.kb.ingest.sources import USER_AGENT
from pok.kb.ingest.verify import (
    SourceEntity,
    acquisition_coverage,
    cross_source,
    substance_floor,
    verification_block,
)

# poe2db 트리 일괄 데이터 (4.5 = PoE2 0.5 트리 버전)
TREE_DATA_URL = "https://poe2db.tw/data/passive-skill-tree/4.5/data_{lang}.json"
TREE_LANGS = ("us", "kr")

# PoB 트리 (게임파일 유래 — 교차 대사 축)
POB_TREE_REL = "src/TreeData/0_5/tree.json"

# 미구현 표식 (poe2db가 명시) — 예: "[DNT-UNUSED] Templar1Notable1"
_UNIMPLEMENTED = re.compile(r"\[(DNT|UNUSED|DNT-UNUSED)[^\]]*\]|^DNT[ _-]", re.I)

# poe2db가 정리하지 않은 위키 마크업 — "[Jewel] Socket", "[Key|표시]" 형태
_MARKUP = re.compile(r"\[([^\]|]+)\|([^\]]+)\]|\[([^\]]+)\]")


_WS = re.compile(r"\s+")


def clean_name(raw: str) -> str:
    """위키 마크업 제거 + 공백 정리 (poe2db 원본에 잔재가 섞여 있음)."""
    return _MARKUP.sub(lambda m: m.group(2) or m.group(3) or "", raw).strip()


def _stat_lines(entry: str) -> list[str]:
    """항목 1개를 개행 기준으로 쪼개고 마크업·공백을 정리한다."""
    return [t for t in (clean_name(p).strip() for p in str(entry).split("\n")) if t]


def _fold(entry: str) -> str:
    """개행을 공백으로 접는다 — 줄바꿈이 효과 경계가 아닐 때의 안전한 처리."""
    return " ".join(_stat_lines(entry))


def normalize_stats(en_raw: Any, ko_raw: Any) -> tuple[list[str], list[str]]:
    """stats를 en/ko 쌍으로 정규화한다 (KB_INGEST §4-0의 3a·3b 결정).

    - **마크업 제거**(3a): poe2db가 `[Projectile|Projectile]` 같은 위키 링크를 남긴다.
    - **개행 분할은 en/ko 항목 수가 일치할 때만**(3b): poe2db의 `\\n`은 효과 경계일 때도
      있고(`Avatar of Fire`) 단순 줄바꿈일 때도 있다(`Crystalline Resistance`의
      "…if you have at\\nleast 5 Red…"). 어느 소스도 단독 정답이 아니므로 — PoB도 같은
      자리를 잘못 쪼갠다 — **두 언어의 합의**를 기준으로 삼고, 합의가 없으면 접는다.
      이렇게 하면 두 배열의 길이가 구조적으로 같아진다(위치 대응 보장).
    """
    en_e = [str(s) for s in (en_raw or [])]
    ko_e = [str(s) for s in (ko_raw or [])]
    if len(en_e) != len(ko_e):
        # 항목 수 자체가 다르면 짝지을 수 없다 → 분할하지 않고 각자 접기만
        return [t for t in map(_fold, en_e) if t], [t for t in map(_fold, ko_e) if t]

    en_out: list[str] = []
    ko_out: list[str] = []
    for e, k in zip(en_e, ko_e, strict=True):
        ep, kp = _stat_lines(e), _stat_lines(k)
        if len(ep) > 1 and len(ep) == len(kp):
            en_out += ep
            ko_out += kp
            continue
        fe, fk = _fold(e), _fold(k)
        if fe or fk:
            en_out.append(fe)
            ko_out.append(fk)
    return en_out, ko_out


# '+N to any Attribute' 소형 노드 — 뒤따르는 세 줄은 **선택지**이지 동시 부여가 아니다.
_ANY_ATTRIBUTE = re.compile(r"^\+(\d+) to any Attribute$")
_ATTRIBUTE_OPTION = re.compile(r"^base (strength|dexterity|intelligence) (\d+)$")


def extract_attribute_choice(
    stats_en: list[str], stats_ko: list[str]
) -> tuple[list[str], list[str], dict[str, Any] | None]:
    """능력치 선택 노드의 선택지를 stats에서 빼내 구조 필드로 올린다.

    poe2db는 표시 문구("+5 to any Attribute") 뒤에 고를 수 있는 능력치를 내부 stat id로
    덧붙인다. 이걸 평평한 stats에 두면 읽는 쪽이 **"힘·민첩·지능을 각각 +5씩 준다"**로
    해석한다 — 실제로는 **셋 중 하나를 고르는** 노드다(사람 판정 2026-07-29).
    PoB도 표시 문구 한 줄만 갖고 있다.

    삭제만 하면 이번엔 선택지가 사라져 생성기가 "무엇을 고를지"를 결정할 수 없다.
    아이템·스킬 요구치 충족과 스탯 스태킹의 핵심 노드라(사용자 지적) 기계가 쓸 수 있는
    형태로 남겨야 한다 — 조건 1급 필드 원칙(RC1)의 적용 지점.

    ⚠️ 이 규칙은 **이 패턴에만** 적용한다. 다른 내부 stat id(`focus decay delay ms 5000`
    등 32줄)는 노드 고유의 조건·한계치를 담고 있을 수 있어 **보존**한다(사람 판정) —
    지우면 예상 못 한 리스크를 안은 빌드나 성립하지 않는 조건이 나올 수 있다.
    """
    if not stats_en:
        return stats_en, stats_ko, None
    head = _ANY_ATTRIBUTE.match(stats_en[0])
    if head is None:
        return stats_en, stats_ko, None
    value = int(head.group(1))
    options: list[str] = []
    drop: set[int] = set()
    for i, line in enumerate(stats_en[1:], start=1):
        m = _ATTRIBUTE_OPTION.match(line)
        if m and int(m.group(2)) == value:
            options.append(m.group(1))
            drop.add(i)
    if not options:
        return stats_en, stats_ko, None
    keep_en = [s for i, s in enumerate(stats_en) if i not in drop]
    keep_ko = [s for i, s in enumerate(stats_ko) if i not in drop]
    return keep_en, keep_ko, {"value": value, "options": options}


def norm_stat(raw: str) -> str:
    """⑥ 효과 대조용 정규화 — 마크업·공백·대소문자 차이를 지운다.

    poe2db는 `[Projectile|Projectile] [Stun|Stun Buildup]`처럼 위키 링크를 남기고
    PoB는 평문이다. 정규화 없이 대조하면 4,255/4,914가 "불일치"로 나와 무용하다.
    """
    return _WS.sub(" ", clean_name(raw)).strip().lower()


# 처리 청크 (분할 단위) — 앞쪽일수록 큐레이션 가치가 높다
CHUNKS = ("keystone", "ascendancy-start", "notable", "jewel", "small")

# mastery(368) = 트리 구역 라벨/배경 그래픽. KB 수록 대상 아님 (사람 판정 2026-07-29):
#   · PoB가 isOnlyImage → type="OnlyImage"로 분류 (할당·계산 불가, PassiveTree.lua:223)
#   · masteryEffects가 양 소스 0건, stats는 비었거나 "Requires The Unseen Path" 한 줄뿐
#   · '가지 않은 길'(Paths_Not_Taken) 선택 가능 노드 목록에 Mastery 이름이 0건
# 실제 '보이지 않는 길' 조건부 효과 노드는 isMastery=False인 별개 노드들로,
# notable/small 청크에 이미 수록됨 (0.5.4b 기준 176건).
EXCLUDED_KINDS = ("mastery",)


def node_kind(node: dict[str, Any]) -> str:
    if node.get("isMastery"):
        return "mastery"
    if node.get("isAscendancyStart"):
        return "ascendancy-start"
    if node.get("isKeystone"):
        return "keystone"
    if node.get("isNotable"):
        return "notable"
    if node.get("isJewelSocket"):
        return "jewel"
    return "small"


def fetch_tree(raw_dir: Path, pob_dir: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """poe2db 일괄 JSON(kr/us) + PoB tree.json을 원시로 저장한다 (멱등)."""
    out = raw_dir / "tree"
    out.mkdir(parents=True, exist_ok=True)
    own = client is None
    c = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    )
    saved: dict[str, Any] = {}
    try:
        for lang in TREE_LANGS:
            dst = out / f"poe2db_{lang}.json"
            if dst.exists():
                saved[lang] = "skipped"
                continue
            r = c.get(TREE_DATA_URL.format(lang=lang))
            r.raise_for_status()
            dst.write_bytes(r.content)
            saved[lang] = len(r.content)
            time.sleep(1.0)  # 정중함 정책
    finally:
        if own:
            c.close()

    pob_src = pob_dir / POB_TREE_REL
    pob_dst = out / "pob_tree.json"
    if pob_src.exists() and not pob_dst.exists():
        pob_dst.write_bytes(pob_src.read_bytes())
        saved["pob"] = pob_dst.stat().st_size
    return saved


def _load(raw_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    out = raw_dir / "tree"
    us = json.loads((out / "poe2db_us.json").read_text(encoding="utf-8"))
    kr = json.loads((out / "poe2db_kr.json").read_text(encoding="utf-8"))
    pob = json.loads((out / "pob_tree.json").read_text(encoding="utf-8"))
    return us, kr, pob


def _name_overrides(knowledge: Path | None) -> dict[str, dict[str, str]]:
    """poe2db 트리 JSON이 구 이름을 유지하는 노드의 한국어 보정표 (정본)."""
    if knowledge is None:
        from pok.common.paths import knowledge_dir

        knowledge = knowledge_dir()
    path = knowledge / "ingest" / "name-overrides.json"
    if not path.exists():
        return {}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    nodes: dict[str, dict[str, str]] = data.get("nodes", {})
    return nodes


def _oil_grantable(raw_dir: Path) -> set[str]:
    """성유(액체 감정)로 부여 가능한 노드 이름 — 원시가 있을 때만 (⑧ 획득 경로).

    트리 데이터엔 "어떻게 얻는가"가 없다. poe2db Liquid_Emotions 페이지가 유일한 출처라
    아직 수집 전이면 빈 집합 — 그 경우 커버리지가 낮게 나오는 것 자체가 수집 누락 신호다.
    """
    src = raw_dir / "liquid-emotions" / "us.html"
    if not src.exists():
        return set()
    from pok.kb.ingest.liquid_emotions import parse_page

    return set(parse_page(src.read_text(encoding="utf-8")))


def _verify(
    raw_dir: Path,
    db_entities: list[SourceEntity],
    pob_nodes: dict[str, Any],
    chunks: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """완전성 기준 ⑥⑦⑧ (KB_INGEST §4) — 판정하지 않고 리포트만 한다."""
    pob_entities = [
        SourceEntity(
            key=nid,
            name=clean_name(str(v["name"])),
            sets={"stats": frozenset(norm_stat(str(s)) for s in (v.get("stats") or []))},
        )
        for nid, v in pob_nodes.items()
        if isinstance(v, dict) and v.get("name")
    ]

    included = [n for items in chunks.values() for n in items]
    included_ids = {n["node_id"] for n in included}
    # 저장은 단방향이므로 양방향으로 펼쳐야 "트리로 도달 가능"을 제대로 센다
    degree: dict[str, int] = {}
    for n in included:
        for target in n["connections"]:
            if target in included_ids:
                degree[n["node_id"]] = degree.get(n["node_id"], 0) + 1
                degree[target] = degree.get(target, 0) + 1
    oils = _oil_grantable(raw_dir)

    inc_entities: list[SourceEntity] = []
    for n in included:
        routes: list[str] = []
        if degree.get(n["node_id"]):
            routes.append("tree-edge")
        if n["name_en"] in oils:
            routes.append("liquid-emotion")
        if n["kind"] == "ascendancy-start" or (n["structural"] and n.get("ascendancy")):
            routes.append("ascendancy-choice")
        inc_entities.append(
            SourceEntity(
                key=n["node_id"],
                name=n["name_en"],
                substance=tuple(n["stats_en"]),
                acquisition=tuple(routes),
                structural=bool(n["structural"]),
            )
        )

    return verification_block(
        cross=[
            cross_source(db_entities, pob_entities, labels=("poe2db", "pob"), compare_names=True)
        ],
        substance=[substance_floor(inc_entities, scope="passive:included")],
        acquisition=[acquisition_coverage(inc_entities, entity_type="passive")],
    )


def process_tree(raw_dir: Path, out_dir: Path, knowledge: Path | None = None) -> dict[str, Any]:
    """판정·분류하고 청크별 중간 산출물을 만든다."""
    us, kr, pob = _load(raw_dir)
    ko_overrides = _name_overrides(knowledge)
    kr_nodes = kr["nodes"]
    pob_nodes = pob.get("nodes", {})
    pob_by_id = {
        nid: clean_name(str(v["name"]))
        for nid, v in pob_nodes.items()
        if isinstance(v, dict) and v.get("name")
    }
    pob_by_name = {name.lower() for name in pob_by_id.values()}
    name_overrides: list[dict[str, str]] = []

    chunks: dict[str, list[dict[str, Any]]] = {k: [] for k in CHUNKS}
    excluded: list[str] = []
    attribute_choices = 0
    db_entities: list[SourceEntity] = []  # ⑥ — 보정 전 원본 이름으로 담는다
    for nid, node in us["nodes"].items():
        if not isinstance(node, dict) or not node.get("name") or nid == "root":
            continue
        name_en = clean_name(str(node["name"]))  # 마크업·공백 잔재 정리
        db_entities.append(
            SourceEntity(
                key=nid,
                name=name_en,
                sets={"stats": frozenset(norm_stat(str(s)) for s in (node.get("stats") or []))},
            )
        )
        # 같은 노드 id인데 이름이 다르면 PoB(게임파일 유래)를 따른다.
        # poe2db 트리 JSON이 구 이름을 남겨둔 사례 실측(0.5.4b: 22건 —
        # 'Arsonist'→Pyromancer, 'Necromancer'→Lich 등. poe2db 웹페이지는 PoB와 일치)
        pob_name = pob_by_id.get(nid)
        if pob_name and pob_name != name_en:
            name_overrides.append({"node_id": nid, "poe2db": name_en, "pob": pob_name})
            name_en = pob_name
        kind = node_kind(node)
        stats = [str(s) for s in (node.get("stats") or [])]
        in_pob = pob_name is not None or name_en.lower() in pob_by_name
        unimpl = bool(_UNIMPLEMENTED.search(name_en))
        # 어센던시 '선택 허브' — 효과가 없는 것이 정상인 구조 노드 (사람 판정 2026-07-29).
        # 여기 매달린 실존 노드가 허브를 빼면 트리에서 끊긴다 (0.5.4b: 13노드 —
        # Far Shot·Point Blank는 'Projectile Proximity Specialisation'(데드아이)에,
        # 혼합물 5종은 'Brew Concoction'(패스파인더)에만 연결돼 있다).
        # 미구현 자리표(AscendancyTemplar1Small7 등)는 PoB에 없어 그대로 제외된다.
        hub = bool(
            kind == "notable" and not stats and pob_name is not None and node.get("ascendancyName")
        )
        # 어센던시 시작·주얼 슬롯도 stats가 없는 게 정상 (효과 아닌 구조 노드)
        structural = kind in {"jewel", "ascendancy-start"} or hub
        has_effect = bool(stats) or kind == "keystone" or structural
        if kind in EXCLUDED_KINDS or unimpl or not (has_effect and (in_pob or structural)):
            excluded.append(f"{nid}:{name_en}")
            continue
        kr_node = kr_nodes.get(nid) or {}
        stats_en, stats_ko = normalize_stats(stats, kr_node.get("stats"))
        stats_en, stats_ko, attribute_choice = extract_attribute_choice(stats_en, stats_ko)
        if attribute_choice is not None:
            attribute_choices += 1
        chunks[kind].append(
            {
                "node_id": nid,
                "kind": kind,
                "name_en": name_en,
                "name_ko": (
                    ko_overrides.get(nid, {}).get("ko")
                    or clean_name(str(kr_node.get("name") or name_en))
                ),
                "stats_en": stats_en,
                "stats_ko": stats_ko,
                "ascendancy": node.get("ascendancyName"),
                "connections": sorted(
                    str(c["id"]) for c in (node.get("connections") or []) if isinstance(c, dict)
                ),
                "in_pob": in_pob,
                "structural": structural,  # ⑦ 면제 대상 (효과 없는 게 정상)
                "attribute_choice": attribute_choice,  # 셋 중 택1 (None이면 해당 없음)
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, items in chunks.items():
        (out_dir / f"tree_{kind}.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

    verification = _verify(raw_dir, db_entities, pob_nodes, chunks)
    report = {
        "poe2db_nodes": len(us["nodes"]),
        "pob_named_nodes": len(pob_by_name),
        "included": {k: len(v) for k, v in chunks.items()},
        "included_total": sum(len(v) for v in chunks.values()),
        "excluded": len(excluded),
        "excluded_sample": excluded[:20],
        "name_overrides": len(name_overrides),
        "name_overrides_sample": name_overrides[:20],
        "attribute_choice_nodes": attribute_choices,
        "verification": verification,
    }
    (raw_dir / "tree" / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
