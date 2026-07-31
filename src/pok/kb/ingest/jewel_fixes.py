"""고유 주얼 13종 explicits 보정 — 주얼 한정 큐레이션 테이블 (task #32).

왜 파서 일반 수정이 아니라 큐레이션인가:
① 6종(Against the Darkness·Flesh Crucible·From Nothing·Heart of the Well·
   Megalomaniac·Prism of Belief)은 PoB `Data/Uniques/*.lua` 텍스트 블록에 없다 —
   `Special/Generated.lua`에서 **Lua 코드로 생성**되므로 텍스트 파서가 못 읽는다.
   그래서 poe2db 목록 페이지 텍스트로 폴백했는데, `get_text("\\n")`이 인라인 태그
   (`span.mod-value`·키워드 링크·`span.ndash`) 경계마다 줄을 끊어 모드가 조각났다.
② 7종(PoB 수록분)은 변형(variant)이 패치 이력이 아니라 **롤 선택지**(직업·링 크기·
   소켓 수·부족명)라서 "마지막 변형 = 현재 패치본" 규칙이 오작동 — 선택지 하나만
   남거나(`Split Personality` Warrior만), 동명 별개 베이스가 소실되거나
   (`Grand Spectrum` Ruby만), 메타 줄이 새어 들어갔다(`Selected Alt Variant: 6`).
③ 같은 결함이 주얼 밖에도 있으나(예: Mageblood의 `Selected Alt Variant` 누출,
   비-PoB 24종의 조각난 모드) **이번 교정은 주얼 13종으로 국한**한다 — knowledge/
   diff가 13종을 벗어나면 안 된다는 사용자 게이트(2026-07-31) 때문에 파서 전역
   수정 대신 이 테이블을 쓴다.

표기 규약:
- 선택지 변형은 한 줄로 열거한다: `(A/B/C)` — 실제 아이템엔 하나만 롤된다.
- `[...]`·`Passive Skill`·`Specific Skill`은 poe2db 원문 그대로의 플레이스홀더.
- 모드 값은 PoB 우선(D8), PoB에 없으면 poe2db 원문. 러시 정규화만 한다
  (`(1 — 3)`→`(1-3)`, `2 %`→`2%`).
- 한국어(explicits_ko)는 poe2db kr 원문 문형에 선택지 열거를 끼운 것 —
  kr 페이지가 영문 플레이스홀더를 그대로 쓰는 항목은 부착하지 않는다.

근거 원문: `artifacts/ingest-raw/0.5.4b/uniques/detail/{us,kr}_<Name>.html`
(2026-07-31 수집) + `external/pob/5d173cb/src/Data/Uniques/jewel.lua`·
`Special/Generated.lua`.
"""

from __future__ import annotations

from typing import Any

# (name_en, class_group) → item(중간 산출물 dict) 필드 덮어쓰기
JEWEL_FIXES: dict[tuple[str, str], dict[str, Any]] = {
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
}


def apply_jewel_fixes(items: list[dict[str, Any]]) -> int:
    """중간 산출물 items에 주얼 보정을 제자리 적용한다. 반환 = 적용 건수."""
    applied = 0
    for item in items:
        fix = JEWEL_FIXES.get((item["name_en"], item["class_group"]))
        if fix is None:
            continue
        item.update(fix)
        applied += 1
    return applied


__all__ = ["JEWEL_FIXES", "apply_jewel_fixes"]
