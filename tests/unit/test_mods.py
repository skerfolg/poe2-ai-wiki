"""P1b ④: 베이스 아이템 + 모드 풀 — 파싱·⑥⑦⑧·스키마 왕복 (픽스처, 네트워크 없음)."""

from __future__ import annotations

import json
from pathlib import Path

from pok.kb.ingest.mods import (
    base_to_record,
    essence_acquisition,
    mod_to_record,
    parse_base,
    parse_mod,
    parse_rune,
    process_mods,
)

# PoB ModItem.lua 원형 (덤프 JSON 형태)
STRENGTH1 = {
    "1": "+(5-8) to Strength",
    "affix": "of the Brute",
    "group": "Strength",
    "level": 1,
    "modTags": ["attribute"],
    "type": "Suffix",
    "weightKey": ["ring", "amulet", "default"],
    "weightVal": [1, 1, 0],
}
# 가중치 전부 0 = 현재 스폰 불가 (레거시/비활성 — KI-8 판정 대상)
DEAD_MOD = {
    "1": "Bow Attacks fire an additional Arrow",
    "affix": "of Splintering",
    "group": "AdditionalArrow",
    "level": 82,
    "type": "Suffix",
    "weightKey": ["bow", "default"],
    "weightVal": [0, 0],
}
ESSENCE_ONLY_MOD = {
    "1": "(31-35)% increased Spell Damage",
    "affix": "Apocalyptic",
    "group": "SpellDamage",
    "level": 60,
    "type": "Prefix",
    "weightKey": ["default"],
    "weightVal": [0],
}
RUNE = {
    "armour": {"1": "+9 to Dexterity", "rank": [15], "type": "Rune"},
    "caster": {"1": "+9 to Dexterity", "rank": [15], "type": "Rune"},
    "weapon": {"1": "9% increased Attack Speed", "rank": [15], "type": "Rune"},
}
ESSENCE = {
    "Metadata/E1": {
        "mods": {"Ring": "EssenceSpell1", "Amulet": "EssenceSpell1"},
        "name": "Essence of Woe",
        "tierLevel": 1,
        "type": "Woe",
    },
    "Metadata/E2": {
        "mods": {"Helmet": "GhostMod"},
        "name": "Essence of Loss",
        "tierLevel": 1,
        "type": "Loss",
    },
    "Metadata/E3": {"mods": [], "name": "Corrupted One", "tierLevel": 1, "type": "Abyss"},
}
BASE_WEAPON = {
    "type": "One Hand Mace",
    "quality": 20,
    "socketLimit": 3,
    "tags": {"default": True, "mace": True, "one_hand_weapon": True, "weapon": True},
    "implicitModTypes": [],
    "weapon": {
        "PhysicalMin": 6,
        "PhysicalMax": 10,
        "CritChanceBase": 5,
        "AttackRateBase": 1.45,
        "Range": 13,
    },
    "req": [],
    "_base_file": "mace",
}
BASE_RING = {
    "type": "Ring",
    "tags": {"default": True, "ring": True},
    "implicit": "Adds 1 to 4 Physical Damage to Attacks",
    "implicitModTypes": [["physical_damage", "damage", "physical", "attack"]],
    "req": {"level": 12},
    "_base_file": "ring",
}
BASE_FLASK = {  # 실질 수치 없음 — ⑦ 대상 (자동 제외 금지, 사람 판정)
    "type": "Flask",
    "tags": {"default": True, "flask": True, "life_flask": True},
    "implicitModTypes": [],
    "req": [],
    "_base_file": "flask",
}


def test_parse_mod_spawnable_prefix_suffix() -> None:
    routes, _ = essence_acquisition(ESSENCE)
    m = parse_mod("Strength1", STRENGTH1, "item", routes)
    assert m["affix_type"] == "suffix"
    assert m["affix_name"] == "of the Brute"
    assert m["texts"] == ["+(5-8) to Strength"]
    assert m["group"] == "Strength", "그룹 배타(RC4)의 축"
    assert m["ilvl"] == 1
    assert m["spawn_weights"] == {"ring": 1, "amulet": 1, "default": 0}
    assert m["acquisition"] == ["crafting-currency"], "가중치 양수 → 일반 제작 풀"


