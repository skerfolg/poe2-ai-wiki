"""롤 선택지 변형·조각화 explicits 보정 — 유니크 큐레이션 테이블 (task #32→확장).

왜 파서 일반 수정이 아니라 큐레이션인가:
① 일부는 PoB `Data/Uniques/*.lua` 텍스트 블록에 없다(주얼 6종은
   `Special/Generated.lua`에서 **Lua 코드로 생성**). poe2db 폴백은 상세 페이지
   element-wise 추출(uniques_page._parse_detail_cards)로 해결하지만, 카드가
   여러 장인 항목(Grip of Kulemak·The Master's Reach)은 카드 선택이 판단이라
   여기서 확정한다.
② 변형(variant)이 패치 이력이 아니라 **롤 선택지**(직업·링 크기·소켓 수·부족명·
   원소 배정·저주·유산)인 항목은 "마지막 변형 = 현재 패치본" 규칙이 오작동 —
   선택지 하나만 남거나(`Split Personality` Warrior만), 동명 별개 베이스가
   소실되거나(`Grand Spectrum` Ruby만), Alt Variant 메타가 새었다. 선택지
   의미(순열 배정·중복 허용·N개 롤)는 아이템마다 달라 일반화하지 않는다.

task #32(커밋 4d807b4)는 사용자 게이트로 주얼 13종에 국한했고, 본 확장(2026-07-31
협의)에서 비주얼 11종을 추가했다.

표기 규약:
- 선택지 변형은 한 줄로 열거한다: `(A/B/C)` — 실제 아이템엔 하나만 롤된다.
- `[...]`·`Passive Skill`·`Specific Skill`은 poe2db 원문 그대로의 플레이스홀더.
- 모드 값은 PoB 우선(D8), PoB에 없으면 poe2db 원문. 러시 정규화만 한다
  (`(1 — 3)`→`(1-3)`, `2 %`→`2%`).
- 한국어(explicits_ko)는 poe2db kr 원문 문형에 선택지 열거를 끼운 것 —
  kr 페이지가 영문을 그대로 쓰는 줄은 원문(영문)대로 둔다.

근거 원문: `artifacts/ingest-raw/0.5.4b/uniques/detail/{us,kr}_<Name>.html`
(2026-07-31 수집) + `external/pob/5d173cb/src/Data/Uniques/*.lua`·
`Special/Generated.lua`.
"""

from __future__ import annotations

from typing import Any

