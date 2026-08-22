"""능동 탐사 — 술어 추출·맞물림 스캔·가설 큐.

문구는 전부 **정본에서 그대로 가져온 실제 텍스트**다(추측 문구 금지). 스캐너가
거짓 양성을 내면 게이트가 마비되므로, 이 파일의 절반은 "잡지 말아야 할 것을
안 잡는가"를 지킨다.
"""

from __future__ import annotations

import json
from pathlib import Path

from pok.kb.graph.predicates import SUPPLIABLE_SUBJECTS, extract_predicates, record_texts
from pok.kb.graph.synergy import scan_synergies
from pok.kb.store import Record, Store
from pok.learning.hypothesis import find_hypotheses

_SUBJECTS = json.loads(
    (Path(__file__).parents[2] / "knowledge/schema/vocab/condition-subjects.json").read_text(
        encoding="utf-8"
    )
)["subjects"]


def _predicates(*texts: str) -> dict[str, str]:
    """{key: direction} 로 납작하게 — 방향까지 같이 봐야 의미가 있다."""
    return {p.key: p.direction for p in extract_predicates(list(texts), _SUBJECTS)}


# ── 요구·공급 추출 (문구는 정본 원문) ─────────────────────────────────


def test_요구_상태이상_against절() -> None:
    # modifier: 100% increased Melee Damage against Shocked Enemies
    assert _predicates("100% increased Melee Damage against Shocked Enemies") == {
        "enemy.status=shocked": "demand"
    }


def test_공급_상태이상_chance_to절() -> None:
    assert _predicates("20% increased chance to Chill") == {"enemy.status=chilled": "supply"}


def test_공급과_요구는_같은_키로_맞물린다() -> None:
    supply = _predicates("20% increased chance to Chill")
    demand = _predicates("Damage Penetrates 20% Cold Resistance against Chilled Enemies")
    assert set(supply) == set(demand)  # 같은 축 — 이 일치가 시너지의 정의다
    assert supply["enemy.status=chilled"] == "supply"
    assert demand["enemy.status=chilled"] == "demand"


def test_로우라이프_요구와_점유_공급() -> None:
    # v6가 실제로 쓴 경로: 생명력 점유로 로우라이프를 만들고 그 조건을 소비한다
    assert _predicates("80% increased Armour and Evasion Rating when on Low Life") == {
        "self.life.low": "demand"
    }
    assert _predicates("Reserves 25% of Life") == {"self.life.low": "supply"}


def test_수치_없는_점유_전환도_공급이다() -> None:
    """앗지리의 성찬식 계열 — %패턴만 있어서 v6의 핵심 경로를 놓쳤었다(2026-08-04)."""
    assert _predicates(
        "Supports Persistent Skills, making them Reserve Life instead of Spirit"
    ) == {"self.life.low": "supply"}
    assert _predicates("Socketed Gems Cost and Reserve Life instead of Mana") == {
        "self.life.low": "supply"
    }


def test_생명력_소모는_점유가_아니다() -> None:
    """로우라이프 공급은 점유(reserve)여야 한다 — 소모는 회복으로 돌아온다
    (사용자 판정 2026-08-04). 아탈루이의 사혈·생명력 전환·자해가 여기 해당한다."""
    assert _predicates("Supports any Skill, turning its Mana cost into a Life cost.") == {}
    assert _predicates("Lose 5% of maximum Life per second") == {}
    assert _predicates("Lose 3% of maximum Life and Energy Shield when you use a Chaos Skill") == {}


def test_적의_생명력_점유는_내_로우라이프가_아니다() -> None:
    assert _predicates("Targets Cursed by you have at least 15% of Life Reserved") == {}
    assert _predicates("Enemies in your Presence have at least 10% of Life Reserved") == {}


def test_충전_획득은_공급_소비는_요구() -> None:
    assert _predicates("20% chance to gain a Frenzy Charge on killing a Frozen enemy") == {
        "self.charge.frenzy": "supply"
    }
    assert _predicates("Consume 3 Endurance Charges to Raise a Totem") == {
        "self.charge.endurance": "demand"
    }


def test_출혈_공급_동사도_잡는다() -> None:
    """Bleed 누락으로 '출혈 요구 15 · 공급 0' 이라는 거짓 갭이 났었다(2026-08-04)."""
    assert _predicates("Attacks have 25% chance to Bleed") == {"enemy.status=bleeding": "supply"}


