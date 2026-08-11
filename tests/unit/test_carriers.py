"""`item-exclusive` 접사의 담체 확인 — 모드의 존재가 획득 가능성은 아니다 (#39)."""

from __future__ import annotations

import pytest


def _pob_ready() -> bool:
    from pok.kb.pob_pin import pob_src_dir

    return (pob_src_dir() / "Data" / "Uniques").is_dir()


needs_pob = pytest.mark.skipif(not _pob_ready(), reason="external/pob 스냅샷 없음")


def test_generated_uniques_count_as_carriers() -> None:
    """정적 `[[…]]` 블록만 보면 **가짜 고아**가 나온다 (#39).

    `Special/Generated.lua`가 접사 풀에서 유니크를 **만들어 낸다**:
    `Against the Darkness`(`UniqueJewelRadius*`) · `Heart of the Well`(`UniqueHeart*`) ·
    `Loreweave`(`UniqueLoreweave*`) 등. 실측 2026-08-10: 정적만 세면 2,266건(41%)이
    고아였는데 생성분을 세니 2,163건(39.4%)이었다 — **103건이 그 차이**다.
    """
    from pok.pob.carriers import GENERATED_PREFIXES, carrier_kind

    assert carrier_kind({"pob_key": "UniqueJewelRadiusFire", "texts": ["x"]}, set()) == "generated"
    assert carrier_kind({"pob_key": "UniqueHeartThing", "texts": ["x"]}, set()) == "generated"
    assert carrier_kind({"pob_key": "SomethingElse", "texts": ["x"]}, set()) == "unknown"
    assert "UniqueJewelRadius" in GENERATED_PREFIXES


def test_static_carrier_is_matched_by_normalised_text() -> None:
    """롤 범위가 달라도 같은 문구다 — 수치를 뭉개고 맞춘다."""
    from pok.pob.carriers import carrier_kind

    carriers = {"+# to maximum life"}
    assert carrier_kind({"texts": ["+(20-30) to maximum Life"]}, carriers) == "static"
    assert carrier_kind({"texts": ["+50 to maximum Life"]}, carriers) == "static"
    assert carrier_kind({"texts": ["+50 to maximum Mana"]}, carriers) == "unknown"


@needs_pob
def test_the_reported_orphans_are_flagged_in_the_kb() -> None:
    """보고된 오판 사례가 정본에 표시돼 있는가 (빌드 세션 이관, 오판 5건).

    `modifier.uniquestatlifereservation1`("Reserves 15% of Life")로 점유 원장을
    짰다가 폐기했다 — 담체가 없다는 사실이 어디에도 없었기 때문이다.
    """
    from pok.common.paths import knowledge_dir
    from pok.kb.store import load

    store = load(knowledge_dir())
    for record_id in (
        "modifier.uniquestatlifereservation1",
        "modifier.gainfrenzychargeoncriticalhit",
        "modifier.chancetogainfrenzychargeonstununique-1",
    ):
        data = store.get(record_id).raw["data"]
        assert data.get("carrier_unknown") is True, record_id

    # 게이트는 양방향 — 담체가 있는 것에는 안 붙는다
    flagged = [
        rid
        for rid, rec in store.records.items()
        if (rec.raw.get("data") or {}).get("carrier_unknown")
    ]
    assert 1500 < len(flagged) < 3000, f"{len(flagged)}건 — 규모가 크게 달라졌으면 재확인"


@needs_pob
def test_search_hits_carry_the_warning() -> None:
    """정본에만 있으면 못 본다 — **히트에 실려야** 세션이 읽는다(#39 요청안)."""
    from pok.index.search import search

    hits = search("Reserves 15% of Life", type_="Modifier", limit=3)
    target = next(h for h in hits if h.id == "modifier.uniquestatlifereservation1")
    assert target.carrier_unknown and "확인 못 함" in target.carrier_unknown
    assert "획득 불가" in target.carrier_unknown, "「모른다」와 「없다」를 섞지 않는다"


def test_vaal_mutated_affixes_are_not_carrier_unknown() -> None:
    """바알 함양 변이 접사는 **구조적 오탐**이었다 (`[빌드]` 이관 D2, 2026-08-11).

    이 계열은 어느 정적 유니크 정의에도 안 붙어 있다 — 함양 오브가 **사후에** 붙이기
    때문이다. 그래서 "유니크 원문 대조"로는 영영 못 찾고, 계열 전량이 `carrier_unknown`이
    되어 규율상 설계 근거로 쓰이지 못했다. PoB 데이터가 실재를 뒷받침한다:
    `affix=""`·`weightKey={}`(정상 롤 불가)인데 `tradeHashes`는 있다(=거래되는 모드).
    """
    from pok.pob.carriers import carrier_kind

    vaal = {
        "pob_key": "UniqueMutatedVaalSpellDamagePerMana",
        "texts": ["x"],
        "mod_tags": ["mutatedunique_vaal"],
    }
    assert carrier_kind(vaal, set()) == "vaal-mutated"
    # 태그만 있고 접두가 달라도 잡는다 (둘 중 하나면 충분)
    assert (
        carrier_kind({"texts": ["x"], "mod_tags": ["mutatedunique_vaal"]}, set()) == "vaal-mutated"
    )
    # 정적 유니크에 실린 문구면 그쪽이 우선이다 — 담체가 이미 확인된 것이다
    assert (
        carrier_kind({**vaal, "texts": ["+50 to maximum Life"]}, {"+# to maximum life"}) == "static"
    )
    # 무관한 모드는 여전히 unknown
    assert carrier_kind({"pob_key": "SomethingElse", "texts": ["x"]}, set()) == "unknown"


def test_verisium_implicit_names_its_carrier() -> None:
    """베리시움 각인은 **담체를 이름까지 안다** (`[빌드]` 이관 D5, 2026-08-11).

    바알 변이(위)와 같은 계열이지만 결정적 차이가 있다: 담체가 키에 박혀 있다
    (`BloodThornVerisiumImplicit…` → Blood Thorn). 「모른다」로 두면 그 정보를
    **버리는** 것이다 — 실측 31/32가 특정 유니크로 해석된다.

    ⚠ 이름 접기가 없으면 실존 담체를 놓친다: `Mjölner`(발음 구별 기호)와
    `The Sentry`(관사)가 그래서 안 맞았다.
    """
    from pok.pob.carriers import _fold_name, verisium_carrier

    uniques = {"bloodthorn": "item.blood-thorn", "mjolner": "item.mjolner"}
    assert (
        verisium_carrier({"pob_key": "BloodThornVerisiumImplicitBleedMagnitude1"}, uniques)
        == "item.blood-thorn"
    )
    assert (
        verisium_carrier({"pob_key": "MjolnerVerisiumImplicitLightningSkills1"}, uniques)
        == "item.mjolner"
    )
    # 베리시움 각인이 아니면 관여하지 않는다
    assert verisium_carrier({"pob_key": "UniqueMutatedVaalThing"}, uniques) is None
    # 담체를 못 찾으면 **지어내지 않는다** — 미확인으로 남는 게 옳다
    assert verisium_carrier({"pob_key": "NoSuchUniqueVerisiumImplicitX"}, uniques) is None
    assert _fold_name("Mjölner") == "mjolner"