def test_parse_mod_dead_weights_have_no_acquisition() -> None:
    """가중치 전부 0 = 스폰 불가 — ⑧이 KI-8 판정 대상으로 드러낸다."""
    m = parse_mod("AdditionalArrow1", DEAD_MOD, "item", {})
    assert m["acquisition"] == [], "스폰 불가·에센스 아님 → 획득 경로 없음"


def test_parse_mod_essence_route() -> None:
    """에센스는 모드가 아니라 '모드 키 → 부여 에센스' 매핑 (⑧ 원천)."""
    routes, refs = essence_acquisition(ESSENCE)
    m = parse_mod("EssenceSpell1", ESSENCE_ONLY_MOD, "item", routes)
    assert m["acquisition"] == ["essence:Essence of Woe"], "스폰 0이어도 에센스로 획득 가능"
    assert "GhostMod" in refs, "깨진 참조 후보도 목록에 남는다 (⑥에서 대조)"


def test_parse_rune_per_slot() -> None:
    m = parse_rune("Adept Rune", RUNE)
    assert m["affix_type"] == "rune"
    assert m["per_slot"]["weapon"] == ["9% increased Attack Speed"]
    assert m["per_slot"]["armour"] == ["+9 to Dexterity"]
    assert m["rank"] == 15
    assert m["acquisition"] == ["rune-socket"]


def test_parse_base_weapon_and_ring() -> None:
    w = parse_base("Wooden Club", BASE_WEAPON)
    assert w["item_class"] == "One Hand Mace"
    assert w["category"] == "mace"
    assert w["weapon"]["PhysicalMax"] == 10, "PoB 키 원형 보존 (가공 최소)"
    assert w["socket_limit"] == 3
    assert "one_hand_weapon" in w["spawn_tags"], "모드 spawn_weights와 대조하는 열쇠"

    r = parse_base("Iron Ring", BASE_RING)
    assert r["implicit"] == "Adds 1 to 4 Physical Damage to Attacks"
    assert r["req"] == {"level": 12}


def _write_dumps(pob: Path) -> None:
    pob.mkdir(parents=True)
    files = {
        "moditem.json": {
            "Strength1": STRENGTH1,
            "AdditionalArrow1": DEAD_MOD,
            "EssenceSpell1": ESSENCE_ONLY_MOD,
        },
        "moditemexclusive.json": {},
        "modcorrupted.json": {
            "CorruptMod1": {
                "1": "Loads an additional bolt",
                "affix": "",
                "level": 1,
                "group": "AdditionalAmmo",
                "type": "Corrupted",
                "weightKey": ["crossbow", "default"],
                "weightVal": [1, 0],
            },
        },
        "modflask.json": {},
        "modcharm.json": {},
        "modjewel.json": {},
        "modrunes.json": {"Adept Rune": RUNE},
        "essence.json": ESSENCE,
        "bases.json": {
            "Wooden Club": BASE_WEAPON,
            "Iron Ring": BASE_RING,
            "Small Life Flask": BASE_FLASK,
        },
    }
    for name, data in files.items():
        (pob / name).write_text(json.dumps(data), encoding="utf-8")


def test_process_mods_end_to_end(tmp_path: Path) -> None:
    """process → 중간 산출물 + ⑥⑦⑧ 리포트 (KB_INGEST §4)."""
    raw = tmp_path / "raw"
    _write_dumps(raw / "pob")

    report = process_mods(raw, tmp_path / "out")
    assert report["mods_total"] == 5
    assert report["pool_merged_duplicates"] == 0
    assert report["mods_by_origin"] == {"corrupted": 1, "item": 3, "rune": 1}
    assert report["bases_total"] == 3

    v = report["verification"]
    ess = v["6_cross_source"][0]
    assert ess["only_in_essence-refs"]["sample"] == ["GhostMod"], "⑥ 에센스 깨진 참조"
    tags = v["6_cross_source"][1]
    assert "crossbow" in tags["only_in_mod-weight-tags"]["sample"], (
        "⑥ 대응 베이스 없는 스폰 태그 (석궁 베이스 미수집을 드러냄)"
    )

    floors = {s["scope"]: s for s in v["7_substance_floor"]}
    assert floors["modifier:all"]["empty"]["count"] == 0
    assert [x["name"] for x in floors["base-item:all"]["empty"]["sample"]] == [
        "Small Life Flask"
    ], "⑦ 실질 수치 없는 베이스 — 자동 제외하지 않고 사람 판정 대기"

    cov = {a["entity_type"]: a for a in v["8_acquisition_coverage"]}
    assert cov["modifier:item"]["coverage"] == round(2 / 3, 4), "죽은 모드 1개가 깎는다"
    assert cov["modifier:item"]["missing"]["sample"][0]["name"] == "of Splintering"
    assert cov["modifier:corrupted"]["coverage"] == 1.0
    assert cov["modifier:rune"]["coverage"] == 1.0
    assert (raw / "pob" / "mods-report.json").exists(), "리포트 = 데이터 repo 증거"

    mods = json.loads((tmp_path / "out" / "mods.json").read_text(encoding="utf-8"))
    bases = json.loads((tmp_path / "out" / "base_items.json").read_text(encoding="utf-8"))
    assert len(mods) == 5 and len(bases) == 3


