"""담체 판정 **규칙**만 시험한다 — PoB 데이터 없이 (2026-08-11).

`tests/integration/test_hosting.py`는 실제 PoB 스킬 정의로 대조하는데, CI엔
`Data/Skills/sup_dex.lua` 하나뿐이라 통째로 스킵된다. 그러면 **이 도구의 핵심
의미론이 CI에서 한 번도 안 돌아간다** — 스킵은 "검증했다"가 아니다.

가장 틀리기 쉬운 것이 후위 식 평가다: `{Spell, Totemable, AND}`는 "둘 다"지만
`{Spell, Totemable}`는 "둘 중 하나"다. 집합 포함으로 짜면 **조용히 틀린다**.
그 규칙은 데이터가 필요 없으므로 손으로 만든 게이트로 잠근다.
"""

from __future__ import annotations

from pok.engine.hosting import can_host
from pok.kb.skill_facts import SkillGate


def _gate(
    name: str,
    *,
    types: tuple[str, ...] = (),
    minion_types: tuple[str, ...] = (),
    ignore_minion_types: bool = False,
    require: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
    from_item: bool = False,
    cannot_be_supported: bool = False,
    support_gems_only: bool = False,
    is_support: bool = False,
    catalog_source: str = "",
) -> SkillGate:
    return SkillGate(
        skill_id=name,
        name=name,
        types=frozenset(types),
        require=require,
        exclude=exclude,
        adds=(),
        minion_types=frozenset(minion_types),
        ignore_minion_types=ignore_minion_types,
        from_item=from_item,
        cannot_be_supported=cannot_be_supported,
        support_gems_only=support_gems_only,
        is_support=is_support,
        catalog_source=catalog_source,
    )


def test_and_requires_both() -> None:
    """`(Spell, Totemable, AND)` — 하나만 있으면 안 된다."""
    host = _gate("Totem", require=("Spell", "Totemable", "AND"), is_support=True)
    assert can_host(host, _gate("둘 다", types=("Spell", "Totemable"))).ok
    assert not can_host(host, _gate("Spell만", types=("Spell",))).ok
    assert not can_host(host, _gate("Totemable만", types=("Totemable",))).ok


def test_without_and_it_is_or() -> None:
    """연산자가 없으면 **둘 중 하나**다 — 스택에 참이 하나라도 남으면 통과한다.

    집합 포함(`require <= types`)으로 짰다면 여기서 거부가 나온다.
    """
    host = _gate("느슨", require=("Spell", "Totemable"), is_support=True)
    assert can_host(host, _gate("Spell만", types=("Spell",))).ok


def test_not_inverts_the_top_of_stack() -> None:
    host = _gate("비주문", require=("Spell", "NOT"), is_support=True)
    assert can_host(host, _gate("공격", types=("Attack",))).ok
    assert not can_host(host, _gate("주문", types=("Spell",))).ok


def test_exclusion_wins_over_requirement() -> None:
    """순서는 `canGrantedEffectSupportActiveSkill` 그대로 — 배제가 먼저다."""
    host = _gate("토템", require=("Spell",), exclude=("Persistent",), is_support=True)
    blocked = can_host(host, _gate("지속 주문", types=("Spell", "Persistent")))
    assert not blocked.ok
    assert "Persistent" in blocked.reason, "무엇에 걸렸는지 말해야 뒤집을 수 있다"


def test_item_granted_skills_and_gem_only_carriers() -> None:
    """`fromItem`·`cannotBeSupported`·`supportGemsOnly` 세 플래그."""
    gem_only = _gate("젬 전용", support_gems_only=True, is_support=True)
    assert not can_host(gem_only, _gate("부여 스킬", from_item=True)).ok

    plain = _gate("보통", is_support=True)
    assert not can_host(plain, _gate("보조 불가", cannot_be_supported=True)).ok

    item_support = _gate("아이템 보조", from_item=True, is_support=True)
    assert not can_host(item_support, _gate("부여 스킬", from_item=True)).ok
    assert can_host(item_support, _gate("젬 스킬")).ok


def test_poe2db_gem_source_beats_pob_from_item() -> None:
    """`fromItem`이어도 **poe2db가 젬이라 하면 젬이다** (D8 · 이관 D1, 2026-08-11).

    PoB의 정적 `fromItem`은 젬의 부재를 뜻하지 않는다 — 살아있는 폭탄은 `fromItem`이면서
    `Uncut Skill Gem`으로 커팅되는 tier 3 젬이다. 이 규칙이 없으면 그 스킬이
    **젬 전용 담체에서 거짓 차단**되고, 실제로 컨셉 하나가 폐기될 뻔했다.
    """
    gem_only = _gate("젬 전용", support_gems_only=True, is_support=True)
    dual = _gate("이중 경로", from_item=True, catalog_source="gem")
    item_only = _gate("아이템 전용", from_item=True, catalog_source="item-granted")

    assert can_host(gem_only, dual).ok, "poe2db가 젬이라 한 스킬을 막으면 안 된다"
    assert not can_host(gem_only, item_only).ok
    assert dual.socketable and not item_only.socketable


def test_no_requirement_means_anything_goes() -> None:
    """요구가 비어 있으면 전부 통과다 — PoB의 `not requireSkillTypes[1]` 분기."""
    assert can_host(_gate("무조건", is_support=True), _gate("아무거나")).ok


def test_minion_types_satisfy_requirements_but_not_exclusions() -> None:
    """PoB는 **요구 판정에만** 소환수 타입을 함께 본다 — 배제엔 안 넘긴다.

    `doesTypeExpressionMatch(exclude, skillTypes)` vs
    `doesTypeExpressionMatch(require, skillTypes, minionTypes)`의 비대칭이다.
    빠뜨리면 소환수 빌드에서 거짓 배제가 난다 — 실측 2026-08-11: 이 축 하나로
    **6,335쌍**의 판정이 바뀌었다(스킬 42종이 `minionSkillTypes`를 갖는다).
    """
    host = _gate("주문 요구", require=("Spell",), is_support=True)
    minion_spell = _gate("소환수 주문", types=("Minion",), minion_types=("Spell",))
    assert can_host(host, minion_spell).ok, "소환수의 주문 타입이 요구를 채운다"

    # 배제는 소환수 타입을 보지 않는다 — 본체 타입에만 걸린다
    blocker = _gate("주문 배제", exclude=("Spell",), is_support=True)
    assert can_host(blocker, minion_spell).ok, "배제에는 소환수 타입이 안 넘어간다"


def test_ignore_minion_types_turns_the_axis_off() -> None:
    """`ignoreMinionTypes`인 보조는 소환수 타입을 안 본다 (150종 해당)."""
    host = _gate("주문 요구", require=("Spell",), ignore_minion_types=True, is_support=True)
    minion_spell = _gate("소환수 주문", types=("Minion",), minion_types=("Spell",))
    assert not can_host(host, minion_spell).ok
