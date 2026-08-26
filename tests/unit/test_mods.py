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
        json.dumps(
            {
                "AlloyX1": {"pools": ["perfect_essence"], "key": "kalloy"},
                "Strength1": {"pools": ["normal", "chronomancy"], "key": "kstr"},
            }
        ),
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
                },
                "kstr": {
                    "affix_name": "of the Brute",
                    "affix_name_ko": "- 짐승",
                    # 슬롯 키가 유일하지 않아 **옆 모드의 줄**이 함께 쌓인 상태 —
                    # 실측 0.5.4b에서 728슬롯이 이 모양이었다. 통째로 붙이면 오염된다.
                    "ko_by_text": {
                        "+(5-8) to strength": "힘 +(5-8)",
                        "notable passive skills in radius also grant +(2-3) to strength": (
                            "반경 내 주요 패시브 스킬이 힘 +(2-3)도 부여"
                        ),
                    },
                    "ilvl": 1,
                    "affix_type": "suffix",
                    "families": ["strength"],
                    "texts": ["+(5-8) to Strength"],
                    "pools": {"normal": ["Amulets"]},
                    "mod_tags": [],
                    "drop_chance": 1000,
                },
                "kalloy": {
                    "affix_name": "Celestial Alloy",  # 화폐명 — PoB 접사명과 다름
                    "affix_name_ko": "천상의 합금",
                    "ko_by_text": {
                        "(35-42)% increased archon buff duration": "집정관 버프 지속시간 증가"
                    },
                    "ilvl": 45,
                    "affix_type": "suffix",
                    "families": ["archonduration"],
                    "texts": ["(35-42)% increased Archon Buff duration"],
                    "pools": {"perfect_essence": ["Amulets"]},
                    "mod_tags": [],
                    "drop_chance": None,
                },
            }
        ),
        encoding="utf-8",
    )
    (out / "base_names_ko.json").write_text("{}", encoding="utf-8")
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

    # 다른 단계(heart_mods)가 쓴 샤드 — merge의 잔재 청소가 이걸 지우면 KB가 깎인다
    from pok.kb.ingest.heart_mods import SHARD as HEART_SHARD

    heart_rec = {
        "id": "modifier.heart-test",
        "type": "Modifier",
        "name": {"ko": "심장", "en": "Heart"},
        "tags": [],
        "data": {
            "affix_type": "prefix",
            "origins": ["heart-of-the-well"],
            "pob_key": "UniqueHeartPrefixTest",
            "texts": ["10% increased Heart"],
            "ilvl": 1,
            "acquisition": ["unique:heart-of-the-well"],
        },
        "verification": "POB_CODE",
        "sources": [{"src": "pob", "ref": "Data/ModVeiled.lua UniqueHeart*"}],
    }
    (knowledge / "game-data" / "modifiers").mkdir(parents=True)
    (knowledge / "game-data" / "modifiers" / HEART_SHARD).write_text(
        json.dumps(heart_rec, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    summary = merge_mods(out, knowledge, "t")
    assert (
        (knowledge / "game-data" / "modifiers" / HEART_SHARD).read_text(encoding="utf-8").strip()
    ), "다른 단계 소유 샤드는 잔재가 아니다 — 재실행이 지우면 안 된다"
    assert summary["mods_included"] == 2, "확인분 승격 + 기존 수록분"
    assert summary["mods_excluded_to_ledger"] == 1, "미확인분은 원장으로"
    assert summary["mods_by_pool"]["desecrated"] == 2
    assert summary["kb_total"] == 5, "수록 2 + Desecrated 2 + 보존된 heart 1"

    ledger = json.loads((knowledge / "ingest" / "exclusions.json").read_text(encoding="utf-8"))
    assert ledger["unobtainable_mods"][0]["pob_keys"] == ["DeadZeal1"]

    shard_text = "".join(
        p.read_text(encoding="utf-8")
        for p in (knowledge / "game-data" / "modifiers").glob("*.ndjson")
    )
    records = {json.loads(line)["id"]: json.loads(line) for line in shard_text.splitlines()}
    assert records["modifier.alloyx1"]["data"]["acquisition"] == ["poe2db:perfect_essence"]
    assert records["modifier.alloyx1"]["verification"] == "GAME_DATA", "양 소스 확인 → 승격"
    assert records["modifier.alloyx1"]["name"]["ko"] == "of the Stars", (
        "poe2db 접사명이 화폐명이면 name.ko 오염 금지 — texts_ko만"
    )
    assert records["modifier.alloyx1"]["data"]["texts_ko"] == ["집정관 버프 지속시간 증가"]
    assert records["modifier.strength1"]["data"]["texts_ko"] == ["힘 +(5-8)"], (
        "슬롯에 옆 모드의 반경 부여 줄이 함께 있어도 **자기 영문 줄의 한글만** 온다 —"
        " 통째로 붙이던 시절 1,536건이 오염됐다 (2026-08-07)"
    )
    assert records["modifier.strength1"]["name"]["ko"] == "- 짐승", "접사명 일치 → ko 부착"
    assert records["modifier.strength1"]["data"]["acquisition"] == [
        "crafting-currency",
        "poe2db:chronomancy",
        "poe2db:normal",
    ], "E-2 유지 — 실존 풀이 획득 경로로 붙는다"
    des = next(r for r in records.values() if "desecrated" in r["data"]["origins"])
    assert des["verification"] == "SUPPORTED_INFERENCE", "poe2db 단독 소스"
    lightless = records["modifier.desecrated-equipment-lightless-5-10-increased-armour"]
    assert lightless["data"]["applicable_pages"] == ["Body_Armours_str"], "카탈로그로 클래스 보강"


CURRENCY_HTML_US = """
<html><body>
<div class="card"><h5 class="card-header">Stackable Currency Item /2</h5>
<div class="row">
 <div class="col"><a class="item_currency" href="Chaos_Orb">Chaos Orb</a>
   <div>Stack Size:</div><div>1 / 20</div>
   <div>Removes a random modifier</div><div>from a rare item</div></div>
 <div class="col"><a class="item_currency" href="Runic_Alloy">Runic Alloy</a>
   <div>Stack Size:</div><div>1 / 10</div>
   <div>Augments a Rare item</div></div>
</div></div>
<div class="card"><h5 class="card-header">Essence /1</h5>
<div class="row">
 <div class="col"><a class="item_currency" href="Runic_Alloy">Runic Alloy</a>
   <div>Stack Size:</div><div>1 / 10</div>
   <div>Augments a Rare item</div></div>
</div></div>
<div class="card"><h5 class="card-header">Splinter Item /1</h5>
<div class="row">
 <div class="col"><a class="item_currency" href="Breach_Splinter">Breach Splinter</a>
   <div>Stack Size:</div><div>1 / 300</div></div>
</div></div>
</body></html>
"""

CURRENCY_HTML_KR = (
    CURRENCY_HTML_US.replace("Stackable Currency Item /2", "중첩 가능 화폐 아이템 /2")
    .replace("Essence /1", "에센스 /1")
    .replace("Splinter Item /1", "Splinter 아이템 /1")
    .replace(">Chaos Orb</a>", ">카오스 오브</a>")
    .replace("Stack Size:", "중첩 개수:")
    .replace(
        "<div>Removes a random modifier</div><div>from a rare item</div>",
        "<div>희귀 아이템의</div><div>무작위 속성 제거</div>",
    )
)


def test_currency_parse_and_merge(tmp_path: Path) -> None:
    """화폐 수록 (④ 보강, 승인 2026-07-30) — href 조인·카드 중복 dedup·⑦."""
    import shutil

    from pok.common.paths import project_root
    from pok.kb.ingest.currency import parse_page, process_and_merge

    us = parse_page(CURRENCY_HTML_US)
    assert set(us) == {"Chaos_Orb", "Runic_Alloy", "Breach_Splinter"}
    assert us["Chaos_Orb"]["effect"] == "Removes a random modifier from a rare item", (
        "키워드 링크로 쪼개진 텍스트를 공백으로 복원"
    )
    assert us["Chaos_Orb"]["stack_size"] == 20
    assert us["Runic_Alloy"]["category"] == "stackable", (
        "Stackable∩Essence 중복 게재는 첫 카드 분류 유지 (Alloy 13종 실측)"
    )

    raw = tmp_path / "raw"
    (raw / "currency").mkdir(parents=True)
    (raw / "currency" / "stackable.us.html").write_text(CURRENCY_HTML_US, encoding="utf-8")
    (raw / "currency" / "stackable.kr.html").write_text(CURRENCY_HTML_KR, encoding="utf-8")
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    (knowledge / "game-data").mkdir()

    report = process_and_merge(raw, knowledge, "t")
    assert report["written"] == 3 and report["kb_total"] == 3
    assert report["by_category"] == {"splinter": 1, "stackable": 2}
    assert report["ko_names"] == 1, "카오스 오브만 ko가 다르다 (픽스처)"
    floor = report["verification"]["7_substance_floor"][0]
    assert [x["name"] for x in floor["empty"]["sample"]] == ["Breach Splinter"], (
        "⑦ 효과 문구 없는 교환 재화 — 자동 제외하지 않고 리포트"
    )

    shard = (knowledge / "game-data" / "currency" / "currency-01.ndjson").read_text(
        encoding="utf-8"
    )
    recs = {json.loads(x)["id"]: json.loads(x) for x in shard.splitlines()}
    chaos = recs["item.chaos-orb"]
    assert chaos["data"]["rarity"] == "currency"
    assert chaos["name"]["ko"] == "카오스 오브"
    assert chaos["data"]["effect_ko"] == "희귀 아이템의 무작위 속성 제거"


def test_base_category_prefers_weapon_family_over_filename() -> None:
    """육척봉이 시전 지팡이로 뭉뚱그려지지 않아야 한다 — `staff.lua`가 두 계열을 담는다.

    실측 0.5.4b: `staff.lua` 48건 중 31건이 `subType="Warstaff"`(육척봉)이고
    17건은 시전 지팡이다. 파일명만 쓰면 둘이 같은 `staff`가 되어, 설계가 육척봉을
    시전 무기로 오판한다(2026-08-05 실측 사고).
    """
    from pok.kb.ingest.mods import _base_category

    quarterstaff = {
        "_base_file": "staff",
        "subType": "Warstaff",
        "tags": {"weapon": True, "warstaff": True, "twohand": True},
    }
    assert _base_category(quarterstaff) == "warstaff"

    caster_staff = {
        "_base_file": "staff",
        "tags": {"weapon": True, "staff": True, "twohand": True},
    }
    assert _base_category(caster_staff) == "staff", "시전 지팡이는 그대로"

    mace = {"_base_file": "mace", "tags": {"weapon": True, "mace": True}}
    assert _base_category(mace) == "mace", "파일명이 tags에 있으면 파일명 (무기 306건)"

    # 방어구의 subType은 방어 타입(Armour/Evasion)이지 계열이 아니다 — 건드리면 안 된다
    body = {"_base_file": "body", "subType": "Armour/Evasion", "tags": {"body_armour": True}}
    assert _base_category(body) == "body"


def test_unique_category_inherits_from_base() -> None:
    """유니크 계열은 `Uniques/*.lua` 파일명이 아니라 **베이스**가 정한다.

    `Uniques/staff.lua`에 육척봉 유니크와 지팡이 유니크가 섞여 있다 — 실측 0.5.4b:
    유니크 476건 중 7건(전부 육척봉)이 파일명으로는 `staff`로 잘못 잡혔다.
    """
    from pok.kb.ingest.uniques_page import _unique_category

    base_cats = {"Long Quarterstaff": "warstaff", "Chiming Staff": "staff"}
    pillar = {"base_type": "Long Quarterstaff", "category": "staff"}
    assert _unique_category(pillar, base_cats) == "warstaff", "갇힌 신의 기둥은 육척봉"

    shards = {"base_type": "Chiming Staff", "category": "staff"}
    assert _unique_category(shards, base_cats) == "staff"

    # 베이스를 모르면 파일명이 폴백 — 계열을 통째로 잃는 것보다 낫다
    unknown = {"base_type": "Nonexistent Base", "category": "amulet"}
    assert _unique_category(unknown, base_cats) == "amulet"


def test_poe1_remnant_mods_stay_out_of_the_kb() -> None:
    """PoE1 잔재 7건은 **재수집해도 안 돌아온다** (백로그 #17, 사용자 판정 2026-08-09).

    이 7건은 얹으면 `new("Item", raw)`가 **예외를 던져 조립 자체가 실패**한다 —
    다른 파싱 갭(조용한 0)과 성질이 다르다. 레코드만 지우면 다음 ingest가 되살린다:
    `item-exclusive`는 스폰 가중치가 없는 게 정상이라 `_ALWAYS_INCLUDE` 지름길로
    **무증거 수록**되기 때문이다. 그래서 원장 기재 + `is_included` 양쪽을 잠근다.
    """
    from pok.common.paths import knowledge_dir
    from pok.kb.ingest.mods import is_included, poe1_remnant_keys
    from pok.kb.store import load

    remnants = poe1_remnant_keys()
    assert len(remnants) == 7, remnants

    # ① 수집이 다시 넣지 않는다 — item-exclusive 지름길보다 먼저 걸려야 한다
    mod = {"pob_key": "SupportedByInnervateUnique__1", "origins": ["item-exclusive"]}
    assert not is_included(mod), "지름길이 잔재를 삼키면 다음 패치에 되살아난다"
    assert is_included({"pob_key": "Strength1", "origins": ["item-exclusive"]}), (
        "잔재가 아닌 item-exclusive는 그대로 수록된다 (게이트는 양방향)"
    )

    # ② 지금 정본에 없다
    store = load(knowledge_dir())
    present = [
        rid
        for rid, rec in store.records.items()
        if (rec.raw.get("data") or {}).get("pob_key") in remnants
    ]
    assert not present, f"정본에 남아 있다: {present}"


def test_결속을_해제하는_우상에는_조건_주석을_안_단다() -> None:
    """⛔ **우회 수단이 우회 대상으로 표기되면 읽는 쪽이 정반대로 판단한다** (#112).

    `Fox Idol`은 *"Idols socketed in this item gain the benefits of their Bonded
    modifiers"* 라 결속을 **켜는** 쪽인데, 정본이 그 자신에게 「샤먼 전용」 주석을
    달고 있었다. 엔진이 그걸 읽고 항상 빼면 Fox Idol 구성에서 **과소 계상**한다.
    """
    from pok.kb.ingest.mods import parse_rune

    raw = {"body armour": {"1": "X", "2": "Bonded: Y", "rank": [1]}}
    fox = parse_rune("Fox Idol", raw)
    other = parse_rune("Hawk Idol", raw)
    assert fox["bonded_lines"], "조건부 줄 자체는 그대로 보존한다"
    assert "bonded_condition" not in fox, "해제하는 쪽에는 조건 주석을 달지 않는다"
    assert "bonded_condition" in other, "다른 우상은 그대로 조건부다"


def test_조건_문구가_해제_경로를_알린다() -> None:
    """조건이 「샤먼 전용」으로 고정이 아니라는 사실이 문구에 있어야 한다 (#112)."""
    from pok.kb.ingest.mods import BONDED_CONDITION

    assert "Fox Idol" in BONDED_CONDITION


def test_근거_없는_레코드_감소를_거부한다() -> None:
    """⛔⛔ 정본 유실을 **쓰기 전에** 막는다 (#127).

    `mods merge`는 샤드를 **무조건 지우고** 조건부로 다시 쓴다(`desecrated.json`이
    있을 때만). 상류 산출물이 빠지면 그 풀이 통째로 사라진다 — 실측 2026-08-25:
    `modifiers`+`base-items` **10,343 → 9,908**, 유실 435건에 **신규 0**(옮겨간 곳이 없다).

    `store.write_shard`의 안전장치는 **샤드 단위**라 파일을 통째로 지우는 이 경로를
    못 본다. 그래서 여기 따로 둔다.
    """
    import pytest

    from pok.kb.ingest.mods import _reject_unexplained_loss
    from pok.kb.store import KBWriteError

    before = {"modifier.a", "modifier.b", "modifier.c"}
    with pytest.raises(KBWriteError, match="근거 없는 레코드 감소"):
        _reject_unexplained_loss(before, {"modifier.a"}, [], "0.5.4b")


def test_감소가_없으면_통과한다() -> None:
    """⛔ 반대 방향 — 게이트가 정상 실행을 막으면 거짓 거부가 된다(#117·#118의 형태)."""
    from pok.kb.ingest.mods import _reject_unexplained_loss

    ids = {"modifier.a", "modifier.b"}
    _reject_unexplained_loss(ids, ids | {"modifier.c"}, [], "0.5.4b")  # 증가는 정상


def test_검사는_쓰기_전에_돈다() -> None:
    """⚠ 예외가 **쓰기 뒤**에 나면 정본이 이미 훼손된 채 남아 「거부했다」가 무의미해진다.

    실측으로 확인했다 — 사후 검사판은 435건을 잡고도 샤드 3개가 지워진 상태로 끝났다.
    """
    import inspect

    from pok.kb.ingest import mods

    src = inspect.getsource(mods.merge_mods)
    check_at = src.index("_reject_unexplained_loss(")
    unlink_at = src.index("stale.unlink()")
    assert check_at < unlink_at, "검사가 삭제보다 앞서야 한다"
