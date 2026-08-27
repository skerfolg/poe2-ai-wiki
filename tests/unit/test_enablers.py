"""조건 성립기 — **이 노드를 살리려면 무엇이 필요한가** (#125).

`scan_state_edges`(#92)의 54축은 **가하거나 생성하는** 상태다. 조건부 노드가 요구하는
것은 **자신이 처한 상태**로 축이 다르다 — 착수 전 대조에서 `low_life`·`surrounded`·
`moving` 중 어느 것도 그 54축에 없었다.

⚠ 이 시험들은 **사용자 인게임 지적**에서 나왔다(2026-08-27). 초판은 주체를 레코드
단위로 붙였고, 사용자가 *"Execute I~III 이거 보조젬 얘기하는거 아냐? 이거 내가 낮은
생명력일 때 데미지 증폭시켜주는건데?"*라고 짚어 **줄 단위**여야 함이 드러났다.
"""

from __future__ import annotations

import pytest

from pok.kb import store as kb_store
from pok.kb.graph.enablers import (
    CONDITION_AXES,
    DEFAULT_STATES,
    SATISFY_BY,
    _enabler_subject,
    _subject_of,
    axis_report,
    mixed_subject_carriers,
    scan_condition_uses,
    scan_enablers,
)
from pok.kb.store import Store


@pytest.fixture(scope="module")
def store() -> Store:
    return kb_store.load()


def test_execute_iii는_자신용과_적용을_함께_갖는다(store: Store) -> None:
    """⚠ **이 회귀가 존재하는 이유** — 사용자가 인게임 지식으로 짚어 드러났다.

    Execute I·II는 적 전용인데 **III만 자신 쪽 줄이 하나 더 있다**:

        "deal 30% more Damage with Hits while you are on Low Life"             ← self
        "deal 30% more Damage with Hits against Enemies that are on Low Life"  ← enemy

    레코드 단위로 주체를 붙이면 III가 통째로 「적 전용」으로 찍히고, 낮은 생명력 빌드가
    **자기한테 맞는 젬을 후보에서 잃는다.**
    """
    rows = [u for u in scan_condition_uses(store, axis="low_life") if "execute" in u.carrier_id]
    by_id: dict[str, set[str]] = {}
    for row in rows:
        by_id.setdefault(row.carrier_id, set()).add(row.subject)

    assert by_id.get("support.execute-iii") == {"self", "enemy"}, "III의 자신 쪽 줄을 잃었다"
    for gem in ("support.execute-i", "support.execute-ii"):
        assert by_id.get(gem) == {"enemy"}, f"{gem}는 적 전용이어야 한다"


def test_혼재_담체를_따로_낸다(store: Store) -> None:
    """레코드 단위 분류가 깨지는 자리를 **목록으로** 낸다 — 조용히 한쪽으로 접지 않는다."""
    mixed = {m["carrier_id"] for m in mixed_subject_carriers(store)}
    assert "support.execute-iii" in mixed
    assert all(m["axes"] for m in mixed_subject_carriers(store))


def test_주체는_조건_문구_바로_앞에서_잡는다() -> None:
    """⛔ 줄 전체를 보면 적이 **피해 대상**일 뿐인데 조건 주체로 오인된다."""
    line = "Deal 20% more Damage to Enemies while you are on Low Life"
    at = line.index("Low Life")
    assert _subject_of(line, at) == "self"

    enemy_line = "deal more Damage against Enemies that are on Low Life"
    assert _subject_of(enemy_line, enemy_line.index("Low Life")) == "enemy"


def test_성립기_주체는_문장_주어로_잡는다() -> None:
    """⚠ 창(window) 방식이 **양방향으로** 틀렸다 — 그래서 규칙을 나눴다.

    `Require (2-4) fewer enemies to be Surrounded` → 창에 `enemies`가 있지만 포위되는
    것은 **나**다. `Enemies in your Presence count as being on Low Life` → `Enemies`가
    창 **밖**으로 밀리지만 낮은 생명력이 되는 것은 **적**이다.
    """
    assert _enabler_subject("Require (2-4) fewer enemies to be Surrounded") == "self"
    assert _enabler_subject("Enemies in your Presence count as being on Low Life") == "enemy"
    assert _enabler_subject("You count as on Low Life while at 35% of maximum Mana") == "self"


