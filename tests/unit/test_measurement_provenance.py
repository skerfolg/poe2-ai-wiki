"""Disk observations detect content changes without certifying loaded execution."""

import json

from pok.engine.measurement_provenance import compare_observations, observe_sources


def fixture_root(root):
    for name in ("src/pok", "scripts", "knowledge/ingest"):
        (root / name).mkdir(parents=True)
    (root / "src/pok/example.py").write_text("value = 1", encoding="utf-8")
    (root / "scripts/driver.lua").write_text("return 1", encoding="utf-8")
    (root / "knowledge/ingest/manifest.json").write_text(
        json.dumps({"pob_commit": "abc"}), encoding="utf-8"
    )


def test_content_change_with_same_size_and_timestamp_is_detected(tmp_path):
    import os

    fixture_root(tmp_path)
    before = observe_sources(root=tmp_path)
    file = tmp_path / "src/pok/example.py"
    stat = file.stat()
    file.write_text("value = 2", encoding="utf-8")
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    after = observe_sources(root=tmp_path)
    report = compare_observations(before, after)
    assert report["changed"] == ["python_source"]
    assert report["status"] == "changed"
    assert report["execution_identity"] == "not_verified_disk_observation_only"


def test_unavailable_is_not_stable_or_verified(tmp_path):
    before = observe_sources(root=tmp_path)
    report = compare_observations(before, observe_sources(root=tmp_path))
    assert report["status"] == "incomplete"
    assert set(report["unavailable"]) == {"python_source", "scripts", "knowledge", "pob_pin"}
    assert compare_observations({}, {})["status"] == "incomplete"


def test_stable_observation_and_changed_pin(tmp_path):
    fixture_root(tmp_path)
    before = observe_sources(root=tmp_path)
    assert compare_observations(before, observe_sources(root=tmp_path))["status"] == (
        "stable_observation"
    )
    (tmp_path / "knowledge/ingest/manifest.json").write_text(
        json.dumps({"pob_commit": "def"}), encoding="utf-8"
    )
    report = compare_observations(before, observe_sources(root=tmp_path))
    assert report["changed"] == ["knowledge", "pob_pin"]