# (name_en, class_group) → item(중간 산출물 dict) 필드 덮어쓰기
UNIQUE_FIXES: dict[tuple[str, str], dict[str, Any]] = {
    # ── poe2db 전용 6종 (PoB Generated.lua = 코드 생성분) ──────────────────
    ("Against the Darkness", "other"): {
        # 종전: implicit용 내부 스탯 문자열("local jewel effect base radius [1000]")이
        # explicits에 섞여 있었다 → 반경은 radius 필드로, explicits는 원문 유지
        "implicits": [],
        "explicits": ["[2 Random Jewel Modifiers]"],
        "category": "jewel",
        "radius": "Small (1000)",
        "limited_to": "1",
    },
    ("Flesh Crucible", "other"): {
        "implicits": [],
        "explicits": [
            "Random 1 Keystone Passive Skill [1,33]",
            "(20-10)% less [random stat]",
            "Corrupted",
        ],
        "category": "jewel",
        "limited_to": "1",
    },
    ("Flesh Crucible", "cultivated"): {
        # 종전: 다운사이드 풀 6종이 "(10"·"—"·"20)"… 조각으로 흩어져 있었다.
        # 키스톤 1개 + 아래 풀 중 1줄이 롤된다 (poe2db Cultivated 카드 원문).
        "implicits": [],
        "explicits": [
            "Random 1 Keystone Passive Skill [1,33]",
            "(10-20)% less maximum Life",
            "(10-20)% less maximum Mana",
            "(10-20)% less Armour, Evasion and Energy Shield",
            "(10-20)% less Spirit",
            "(10-20)% less Movement Speed",
            "(10-20)% less Damage",
        ],
        "explicits_ko": [
            "Random 1 Keystone Passive Skill [1,33]",
            "생명력 최대치 (10-20)% 감폭",
            "마나 최대치 (10-20)% 감폭",
            "방어도, 회피, 에너지 보호막 (10-20)% 감폭",
            "정신력 (10-20)% 감폭",
            "이동 속도 (10-20)% 감폭",
            "피해 (10-20)% 감폭",
        ],
        "category": "jewel",
        "limited_to": "1",
    },
    ("From Nothing", "other"): {
        "implicits": [],
        "explicits": [
            "Passives in Radius of Passive Skill can be Allocated"
            " without being connected to your tree",
            "Corrupted",
        ],
        "explicits_ko": [
            "반경 Passive Skill 내 패시브 스킬이 트리와 연결되지 않아도 할당 가능",
            "타락",
        ],
        "category": "jewel",
        "radius": "Small (1000)",
        "limited_to": "1",
    },
    ("Heart of the Well", "other"): {
        # 훼손(Desecrated) 접두 2 + 접미 2 선택 — poe2db 원문 플레이스홀더 유지
        "implicits": [],
        "explicits": [
            "[Custom Desecrated prefix]",
            "[Custom Desecrated prefix]",
            "[Custom Desecrated suffix]",
            "[Custom Desecrated suffix]",
        ],
        "category": "jewel",
        "limited_to": "1",
    },
    ("Megalomaniac", "other"): {
        # 종전: "Allocates"와 "Passive Skill"이 줄로 갈라져 있었다.
        # 노터블 2~3개 랜덤 할당 (poe2db 상세엔 2모드·3모드 팝업이 공존).
        "implicits": [],
        "explicits": [
            "Allocates Passive Skill",
            "Allocates Passive Skill",
            "Allocates Passive Skill",
            "Corrupted",
        ],
        "explicits_ko": [
            "할당 Passive Skill",
            "할당 Passive Skill",
            "할당 Passive Skill",
            "타락",
        ],
        "category": "jewel",
        "limited_to": "1",
    },
    ("Prism of Belief", "other"): {
        # 종전: "+"·"(1"·"—"·"3)"… 조각 — 랜덤 스킬군 +1~3 레벨 한 줄이 원문
        "implicits": [],
        "explicits": [
            "+(1-3) to Level of all Specific Skill Skills",
            "Corrupted",
        ],
        "explicits_ko": [
            "모든 Specific Skill 스킬 레벨 +(1-3)",
            "타락",
        ],
        "category": "jewel",
        "limited_to": "1",
    },
    # ── PoB 수록 7종 (선택지 변형 평탄화 보정) ────────────────────────────
    ("Controlled Metamorphosis", "other"): {
        # 종전: "Selected Alt Variant: 6" 메타 누출 + 링 크기 하나(Massive)만 잔존
        "implicits": [],
        "explicits": [
            "Only affects Passives in (Very Small/Small/Medium-Small/Medium"
            "/Medium-Large/Large/Very Large/Massive) Ring",
            "Passives in Radius can be Allocated without being connected to your tree",
            "-(20-5)% to all Elemental Resistances",
        ],
        "explicits_ko": [
            "(Very Small/Small/Medium-Small/Medium/Medium-Large/Large"
            "/Very Large/Massive) Ring의 패시브 스킬에만 영향을 미침",
            "반경 내 패시브 스킬이 트리와 연결되지 않아도 할당 가능",
            "모든 원소 저항 -(20-5)%",
        ],
        "radius": "Variable (ring variant)",
        "limited_to": "1",
    },
    ("Grand Spectrum", "other"): {
        # 종전: 동명 3종(Ruby/Emerald/Sapphire) 중 Ruby만 잔존 — 이름 dedup 탓.
        # 단일 레코드에 열거한다 — 줄 순서 = variants 순서(Ruby/Emerald/Sapphire).
        # 라벨 접두는 붙이지 않는다(실물 아이템 줄과의 legality 대조가 깨진다).
        # 3레코드 분리는 id 변경이라 사용자 협의 필요.
        "implicits": [],
        "explicits": [
            "2% increased Maximum Life per socketed Grand Spectrum",
            "2% increased Spirit per socketed Grand Spectrum",
            "+6% to all Elemental Resistances per socketed Grand Spectrum",
        ],
        "explicits_ko": [
            "장대한 파장 하나당 최대 생명력 2% 증가",
            "장대한 파장 하나당 정신력 2% 증가",
            "장대한 파장 하나당 모든 원소 저항 +6%",
        ],
        "variants": ["Ruby", "Emerald", "Sapphire"],
        "limited_to": "3",
    },
    ("Heroic Tragedy", "other"): {
        "implicits": [],
        "explicits": [
            "Remembrancing (100-8000) songworthy deeds by the line of (Vorana/Medved/Olroth)",
            "Passives in radius are Conquered by the Kalguur",
            "Historic",
        ],
        "explicits_ko": [
            "(Vorana/Medved/Olroth)의 핏줄이 행한 노래로 남을 공적 (100-8000)개 추모",
            "반경 내 패시브 스킬이 칼구르의 지배를 받음",
            "역사적인 순간",
        ],
        "radius": "Very Large (1500)",
        "limited_to": "1 Historic",
    },
    ("Split Personality", "other"): {
        # 종전: Warrior(마지막 변형) 한 줄만 잔존
        "implicits": [],
        "explicits": [
            "Can Allocate Passive Skills from the (Mercenary/Ranger/Shadow"
            "/Sorceress/Templar/Warrior)'s starting point",
            "Corrupted",
        ],
        "explicits_ko": [
            "(Mercenary/Ranger/Shadow/Sorceress/Templar/Warrior)의"
            " 시작 지점에서 패시브 스킬 할당 가능",
            "타락",
        ],
        "limited_to": "1",
    },
    ("The Adorned", "other"): {
        # 종전: 한 모드가 두 줄로 갈라져 있었다 (PoB 표시용 개행)
        "implicits": [],
        "explicits": [
            "(0-150)% increased Effect of Jewel Socket Passive Skills"
            " containing Corrupted Magic Jewels",
            "Corrupted",
        ],
        "explicits_ko": [
            "타락한 마법 주얼을 장착한 주얼 슬롯 패시브 스킬의 효과 (0-150)% 증가",
            "타락",
        ],
        "limited_to": "1",
    },
    ("The Adorned", "cultivated"): {
        "implicits": [],
        "explicits": [
            "(0-150)% increased Effect of Jewel Socket Passive Skills"
            " containing Corrupted Magic Jewels",
        ],
        "explicits_ko": [
            "타락한 마법 주얼을 장착한 주얼 슬롯 패시브 스킬의 효과 (0-150)% 증가",
        ],
        "limited_to": "1",
    },
    ("Undying Hate", "other"): {
        # 종전: Ulaman(마지막 변형) 한 줄만 잔존.
        # ⚠️ poe2db 0.5.4b는 범위 (79-30977) + "Desecration makes this item
        # unstable" 줄을 보인다 — PoB(5d173cb)는 (100-8000)·해당 줄 없음.
        # D8(PoB=계산 소스) 우선으로 PoB 값을 쓰고 모순은 리포트로 사용자 판정.
        "implicits": [],
        "explicits": [
            "Glorifying the defilement of (100-8000) souls in tribute to"
            " (Amanamu/Kulemak/Kurgal/Tecrod/Ulaman)",
            "Passives in radius are Conquered by the Abyssals",
            "Historic",
        ],
        "explicits_ko": [
            "(Amanamu/Kulemak/Kurgal/Tecrod/Ulaman)에게 바치는 영혼"
            " (100-8000)개를 더럽힌 것을 찬미함",
            "반경 내 패시브 스킬이 심연의 존재들에게 정복됨",
            "역사적인 순간",
        ],
        "radius": "Very Large (1500)",
        "limited_to": "1 Historic",
    },
    ("Voices", "other"): {
        # 종전: 소켓 수 변형 중 4개(마지막)만 잔존 — 2/3/4 롤 열거
        "implicits": [],
        "explicits": [
            "Allocates (2/3/4) Sinister Jewel sockets",
            "Corrupted",
        ],
        "explicits_ko": [
            "험악한 주얼 홈 (2/3/4)개 할당",
            "타락",
        ],
        "limited_to": "1",
    },
    # ── 비주얼 확장 11종 (2026-07-31 협의) — 선택지 변형·Alt Variant·다중 카드 ──
    ("Darkness Enthroned", "other"): {
        # 종전: 장비 부위 변형 중 Shield(마지막)만 잔존
        "implicits": ["Has (1-3) Charm Slot", "Flasks gain 0.17 charges per Second"],
        "explicits": [
            "(50-100)% increased effect of Socketed Augment Items",
            "This item gains bonuses from Socketed Items as though it was"
            " (a Helmet/a Body Armour/Gloves/Boots/a Shield)",
            "Has 2 Augment Sockets (Hidden)",
        ],
        "explicits_ko": [
            "장착된 아이템의 효과 (50-100)% 증가",
            "이 아이템은 (투구/갑옷/장갑/장화/방패)인 것처럼 장착된 아이템의 보너스를 받음",
            "Has 2 Augment Sockets (Hidden)",
        ],
    },
    ("Atziri's Splendour", "armour"): {
        # 종전: 부위 변형 중 Shield(마지막)만 잔존 + 소켓 줄 없음
        "implicits": ["+1 to Level of all Corrupted Skill Gems"],
        "explicits": [
            "Only Soul Cores can be Socketed in this item",
            "This item gains bonuses from Socketed Soul Cores as though it was also"
            " (a Helmet/Gloves/Boots/a Shield)",
            "Has no Attribute Requirements",
            "(80-120)% increased Armour, Evasion and Energy Shield",
            "+(10-20)% to all Elemental Resistances",
            "Skills from Corrupted Gems have 50% of Mana Costs Converted to Life Costs",
            "Has 6 Augment Sockets (Hidden)",
        ],
        "explicits_ko": [
            "이 아이템에는 영혼 핵만 장착 가능",
            "이 아이템은 (투구/장갑/장화/방패)이기도 한 것처럼 장착된 영혼 핵의 보너스를 받음",
            "능력치 요구사항 없음",
            "방어도, 회피, 에너지 보호막 (80-120)% 증가",
            "모든 원소 저항 +(10-20)%",
            "타락한 젬 스킬의 마나 소모의 50%가 생명력 소모로 전환",
            "Has 6 Augment Sockets (Hidden)",
        ],
    },
    ("Morior Invictus", "armour"): {
        # 종전: Alt Variant 메타 4줄이 explicits에 누출, 룬 소켓 모드 3종 소실.
        # 소켓 모드 풀(PoB 현행 변형): Spirit·Life·Mana·Global Defences·
        # All Resistances·Attributes·Chaos Resistance·Stun Threshold·
        # Life Regeneration·Reduced Crit Damage — 이 중 3종이 랜덤 롤(poe2db 표기).
        "implicits": [],
        "explicits": [
            "(300-400)% increased Armour, Evasion and Energy Shield",
            "[3 Random Socket Modifiers]",
            "Has 4 Augment Sockets (Hidden)",
        ],
        "explicits_ko": [
            "방어도, 회피, 에너지 보호막 (300-400)% 증가",
            "[3 Random Socket Modifiers]",
            "Has 4 Augment Sockets (Hidden)",
        ],
    },
    ("Rite of Passage", "other"): {
        # 종전: 아즈메리 혼백 변형 중 Cat(마지막)만 잔존
        "implicits": ["Used when you kill a Rare or Unique enemy"],
        "explicits": [
            "Possessed by Spirit Of The (Owl/Serpent/Primate/Bear/Boar/Ox/Wolf/Stag/Cat)"
            " for (10-20) seconds on use",
        ],
    },
    ("The Vertex", "armour"): {
        # 종전: Equipment/Skill Gems 변형 중 마지막만 잔존 + poe2db의
        # "Has no Attribute Requirements" 줄 누락 (PoB 미수록, poe2db=카탈로그 권위)
        "implicits": [],
        "explicits": [
            "Has no Attribute Requirements",
            "(100-150)% increased Evasion and Energy Shield",
            "(20-30)% increased Critical Hit Chance",
            "+(13-17)% to Chaos Resistance",
            "(Equipment/Skill Gems) have no Attribute Requirements",
        ],
        "explicits_ko": [
            "능력치 요구사항 없음",
            "회피 및 에너지 보호막 (100-150)% 증가",
            "치명타 확률 (20-30)% 증가",
            "카오스 저항 +(13-17)%",
            "(장비/스킬 젬)에 능력치 요구사항 없음",
        ],
    },
    ("Sunsplinter", "armour"): {
        # 종전: "Selected Alt Variant: 7"이 implicit로 누출, 최대 저항 3줄 소실,
        # 레벨 3줄은 마지막 순열만 잔존. 1·2·3은 원소별 중복 없는 **순열 배정**이며
        # 레벨 배정과 최대 저항 배정은 서로 독립이다 (PoB 변형 6x6, D8).
        "implicits": ["Grants Skill: Parry"],
        "explicits": [
            "(100-300)% increased Evasion Rating",
            "+(1/2/3) to Level of all Fire Skills",
            "+(1/2/3) to Level of all Cold Skills",
            "+(1/2/3) to Level of all Lightning Skills",
            "+(1/2/3)% to Maximum Fire Resistance",
            "+(1/2/3)% to Maximum Cold Resistance",
            "+(1/2/3)% to Maximum Lightning Resistance",
        ],
        "explicits_ko": [
            "회피 (100-300)% 증가",
            "모든 화염 스킬 레벨 +(1/2/3)",
            "모든 냉기 스킬 레벨 +(1/2/3)",
            "모든 번개 스킬 레벨 +(1/2/3)",
            "화염 저항 최대치 +(1/2/3)%",
            "냉기 저항 최대치 +(1/2/3)%",
            "번개 저항 최대치 +(1/2/3)%",
        ],
    },
    ("The Unborn Lich", "weapon"): {
        # 종전: Alt Variant 메타 5줄이 implicits에 누출, His 스킬 변형 소실,
        # 훼손 접사 자리가 Unholy Might(마지막 변형) 값으로 채워짐.
        # 훼손 접사 롤 풀(PoB): Elemental Damage+Ailment Duration / Spirit+
        # Reservation / Chaos Damage+Curse / Spell Phys+Bleed / Chaos Damage+
        # Explode / Unholy Might — poe2db 카드는 접사 플레이스홀더로 표기.
        "implicits": [
            "Grants Skill: Level (1-20) Feast of Flesh",
            "Grants Skill: Level (1-20) (His Dark Horizon/His Foul Emergence"
            "/His Grave Command/His Scattering Calamity/His Vile Intrusion"
            "/His Winnowing Flame)",
        ],
        "explicits": [
            "(60-80)% increased Desecrated Modifier magnitudes",
            "[Custom Desecrated prefix]",
            "[Lich's Desecrated prefix]",
            "[Lich's Desecrated suffix]",
            "[Lich's Desecrated suffix]",
        ],
        "explicits_ko": [
            "훼손된 속성 강도 (60-80)% 증가",
            "[Custom Desecrated prefix]",
            "[Lich's Desecrated prefix]",
            "[Lich's Desecrated suffix]",
            "[Lich's Desecrated suffix]",
        ],
    },
    ("Cursecarver", "weapon"): {
        # 종전: 저주 변형 중 Temporal Chains(마지막)만 잔존
        "implicits": ["Grants Skill: Level (1-20) Decompose"],
        "explicits": [
            "(80-100)% increased Spell Damage",
            "(10-20)% increased Cast Speed",
            "Lose 10 Life per enemy killed",
            "(30-50)% increased Mana Regeneration Rate",
            "+4 to Level of (Elemental Weakness/Vulnerability/Despair/Enfeeble"
            "/Temporal Chains) Skills",
        ],
        "explicits_ko": [
            "주문 피해 (80-100)% 증가",
            "시전 속도 (10-20)% 증가",
            "처치한 적 하나당 생명력 10 상실",
            "마나 재생 속도 (30-50)% 증가",
            "(원소 약화/취약성/절망/무기력/시간의 사슬) 스킬 레벨 +4",
        ],
    },
    ("Mageblood", "other"): {
        # 종전: Alt Variant 메타 6줄 누출 + 유산 변형 중 Topaz(마지막)만 잔존.
        # 유산(Mage's Legacy) 4개 롤, 중복 허용(Allow Duplicate Variants) —
        # 중복 시 효과 증가 줄과 시너지.
        "implicits": ["Has (1-3) Charm Slot", "20% of Flask Recovery applied Instantly"],
        "explicits": [
            "All Mage's Legacies have (25-50)% increased effect"
            " per duplicate Mage's Legacy you have",
            "Legacy of (Amethyst/Basalt/Bismuth/Diamond/Gold/Granite/Jade"
            "/Quicksilver/Ruby/Sapphire/Silver/Stibnite/Sulphur/Topaz)",
            "Legacy of (Amethyst/Basalt/Bismuth/Diamond/Gold/Granite/Jade"
            "/Quicksilver/Ruby/Sapphire/Silver/Stibnite/Sulphur/Topaz)",
            "Legacy of (Amethyst/Basalt/Bismuth/Diamond/Gold/Granite/Jade"
            "/Quicksilver/Ruby/Sapphire/Silver/Stibnite/Sulphur/Topaz)",
            "Legacy of (Amethyst/Basalt/Bismuth/Diamond/Gold/Granite/Jade"
            "/Quicksilver/Ruby/Sapphire/Silver/Stibnite/Sulphur/Topaz)",
        ],
    },
    ("Grip of Kulemak", "other"): {
        # 비-PoB·다중 카드(훼손 모드 0~4개 진행 상태별 5장) — 병합해 한 레코드로
        "implicits": ["Inflict Abyssal Wasting on Hit"],
        "explicits": [
            "(20-30)% reduced Presence Area of Effect",
            "(20-30)% reduced Light Radius",
            "[Can gain (0-4) custom Desecrated Modifiers]",
        ],
        "explicits_ko": [
            "접근 효과 범위 (20-30)% 감소",
            "시야 반경 (20-30)% 감소",
            "[Can gain (0-4) custom Desecrated Modifiers]",
        ],
    },
    ("The Master's Reach", "armour"): {
        # 비-PoB·다중 카드 — 표준판(레벨 15 Untether)을 정본으로 기록.
        # 두 번째 카드(레벨 1 Untether·플레이어 레벨 비례 방어·Unmodifiable)는
        # 별개 획득 경로의 변종으로 보임 — 별도 레코드 여부는 사용자 판정 대기.
        "implicits": ["Grants Skill: Level 15 Untether"],
        "explicits": [
            "(200-300)% increased Armour and Energy Shield",
            "+(75-125) to maximum Life",
            "+(15-25) to Intelligence",
            "Reveal Weaknesses against Rare and Unique enemies",
            "(80-100)% of damage taken from enemies with an Open Weakness Recouped as Life",
            "Eat a Soul when you Hit an enemy with an Open Weakness",
        ],
        "explicits_ko": [
            "방어도 및 에너지 보호막 (200-300)% 증가",
            "생명력 최대치 +(75-125)",
            "지능 +(15-25)",
            "희귀 및 고유 적의 약점을 드러냄",
            "(80-100)% of damage taken from enemies with an Open Weakness Recouped as Life",
            "Eat a Soul when you Hit an enemy with an Open Weakness",
        ],
    },
}


def apply_unique_fixes(items: list[dict[str, Any]]) -> int:
    """중간 산출물 items에 유니크 보정을 제자리 적용한다. 반환 = 적용 건수.

    보정 대상에선 이 표가 explicits_ko까지 권위다 — 상세 페이지 자동 추출분이
    남아 있으면 보정된 explicits와 줄이 어긋날 수 있어, 표가 정의하지 않은
    explicits_ko는 지운다.
    """
    applied = 0
    for item in items:
        fix = UNIQUE_FIXES.get((item["name_en"], item["class_group"]))
        if fix is None:
            continue
        if "explicits_ko" not in fix:
            item.pop("explicits_ko", None)
        item.update(fix)
        applied += 1
    return applied


__all__ = ["UNIQUE_FIXES", "apply_unique_fixes"]
