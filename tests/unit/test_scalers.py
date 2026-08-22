"""스케일러 크기 판정(#102) — **세 번 반복한 오독**을 각각 회귀로 고정한다.

2026-08-22 빌드 탐색에서 `per Power` 계열을 세 번 연속 과대평가했고 원인이 같았다:
**담체 개수·수치 크기를 배율 크기로 착각**. 문서 경고로는 못 막는다(철칙 5) —
아래 테스트가 각 오독의 재발을 막는다.
"""

from __future__ import annotations

import pytest

from pok.kb import store as kb_store
from pok.kb.graph.scalers import (
    ScalerScan,
    classify_attribution,
    classify_payoff,
    find_cap,
    scan_scalers,
)
from pok.kb.store import Store


@pytest.fixture(scope="module")
def store() -> Store:
    return kb_store.load()


@pytest.fixture(scope="module")
def power(store: Store) -> ScalerScan:
    return scan_scalers(store, input_axis="Power")


# ── 오독 ① 담체가 많다 ≠ 배율이 크다 ────────────────────────────────────


def test_per_power는_대부분_배율이_아니다(power: ScalerScan) -> None:
    """「per Power 17종」을 풍부한 광맥이라 보고했는데 실제 곱연산은 소수다.

    대부분 메타 젬 **에너지 게이지**(resource)와 **횟수**(counter)였다.
    이 비율이 뒤집히면 분류기가 망가진 것이다.
    """
    kinds = dict(power.by_kind)
    assert kinds.get("more", 0) <= 8, "more가 갑자기 늘었다 — 분류가 느슨해졌다"
    assert kinds.get("resource", 0) + kinds.get("counter", 0) >= kinds.get("more", 0) * 2


def test_곱연산만_따로_뽑을_수_있다(power: ScalerScan) -> None:
    """판정의 첫 걸음은 「이 중 진짜 배율이 뭐냐」다 — 그게 한 번에 나와야 한다."""
    more = [s for s in power.scalers if s.payoff_kind == "more"]
    assert more
    assert all("more" in s.evidence.lower() for s in more)


# ── 오독 ② 반경은 페이오프가 아니다 ─────────────────────────────────────


def test_반경_확장은_페이오프가_아니다() -> None:
    """사용자 판정 2026-08-22: *"접근 범위가 넓어진다! 그래서 뭐?"*

    위세(Presence) 담체 93종을 「연쇄」라고 보고했는데, 반경은 배율이 아니다.
    `increased`보다 **먼저** 걸러야 "60% 증가"가 배율처럼 보이지 않는다.
    """
    assert classify_payoff("(60-80)% increased Presence Area of Effect") == "reach"
    assert classify_payoff("Presence Radius is doubled") == "reach"
    assert classify_payoff("Remnants can be collected from 50% further away") == "reach"


def test_면적_배율과_피해_배율을_가른다() -> None:
    """`5% more Area of Effect`는 곱연산이지만 **딜 배율이 아니다** — 경고로 가른다."""
    from pok.kb.graph.scalers import _warnings

    area = _warnings("more", None, "unattributed", True, "5% more Area of Effect per Power")
    assert any("면적" in w for w in area)
    dmg = _warnings("more", None, "unattributed", True, "10% more Damage per Power")
    assert not any("면적" in w for w in dmg)


# ── 오독 ③ 상한을 못 봤다 ───────────────────────────────────────────────


def test_줄이_잘려도_상한을_찾는다() -> None:
    """`Seismic Cry`의 상한이 **다음 줄**에 있어서 못 봤다(실측 2026-08-22).

    "Empowers one Slam per 10 enemy Power in" / "range, counting up to 50 Power"
    — 소문자로 시작하는 줄은 앞줄의 연속이다.
    """
    assert find_cap("Empowers one Slam per 10 enemy Power in range, counting up to 50 Power") == (
        50,
        "line",
    )
    assert find_cap(
        "... to gain Mountain's Teachings on Immobilising an enemy, up to a maximum of 30"
    ) == (30, "line")
    assert find_cap("10% more Damage per Power of killed target") == (None, None)
    # 다른 줄에서 온 상한은 출처가 표시된다 (오탐 가능 — 사람이 원문 확인)
    assert find_cap("10% more damage per allied Totem", ["up to 5 Totems in radius"]) == (
        5,
        "carrier",
    )


