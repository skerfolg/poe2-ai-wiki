"""측정 config 프로파일 계약 (2026-08-22).

PoB 기본 config는 아무 조건도 안 켠 상태라, 조건부 노드가 **계산은 되는데 0**으로
나온다 — 못 재는 게 아니라 안 켠 것이다. 판정 큐 37건 중 14건이 여기 해당한다.

가정을 숨기지 않는 것이 이 모듈의 존재 이유다: 어느 조건을 켤지는 판단이므로
(철칙 3) 상수로 박지 않고 **이름 붙은 프로파일**로 낸다.
"""

from __future__ import annotations

import dataclasses

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


def test_스택은_프로파일만으로_영원히_0이다() -> None:
    """#111 — PoB `BuildModList`는 config를 `ifFlag`와 **무관하게** 적용한다.

    (`Classes/ConfigTab.lua:891-901` — 그 조건들은 UI 표시용이다.) 그래서
    `multiplierTailwind=10`을 켜 두면 `Gathering Winds`를 빼도 승수가 남아 델타가
    영원히 0이다. 「켜도 0이니 모델 갭」이라 닫았던 것이 사실은 이 구조였다.

    실측 2026-08-23: 결합을 넣자 25/25벌에서 열렸다 — DPS 9.6%·EHP 12.7%·회피 16.4%.
    """
    from pok.engine.config_profiles import PROFILES, stack_coupler

    stacked = PROFILES["stacked"]
    couple = stack_coupler(stacked)

    spec = _FakeSpec(
        config=(("multiplierTailwind", 10), ("multiplierCombo", 10), ("enemyIsBoss", "Boss"))
    )

    out = couple(spec, 30)  # Gathering Winds — Tailwind의 원천
    assert dict(out.config)["multiplierTailwind"] == 0, "노드를 빼면 그 노드가 준 스택도 0이다"
    assert dict(out.config)["multiplierCombo"] == 10, "다른 스택은 건드리지 않는다"
    assert dict(out.config)["enemyIsBoss"] == "Boss", "스택과 무관한 config는 그대로다"

    assert dict(couple(spec, 12345).config)["multiplierTailwind"] == 10, (
        "원천이 아닌 노드는 그냥 통과한다"
    )


def test_빌드가_직접_켠_승수는_건드리지_않는다() -> None:
    """⚠ 결합은 **가정**이다 — 「이 노드가 그 스택의 유일한 원천이다」.

    그래서 **프로파일이 넣은 키만** 0으로 만든다. 빌드 주인이 자기 config로 들고 온
    승수는 우리 가정이 아니라 그 사람의 선언이므로 그대로 둔다(#104와 같은 자리).
    """
    from pok.engine.config_profiles import BASELINE, stack_coupler

    couple = stack_coupler(BASELINE)  # 아무 토글도 안 넣는 프로파일

    spec = _FakeSpec(config=(("multiplierTailwind", 7),))

    assert dict(couple(spec, 30).config)["multiplierTailwind"] == 7


def test_상태_프로파일은_결합이_필요없다() -> None:
    """상태(질주·적 약점 발현)는 **상황**이지 노드가 만드는 것이 아니다 (#111).

    노드를 빼면 그 상황에 걸린 모드만 빠지므로 토글만으로 델타가 잡힌다 —
    실측: Marathon Runner 25/25벌 · In for the Kill 25/25벌(DPS 17.9%).
    """
    from pok.engine.config_profiles import PROFILES, STACK_SOURCES

    for name in ("sprinting", "open-weakness-presence", "allies"):
        prof = PROFILES[name]
        assert prof.toggles, f"{name}에 토글이 없다"
        keys = {k for k, _ in prof.toggles}
        coupled = {k for src in STACK_SOURCES.values() for k, _ in src}
        assert not (keys & coupled), f"{name}은 상태 프로파일인데 결합 대상 키를 들고 있다"


def test_스택_원천에는_근거가_붙는다() -> None:
    """⛔ 근거 없는 매핑은 「측정된 것」으로 굳어 정본을 오염시킨다 (#97과 같은 형태)."""
    from pok.engine.config_profiles import STACK_SOURCES

    assert STACK_SOURCES, "비어 있으면 이 규율이 아무것도 안 막는다"
    for node_id, entries in STACK_SOURCES.items():
        assert isinstance(node_id, int)
        for key, why in entries:
            assert key.strip() and len(why) > 15, f"{node_id}의 {key}에 근거가 없다"


@dataclasses.dataclass(frozen=True)
class _FakeSpec:
    """`stack_coupler`는 `dataclasses.replace`를 쓴다 — 스펙 전체가 필요하진 않다."""

    config: tuple[tuple[str, object], ...]
