"""P1a Exit: ensure_index 3트리거 + search/get_entry/related 왕복."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

import pok.index.build as build_mod
from pok.common.paths import knowledge_dir, project_root
from pok.index.build import build_index
from pok.index.search import ensure_index, get_entry, related, search
from pok.kb.store import KBValidationError, _fingerprint

ROOT = project_root()


@pytest.fixture()
def kb_env(tmp_path: Path) -> tuple[Path, Path]:
    """정본 **사본** + 임시 인덱스 경로 — **정본을 고치는 시험만** 쓴다.

    사본은 695파일·81MB라 한 번에 ~10초다. 안 고치는 시험까지 이걸 쓰면 그 10초가
    시험 수만큼 곱해진다 — 실측 2026-08-26: 이 파일 7건이 CI에서 8분을 먹었다.
    고치지 않는 시험은 `kb_readonly`를 쓸 것.
    """
    shutil.copytree(ROOT / "knowledge", tmp_path / "knowledge")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    return tmp_path, tmp_path / "index.sqlite"


@pytest.fixture()
def kb_readonly(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """정본 **그대로** + 임시 인덱스 경로. 사본을 뜨지 않아 빠르고, 로드 캐시도 탄다.

    ⛔ 정본을 고치는 시험은 이걸 쓰면 안 된다 — git 추적 파일이 망가진다. 말로만
    금지하면 지켜지지 않으므로(철칙 5) **지문으로 확인한다**: 끝날 때 정본 지문이
    달라져 있으면 그 자리에서 실패한다. 인덱스는 `tmp_path`에 쓰므로 `var/`도 안 탄다.
    """
    before = _fingerprint(knowledge_dir())
    yield ROOT, tmp_path / "index.sqlite"
    assert _fingerprint(knowledge_dir()) == before, (
        "이 시험이 정본을 고쳤다 — `kb_env`(사본)로 바꿀 것"
    )


def test_trigger1_missing_builds(kb_readonly: tuple[Path, Path]) -> None:
    root, db = kb_readonly
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
    kb_readonly: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, db = kb_readonly
    ensure_index(root, db)
    monkeypatch.setattr(build_mod, "SCHEMA_VERSION", build_mod.SCHEMA_VERSION + 1)
    ensure_index(root, db)
    ver = (
        sqlite3.connect(db)
        .execute("SELECT value FROM meta WHERE key='schema_version'")
        .fetchone()[0]
    )
    assert ver == str(build_mod.SCHEMA_VERSION), "③ 버전업 → 자동 재빌드"


def test_search_roundtrip(kb_readonly: tuple[Path, Path]) -> None:
    root, db = kb_readonly
    hits = search("spark", root=root, db_path=db)
    assert any(h.id == "skill.spark" for h in hits)

    hits_ko = search("전기불꽃", root=root, db_path=db)
    assert any(h.id == "skill.spark" for h in hits_ko), "한국어 이름 검색 (공식 용어)"

    hits_tag = search(tags=["lightning"], type_="Skill", limit=200, root=root, db_path=db)
    assert {h.id for h in hits_tag} >= {"skill.spark", "skill.lightning-arrow"}


def test_get_entry_fields(kb_readonly: tuple[Path, Path]) -> None:
    root, db = kb_readonly
    full = get_entry("skill.gas-arrow", root=root, db_path=db)
    # fire-infusion은 0.5 개명(Fire Attunement)으로 삭제·교체됐다 (#63 잔재 정리)
    assert full["conditions"][1]["satisfiable_by"] == ["skill.fireball", "support.fire-attunement"]

    partial = get_entry("skill.gas-arrow", fields=["name"], root=root, db_path=db)
    assert set(partial) == {"id", "type", "name"}, "D14: 선별 상세"


def test_reverse_relations(kb_readonly: tuple[Path, Path]) -> None:
    """정본은 정방향만 저장 — 역방향은 인덱스가 제공 (KB_DATA_MODEL §4)."""
    root, db = kb_readonly
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