def test_상한이_실물에서_붙는다(power: ScalerScan) -> None:
    """정본 실물로 확인 — 이게 깨지면 줄 잇기가 다시 망가진 것이다."""
    by_name = {s.carrier_name: s for s in power.scalers if s.cap is not None}
    assert by_name["Seismic Cry"].cap == 50
    assert by_name["Way of the Mountain"].cap == 30


def test_상한이_있으면_경고가_붙는다() -> None:
    from pok.kb.graph.scalers import _warnings

    assert any("상한" in w for w in _warnings("counter", 50, "unattributed", True))


# ── 프록시 귀속 (인게임 실측 2026-08-22) ────────────────────────────────


def test_무기_귀속은_프록시를_통과하고_플레이어_귀속은_막힌다() -> None:
    """사용자 인게임 확인: 공허의 형상 분신이 가학자의 자비로 때렸을 때

    · *"Hits with **this Weapon** inflict Gruelling Madness"* → **적용됨**(10/10 확인)
    · *"Rare or Unique enemies **you** Hit"*(광기의 선구자) → **발동 안 됨**
    """
    assert classify_attribution("Hits with this Weapon inflict (2-5) Gruelling Madness") == "weapon"
    assert (
        classify_attribution("Draws out an Apparition from Rare or Unique enemies you Hit")
        == "player"
    )
    assert (
        classify_attribution("Enemies in your Presence gain 1 Gruelling Madness each second")
        == "unattributed"
    )


def test_발동_조건이_다른_줄에_있어도_귀속을_잡는다(power: ScalerScan) -> None:
    """광기의 선구자의 배율 줄에는 「you」가 없다 — 조건은 설명문에 있다.

    담체 전체를 안 보면 **차단된 스케일러가 쓸 수 있는 것처럼 보인다**.
    """
    harbinger = [s for s in power.scalers if s.carrier_name == "Harbinger of Madness"]
    assert harbinger
    assert harbinger[0].attribution == "player"
    assert any("프록시" in w for w in harbinger[0].warnings)


# ── 획득 가능성 관문 ────────────────────────────────────────────────────


def test_unused_모드는_아예_안_나온다(power: ScalerScan) -> None:
    """최고 후보였던 `(3-5)% increased Attack damage per Power of target`이

    id가 `...1unused` — 게임 데이터상 미사용이라 담체가 없다. 담체 확인 없이
    설계 근거로 쓸 뻔했다(실측 2026-08-22).
    """
    assert not any("unused" in s.carrier_id.lower() for s in power.scalers)
    assert dict(power.excluded).get("unused-id", 0) >= 1


def test_배제는_조용히_사라지지_않는다(power: ScalerScan) -> None:
    """「없다」와 「걸러냈다」는 다르다 — 사유별로 세어 낸다(#21)."""
    reasons = dict(power.excluded)
    assert reasons
    assert set(reasons) <= {"unused-id", "carrier-unknown", "unknown"}


# ── 어휘 분리 ───────────────────────────────────────────────────────────


def test_신념_충전은_몬스터_Power가_아니다(store: Store) -> None:
    """`per Power Charge`는 **플레이어 자원**이다. 섞으면 판정이 통째로 무너진다.

    정본에 `per Power Charge` 문구가 50건 넘게 있어, 안 가르면 몬스터 Power
    스케일러 17종이 70종처럼 보인다.
    """
    power = scan_scalers(store, input_axis="Power")
    assert not any("Power Charge" in s.evidence for s in power.scalers)
