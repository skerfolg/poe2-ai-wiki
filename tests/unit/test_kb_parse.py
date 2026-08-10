"""poe2db 파싱 — 무엇이 효과 문구이고 무엇이 엔진 내부값인가 (#8-c)."""

from __future__ import annotations


def test_engine_internal_phrases_are_not_effect_text() -> None:
    """띄어 쓴 엔진 내부 문구는 효과 문구가 아니다 (#8-c, 사용자 판정 2026-08-09).

    `_INTERNAL_ID`가 **공백 없는** 식별자만 걸러서 이 형태가 통과했고, Skill 3,526줄 ·
    Support 208줄이 효과 문구인 척 수록돼 있었다. 판정 근거는 꼬리 `[N]`이다 —
    poe2db가 내부 stat의 **원값**을 그렇게 표기한다.
    """
    from pok.kb.ingest.parse import _INTERNAL_PHRASE

    for line in (
        "is area damage [1]",
        "base deal no damage [1]",
        "movement speed +% final while performing action [-70]",
        "monster no drops or experience [1]",
    ):
        assert _INTERNAL_PHRASE.fullmatch(line), line

    # 게이트는 양방향 — 진짜 효과 문구를 삼키면 스킬 설명이 통째로 빈다
    for line in (
        "Deals 76.52 to 114.8 Physical Damage",
        "Fires 5 additional Projectiles",
        "+15% to Critical Hit Chance",
        "50% increased Ignite Magnitude",
    ):
        assert not _INTERNAL_PHRASE.fullmatch(line), line


def test_engine_phrases_are_moved_not_deleted() -> None:
    """효과 문구에서는 빠지되 **사라지지는 않는다** (사용자 우려 2026-08-09).

    처음엔 지웠는데 재 보니 921종 중 **609종(66%)이 값 1이 아니었다** — 실수치가
    섞여 있다(`bell shockwave cooldown ms [100]` · `toxic domain mana cost +% [25]`).
    문제는 **효과 문구인 척** `stats`에 있었던 것이지 존재 자체가 아니었다.
    """
    from pok.common.paths import knowledge_dir
    from pok.kb.ingest.parse import _INTERNAL_PHRASE
    from pok.kb.store import load

    store = load(knowledge_dir())
    leftovers = [
        (rid, text)
        for rid, rec in store.records.items()
        for text in (rec.raw.get("data") or {}).get("stats") or []
        if isinstance(text, str) and _INTERNAL_PHRASE.fullmatch(text.strip())
    ]
    assert not leftovers, f"효과 문구에 남아 있다: {leftovers[:5]}"

    moved = sum(
        len((rec.raw.get("data") or {}).get("engine_stats") or []) for rec in store.records.values()
    )
    assert moved > 3000, f"옮긴 줄이 {moved}건 — 지워졌다면 복구할 것"
