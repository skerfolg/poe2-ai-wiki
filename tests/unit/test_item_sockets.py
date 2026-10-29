"""아이템 룬 소켓 표현 한계와 원시 PoB 참고값을 신고하는가 (#120·#192).

사용자 신고 2026-08-25: 우리가 낸 PoB 코드에서 아이템을 클릭하면 예외가 났다.
원인은 `Sockets:` 줄의 칸 수와 PoB의 표현 한계였다 — 룬 드롭다운이 6개뿐인데
`ItemsTab:UpdateRuneControls`가 `itemSocketCount`까지 돌며 인덱싱한다.

⛔ **계산 경로에서는 안 터진다.** PoB는 `Sockets:` 줄을 그대로 믿고(`Item.lua:577`)
어디와도 대조하지 않는다 — 적법성 검사·조립·기록이 전부 통과했다.

⚠⚠ **첫 판은 베이스 한도로 쟀고, 그래서 정상 3건을 거부했다.** 마셜 아티스트
`Runic Meridians`(39552)가 투구+1·갑옷+2·장갑+1·장화+1을 주는데 PoB는 그 노드를
한 줄도 파싱하지 못한다. 이 모듈은 원시 메타데이터와 편집기 표현 검사를 맡는다.
게임 내 획득 가능성은 `test_socket_acquisition.py`의 별도 검사 대상이다.
"""

from __future__ import annotations

from pok.pob.runner import (
    RUNE_CONTROL_SLOTS,
    PobResult,
    socket_budget,
    socket_problems,
    socket_warnings,
)


def _row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "1",
        "name": "테스트",
        "base": "Fists of Stone",
        "rarity": "RARE",
        "slot": "Gloves",
        "sockets": 3,
        "limit": 3,
        "limitSource": "base",
        "grant": 0,
        "corrupted": False,
        "unknownRunes": [],
    }
    base.update(over)
    return base


def _result(*rows: dict[str, object]) -> PobResult:
    return PobResult(
        stats={}, meta={"items": list(rows)}, allocated_nodes=(), pruned_nodes=(), cached=False
    )


# ── 막는 것: PoB가 **표현하지 못하는** 칸 수 하나뿐 ────────────────────────


def test_상세보기_컨트롤_수를_넘으면_막는다() -> None:
    """유일한 차단 사유다 — 인게임 가부가 아니라 **도구 한계**로 막는다."""
    problems = socket_problems([_row(name="Morior Invictus", slot="Body Armour", sockets=7)])
    assert len(problems) == 1
    assert str(RUNE_CONTROL_SLOTS) in problems[0] and "표현하지 못한다" in problems[0]


def test_컨트롤_수까지는_막지_않는다() -> None:
    """Atziri's Splendour가 정확히 6칸이다 — 6을 막으면 정상 유니크가 죽는다."""
    assert socket_problems([_row(sockets=RUNE_CONTROL_SLOTS, limit=RUNE_CONTROL_SLOTS)]) == ()


def test_PoB_참고값_초과만으로_표현_불가라_하지_않는다() -> None:
    """원시 참고값과 편집기 상한을 구분한다. 획득 검사는 별도다."""
    over = [_row(name="Powertread", slot="Boots", base="Hunting Shoes", sockets=5, limit=3)]
    assert socket_problems(over) == (), "PoB 참고값 초과가 곧 표현 불가는 아니다"
    assert socket_warnings(over), "그래도 조용히 넘기지는 않는다"


# ── 참고값: PoB 베이스/유니크 limit + 관측된 트리 부여 ─────────────────────


def test_관측된_트리_부여가_참고값에_들어간다() -> None:
    """`Runic Meridians`(39552) — PoB는 이 노드를 한 줄도 파싱하지 못한다.

    실측 2026-08-25: 이걸 빼고 쟀더니 신고 빌드 4건 중 **3건이 거짓 거부**였고
    셋 다(투구 3+1 · 장갑 3+1 · 장화 3+1) 이 노드 하나로 정확히 설명됐다.
    """
    granted = _row(slot="Gloves", sockets=4, limit=3, grant=1)
    assert socket_budget(granted) == 4
    assert socket_warnings([granted]) == (), "부여를 세면 경고가 아니다"
    assert socket_problems([granted]) == ()