def test_dedup_across_pools_and_alt_variants() -> None:
    """같은 모드가 두 풀에 동일 내용으로 실리면 병합, `_` 변형은 id로 갈린다."""
    from pok.kb.ingest.mods import _dedup_across_pools, mod_slug

    flask = parse_mod("FlaskCharges1", STRENGTH1, "flask", {})
    charm = parse_mod("FlaskCharges1", STRENGTH1, "charm", {})
    deduped, merged = _dedup_across_pools([flask, charm])
    assert merged == 1 and len(deduped) == 1
    assert deduped[0]["origins"] == ["charm", "flask"], "계보 양쪽 보존 (조용한 폐기 금지)"

    # 내용이 다르면 병합하지 않는다
    other = parse_mod("FlaskCharges1", DEAD_MOD, "charm", {})
    kept, merged2 = _dedup_across_pools([flask, other])
    assert merged2 == 0 and len(kept) == 2

    assert mod_slug("GrantCursePillarSkillUnique") == "grantcursepillarskillunique"
    assert mod_slug("GrantCursePillarSkillUnique__") == "grantcursepillarskillunique-alt2"


def test_seed_records_pass_schema_roundtrip(tmp_path: Path) -> None:
    """시드 실증 (P1a 방식): 대표 레코드가 실제 스키마 검증 + store 로드를 왕복한다."""
    import shutil

    from pok.common.paths import project_root
    from pok.kb.ingest.mods import _dedup_across_pools
    from pok.kb.store import load as store_load

    routes, _ = essence_acquisition(ESSENCE)
    raw_mods = [
        parse_mod("Strength1", STRENGTH1, "item", routes),
        parse_mod("EssenceSpell1", ESSENCE_ONLY_MOD, "item", routes),
        parse_mod("AdditionalArrow1", DEAD_MOD, "item", {}),
        parse_rune("Adept Rune", RUNE),
    ]
    deduped, _n = _dedup_across_pools(raw_mods)
    seeds = [
        *[mod_to_record(m, "t", "c0ffee") for m in deduped],
        base_to_record(parse_base("Wooden Club", BASE_WEAPON), "t", "c0ffee"),
        base_to_record(parse_base("Iron Ring", BASE_RING), "t", "c0ffee"),
        base_to_record(parse_base("Small Life Flask", BASE_FLASK), "t", "c0ffee"),
    ]
    assert seeds[0]["id"] == "modifier.strength1"
    assert seeds[0]["data"]["origins"] == ["item"]
    assert seeds[3]["data"]["per_slot"]["weapon"] == ["9% increased Attack Speed"]
    assert seeds[4]["id"] == "item.wooden-club"
    assert seeds[4]["data"]["rarity"] == "normal", "베이스 = 같은 Item 타입, 다른 rarity"
    assert all(s["verification"] == "POB_CODE" for s in seeds), (
        "PoB 단독 소스 — poe2db 대사 후 GAME_DATA 승격"
    )

    # 실제 스키마로 store 왕복 (스키마 결함을 소수 시드로 조기 발견)
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    out = knowledge / "game-data" / "modifiers"
    out.mkdir(parents=True)
    (out / "seed.ndjson").write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in seeds), encoding="utf-8"
    )
    kb = store_load(root)
    assert len(kb.records) == 7
    assert kb.records["modifier.strength1"].type == "Modifier"