def test_성립기_세_부류가_정본에_있다(store: Store) -> None:
    """`redefine`(무엇이 그 상태로 치나) · `force`(그 상태에 둔다) · `relax`(문턱을 낮춘다).

    실측 2026-08-27: 전부 합쳐 한 자릿수~수십 종이지만 **그것이 「무엇을 사야 하나」의
    답 전부**다.
    """
    made = scan_enablers(store)
    assert {e.kind for e in made} == {"redefine", "force", "relax"}
    ids = {e.carrier_id for e in made}
    assert "item.serpents-lesson" in ids, "마나로 낮은 생명력을 만드는 아이템을 잃었다"
    assert "item.constricting-command" in ids, "포위 문턱 완화 아이템을 잃었다"
    assert "item.cat-o-nine-tails" in ids, "낮은 생명력 강제 아이템을 잃었다"


def test_적_쪽_성립기가_따로_나온다(store: Store) -> None:
    """⚠ 적을 그 상태로 만드는 것은 **자신 페이오프와 짝이 다르다**.

    `Enemies in your Presence count as being on Low Life`는 **Execute I·II**(적 페이오프)를
    켜지, 자신이 낮은 생명력이어야 하는 노드는 안 켠다.
    """
    enemy_made = [e for e in scan_enablers(store) if e.subject == "enemy"]
    assert enemy_made, "적 쪽 성립기를 통째로 잃었다"
    assert any("enemiesinpresence" in e.carrier_id for e in enemy_made)


def test_살_것이_없는_축을_갭으로_찍지_않는다(store: Store) -> None:
    """⛔ **「무엇을 사야 하나」의 답이 범주마다 다르다.**

    `behaviour`(이동·정지·채널링)는 조작이라 **살 것이 없고**, `equipment`는 슬롯을
    채우면 된다. 그 축에서 성립기 0건을 갭으로 보고하면 **없는 갭을 쫓게 만든다**
    (§0 ⑥ — 갭이 닫혔는지는 확인해야 안다의 역방향).
    """
    for row in axis_report(store):
        if row["satisfy_by"] in ("equipment", "behaviour", "form"):
            assert not row["gap_candidate"], f"{row['axis']}: 살 것이 없는 축을 갭으로 찍었다"


def test_기본_상태는_성립기가_없어도_정상이다(store: Store) -> None:
    """`full_life`는 피해를 안 입으면 그 상태다 — 성립기 0건이 **답**이지 갭이 아니다."""
    rows = {r["axis"]: r for r in axis_report(store)}
    assert "full_life" in DEFAULT_STATES
    assert rows["full_life"]["uses"] > 0
    assert not rows["full_life"]["gap_candidate"]


def test_모든_축이_만족_경로를_선언한다() -> None:
    """⛔ 선언 없는 축이 생기면 「살 것이 없다」와 「못 찾았다」가 다시 섞인다."""
    assert {axis for axis, _ in CONDITION_AXES} == set(SATISFY_BY)
    assert set(SATISFY_BY) >= DEFAULT_STATES


def test_적_주체가_과소계상되지_않는다(store: Store) -> None:
    """⚠ 조건 어휘를 `while|if you|when you|during`만 보면 **240줄(+14%)**을 놓친다.

    가장 큰 누락(`on enemies` 124건)이 전부 적 쪽이라 **적 주체가 계통적으로
    과소계상**됐다(형태 ⑭ — 어휘를 절반만 봄. 이번 세션에서 세 번째다).
    """
    enemy = [u for u in scan_condition_uses(store, axis="low_life") if u.subject == "enemy"]
    assert len(enemy) >= 20, (
        f"적 쪽 조건 문구가 {len(enemy)}건으로 줄었다 — 어휘가 좁아졌는지 볼 것"
    )
