"""P1a Exit: ensure_index 3트리거 + search/get_entry/related 왕복."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import pok.index.build as build_mod
from pok.common.paths import project_root
from pok.index.build import build_index
from pok.index.search import ensure_index, get_entry, related, search
from pok.kb.store import KBValidationError

ROOT = project_root()


@pytest.fixture()
def kb_env(tmp_path: Path) -> tuple[Path, Path]:
    """정본 사본 + 임시 인덱스 경로 (정본·var를 절대 건드리지 않음)."""
    shutil.copytree(ROOT / "knowledge", tmp_path / "knowledge")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    return tmp_path, tmp_path / "index.sqlite"


def test_trigger1_missing_builds(kb_env: tuple[Path, Path]) -> None:
    root, db = kb_env
    assert not db.exists()
    ensure_index(root, db)
    assert db.exists(), "① 없음 → 자동 빌드 (PC 이동 시나리오)"


def test_trigger2_kb_edit_rebuilds(kb_env: tuple[Path, Path]) -> None:
    root, db = kb_env
    ensure_index(root, db)
    before = (
        sqlite3.connect(db)
        .execute("SELECT value FROM meta WHERE key='source_fingerprint'")
        .fetchone()[0]
    )

    spark = root / "knowledge/game-data/skills/spark.json"
    raw = json.loads(spark.read_text(encoding="utf-8"))
    raw["notes"] = "패치로 상향됨"
    spark.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    ensure_index(root, db)
    after = (
        sqlite3.connect(db)
        .execute("SELECT value FROM meta WHERE key='source_fingerprint'")
        .fetchone()[0]
    )
    assert before != after, "② KB 수정 → 자동 재빌드"


def test_trigger3_schema_version_rebuilds(
    kb_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, db = kb_env
    ensure_index(root, db)
    monkeypatch.setattr(build_mod, "SCHEMA_VERSION", build_mod.SCHEMA_VERSION + 1)
    ensure_index(root, db)
    ver = (
        sqlite3.connect(db)
        .execute("SELECT value FROM meta WHERE key='schema_version'")
        .fetchone()[0]
    )
    assert ver == str(build_mod.SCHEMA_VERSION), "③ 버전업 → 자동 재빌드"


def test_search_roundtrip(kb_env: tuple[Path, Path]) -> None:
    root, db = kb_env
    hits = search("spark", root=root, db_path=db)
    assert any(h.id == "skill.spark" for h in hits)

    hits_ko = search("전기불꽃", root=root, db_path=db)
    assert any(h.id == "skill.spark" for h in hits_ko), "한국어 이름 검색 (공식 용어)"

    hits_tag = search(tags=["lightning"], type_="Skill", limit=200, root=root, db_path=db)
    assert {h.id for h in hits_tag} >= {"skill.spark", "skill.lightning-arrow"}


def test_get_entry_fields(kb_env: tuple[Path, Path]) -> None:
    root, db = kb_env
    full = get_entry("skill.gas-arrow", root=root, db_path=db)
    # fire-infusion은 0.5 개명(Fire Attunement)으로 삭제·교체됐다 (#63 잔재 정리)
    assert full["conditions"][1]["satisfiable_by"] == ["skill.fireball", "support.fire-attunement"]

    partial = get_entry("skill.gas-arrow", fields=["name"], root=root, db_path=db)
    assert set(partial) == {"id", "type", "name"}, "D14: 선별 상세"


def test_reverse_relations(kb_env: tuple[Path, Path]) -> None:
    """정본은 정방향만 저장 — 역방향은 인덱스가 제공 (KB_DATA_MODEL §4)."""
    root, db = kb_env
    edges = related("resource.mana", root=root, db_path=db)
    reverse = [e for e in edges if e["direction"] == "reverse"]
    assert any(e["src"] == "skill.spark" and e["rel"] == "consumes" for e in reverse)


def test_atomic_build_no_partial(kb_env: tuple[Path, Path]) -> None:
    """검증 실패 시 기존 인덱스가 파괴되지 않는다 (원자적 교체)."""
    root, db = kb_env
    build_index(root, db)
    broken = root / "knowledge/game-data/skills/broken.json"
    broken.write_text(json.dumps({"id": "skill.broken", "type": "Skill"}), encoding="utf-8")
    with pytest.raises(KBValidationError):
        build_index(root, db)
    assert db.exists()
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM records").fetchone()[0] >= 30
