"""임플리싯 후보 축 — 접사 풀에 안 들어오는 경로를 보이게 한다 (백로그 #22)."""

from __future__ import annotations

from pok.engine.implicits import (
    ImplicitOption,
    enumerate_implicits,
    implicit_category,
    render_implicit,
    uncertain_note,
    unmeasurable_note,
)


def test_class_token_is_derived_longest_first() -> None:
    """`BodyArmour`가 `Body`보다 먼저 걸려야 한다 — 짧은 토큰이 삼키면 계열이 틀린다."""
    assert implicit_category("BodyArmourImplicitLife1") == "body"
    assert implicit_category("RingImplicitMaximumQualityAdditional1") == "ring"
    assert implicit_category("TwoHandMaceImplicitStun1") == "mace"
    # 모르면 **None** — 지어내지 않는다
    assert implicit_category("AllAttributesImplicitWreath1") is None


def test_unknown_class_is_kept_but_marked() -> None:
    """빼면 조용한 누락, 섞으면 거짓 정밀 — 뒤로 미루고 **말한다**."""
    records = {
        "item.probe-ring": {
            "type": "Item",
            "name": {"en": "Probe Ring"},
            "data": {"rarity": "normal", "category": "ring", "implicit": "+10 to Strength"},
        },
        "modifier.sure": {
            "type": "Modifier",
            "data": {"pob_key": "RingImplicitChaosDamage", "texts": ["(11-23)% increased Chaos"]},
        },
        "modifier.unsure": {
            "type": "Modifier",
            "data": {"pob_key": "AllAttributesImplicitWreath1", "texts": ["+(16-24) to all"]},
        },
        "modifier.other-slot": {
            "type": "Modifier",
            "data": {"pob_key": "BootsImplicitMovement1", "texts": ["10% increased Movement"]},
        },
    }
    options = enumerate_implicits("Probe Ring", records)
    labels = [o.label for o in options]
    assert "modifier.other-slot" not in labels, "다른 슬롯은 뺀다(클래스가 갈렸다)"
    assert "modifier.unsure" in labels, "모르는 것을 빼면 조용한 누락이다"
    assert options[0].source == "base", "확실한 것부터"
    unsure = next(o for o in options if o.label == "modifier.unsure")
    assert not unsure.slot_certain
    assert "확실하지 않다" in uncertain_note(options)


def test_pob_blindness_is_reported_not_scored_as_zero() -> None:
    """PoB가 못 읽는 문구의 델타 0은 **'측정 안 됨'**이다 (§0 ③)."""
    blind = ImplicitOption("modifier", "modifier.q", ("+20% to Maximum Quality",), False, "unknown")
    assert "측정 안 됨" in unmeasurable_note([blind])
    assert unmeasurable_note([ImplicitOption("base", "x", ("y",))]) == ""


def test_render_declares_the_implicit_count() -> None:
    """선언 없이도 **적용은 된다**(실측) — 그래도 적는 이유는 **접사 한도**다.

    선언이 없으면 검사기가 이 줄을 접사로 세어 한도를 터뜨린다.
    """
    text = "Rarity: RARE\nProbe\nBreach Ring\nItem Level: 80\n+50 to maximum Life"
    out = render_implicit(text, ["+20% to Maximum Quality"]).splitlines()
    assert "Implicits: 1" in out
    assert out.index("Implicits: 1") < out.index("+20% to Maximum Quality")
    # 이미 있으면 갈아 끼운다 — 두 줄이 남으면 PoB가 뒤엣것만 읽는다
    again = render_implicit("\n".join(out), ["+25% to Maximum Quality"])
    assert again.count("Implicits:") == 1


def test_the_users_path_is_actually_enumerable() -> None:
    """사용자가 짚은 경로의 부품이 실제로 후보에 오르는가 — 이게 #22의 본론이다."""
    from pok.engine.implicits import load_records

    options = enumerate_implicits("Breach Ring", load_records())
    labels = {o.label for o in options}
    assert "Breach Ring" in labels, "베이스 자신의 최대 퀄리티 임플리싯"
    assert any("maximumquality" in label for label in labels), sorted(labels)[:5]
    quality = [o for o in options if "maximumquality" in o.label]
    assert quality

    # ⚠ 전부 못 재는 게 아니다 — 표기에 따라 갈린다(실측 2026-08-09):
    #     `+20% to Maximum Quality`  (Additional1·2)  PoB **못 읽음**
    #     `Maximum Quality is 40%`   (Override1)      PoB **읽음**
    # 그래서 "이 축은 측정 불가"라고 뭉뚱그리면 틀린다. 읽히는 표기가 곧 대리 측정의
    # 후보다 — `ItemSpec.substitutes`에 넣을 등가 문구를 여기서 고를 수 있다.
    blind = [o for o in quality if not o.pob_measurable]
    assert blind, "Additional 계열은 못 읽는다 — 그 델타 0은 '값어치 없음'이 아니다"
    assert any(o.pob_measurable for o in quality), "Override 표기는 읽힌다"
    assert "측정 안 됨" in unmeasurable_note(options)
