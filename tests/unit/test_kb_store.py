"""P1a Exit: 시드 KB가 4층 검증(envelope·타입·vocab·참조 무결성)을 통과한다."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pok.common.paths import project_root
from pok.kb.store import KBValidationError, load

ROOT = project_root()


def test_seed_kb_loads_and_validates() -> None:
    store = load()
    assert len(store.records) >= 30, "시드는 30개 이상"
    spark = store.get("skill.spark")
    assert spark.name_ko == "스파크"
    assert "lightning" in spark.tags


def test_all_relation_targets_resolve() -> None:
    store = load()
    for r in store.records.values():
        for edge in r.relations:
            assert edge["target"] in store.records


def _copy_knowledge(tmp_path: Path) -> Path:
    dst = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", dst)
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")  # project_root 마커
    return dst


def test_bad_subject_rejected(tmp_path: Path) -> None:
    """vocab에 없는 조건 subject → 로드 실패 (임의 문자열 우회 금지, KD-2)."""
    kdir = _copy_knowledge(tmp_path)
    bad = json.loads((kdir / "game-data/skills/spark.json").read_text(encoding="utf-8"))
    bad["conditions"] = [
        {
            "text": "임의 조건",
            "expr": {"subject": "self.made-up-thing", "op": "==", "value": True},
            "satisfiable_by": [],
            "uptime": "always",
        }
    ]
    (kdir / "game-data/skills/spark.json").write_text(
        json.dumps(bad, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(KBValidationError, match="vocab에 없음"):
        load(tmp_path)


def test_dangling_relation_rejected(tmp_path: Path) -> None:
    """실존하지 않는 relations.target → 로드 실패 (참조 무결성 = 완전성 기준 ④)."""
    kdir = _copy_knowledge(tmp_path)
    bad = json.loads((kdir / "game-data/skills/spark.json").read_text(encoding="utf-8"))
    bad["relations"] = [{"rel": "scales_with", "target": "modifier.does-not-exist"}]
    (kdir / "game-data/skills/spark.json").write_text(
        json.dumps(bad, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(KBValidationError, match="실존하지 않는 id"):
        load(tmp_path)


def test_envelope_violation_rejected(tmp_path: Path) -> None:
    """envelope 위반(필수 필드 누락) → 로드 실패."""
    kdir = _copy_knowledge(tmp_path)
    (kdir / "game-data/skills/broken.json").write_text(
        json.dumps({"id": "skill.broken", "type": "Skill"}), encoding="utf-8"
    )
    with pytest.raises(KBValidationError, match="envelope"):
        load(tmp_path)
