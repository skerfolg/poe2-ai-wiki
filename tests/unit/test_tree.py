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


def test_verification_criteria_in_tree_report(tmp_path: Path) -> None:
    """⑥⑦⑧이 트리 리포트에 자동으로 실린다 (KB_INGEST §4)."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    # PoB 쪽 효과 문구가 한 줄 더 있는 노드 — ⑥ 집합 차집합으로 잡힌다
    pob = json.loads((raw / "tree/pob_tree.json").read_text(encoding="utf-8"))
    pob["nodes"]["1"]["stats"] = ["Maximum Life becomes 1"]
    pob["nodes"]["2"]["stats"] = ["10% increased [Chaos] Damage", "Also grants Resistance"]
    (raw / "tree/pob_tree.json").write_text(json.dumps(pob), encoding="utf-8")

    v = process_tree(raw, out)["verification"]
    cross = v["6_cross_source"][0]
    assert cross["name_mismatch"]["count"] == 0
    stats = cross["set_diff"]["stats"]
    assert stats["only_in_pob"]["sample"][0]["values"] == ["also grants resistance"]
    assert stats["only_in_poe2db"]["count"] == 0, "마크업 차이는 정규화로 흡수 (norm_stat)"
    assert cross["only_in_poe2db"]["count"] == 2, "⑥ 양방향 — DNT·PoB 부재 노드"
    assert cross["only_in_pob"]["count"] == 0

    floor = v["7_substance_floor"][0]
    assert floor["empty"]["count"] == 0
    assert floor["structural_exempt"] == 1, "어센던시 시작점은 효과 없는 게 정상"

    acq = v["8_acquisition_coverage"][0]
    assert (acq["entity_type"], acq["total"], acq["coverage"]) == ("passive", 3, 1.0)
    assert acq["routes_top"] == {"tree-edge": 2, "ascendancy-choice": 1}


def test_acquisition_coverage_flags_node_severed_from_tree(tmp_path: Path) -> None:
    """⑧ 이웃이 전부 제외되면 실존 노드가 트리에서 끊긴다 — 커버리지가 알려준다.

    실측(0.5.4b): stats가 빈 '전문화' 노터블이 제외되면서 Far Shot·Point Blank 등
    18개 노드가 엣지를 잃었다.
    """
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    us = json.loads((raw / "tree/poe2db_us.json").read_text(encoding="utf-8"))
    us["nodes"]["7"] = {
        "name": "Far Shot",
        "isKeystone": True,
        "stats": ["Attacks have increased Damage at range"],
        "connections": [{"id": "4"}],  # 4 = PoB 부재로 제외되는 노드
    }
    (raw / "tree/poe2db_us.json").write_text(json.dumps(us), encoding="utf-8")
    pob = json.loads((raw / "tree/pob_tree.json").read_text(encoding="utf-8"))
    pob["nodes"]["7"] = {"name": "Far Shot"}
    (raw / "tree/pob_tree.json").write_text(json.dumps(pob), encoding="utf-8")

    acq = process_tree(raw, out)["verification"]["8_acquisition_coverage"][0]
    assert {m["name"] for m in acq["missing"]["sample"]} == {"Far Shot"}


def test_normalize_stats_splits_only_on_bilingual_agreement() -> None:
    """3b: `\\n`은 효과 경계일 때도, 단순 줄바꿈일 때도 있다 — 두 언어의 합의로 가른다."""
    from pok.kb.ingest.tree import normalize_stats

    # 효과 경계: 양 언어가 같은 자리에서 끊는다 → 분할
    en, ko = normalize_stats(
        ["75% of Damage Converted to [Fire] Damage\nDeal no Non-Fire Damage"],
        ["피해의 75%를 화염 피해로 전환\n화염 피해만 줄 수 있음"],
    )
    assert en == ["75% of Damage Converted to Fire Damage", "Deal no Non-Fire Damage"]
    assert ko == ["피해의 75%를 화염 피해로 전환", "화염 피해만 줄 수 있음"]

    # 단순 줄바꿈: 한국어는 한 줄 → 접어서 문장을 살린다 (PoB도 여기서 잘못 쪼갠다)
    en, ko = normalize_stats(
        ["+1% to all [MaximumResistances|Maximum Elemental Resistances] if you have at\nleast 5"],
        ["보조 젬을 5개 이상 장착한 경우 모든 원소 저항 최대치 +1%"],
    )
    assert en == ["+1% to all Maximum Elemental Resistances if you have at least 5"]
    assert len(en) == len(ko)


def test_normalize_stats_keeps_arrays_aligned() -> None:
    """분할 여부와 무관하게 en/ko 배열 길이가 같아야 한다 (위치 대응 보장)."""
    from pok.kb.ingest.tree import normalize_stats

    en, ko = normalize_stats(["A\nB", "C"], ["가\n나", "다"])
    assert en == ["A", "B", "C"] and ko == ["가", "나", "다"]

    # 항목 수 자체가 다르면 짝지을 수 없다 → 분할 없이 접기만
    en, ko = normalize_stats(["A\nB"], [])
    assert en == ["A B"] and ko == []


def test_ascendancy_hub_node_is_included(tmp_path: Path) -> None:
    """stats 빈 어센던시 노터블은 구조 노드 — 빼면 매달린 실존 노드가 끊긴다."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    us = json.loads((raw / "tree/poe2db_us.json").read_text(encoding="utf-8"))
    us["nodes"]["6"] = {
        "name": "Projectile Proximity Specialisation",
        "isNotable": True,
        "stats": [],
        "ascendancyName": "Ranger1",
        "connections": [],
    }
    us["nodes"]["7"] = {
        "name": "Far Shot",
        "isKeystone": True,
        "stats": ["Projectiles deal more damage at range"],
        "connections": [{"id": "6"}],
    }
    (raw / "tree/poe2db_us.json").write_text(json.dumps(us), encoding="utf-8")
    pob = json.loads((raw / "tree/pob_tree.json").read_text(encoding="utf-8"))
    pob["nodes"]["6"] = {"name": "Projectile Proximity Specialisation"}
    pob["nodes"]["7"] = {"name": "Far Shot"}
    (raw / "tree/pob_tree.json").write_text(json.dumps(pob), encoding="utf-8")

    report = process_tree(raw, out)
    notables = json.loads((out / "tree_notable.json").read_text(encoding="utf-8"))
    hub = next(n for n in notables if n["name_en"] == "Projectile Proximity Specialisation")
    assert hub["structural"], "⑦ 면제 대상 — 효과가 없는 게 정상"
    acq = report["verification"]["8_acquisition_coverage"][0]
    assert acq["missing"]["count"] == 0, "허브가 살아 Far Shot이 트리에 붙는다"
    assert acq["routes_top"]["ascendancy-choice"] >= 1


