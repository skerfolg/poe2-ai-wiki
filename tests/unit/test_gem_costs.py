"""ingest/gem_costs — 젬 코스트·점유 전수 수록 (사용자 지시 2026-08-02)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pok.common.paths import project_root
from pok.kb.ingest.gem_costs import apply_gem_costs
from pok.kb.ingest.parse import parse_stats_costs

# 실제 poe2db Stats 텍스트 형태들 (0.5.4b 실측 발췌)
_SKILL = (
    "AoE , Projectile , Fire , Duration , Repeatable Tier: 5 Level: (1 — 20) "
    "Cost: (3 — 37) Mana Cast Time: 0.40 sec Critical Hit Chance: 7.00% "
    "Requires: Level (1 — 90) , (4 — 157) Int"
)
_PERSISTENT = (
    "Persistent , Trigger , Meta Tier: 14 Level: (1 — 20) "
    "Reservation: 100 Spirit Requires: Level (1 — 90)"
)
_SUPPORT_RESV = (
    "Buff , Persistent Category : Cool Headed Tier: 3 Additional Reservation: 15 Spirit "
    "Support Requirements : +5 Str Supports Persistent Buff Skills"
)
_SUPPORT_MULT = (
    "Spell Category : Considered Casting Tier: 2 Cost Multiplier: 115% "
    "Support Requirements : +5 Int"
)


def test_스킬_코스트와_시전시간() -> None:
    got = parse_stats_costs(_SKILL)
    assert got["costs"] == [{"resource": "Mana", "min": 3.0, "max": 37.0}]
    assert got["cast_time_s"] == 0.4
    assert got["reservation"] == [] and got["additional_reservation"] == []


def test_지속_스킬_점유() -> None:
    got = parse_stats_costs(_PERSISTENT)
    assert got["reservation"] == [{"resource": "Spirit", "min": 100.0, "max": 100.0}]
    assert got["costs"] == []


def test_보조_추가_점유는_일반_점유와_구분() -> None:
    got = parse_stats_costs(_SUPPORT_RESV)
    assert got["additional_reservation"] == [{"resource": "Spirit", "min": 15.0, "max": 15.0}]
    assert got["reservation"] == []  # 'Additional Reservation'이 일반 점유로 새면 안 된다


def test_보조_비용_배율() -> None:
    assert parse_stats_costs(_SUPPORT_MULT)["cost_multiplier_pct"] == 115.0


def _html(stats: str, description: str = "") -> str:
    og = f'<meta property="og:description" content="{description}"/>' if description else ""
    return (
        f"<html><head><title>Testspark - PoE2DB</title>{og}</head>"
        f'<body><div class="Stats">{stats}</div></body></html>'
    )


def test_apply_전수_수록_멱등(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    gems = knowledge / "game-data" / "gems"
    gems.mkdir(parents=True)
    record = {
        "id": "skill.testspark",
        "type": "Skill",
        "name": {"ko": "테스트", "en": "Testspark"},
        "tags": [],
        "data": {"category": "spell"},
        "verification": "GAME_DATA",
        "sources": [{"src": "poe2db", "ref": "https://poe2db.tw/us/Testspark", "patch": "t"}],
    }
    (gems / "skills.ndjson").write_text(json.dumps(record) + "\n", encoding="utf-8")
    raw = root / "raw"
    (raw / "poe2db" / "us").mkdir(parents=True)
    (raw / "poe2db" / "us" / "Testspark.html").write_text(
        _html(_SKILL, "Reserve Life instead of Spirit."), encoding="utf-8"
    )
    for _ in range(2):  # 두 번 적용해도 결과 동일 (멱등)
        stats = apply_gem_costs(raw, knowledge)
        assert stats["updated"] == 1 and not stats["missing_html"]
        rec = json.loads((gems / "skills.ndjson").read_text(encoding="utf-8"))
        assert rec["data"]["cost"] == [{"resource": "Mana", "min": 3.0, "max": 37.0}]
        assert rec["data"]["cast_time_s"] == 0.4
        assert rec["data"]["converts_reservation_to"] == "life"
        assert rec["data"]["category"] == "spell"  # 기존 필드 보존


def test_서술형_조건부_점유_추출() -> None:
    """B-4 실증: 조건부 점유는 라벨(`Reservation:`)이 아니라 문장으로,
    그것도 메인 젬 팝업이 아닌 **버프 팝업** 블록에 적힌다."""
    from pok.kb.ingest.parse import parse_conditional_reservation

    buff = "Socketed Curse Skills apply in an Aura around you Reserves 60 Spirit per socketed Curse"
    assert parse_conditional_reservation(buff) == [
        {"resource": "Spirit", "amount": 60.0, "per": "socketed Curse"}
    ]
    # 조건 없는 서술형도 잡는다 / 중복은 제거된다
    assert parse_conditional_reservation("Reserves 30 Spirit. Reserves 30 Spirit") == [
        {"resource": "Spirit", "amount": 30.0}
    ]
    assert parse_conditional_reservation("Cast Time: 0.5 sec") == []


def test_전_Stats_블록을_스캔한다() -> None:
    """페이지에 `.Stats`가 여러 개(메인·버프·보조)라 첫 블록만 보면 놓친다."""
    from pok.kb.ingest.parse import parse_detail

    html = (
        "<html><head><title>T - PoE2DB</title></head><body>"
        '<div class="Stats">Persistent Tier: 8 Level: (1 — 20)</div>'
        '<div class="Stats">Aura around you Reserves 60 Spirit per socketed Curse</div>'
        "</body></html>"
    )
    page = parse_detail(html)
    assert page.tier == 8  # 메인 블록은 그대로
    assert page.conditional_reservation == [
        {"resource": "Spirit", "amount": 60.0, "per": "socketed Curse"}
    ]


def test_cooldown_is_collected_and_absence_is_explicit() -> None:
    """쿨다운 미수록 회귀 (빌드 회차 보고 2026-08-07).

    Skill 401건 전부에 `cooldown` 필드가 없어 **쿨기와 지속 주력기를 구분할 수
    없었다**. 실측 오판: 겨울의 눈을 시전시간 1.4초로만 보고 "초당 1.07시전"을
    전제해 생명력 유출·카오스 획득을 계산했는데 실제로는 10초 쿨다운이었다.
    `quality_stats`엔 "Cooldown Recovery Rate"가 이미 있었다 — 수정 모드는 있는데
    수정 대상인 기저값이 없던 상태다.
    """
    assert parse_stats_costs("Cooldown Time: 10.00 s Cast Time: 1.40 sec")["cooldown_s"] == 10.0
    assert parse_stats_costs("Cooldown Time: 8.00 s")["cooldown_s"] == 8.0
    # 표기가 없으면 파서는 None을 낸다 — 명시적 0으로 바꾸는 것은 호출부(레코드
    # 타입을 아는 곳)의 몫이다. None(미수록)과 0(쿨다운 없음)은 다른 뜻이다.
    assert parse_stats_costs("Cast Time: 0.60 sec")["cooldown_s"] is None


def test_ward_is_a_known_cost_resource() -> None:
    """룬 수호 소모량 미수록 회귀 — 자원 목록에 Ward가 없어 코스트가 통째로 비었다."""
    costs = parse_stats_costs("Cost: (15—81) Ward Cast Time: 0.70 sec")["costs"]
    assert costs == [{"resource": "Ward", "min": 15.0, "max": 81.0}]
