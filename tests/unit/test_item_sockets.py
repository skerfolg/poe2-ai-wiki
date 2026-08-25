"""아이템 룬 소켓 한도를 **오라클이 신고**하는가 (#120).

사용자 신고 2026-08-25: 우리가 낸 PoB 코드에서 아이템을 클릭하면 예외가 났다.
원인은 `Sockets:` 줄에 **존재할 수 없는 칸 수**가 적힌 것이었고(12개 중 4개 초과),
7칸짜리 하나가 PoB 상세보기를 죽였다 — 룬 드롭다운이 6개뿐인데
`ItemsTab:UpdateRuneControls`가 `itemSocketCount`까지 돌며 인덱싱하기 때문이다.

⛔ **계산 경로에서는 안 터진다.** PoB는 `Sockets:` 줄을 그대로 믿고
(`Item.lua:577`) 베이스 한도와 대조하지 않는다 — 그래서 적법성 검사·조립·기록이
전부 통과했다. 검사기는 룬 줄마다 "소켓 한도는 `check_constraints`로 검사하라"고
적어 보냈지만 그 도구는 **에이전트가 칸 수를 손으로 넣어야** 돈다(철칙 5의 전형).
"""

from __future__ import annotations

from pok.pob.runner import RUNE_CONTROL_SLOTS, PobResult, socket_problems


def _row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "1",
        "name": "테스트",
        "base": "Fists of Stone",
        "rarity": "RARE",
        "sockets": 3,
        "limit": 3,
        "limitSource": "base",
        "unknownRunes": [],
    }
    base.update(over)
    return base


def _result(*rows: dict[str, object]) -> PobResult:
    return PobResult(
        stats={}, meta={"items": list(rows)}, allocated_nodes=(), pruned_nodes=(), cached=False
    )


def test_한도_안이면_아무_말도_안_한다() -> None:
    """게이트가 **정상을 막으면 신호가 죽는다**(BACKLOG 형태 ⑤)."""
    assert socket_problems([_row(sockets=3, limit=3), _row(sockets=0, limit=0)]) == ()


def test_베이스_한도_초과를_잡는다() -> None:
    problems = socket_problems([_row(name="Powertread", base="Hunting Shoes", sockets=4, limit=3)])
    assert len(problems) == 1
    # 칸 수·한도·줄일 값이 다 나와야 고칠 수 있다 — "불법"만으로는 못 고친다
    assert "4칸" in problems[0] and "3칸" in problems[0]
    assert "베이스 socketLimit" in problems[0]


def test_유니크는_자기_정의가_한도다() -> None:
    """베이스 한도를 넘는 유니크가 **실재한다** — 베이스로 재면 정상을 거부한다.

    실측(PoB `Data/Uniques`): Atziri's Splendour 6 > 4 · Runeseeker's Call 5 > 3 ·
    Darkness Enthroned 2 > 0. 그중 Runeseeker's Call은 정본 KB에 소켓 문구조차 없어
    (수집 갭) KB로 판정했으면 **거짓 거부**였다. 그래서 판정 주체는 PoB 하나다.
    """
    ok = _row(name="Atziri's Splendour", base="Sacrificial Regalia", rarity="UNIQUE")
    assert socket_problems([{**ok, "sockets": 6, "limit": 6, "limitSource": "unique"}]) == ()
    over = socket_problems([{**ok, "sockets": 7, "limit": 6, "limitSource": "unique"}])
    assert len(over) >= 1 and "유니크 정의" in over[0]


def test_소켓을_못_가지는_베이스도_사유를_말한다() -> None:
    problems = socket_problems(
        [_row(base="Stellar Amulet", sockets=1, limit=0, limitSource="none")]
    )
    assert len(problems) == 1
    assert "룬 소켓을 못 가진다" in problems[0]


def test_상세보기_컨트롤_수를_넘으면_따로_말한다() -> None:
    """한도 초과와 **원인이 다르다** — 이쪽만이 PoB를 예외로 죽인다."""
    problems = socket_problems(
        [
            _row(
                name="Morior Invictus",
                base="Grand Regalia",
                sockets=7,
                limit=4,
                limitSource="unique",
            )
        ]
    )
    assert len(problems) == 2, "한도 초과 + 상세보기 크래시는 별개 사유다"
    crash = next(p for p in problems if "상세보기" in p)
    assert str(RUNE_CONTROL_SLOTS) in crash


def test_한도_안이어도_컨트롤_수를_넘으면_잡는다() -> None:
    """한도가 7인 유니크가 생겨도 상세보기는 여전히 죽는다 — 축이 다르다."""
    problems = socket_problems([_row(sockets=7, limit=7, limitSource="unique")])
    assert len(problems) == 1 and "상세보기" in problems[0]


def test_PoB가_모르는_룬_이름을_잡는다() -> None:
    """미상 룬이 하나라도 있으면 PoB는 `UpdateRunes()`를 **안 돌린다**.

    `Item.lua:1046~1058` — 그러면 손으로 쓴 `{rune}` 줄이 그대로 남아 룬 문구가
    PoB 정의와 어긋나도 아무 말이 없다(조용한 오차).
    """
    problems = socket_problems([_row(unknownRunes=["Rune of Nowhere", "Legacy of Nothing"])])
    assert len(problems) == 1
    assert "Rune of Nowhere" in problems[0] and "2건" in problems[0]


def test_결과가_사실을_그대로_들고_있다() -> None:
    got = _result(_row(sockets=4, limit=3))
    assert len(got.items) == 1 and got.items[0]["sockets"] == 4
    assert not got.is_item_sockets_legal
    assert got.item_socket_problems


def test_옛_결과에는_items가_없어도_안_깨진다() -> None:
    """판 번호를 올려 캐시를 무효화하지만(`_META_PROTOCOL`), 다른 경로에서 온
    `meta`에는 여전히 없을 수 있다. **없음을 「통과」로 읽는다** — 이 축은 거부
    사유를 만들 근거가 없으면 말하지 않는 것이 맞다(거짓 거부 금지).
    """
    old = PobResult(stats={}, meta={}, allocated_nodes=(), pruned_nodes=(), cached=True)
    assert old.items == ()
    assert old.is_item_sockets_legal and old.item_socket_problems == ()
