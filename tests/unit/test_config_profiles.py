"""측정 config 프로파일 계약 (2026-08-22).

PoB 기본 config는 아무 조건도 안 켠 상태라, 조건부 노드가 **계산은 되는데 0**으로
나온다 — 못 재는 게 아니라 안 켠 것이다. 판정 큐 37건 중 14건이 여기 해당한다.

가정을 숨기지 않는 것이 이 모듈의 존재 이유다: 어느 조건을 켤지는 판단이므로
(철칙 3) 상수로 박지 않고 **이름 붙은 프로파일**로 낸다.
"""

from __future__ import annotations

from pok.engine.config_profiles import BASELINE, BOSS, PROFILES
from pok.pob.buildxml import spec_from_dict


def _spec(config=()):
    return spec_from_dict(
        {
            "class_name": "Witch",
            "ascendancy": "Witch1",
            "level": 90,
            "tree_nodes": [],
            "config": list(config),
        },
        validate_catalog=False,
    )


def test_빌드_자기_config를_덮어쓰지_않는다() -> None:
    """⛔ 통째로 갈아 끼우면 빌드 작성자의 가정이 사라진다.

    실측 2026-08-22: 래더 블러드 메이지 DPS가 1,362,791 → 1,293,578로 떨어졌는데,
    그건 프로파일 효과가 아니라 **원본 config 17개를 지운 손실**이었다.
    """
    spec = _spec([("conditionEnemyMaimed", True), ("enemyIsBoss", "None")])
    got = dict(BOSS.apply(spec).config)
    assert got["conditionEnemyMaimed"] is True, "원본 가정이 사라졌다"
    assert got["enemyIsBoss"] == "Boss", "같은 키는 프로파일이 이겨야 한다"


def test_기준선은_원본을_그대로_둔다() -> None:
    """대조군은 아무것도 안 바꿔야 대조가 된다."""
    spec = _spec([("conditionEnemyShocked", True)])
    assert dict(BASELINE.apply(spec).config) == dict(spec.config)


def test_프로파일마다_근거가_있다() -> None:
    """⛔ 이름만 있고 근거가 없으면 「무엇을 가정했나」를 되짚을 수 없다 —
    그러면 수치가 무슨 상황의 것인지 모른 채 정본에 들어간다."""
    for name, profile in PROFILES.items():
        assert profile.why.strip(), f"{name}: 근거가 없다"
        assert profile.name == name


def test_상태이상은_조건별로_쪼개져_있다() -> None:
    """⛔ 뭉쳐 두면 **어느 조건이 노드를 열었는지 측정이 말해 주지 않는다** — 근거가
    측정이 아니라 문구 추론이 된다(사용자 정리 2026-08-22).

    쪼갠 뒤 실측: Power Conduction→shocked 3.42% · Thin Ice→frozen 18.87% ·
    Heavy Frost→frozen 29.44% · Predatory Instinct→open-weakness 33.35%.
    뭉쳐 있을 땐 전부 「ailment에서 열림」까지만 나왔다.
    """
    for name in ("shocked", "frozen", "ignited", "open-weakness"):
        assert len(PROFILES[name].toggles) == 1, f"{name}: 조건이 섞여 있다"
        assert "빌드에서만" in PROFILES[name].why or "구성" in PROFILES[name].why


def test_상태이상을_기본으로_켜지_않는다() -> None:
    """⛔ 화염 주입 빌드는 점화를, 감전 빌드는 감전을 켜야 맞다 — **빌드 메커니즘에
    달린 판단**이라 엔진이 대신 못 한다(사용자 정리). 기본 경로는 원본 그대로다."""
    assert BASELINE.toggles == (), "기준선이 조건을 켠다"
    ailment_keys = {"conditionEnemyShocked", "conditionEnemyFrozen", "conditionEnemyIgnited"}
    assert not ({k for k, _ in BOSS.toggles} & ailment_keys), (
        "보스전 프로파일이 상태이상을 끌고 들어온다 — 빌드 메커니즘과 무관해야 한다"
    )


def test_액트_보상은_복원본이_들고_온다() -> None:
    """액트 보상 선택(저항 5%·능력치 5·이동속도…)은 **빌드 주인의 선택**이고
    PoB 코드에 실려 온다 — 엔진이 정할 것이 아니라 **보존할** 것이다.
    실측 2026-08-22: 기준 빌드에 quest 선택 8건이 그대로 들어 있었다."""
    spec = _spec([("questAct 4Halls Of The DeadTawhoa's Test", "+5% to Lightning Resistance")])
    got = dict(BOSS.apply(spec).config)
    assert got["questAct 4Halls Of The DeadTawhoa's Test"] == "+5% to Lightning Resistance"