def test_inflict형_유발이_정본에서_가장_흔하다() -> None:
    """동사형만 잡던 탓에 출혈 공급이 1건으로 보였다 — 실제로는 44건(2026-08-04)."""
    assert _predicates("10% chance to inflict Bleeding on Hit") == {
        "enemy.status=bleeding": "supply"
    }
    assert _predicates("Enemies you Electrocute have 20% increased Damage taken") == {
        "enemy.status=electrocuted": "supply"
    }


def test_유발_부정문은_공급이_아니다() -> None:
    """'cannot inflict Bleeding on you'는 피격 방어 문구다 — 유발로 세면 거짓 공급."""
    assert _predicates("Deflected Hits cannot inflict Bleeding on you") == {}


def test_부정_관문은_패턴마다가_아니라_공통이다() -> None:
    """`(?<!cannot )`을 패턴에 붙이는 방식은 **붙인 패턴만** 막는다.

    실제로 `inflict`에만 붙어 있어서 동사형 패턴이 "Cannot Immobilise enemies"를
    공급으로 셌다(실측 2026-08-21). #93(부정문 오독)의 세 번째 재발이라 관문을
    매칭 지점 앞을 보는 **공통 검사**로 옮겼다 — 새 패턴을 추가해도 자동으로 막힌다.
    """
    assert _predicates("Cannot Immobilise enemies") == {}
    assert _predicates("Hits do not Freeze Enemies") == {}
    # 부정이 아닌 것까지 죽이면 안 된다
    assert _predicates("Immobilise enemies at 50% buildup instead of 100%") == {
        "enemy.status=immobilised": "supply"
    }


def test_동사형_조건절도_요구다() -> None:
    """ "Enemies are Intimidated for 4 seconds **when you Immobilise them**".

    기존 요구 패턴은 전부 과거분사(상태형)만 봐서 이 형태를 놓쳤고, 그 결과 속박
    페이오프가 실제보다 적게 세어졌다(실측 2026-08-21).
    """
    assert _predicates("Enemies are Intimidated for 4 seconds when you Immobilise them") == {
        "enemy.status=immobilised": "demand"
    }


def test_고정은_어휘에_있다() -> None:
    """고정(Pin)은 속박을 만드는 네 경로 중 하나 — 어휘 밖이면 통째로 안 보인다."""
    assert _predicates("25% increased Pin Buildup") == {}  # 축적 스케일은 공급이 아니다
    assert _predicates("Pin Enemies which are Primed for Pinning") == {
        "enemy.status=pinned": "supply"
    }


# ── 잡지 말아야 할 것 ────────────────────────────────────────────────


def test_스케일링은_공급이_아니다() -> None:
    """감전 '규모'를 키우는 건 감전을 *만들지* 않는다 — 공급으로 세면 거짓 시너지."""
    assert _predicates("20% increased Magnitude of Shock you inflict") == {}


def test_어휘_밖_단어는_버린다() -> None:
    """'against Nearby Enemies'의 Nearby는 상태이상이 아니다 (KD-2 통제 어휘)."""
    assert _predicates("10% increased Damage against Nearby Enemies") == {}


def test_근거는_문장_단위로_좁힌다() -> None:
    """여러 효과가 한 필드에 있으면 필드 전체를 근거로 삼을 수 없다(거짓 양성 원인)."""
    text = (
        "Supports Melee Attacks. Bleeding inflicted by those Hits is more effective. "
        "Hits deal more damage against Poisoned Enemies."
    )
    preds = {p.key: p.evidence for p in extract_predicates([text], _SUBJECTS)}
    assert "Poisoned Enemies" in preds["enemy.status=poisoned"]
    assert "Supports Melee Attacks" not in preds["enemy.status=poisoned"]


def test_레코드_필드_차이를_흡수한다() -> None:
    passive = {"data": {"stats_en": ["Reserves 25% of Life"]}}
    modifier = {"data": {"texts": ["+250 to Accuracy against Bleeding Enemies"]}}
    skill = {"data": {"description": "Freeze enemies around you."}}
    assert record_texts(passive) == ["Reserves 25% of Life"]
    assert record_texts(modifier) == ["+250 to Accuracy against Bleeding Enemies"]
    assert record_texts(skill) == ["Freeze enemies around you."]


# ── 맞물림 스캔 ──────────────────────────────────────────────────────


