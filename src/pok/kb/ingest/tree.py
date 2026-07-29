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

# poe2db 트리 일괄 데이터 (4.5 = PoE2 0.5 트리 버전)
TREE_DATA_URL = "https://poe2db.tw/data/passive-skill-tree/4.5/data_{lang}.json"
TREE_LANGS = ("us", "kr")

# PoB 트리 (게임파일 유래 — 교차 대사 축)
POB_TREE_REL = "src/TreeData/0_5/tree.json"

# 미구현 표식 (poe2db가 명시) — 예: "[DNT-UNUSED] Templar1Notable1"
_UNIMPLEMENTED = re.compile(r"\[(DNT|UNUSED|DNT-UNUSED)[^\]]*\]|^DNT[ _-]", re.I)

# poe2db가 정리하지 않은 위키 마크업 — "[Jewel] Socket", "[Key|표시]" 형태
_MARKUP = re.compile(r"\[([^\]|]+)\|([^\]]+)\]|\[([^\]]+)\]")


def clean_name(raw: str) -> str:
    """위키 마크업 제거 + 공백 정리 (poe2db 원본에 잔재가 섞여 있음)."""
    return _MARKUP.sub(lambda m: m.group(2) or m.group(3) or "", raw).strip()


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
    for nid, node in us["nodes"].items():
        if not isinstance(node, dict) or not node.get("name") or nid == "root":
            continue
        name_en = clean_name(str(node["name"]))  # 마크업·공백 잔재 정리
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
        # 어센던시 시작·주얼 슬롯은 stats가 없는 게 정상 (효과 아닌 구조 노드)
        has_effect = bool(stats) or kind in {"keystone", "jewel", "ascendancy-start"}
        structural = kind in {"jewel", "ascendancy-start"}
        if kind in EXCLUDED_KINDS or unimpl or not (has_effect and (in_pob or structural)):
            excluded.append(f"{nid}:{name_en}")
            continue
        kr_node = kr_nodes.get(nid) or {}
        chunks[kind].append(
            {
                "node_id": nid,
                "kind": kind,
                "name_en": name_en,
                "name_ko": (
                    ko_overrides.get(nid, {}).get("ko")
                    or clean_name(str(kr_node.get("name") or name_en))
                ),
                "stats_en": stats,
                "stats_ko": [str(s) for s in (kr_node.get("stats") or [])],
                "ascendancy": node.get("ascendancyName"),
                "connections": sorted(
                    str(c["id"]) for c in (node.get("connections") or []) if isinstance(c, dict)
                ),
                "in_pob": in_pob,
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, items in chunks.items():
        (out_dir / f"tree_{kind}.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    report = {
        "poe2db_nodes": len(us["nodes"]),
        "pob_named_nodes": len(pob_by_name),
        "included": {k: len(v) for k, v in chunks.items()},
        "included_total": sum(len(v) for v in chunks.values()),
        "excluded": len(excluded),
        "excluded_sample": excluded[:20],
        "name_overrides": len(name_overrides),
        "name_overrides_sample": name_overrides[:20],
    }
    (raw_dir / "tree" / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