def test_merge_promotes_ledger_and_desecrated(tmp_path: Path) -> None:
    """2026-07-30 승인 반영 — 카탈로그 확인분 승격 · 미확인분 원장 · Desecrated 신규."""
    import shutil

    from pok.common.paths import project_root
    from pok.kb.ingest.mods import merge_mods

    out = tmp_path / "out"
    out.mkdir()
    pob_mods = [
        {  # 카탈로그 확인 → 승격 + poe2db 경로
            "pob_key": "AlloyX1",
            "affix_type": "suffix",
            "affix_name": "of the Stars",
            "texts": ["(35-42)% increased Archon Buff duration"],
            "group": "ArchonDuration",
            "ilvl": 45,
            "spawn_weights": {"default": 0},
            "origins": ["item"],
            "acquisition": [],
        },
        {  # 카탈로그 미확인 → 제외 + 원장
            "pob_key": "DeadZeal1",
            "affix_type": "suffix",
            "affix_name": "of Zeal",
            "texts": ["(3-4)% increased Attack and Cast Speed"],
            "group": "AttackAndCastSpeed",
            "ilvl": 15,
            "spawn_weights": {"default": 0},
            "origins": ["item"],
            "acquisition": [],
        },
        {  # 일반 수록분 — poe2db 풀 경로가 추가로 붙는다 (E-2 유지)
            "pob_key": "Strength1",
            "affix_type": "suffix",
            "affix_name": "of the Brute",
            "texts": ["+(5-8) to Strength"],
            "group": "Strength",
            "ilvl": 1,
            "spawn_weights": {"ring": 1},
            "origins": ["item"],
            "acquisition": ["crafting-currency"],
        },
    ]
    (out / "mods.json").write_text(json.dumps(pob_mods), encoding="utf-8")
    (out / "base_items.json").write_text("[]", encoding="utf-8")
    (out / "catalog_match.json").write_text(
        json.dumps({"AlloyX1": ["perfect_essence"], "Strength1": ["normal", "chronomancy"]}),
        encoding="utf-8",
    )
    (out / "mod_catalog.json").write_text(
        json.dumps(
            {
                "k1": {
                    "affix_name": "Lightless",
                    "ilvl": 1,
                    "affix_type": "prefix",
                    "families": ["armourincrease"],
                    "texts": ["(5-10)% increased Armour"],
                    "pools": {"desecrated": ["Body_Armours_str"]},
                    "mod_tags": [],
                    "drop_chance": None,
                }
            }
        ),
        encoding="utf-8",
    )
    (out / "desecrated.json").write_text(
        json.dumps(
            {
                "equipment": [
                    {
                        "affix_name": "Lightless",
                        "ilvl": 1,
                        "affix_type": "prefix",
                        "text": "(5-10)% increased Armour",
                        "mod_tags": ["kurgal_mod"],
                    }
                ],
                "waystone": [
                    {
                        "affix_name": "Abyssal",
                        "ilvl": 0,
                        "affix_type": "prefix",
                        "text": "Abyssal Monsters grant (50-100)% increased Experience",
                        "mod_tags": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    (knowledge / "ingest").mkdir()
    (knowledge / "game-data").mkdir()

    summary = merge_mods(out, knowledge, "t")
    assert summary["mods_included"] == 2, "확인분 승격 + 기존 수록분"
    assert summary["mods_excluded_to_ledger"] == 1, "미확인분은 원장으로"
    assert summary["mods_by_pool"]["desecrated"] == 2
    assert summary["kb_total"] == 4

    ledger = json.loads((knowledge / "ingest" / "exclusions.json").read_text(encoding="utf-8"))
    assert ledger["unobtainable_mods"][0]["pob_keys"] == ["DeadZeal1"]

    shard_text = "".join(
        p.read_text(encoding="utf-8")
        for p in (knowledge / "game-data" / "modifiers").glob("*.ndjson")
    )
    records = {json.loads(line)["id"]: json.loads(line) for line in shard_text.splitlines()}
    assert records["modifier.alloyx1"]["data"]["acquisition"] == ["poe2db:perfect_essence"]
    assert records["modifier.strength1"]["data"]["acquisition"] == [
        "crafting-currency",
        "poe2db:chronomancy",
        "poe2db:normal",
    ], "E-2 유지 — 실존 풀이 획득 경로로 붙는다"
    des = next(r for r in records.values() if "desecrated" in r["data"]["origins"])
    assert des["verification"] == "SUPPORTED_INFERENCE", "poe2db 단독 소스"
    lightless = records["modifier.desecrated-equipment-lightless-5-10-increased-armour"]
    assert lightless["data"]["applicable_pages"] == ["Body_Armours_str"], "카탈로그로 클래스 보강"
