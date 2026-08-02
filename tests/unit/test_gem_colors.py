"""ingest/gem_colors — 보조 젬 색상(요구 속성) 수록, 백로그 B-2."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pok.common.paths import knowledge_dir, project_root
from pok.kb.ingest.gem_colors import apply_gem_colors, color_of
from pok.kb.store import load as store_load

# v6 설계 문서 §7.3 색상 장부 — KB 조회만으로 재현돼야 한다(전사 의존 해소)
_V6_LEDGER = {
    "Execute III": "red",
    "Fire Attunement": "red",
    "Xoph's Pyre": "red",
    "Considered Casting": "blue",
    "Rakiata's Flow": "green",
    "Atziri's Communion": "blue",  # 이름·테마와 달리 지능 요구 = 파랑 (v6 '중요한 정정')
    "Heft": "red",
    "Uul-Netol's Embrace": "red",
    "Armour Break III": "red",
    "Cold Mastery": "blue",
}


def test_요구_속성이_색상을_결정한다() -> None:
    assert color_of({"reqStr": 100}) == ("red", ["reqStr"])
    assert color_of({"reqDex": 100}) == ("green", ["reqDex"])
    assert color_of({"reqInt": 100}) == ("blue", ["reqInt"])
    assert color_of({}) == ("colorless", [])  # 요구 없음 — 분모 포함 방식이 미검증


def test_동률_복합속성은_hybrid() -> None:
    color, reqs = color_of({"reqStr": 50, "reqInt": 50})
    assert color == "hybrid" and set(reqs) == {"reqStr", "reqInt"}


def test_v6_색상_장부가_KB_조회로_재현된다() -> None:
    kb = store_load(knowledge_dir().parent)
    by_en = {r.name_en: r for r in kb.records.values() if r.type == "Support"}
    for name, expected in _V6_LEDGER.items():
        rec = by_en.get(name)
        assert rec is not None, f"{name}: KB Support 레코드 없음"
        assert rec.raw["data"].get("color") == expected, name


def test_apply_멱등_기존_필드_보존(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    gems = knowledge / "game-data" / "gems"
    gems.mkdir(parents=True)
    record = {
        "id": "support.testlink",
        "type": "Support",
        "name": {"ko": "테스트", "en": "Testlink"},
        "tags": [],
        "data": {"applies_to_tags": ["spell"]},
        "verification": "GAME_DATA",
        "sources": [{"src": "pob", "ref": "x", "patch": "t"}],
    }
    (gems / "supports.ndjson").write_text(json.dumps(record) + "\n", encoding="utf-8")
    raw = root / "raw"
    (raw / "pob").mkdir(parents=True)
    (raw / "pob" / "gems.json").write_text(
        json.dumps({"Metadata/X": {"name": "Testlink", "reqStr": 100}}), encoding="utf-8"
    )
    for _ in range(2):
        stats = apply_gem_colors(raw, knowledge)
        assert stats["updated"] == 1 and stats["by_color"] == {"red": 1}
        rec = json.loads((gems / "supports.ndjson").read_text(encoding="utf-8"))
        assert rec["data"]["color"] == "red"
        assert rec["data"]["color_requirements"] == ["reqStr"]
        assert rec["data"]["applies_to_tags"] == ["spell"]  # 기존 필드 보존
