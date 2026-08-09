"""P1b ② 보강: 성유(액체 감정) 부여 정보 파싱·반영 (픽스처, 네트워크 없음)."""

from __future__ import annotations

import json
from pathlib import Path

from pok.kb.ingest.liquid_emotions import apply_to_kb, parse_page


def _entry(name: str, emotions: list[str], effect: str) -> str:
    """실제 poe2db 구조: 각 조각이 별도 인라인 요소 (get_text가 줄 단위로 나눔)."""
    ems = " , ".join(f"<a>{e}</a>" for e in emotions)
    return f"<div><span>{name}</span><span>Liquid Emotions</span>:{ems}<span>{effect}</span></div>"


US_HTML = f"""
<html><body>
<div class="card"><h5 class="card-header">Liquid Emotions Only Passives /1</h5>
 <div class="card-body"><div class="row">
  {_entry("Desert's Scorn", ["Contempt", "Fear", "Suffering"], "25% increased Fire Damage")}
 </div></div></div>
<div class="card"><h5 class="card-header">Liquid Emotions Passives /2</h5>
 <div class="card-body"><div class="row">
  {_entry("Insulated Treads", ["Ire", "Ire", "Ire"], "25% increased Armour")}
  {_entry("Ghost Node", ["Ire", "Fear", "Fear"], "10% increased Nothing")}
 </div></div></div>
</body></html>
"""

KR_HTML = (
    US_HTML.replace("Liquid Emotions Only Passives", "액체 감정 Only Passives")
    .replace("Liquid Emotions Passives", "액체 감정 Passives")
    .replace("Liquid Emotions</span>", "액체 감정</span>")
    .replace("Desert's Scorn", "사막의 경멸")
    .replace("Insulated Treads", "절연 발 보호대")
    .replace("Ghost Node", "유령 노드")
    .replace("Contempt", "경멸")
    .replace("Fear", "두려움")
    .replace("Suffering", "고통")
    .replace("Ire", "진노")
)


def _write(raw: Path) -> None:
    d = raw / "liquid-emotions"
    d.mkdir(parents=True)
    (d / "us.html").write_text(US_HTML, encoding="utf-8")
    (d / "kr.html").write_text(KR_HTML, encoding="utf-8")


def test_parse_page_both_cards() -> None:
    parsed = parse_page(US_HTML)
    assert set(parsed) == {"Desert's Scorn", "Insulated Treads", "Ghost Node"}
    assert parsed["Desert's Scorn"] == {
        "emotions": ["Contempt", "Fear", "Suffering"],
        "acquisition": "anoint-only",
    }
    assert parsed["Insulated Treads"]["acquisition"] == "anointable", "일반 노드는 별도 분류"


def test_parse_page_korean() -> None:
    parsed = parse_page(KR_HTML, kr=True)
    assert parsed["사막의 경멸"]["emotions"] == ["경멸", "두려움", "고통"]


def _kb(tmp_path: Path) -> Path:
    knowledge = tmp_path / "knowledge"
    tree = knowledge / "game-data" / "tree"
    tree.mkdir(parents=True)
    recs = [
        {
            "id": "passive.deserts-scorn-1",
            "type": "Passive",
            "name": {"ko": "사막의 경멸", "en": "Desert's Scorn"},
            "tags": [],
            "data": {"kind": "notable", "node_id": "1", "stats": [], "connections": []},
            "verification": "GAME_DATA",
            "sources": [{"src": "poe2db", "ref": "x"}],
        },
        {
            "id": "passive.insulated-treads-2",
            "type": "Passive",
            "name": {"ko": "절연 발 보호대", "en": "Insulated Treads"},
            "tags": [],
            "data": {"kind": "small", "node_id": "2", "stats": [], "connections": []},
            "verification": "GAME_DATA",
            "sources": [{"src": "poe2db", "ref": "x"}],
        },
    ]
    (tree / "nodes.ndjson").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8"
    )
    return knowledge


def test_apply_to_kb_adds_acquisition(tmp_path: Path) -> None:
    _write(tmp_path)
    knowledge = _kb(tmp_path)
    summary = apply_to_kb(tmp_path, knowledge)

    assert summary["kb_records_updated"] == 2
    assert summary["unmatched_names"] == ["Ghost Node"], "트리에 없는 항목은 리포트에 남긴다"

    recs = [
        json.loads(line)
        for line in (knowledge / "game-data/tree/nodes.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    scorn = next(r for r in recs if r["id"] == "passive.deserts-scorn-1")
    assert scorn["data"]["acquisition"] == "anoint-only"
    assert scorn["data"]["liquid_emotions"] == ["Contempt", "Fear", "Suffering"]
    # 한국어 감정명은 KB의 ko/en 노드명 쌍을 다리 삼아 매핑된다 (순서 대응 아님)
    assert scorn["data"]["liquid_emotions_ko"] == ["경멸", "두려움", "고통"]


def test_apply_is_idempotent(tmp_path: Path) -> None:
    _write(tmp_path)
    knowledge = _kb(tmp_path)
    first = apply_to_kb(tmp_path, knowledge)
    second = apply_to_kb(tmp_path, knowledge)
    assert first["kb_records_updated"] == second["kb_records_updated"]


def test_acquisition_names_say_what_they_mean() -> None:
    """`liquid-emotion`은 **정반대로 읽혔다** — 개명 (사용자 판정 2026-08-09, #2).

    "성유로만 얻는 무작위 노드 = 트리에서 못 찍음"으로 읽어 틀린 설계 판단을 했다.
    실제 뜻은 *"성유로 **부여도** 가능"*이고, 트리에서도 찍을 수 있는 노드다.
    이름이 비슷한 `liquid-emotion-only`(성유 전용·트리 할당 불가)가 따로 있어
    의미가 반대인 줄 몰랐다 — 이제 `anointable` / `anoint-only`로 갈린다.
    """
    from pok.common.paths import knowledge_dir
    from pok.kb.store import load

    seen: dict[str, int] = {}
    for rec in load(knowledge_dir()).records.values():
        value = (rec.raw.get("data") or {}).get("acquisition")
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str):
                seen[item] = seen.get(item, 0) + 1
    assert "liquid-emotion" not in seen and "liquid-emotion-only" not in seen, (
        f"옛 이름이 남아 있다: {[k for k in seen if k.startswith('liquid')]}"
    )
    assert seen.get("anointable", 0) > 800, seen.get("anointable")
    assert seen.get("anoint-only", 0) > 0, "성유 전용 구분이 사라지면 개명이 정보를 지운 것"
