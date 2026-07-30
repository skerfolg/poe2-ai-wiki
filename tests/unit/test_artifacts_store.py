"""artifacts/store — build-id 채번·기록·중복 탐지 (임시 루트에서 격리)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pok.artifacts.store import find_by_hash, new_build_id, record_build, slugify


def _fake_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    return tmp_path


def test_슬러그_정규화() -> None:
    assert slugify("Spark Stormweaver!") == "spark-stormweaver"
    assert slugify("스파크 폭풍위버") == "스파크-폭풍위버"
    assert slugify("///") == "build"


def test_build_id_채번과_충돌_회피(tmp_path: Path) -> None:
    root = _fake_root(tmp_path)
    when = datetime(2026, 7, 30, tzinfo=UTC)
    first = new_build_id("spark", root=root, now=when)
    assert first == "20260730-spark"
    record_build(first, {"a.txt": "x"}, {}, root=root)
    assert new_build_id("spark", root=root, now=when) == "20260730-spark-2"


def test_기록과_해시_중복_탐지(tmp_path: Path) -> None:
    root = _fake_root(tmp_path)
    out = record_build("20260730-a", {"build.xml": "<x/>"}, {"level": 90}, root=root)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["level"] == 90
    assert (out / "build.xml").read_text(encoding="utf-8") == "<x/>"
    record_build("20260730-b", {"build.xml": "<x/>"}, {}, root=root)
    assert find_by_hash(manifest["content_hash"], root=root) == ["20260730-a", "20260730-b"]