def _store(*specs: tuple[str, str, str]) -> Store:
    records = {
        rid: Record(
            id=rid,
            type="Modifier",
            path=Path("x.ndjson"),
            raw={"name": {"ko": name, "en": name}, "data": {"texts": [text]}},
        )
        for rid, name, text in specs
    }
    return Store(records=records, subjects=_SUBJECTS)


_CHILL_SUPPLY = ("m.supply", "냉기원", "20% increased chance to Chill")
_CHILL_DEMAND = (
    "m.demand",
    "냉기소비",
    "60% increased Critical Hit Chance against Chilled Enemies",
)


def test_스캔은_공급자와_요구자를_잇는다() -> None:
    scan = scan_synergies(_store(_CHILL_SUPPLY, _CHILL_DEMAND))
    assert len(scan.pairs) == 1
    pair = scan.pairs[0]
    assert pair.subject_key == "enemy.status=chilled"
    assert (pair.supplier_id, pair.demander_id) == ("m.supply", "m.demand")
    # 근거 두 줄이 판정의 전부다 (AD-8)
    assert "chance to Chill" in pair.supplier_evidence
    assert "Chilled Enemies" in pair.demander_evidence


def test_자기_자신은_시너지가_아니다() -> None:
    both = ("m.both", "자급", "20% increased chance to Chill against Chilled Enemies")
    scan = scan_synergies(_store(both))
    assert scan.pairs == ()
    assert scan.summary[0].suppliers == 1 and scan.summary[0].demanders == 1


def test_상한_초과는_조용히_자르지_않는다() -> None:
    specs = [_CHILL_SUPPLY, _CHILL_DEMAND, ("m.d2", "냉기소비2", "Damage against Chilled Enemies")]
    scan = scan_synergies(_store(*specs), limit=1)
    assert scan.truncated and len(scan.pairs) == 1
    assert scan.summary[0].pairs == 2  # 요약은 잘리지 않는다 — 규모는 늘 보인다


def test_축_지정하면_그_축만() -> None:
    store = _store(_CHILL_SUPPLY, _CHILL_DEMAND, ("m.p", "권능", "Gain a Power Charge"))
    scan = scan_synergies(store, subject_key="enemy.status=chilled")
    assert {s.subject_key for s in scan.summary} == {"enemy.status=chilled"}


# ── 가설 큐 (게이트 입력) ────────────────────────────────────────────


def test_공급_개념이_없는_축은_갭이라_부르지_않는다(tmp_path: Path) -> None:
    """'이동을 요구하는 효과 47건 · 공급 0'은 발견이 아니라 사정거리 밖이다."""
    store = _store(("m.move", "이동", "(25-30)% increased Damage while Moving"))
    assert find_hypotheses(store, root=tmp_path) == ()
    assert "self.moving" not in SUPPLIABLE_SUBJECTS


def test_수급_불균형은_갭으로_올린다(tmp_path: Path) -> None:
    specs = [_CHILL_SUPPLY] + [
        (f"m.d{i}", f"냉기소비{i}", "Damage against Chilled Enemies") for i in range(4)
    ]
    gaps = [h for h in find_hypotheses(_store(*specs), root=tmp_path) if h.kind == "gap"]
    assert len(gaps) == 1
    assert gaps[0].subject_key == "enemy.status=chilled"
    assert "공급 1" in gaps[0].evidence and "요구 4" in gaps[0].evidence


def test_이미_탐사한_조합은_후보에서_빠진다(tmp_path: Path) -> None:
    design = tmp_path / "artifacts" / "builds" / "b1"
    design.mkdir(parents=True)
    (design / "design.md").write_text("냉기원 과 냉기소비 를 함께 썼다", "utf-8")
    pairs = [
        h
        for h in find_hypotheses(_store(_CHILL_SUPPLY, _CHILL_DEMAND), root=tmp_path)
        if h.kind == "pair"
    ]
    assert pairs == []


def test_한_공급자가_큐를_독점하지_못한다(tmp_path: Path) -> None:
    """첫 큐는 12칸을 전부 같은 공급자로 채웠다 — 다양성 없으면 탐사가 아니다."""
    # 요구는 서로 달라야 한다 — 수치만 다르면 티어 변종으로 먼저 접힌다
    demands = [
        "Culling Strike against Chilled Enemies",
        "Damage Penetrates Cold Resistance against Chilled Enemies",
        "increased Critical Hit Chance against Chilled Enemies",
        "increased Accuracy against Chilled Enemies",
    ]
    specs = [_CHILL_SUPPLY] + [(f"m.d{i}", f"냉기소비{i}", text) for i, text in enumerate(demands)]
    pairs = [h for h in find_hypotheses(_store(*specs), root=tmp_path) if h.kind == "pair"]
    assert len(pairs) == 2  # _MAX_PER_SUPPLIER