def test_갑옷_2칸_부여도_같은_경로다() -> None:
    body = _row(name="Morior Invictus", base="Grand Regalia", slot="Body Armour")
    ok = {**body, "sockets": 6, "limit": 4, "limitSource": "unique", "grant": 2}
    assert socket_budget(ok) == 6 and socket_warnings([ok]) == ()
    # 추가 한 칸의 획득 경로는 이 메타데이터만으로 판단할 수 없다.
    over_reference = {**ok, "sockets": 7}
    assert socket_warnings([over_reference])
    assert socket_problems([over_reference]), "7칸은 PoB가 못 그린다"


def test_참고값_이하면_초과_진단을_내지_않는다() -> None:
    """경고 없음은 게임 획득 가능성의 증거가 아니다."""
    rows = [_row(sockets=3, limit=3), _row(sockets=0, limit=0, limitSource="none")]
    assert socket_problems(rows) == () and socket_warnings(rows) == ()


# ── 경고 문구가 고칠 만큼 말하는가 ────────────────────────────────────────


def test_경고가_PoB_참고값의_출처와_한계를_밝힌다() -> None:
    warned = socket_warnings(
        [_row(name="Powertread", slot="Boots", base="Hunting Shoes", sockets=5, limit=3, grant=1)]
    )
    assert len(warned) == 1
    assert "5칸" in warned[0] and "4칸" in warned[0]  # 기재 vs 참고값
    assert "트리 부여 1" in warned[0] and "베이스 socketLimit" in warned[0]
    assert "Boots/" in warned[0], "어느 부위인지 없으면 못 고친다"
    assert "게임의 일반 제작 예산이 아니다" in warned[0]
    assert "소켓 획득 검사" in warned[0]


def test_타락_표식만으로_추가_홈_획득을_인정하거나_권하지_않는다() -> None:
    for corrupted in (False, True):
        warned = socket_warnings([_row(sockets=4, limit=3, corrupted=corrupted)])
        assert "`Corrupted` 표식만으로는 이를 증명할 수 없다" in warned[0]
        assert "타락 결과 공존" in warned[0]
        assert "`Corrupted` 줄을 적을 것" not in warned[0]
        assert "아는 예산" not in warned[0]


def test_PoB_한도_정보_없음을_게임에서_소켓_불가로_단정하지_않는다() -> None:
    warned = socket_warnings([_row(sockets=1, limit=0, limitSource="none")])
    assert "PoB 한도 정보 없음" in warned[0]
    assert "룬 소켓을 안 가진다" not in warned[0]


def test_PoB가_모르는_룬_이름을_경고한다() -> None:
    """미상 룬이 하나라도 있으면 PoB는 `UpdateRunes()`를 **안 돌린다**.

    `Item.lua:1046~1058` — 손으로 쓴 `{rune}` 줄이 그대로 남아 값이 조용히 어긋난다.
    막지는 않는다: 우리 KB가 못 따라간 이름일 수도 있다.
    """
    rows = [_row(unknownRunes=["Rune of Nowhere", "Legacy of Nothing"])]
    warned = socket_warnings(rows)
    assert len(warned) == 1
    assert "Rune of Nowhere" in warned[0] and "2건" in warned[0]
    assert socket_problems(rows) == ()


# ── 결과 객체 ─────────────────────────────────────────────────────────────


def test_결과가_사실을_그대로_들고_있다() -> None:
    got = _result(_row(sockets=7, limit=4, grant=2))
    assert len(got.items) == 1 and got.items[0]["sockets"] == 7
    assert not got.is_item_sockets_legal
    assert got.item_socket_problems and got.item_socket_warnings


def test_옛_결과에는_items가_없어도_안_깨진다() -> None:
    """판 번호를 올려 캐시를 무효화하지만(`_META_PROTOCOL`), 다른 경로에서 온
    `meta`에는 여전히 없을 수 있다. **없음을 「통과」로 읽는다** — 이 축은 거부
    사유를 만들 근거가 없으면 말하지 않는 것이 맞다(거짓 거부 금지).
    """
    old = PobResult(stats={}, meta={}, allocated_nodes=(), pruned_nodes=(), cached=True)
    assert old.items == ()
    assert old.is_item_sockets_legal
    assert old.item_socket_problems == () and old.item_socket_warnings == ()
