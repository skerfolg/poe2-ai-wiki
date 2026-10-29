"""동시 self-healing은 각자 만든 DB만 소유하고 완성본만 공개한다."""

from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier, Event

import pytest

import pok.index.build as build_mod
from pok.kb.store import Record, Store


def _store(name: str) -> Store:
    return Store(
        records={
            name: Record(
                id=name,
                type="Skill",
                path=Path("unused.json"),
                raw={"name": {"ko": name, "en": name}, "verification": "test"},
            )
        },
        subjects={},
    )


@pytest.fixture()
def index_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(build_mod, "load", lambda root: _store("old"))
    monkeypatch.setattr(build_mod, "load_insights", lambda root: [])
    monkeypatch.setattr(build_mod, "source_fingerprint", lambda root: "fixture")
    db = tmp_path / "index.sqlite"
    build_mod.build_index(tmp_path, db)
    monkeypatch.setattr(build_mod, "load", lambda root: _store("new"))
    return db


def _ids(db: Path) -> list[str]:
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        return [row[0] for row in con.execute("SELECT id FROM records")]


def test_simultaneous_builders_publish_complete_databases(
    index_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실제 SQLite 핸들 두 개를 동시에 열어 고정 임시 파일 충돌을 재현한다."""
    db = index_env
    connect = sqlite3.connect
    opened = Barrier(3)
    proceed = Event()
    paths: list[Path] = []

    def connect_and_wait(path: Path) -> sqlite3.Connection:
        con = connect(path)
        if Path(path) != db:
            paths.append(Path(path))
            try:
                opened.wait(timeout=5)
                assert proceed.wait(timeout=5)
            except BaseException:
                con.close()
                raise
        return con

    monkeypatch.setattr(build_mod.sqlite3, "connect", connect_and_wait)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(build_mod.build_index, db.parent, db) for _ in range(2)]
        try:
            opened.wait(timeout=5)
            assert _ids(db) == ["old"], "빌드가 끝나기 전에는 기존 완성본만 공개한다"
        finally:
            proceed.set()
        assert [f.result(timeout=5) for f in futures] == [db, db]
    assert len(set(paths)) == 2, "다른 빌더의 임시 DB를 지우거나 공유하지 않는다"
    assert _ids(db) == ["new"]
    assert list(db.parent.iterdir()) == [db], "각 빌더가 자기 임시 파일만 정리한다"


def test_failed_build_preserves_published_index_and_cleans_own_temp(
    index_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = index_env
    foreign_temp = db.with_suffix(".building")
    foreign_temp.write_text("another builder owns this", encoding="utf-8")

    def fail_after_records(root: Path | None) -> list[object]:
        raise RuntimeError("injected population failure")

    monkeypatch.setattr(build_mod, "load_insights", fail_after_records)
    with pytest.raises(RuntimeError, match="injected population failure"):
        build_mod.build_index(db.parent, db)
    assert _ids(db) == ["old"]
    assert foreign_temp.read_text(encoding="utf-8") == "another builder owns this"
    assert set(db.parent.iterdir()) == {db, foreign_temp}


def test_replacement_waits_for_actual_sqlite_reader_on_windows(
    index_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows 실제 파일 잠금과 POSIX 기존 독자 스냅샷을 둘 다 확인한다."""
    db = index_env
    reader = sqlite3.connect(db)
    waits: list[float] = []
    assert reader.execute("SELECT id FROM records").fetchall() == [("old",)]

    def release_reader(delay: float) -> None:
        waits.append(delay)
        assert _ids(db) == ["old"], "재시도 중에도 기존 완성본은 남아 있어야 한다"
        reader.close()

    monkeypatch.setattr(build_mod, "sleep", release_reader)
    try:
        build_mod.build_index(db.parent, db)
        if os.name == "nt":
            assert waits, "Windows에서 실제 열린 SQLite 파일 교체를 재시도해야 한다"
        else:
            assert not waits
            assert reader.execute("SELECT id FROM records").fetchall() == [("old",)]
    finally:
        reader.close()
    assert _ids(db) == ["new"]
    assert list(db.parent.iterdir()) == [db]


@pytest.mark.parametrize("winerror", [None, 5, 32, 33])
def test_failed_publication_preserves_index_and_cleans_own_temp(
    index_env: Path, monkeypatch: pytest.MonkeyPatch, winerror: int | None
) -> None:
    """Windows 점유 한도 초과나 영구 권한 오류를 성공으로 숨기지 않는다."""
    db = index_env
    error = PermissionError("injected publication failure")
    if winerror is not None:
        error.winerror = winerror

    def reject_replace(source: Path, target: Path) -> Path:
        raise error

    times = iter([0.0, 6.0])
    monkeypatch.setattr(Path, "replace", reject_replace)
    monkeypatch.setattr(build_mod, "monotonic", lambda: next(times))
    with pytest.raises(PermissionError, match="injected publication failure"):
        build_mod.build_index(db.parent, db)
    assert _ids(db) == ["old"]
    assert list(db.parent.iterdir()) == [db]


def test_cli_rebuild_does_not_delete_published_index(
    index_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pok.index.__main__ as cli

    db = index_env
    monkeypatch.setattr(cli, "force_utf8_stdio", lambda: None)

    def reject_build() -> Path:
        assert _ids(db) == ["old"]
        raise RuntimeError("injected validation failure")

    # 구 CLI의 선삭제 경로도 임시 DB를 가리키게 해 정본 파생 파일을 건드리지 않는다.
    monkeypatch.setattr(cli, "index_db_path", lambda: db, raising=False)
    monkeypatch.setattr(cli, "build_index", reject_build)
    with pytest.raises(RuntimeError, match="injected validation failure"):
        cli.main(["rebuild"])
    assert _ids(db) == ["old"]