def test_한_축이_큐를_독점하지_못한다(tmp_path: Path) -> None:
    specs = [
        ("m.s1", "냉기원1", "20% increased chance to Chill"),
        ("m.s2", "냉기원2", "30% increased chance to Chill"),
        ("m.s3", "냉기원3", "40% increased chance to Chill"),
        ("m.d1", "냉기소비", "Culling Strike against Chilled Enemies"),
        ("m.p1", "권능원", "Gain a Power Charge on Hit"),
        ("m.p2", "권능소비", "Consume a Power Charge to empower"),
    ]
    pairs = [h for h in find_hypotheses(_store(*specs), root=tmp_path) if h.kind == "pair"]
    chilled = [p for p in pairs if p.subject_key == "enemy.status=chilled"]
    assert len(chilled) == 2  # _MAX_PER_SUBJECT — 공급자가 3이어도 축 상한이 먼저
    assert any(p.subject_key == "self.charge.power" for p in pairs)  # 다른 축도 자리를 얻는다


def test_티어_변종은_한_후보로_접는다(tmp_path: Path) -> None:
    """수치만 다른 같은 요구를 별개로 세면 큐 자리가 낭비된다(2026-08-04)."""
    specs = [
        _CHILL_SUPPLY,
        ("m.d1", "냉기소비1", "30% increased Attack Damage against Chilled Enemies"),
        ("m.d2", "냉기소비2", "40% increased Attack Damage against Chilled Enemies"),
    ]
    pairs = [h for h in find_hypotheses(_store(*specs), root=tmp_path) if h.kind == "pair"]
    assert len(pairs) == 1


def test_미사용_데이터는_후보가_아니다(tmp_path: Path) -> None:
    """DNT-UNUSED 같은 덤프 잔재를 내밀면 게이트가 실체 없는 항목을 판정하게 된다."""
    specs = [
        _CHILL_SUPPLY,
        ("m.dnt", "DNT-UNUSED Damage against Chilled Enemies", "Damage against Chilled Enemies"),
    ]
    pairs = [h for h in find_hypotheses(_store(*specs), root=tmp_path) if h.kind == "pair"]
    assert pairs == []


def test_획득_경로_미수록은_배제가_아니라_표시다(tmp_path: Path) -> None:
    """`acquisition_unknown`은 poe2db 수집 한계지 게임 부재가 아니다 — 룬 수호
    코스트 스킬들은 0.5.0 시즌 컨텐츠에서 얻을 수 있다(사용자 판정 2026-08-04).
    수집 한계를 성립 판정으로 바꿔 읽으면 멀쩡한 설계 공간이 통째로 사라진다."""
    store = _store(_CHILL_SUPPLY, _CHILL_DEMAND)
    store.records["m.supply"].raw["data"]["acquisition_unknown"] = True
    pairs = [h for h in find_hypotheses(store, root=tmp_path) if h.kind == "pair"]
    assert len(pairs) == 1  # 배제하지 않는다
    assert "획득 경로 미수록" in pairs[0].evidence  # 사실은 게이트에 전한다


def test_큐는_자기_자신을_탐사_흔적으로_보지_않는다(tmp_path: Path) -> None:
    """큐가 코퍼스에 섞이면 지난번 후보가 '이미 다룬 것'이 되어 매번 뒤바뀐다."""
    raw = tmp_path / "artifacts" / "feedback" / "raw" / "q1"
    raw.mkdir(parents=True)
    (raw / "content.md").write_text("# 능동 탐사 가설 큐\n\n냉기원 과 냉기소비 조합", "utf-8")
    pairs = [
        h
        for h in find_hypotheses(_store(_CHILL_SUPPLY, _CHILL_DEMAND), root=tmp_path)
        if h.kind == "pair"
    ]
    assert len(pairs) == 1  # 큐에 적혀 있어도 탐사한 것이 아니다


def test_미탐사_조합은_후보로_올라온다(tmp_path: Path) -> None:
    pairs = [
        h
        for h in find_hypotheses(_store(_CHILL_SUPPLY, _CHILL_DEMAND), root=tmp_path)
        if h.kind == "pair"
    ]
    assert len(pairs) == 1
    assert "냉기원" in pairs[0].text and "냉기소비" in pairs[0].text