def test_ascendancy_placeholder_stays_excluded(tmp_path: Path) -> None:
    """미구현 자리표는 stats도 PoB 항목도 없어 허브 규칙에 걸리지 않는다."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    _write_tree_fixtures(raw)
    us = json.loads((raw / "tree/poe2db_us.json").read_text(encoding="utf-8"))
    us["nodes"]["8"] = {
        "name": "AscendancyTemplar1Small7",
        "isNotable": True,
        "stats": [],
        "ascendancyName": "Templar1",
        "connections": [],
    }
    (raw / "tree/poe2db_us.json").write_text(json.dumps(us), encoding="utf-8")

    report = process_tree(raw, out)
    assert any("AscendancyTemplar1Small7" in e for e in report["excluded_sample"])


def test_clean_name_strips_markup() -> None:
    """poe2db가 남긴 위키 마크업을 제거한다 (0.5.4b: 15건)."""
    from pok.kb.ingest.tree import clean_name

    assert clean_name("[Jewel] Socket") == "Jewel Socket"
    assert clean_name("[SinisterJewelSockets|Sinister] [Jewel] Socket") == "Sinister Jewel Socket"
    assert clean_name("  Inherited Strength  ") == "Inherited Strength"
    assert clean_name("Pyromancer") == "Pyromancer"


def test_pob_name_wins_on_mismatch(tmp_path: Path) -> None:
    """같은 노드 id인데 이름이 다르면 PoB(게임파일 유래)를 따른다.

    실측 근거(0.5.4b): poe2db 트리 JSON이 구 어센던시명을 유지 —
    Arsonist→Pyromancer, Necromancer→Lich 등 5건. poe2db 웹페이지는 PoB와 일치.
    """
    raw, out = tmp_path / "raw", tmp_path / "out"
    (raw / "tree").mkdir(parents=True)
    (raw / "tree/poe2db_us.json").write_text(
        json.dumps(
            {
                "nodes": {
                    "14265": {
                        "name": "Arsonist",
                        "isNotable": True,
                        "stats": ["20% increased Fire Damage"],
                        "connections": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (raw / "tree/poe2db_kr.json").write_text(
        json.dumps({"nodes": {"14265": {"name": "화염 피해", "stats": []}}}), encoding="utf-8"
    )
    (raw / "tree/pob_tree.json").write_text(
        json.dumps({"nodes": {"14265": {"name": "Pyromancer"}}}), encoding="utf-8"
    )

    # 한국어 보정표 (정본)
    knowledge = tmp_path / "knowledge"
    (knowledge / "ingest").mkdir(parents=True)
    (knowledge / "ingest/name-overrides.json").write_text(
        json.dumps(
            {"nodes": {"14265": {"en": "Pyromancer", "ko": "화염술사"}}}, ensure_ascii=False
        ),
        encoding="utf-8",
    )

    report = process_tree(raw, out, knowledge)
    assert report["name_overrides"] == 1
    items = json.loads((out / "tree_notable.json").read_text(encoding="utf-8"))
    assert items[0]["name_en"] == "Pyromancer", "PoB 이름 채택"
    assert items[0]["name_ko"] == "화염술사", "한국어는 보정표 (JSON의 '화염 피해'는 효과 문구)"
