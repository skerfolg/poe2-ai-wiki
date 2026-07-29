"""P1b ②: 패시브 트리 분류·판정 + 청크 merge + 그래프 무결성 (픽스처)."""

from __future__ import annotations

import json
from pathlib import Path

from pok.kb.ingest.tree import node_kind, process_tree
from pok.kb.ingest.tree_merge import merge_tree


def test_node_kind_precedence() -> None:
    # mastery는 분류는 하되 KB 수록에서 제외된다 (EXCLUDED_KINDS)
    assert node_kind({"isMastery": True, "isNotable": True}) == "mastery"
    assert node_kind({"isAscendancyStart": True}) == "ascendancy-start"
    assert node_kind({"isKeystone": True}) == "keystone"
    assert node_kind({"isNotable": True}) == "notable"
    assert node_kind({"isJewelSocket": True}) == "jewel"
    assert node_kind({}) == "small"


def _write_tree_fixtures(raw: Path) -> None:
    (raw / "tree").mkdir(parents=True)
    us_nodes = {
        "root": {"out": ["1"]},
        "1": {
            "name": "Chaos Inoculation",
            "isKeystone": True,
            "stats": ["Maximum Life becomes 1"],
            "connections": [],
        },  # 단방향 저장 — 자기 connections는 비어도 고립 아님
        "2": {
            "name": "Chaos Damage",
            "stats": ["10% increased Chaos Damage"],
            "connections": [{"id": "1", "orbit": 3}],
        },
        "3": {
            "name": "[DNT-UNUSED] Templar1Notable1",
            "isNotable": True,
            "stats": [],
            "connections": [],
        },  # 명시적 미구현
        "4": {
            "name": "Ghost Notable",
            "isNotable": True,
            "stats": ["Something"],
            "connections": [],
        },  # PoB 부재 → 제외
        "5": {
            "name": "Oracle",
            "isAscendancyStart": True,
            "stats": [],
            "ascendancyName": "Druid1",
            "connections": [],
        },  # 구조 노드 — stats 없어도 수록
    }
    kr_nodes = {
        "1": {"name": "카오스 면역", "stats": ["최대 생명력이 1이 됨"]},
        "2": {"name": "카오스 피해", "stats": ["카오스 피해 10% 증가"]},
        "5": {"name": "오라클", "stats": []},
    }
    (raw / "tree/poe2db_us.json").write_text(json.dumps({"nodes": us_nodes}), encoding="utf-8")
    (raw / "tree/poe2db_kr.json").write_text(json.dumps({"nodes": kr_nodes}), encoding="utf-8")
    (raw / "tree/pob_tree.json").write_text(
        json.dumps(
            {
                "nodes": {
                    "1": {"name": "Chaos Inoculation"},
                    "2": {"name": "Chaos Damage"},
                    "5": {"name": "Oracle"},
                }
            }
        ),
        encoding="utf-8",
    )


def test_mastery_excluded_from_kb(tmp_path: Path) -> None:
    """마스터리는 트리 구역 라벨/배경 그래픽 — KB 수록 금지 (사람 판정 2026-07-29)."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    us = json.loads((raw / "tree/poe2db_us.json").read_text(encoding="utf-8"))
    us["nodes"]["9"] = {
        "name": "Armour Mastery",
        "isMastery": True,
        "stats": ["Requires The Unseen Path"],  # stats가 있어도 제외
        "connections": [],
    }
    (raw / "tree/poe2db_us.json").write_text(json.dumps(us), encoding="utf-8")
    pob = json.loads((raw / "tree/pob_tree.json").read_text(encoding="utf-8"))
    pob["nodes"]["9"] = {"name": "Armour Mastery"}  # PoB에 있어도 제외
    (raw / "tree/pob_tree.json").write_text(json.dumps(pob), encoding="utf-8")

    report = process_tree(raw, out)
    assert "mastery" not in report["included"]
    assert not (out / "tree_mastery.json").exists()
    assert any("Armour Mastery" in e for e in report["excluded_sample"])


def test_process_tree_verdicts(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    report = process_tree(raw, out)

    assert report["included"]["keystone"] == 1
    assert report["included"]["small"] == 1
    assert report["included"]["ascendancy-start"] == 1, "구조 노드는 stats 없어도 수록"
    assert report["excluded"] == 2, "DNT 표식 + PoB 부재"

    ks = json.loads((out / "tree_keystone.json").read_text(encoding="utf-8"))
    assert ks[0]["name_ko"] == "카오스 면역", "한국어 이름 대조"
    assert ks[0]["stats_ko"] == ["최대 생명력이 1이 됨"]


def test_merge_tree_chunk_and_edges(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    process_tree(raw, out)

    # 최소 정본 (스키마만 있는 빈 KB) 준비
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    import shutil

    from pok.common.paths import project_root

    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    (knowledge / "game-data").mkdir(parents=True)

    summary = merge_tree(out, knowledge, "t", "small")
    assert summary["written"] == 1
    shard = (knowledge / "game-data/tree/small.ndjson").read_text(encoding="utf-8")
    rec = json.loads(shard.splitlines()[0])
    assert rec["id"] == "passive.chaos-damage-2", "id에 노드 id 포함 (동명 구분)"
    assert rec["data"]["connections"] == ["1"], "엣지 보존 = P4 Steiner 기반"
    assert rec["verification"] == "GAME_DATA"


def test_edges_are_undirected_when_expanded(tmp_path: Path) -> None:
    """단방향 저장을 양방향으로 펼치면 connections가 빈 노드도 이웃을 갖는다."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    process_tree(raw, out)
    items = [
        *json.loads((out / "tree_keystone.json").read_text(encoding="utf-8")),
        *json.loads((out / "tree_small.json").read_text(encoding="utf-8")),
    ]
    adj: dict[str, set[str]] = {}
    for it in items:
        for target in it["connections"]:
            adj.setdefault(it["node_id"], set()).add(target)
            adj.setdefault(target, set()).add(it["node_id"])
    assert adj["1"] == {"2"}, "Chaos Inoculation은 저장상 빈 connections지만 이웃이 있다"
