"""PoB 원본 XML/아이템 원문을 UI에 노출하는 얇은 작업 경계.

이 모듈은 UI가 필요한 "있는 그대로의 PoB" 작업만 다룬다. 계산은 supplied XML을
복원 스펙으로 바꾸지 않고 `runner.run_xml`에 그대로 보낸다. 아이템 원문도 PoB의
`BuildRaw`/유니크 원문 헬퍼를 통해 얻고, 실패는 요청 단위 오류로 돌려준다.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pok.pob.runner import PobResult, run_xml

MAX_XML_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class XmlCompute:
    """직접 XML 계산 결과와 UI가 표시할 진단."""

    result: PobResult
    xml_sha256: str
    requested_nodes: tuple[int, ...]
    diagnostics: dict[str, Any]


def compute_xml(xml_text: str) -> XmlCompute:
    """supplied XML을 그대로 PoB에 보내 계산한다.

    requested_nodes는 pruned_nodes 판정을 위해 XML에서 읽는다. XML을 build_spec으로
    복원하지 않으므로 비활성 세트·알 수 없는 필드·원문은 계산 입력에서 손실되지 않는다.
    """
    requested_nodes, active_spec = active_spec_nodes(xml_text)
    result = run_xml(xml_text, requested_nodes=requested_nodes)
    return XmlCompute(
        result=result,
        xml_sha256=hashlib.sha256(xml_text.encode("utf-8")).hexdigest(),
        requested_nodes=requested_nodes,
        diagnostics={
            "calculation_path": "direct_xml",
            "xml_preserved": True,
            "active_spec": active_spec,
        },
    )


def active_spec_nodes(xml_text: str) -> tuple[tuple[int, ...], dict[str, Any]]:
    """활성 Tree/Spec의 node id를 읽는다. 실패는 계산 전에 명시 오류로 올린다."""
    _reject_unsafe_xml(xml_text)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"PoB XML 파싱 실패: {exc}") from exc
    if root.tag != "PathOfBuilding2":
        raise ValueError(f"PoB XML 루트가 PathOfBuilding2가 아니다: {root.tag}")
    if root.find("Build") is None:
        raise ValueError("PoB XML에 <Build>가 없다")
    tree = root.find("Tree")
    if tree is None:
        raise ValueError("PoB XML에 <Tree>가 없다")
    specs = tree.findall("Spec")
    if not specs:
        raise ValueError("PoB XML에 <Tree><Spec>이 없다")

    active = tree.get("activeSpec") or tree.get("activeTree") or "1"
    spec = next(
        (
            candidate
            for candidate in specs
            if active in {candidate.get("id"), candidate.get("treeId"), candidate.get("title")}
        ),
        None,
    )
    if spec is None and active.isdigit():
        index = int(active)
        if 1 <= index <= len(specs):
            spec = specs[index - 1]
    if spec is None:
        raise ValueError(f"activeSpec {active!r}에 해당하는 <Spec>이 없다")
    nodes = tuple(
        int(raw)
        for raw in (spec.get("nodes") or "").split(",")
        if raw.strip().isdigit()
    )
    return nodes, {
        "requested": active,
        "matched": spec.get("id") or spec.get("treeId") or spec.get("title") or "first",
        "tree_version": spec.get("treeVersion") or "",
        "node_count": len(nodes),
    }


def _reject_unsafe_xml(xml_text: str) -> None:
    if len(xml_text.encode("utf-8")) > MAX_XML_BYTES:
        raise ValueError(f"PoB XML이 너무 크다: {len(xml_text.encode('utf-8'))} bytes")
    head = xml_text.lower()
    if "<!doctype" in head or "<!entity" in head:
        raise ValueError("PoB XML에 DTD/entity 선언은 허용하지 않는다")


def render_pob_item(request: dict[str, Any]) -> dict[str, Any]:
    """UI 아이템 요청 하나를 PoB 계산용 원문으로 렌더한다.

    성공이면 `ok=True`와 `text`를 돌려준다. 실패면 `ok=False`와 `reason`/`error`가 있다.
    """
    kind = str(request.get("kind") or "").strip().lower()
    item_id = _catalog_name(str(request.get("id") or "").strip(), kind)
    if not item_id:
        return _item_error(request, "id가 비어 있다")
    if kind not in {"base", "unique", "rare"}:
        return _item_error(request, "kind는 base|unique|rare 중 하나여야 한다")

    try:
        if kind == "unique":
            return _render_unique_request(request, item_id)
        if kind == "base":
            return _build_item_text(request, _base_spec(item_id, request))
        return _build_item_text(request, _rare_spec(item_id, request))
    except Exception as exc:
        return _item_error(request, f"{type(exc).__name__}: {exc}")


def _render_unique_request(request: dict[str, Any], item_id: str) -> dict[str, Any]:
    from pok.pob.uniques import render_unique
    from pok.pob.uniques import variants as variant_names

    selected = [str(v).strip() for v in request.get("variants") or [] if str(v).strip()]
    if len(selected) > 1:
        return _item_error(request, "현재 unique 렌더링은 Variant 하나만 명시할 수 있다")
    if request.get("mods") or request.get("rolls"):
        return _item_error(request, "유니크 접사 수치 편집은 원문 편집을 사용해야 한다")
    variant = selected[0] if selected else None
    if variant and variant.isdecimal():
        names = variant_names(item_id)
        index = int(variant) - 1
        if index < 0 or index >= len(names):
            return _item_error(request, f"알 수 없는 유니크 변형 ID: {variant}")
        variant = names[index]
    raw = render_unique(item_id, variant)
    if raw is None:
        return _item_error(request, f"PoB 유니크 원문을 찾지 못했다: {item_id}")
    if request.get("quality") is not None:
        quality = int(request["quality"])
        if not 0 <= quality <= 100:
            return _item_error(request, "퀄리티는 0~100이어야 한다")
        lines = [line for line in raw.splitlines() if not line.startswith("Quality:")]
        lines.insert(2, f"Quality: {quality}")
        raw = "\n".join(lines)
    if not raw.lstrip().lower().startswith("rarity:"):
        raw = "Rarity: UNIQUE\n" + raw
    return _item_ok(request, raw)


def _catalog_name(item_id: str, kind: str) -> str:
    """ui_export catalog id를 PoB 원문 이름으로 푼다."""
    if kind == "unique" and item_id.startswith("unique:"):
        parts = item_id.split(":")
        if len(parts) >= 3:
            return ":".join(parts[1:-1]).strip()
    if kind == "base" and item_id.startswith("base:"):
        return item_id.split(":", 1)[1].strip()
    return item_id


def _base_spec(item_id: str, request: dict[str, Any]) -> str:
    lines = ["Rarity: NORMAL", "New Item", item_id]
    quality = request.get("quality")
    if quality is not None:
        lines.append(f"Quality: {int(quality)}")
    return "\n".join(lines)


def _rare_spec(item_id: str, request: dict[str, Any]) -> str:
    mods = request.get("mods") or []
    if not isinstance(mods, list):
        raise ValueError("mods는 문자열 배열이어야 한다")
    rolls = request.get("rolls") or {}
    if rolls and not isinstance(rolls, dict):
        raise ValueError("rolls는 mod id -> roll index 객체여야 한다")
    lines = ["Rarity: RARE", "New Item", item_id, "Crafted: true"]
    quality = request.get("quality")
    if quality is not None:
        lines.append(f"Quality: {int(quality)}")
    for raw in mods:
        line = _mod_line(str(raw).strip(), rolls)
        if not line:
            continue
        lines.append(line)
    return "\n".join(lines)


_MOD_DECL = re.compile(r"^(Prefix|Suffix):\s*(.*)$", re.I)
_RANGE = re.compile(r"\{range:[^}]+\}")


def _mod_line(line: str, rolls: dict[str, Any]) -> str:
    """희귀 접사 선언 또는 raw mod id를 PoB Craft 명세로 정규화한다."""
    match = _MOD_DECL.match(line)
    if match is None:
        kind, rest = _catalog_mod_declaration(line)
    else:
        kind, rest = match.group(1), match.group(2).strip()
    if not rest:
        raise ValueError(f"빈 접사 선언: {line!r}")
    if _RANGE.search(rest):
        return f"{kind}: {rest}"
    roll = rolls.get(rest)
    if roll is None:
        return f"{kind}: {rest}"
    value = float(roll)
    if not 0 <= value <= 1:
        raise ValueError(f"rolls[{rest!r}]={roll!r}은 0..1 범위여야 한다")
    rendered = str(int(value)) if value in (0, 1) else str(value).rstrip("0").rstrip(".")
    return f"{kind}: {{range:{rendered}}}{rest}"


def _catalog_mod_declaration(mod_id: str) -> tuple[str, str]:
    entry = _catalog_mod_types().get(mod_id)
    if entry is None:
        raise ValueError(f"알 수 없는 PoB mod id: {mod_id!r}")
    kind = entry.lower()
    if kind == "prefix":
        return "Prefix", mod_id
    if kind == "suffix":
        return "Suffix", mod_id
    raise ValueError(f"PoB mod {mod_id!r}는 희귀 접두/접미가 아니다: {entry!r}")


@lru_cache(maxsize=1)
def _catalog_mod_types() -> dict[str, str]:
    from pok.pob.ui_export import load_catalog

    out: dict[str, str] = {}
    for entry in load_catalog().get("entries", []):
        if not isinstance(entry, dict) or entry.get("type") != "mod":
            continue
        raw_value = entry.get("raw")
        raw: dict[Any, Any] = raw_value if isinstance(raw_value, dict) else {}
        kind = raw.get("type") or entry.get("category")
        if kind:
            out[str(entry.get("id"))] = str(kind)
    return out


def _build_item_text(request: dict[str, Any], spec_text: str) -> dict[str, Any]:
    from pok.pob.roundtrip import build_items

    built = build_items({"ui": spec_text}).get("ui", "")
    if not built:
        return _item_error(request, "PoB가 아이템 원문을 생성하지 못했다", spec_text=spec_text)
    return _item_ok(request, built, spec_text=spec_text)


def _item_ok(request: dict[str, Any], text: str, *, spec_text: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": True,
        "kind": request.get("kind"),
        "id": request.get("id"),
        "text": text,
    }
    if spec_text is not None:
        out["spec_text"] = spec_text
    return out


def _item_error(
    request: dict[str, Any], error: str, *, spec_text: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "kind": request.get("kind"),
        "id": request.get("id"),
        "reason": error,
        "error": error,
    }
    if spec_text is not None:
        out["spec_text"] = spec_text
    return out
