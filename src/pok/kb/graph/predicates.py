"""효과 문구 → 조건 subject 술어 추출 — 능동 탐사의 재료 (KD-2 통제 어휘 v1).

정본에는 **명시적 관계 엣지가 큐레이션 43건(27개)에만** 있고 대량 레코드
16,575건에는 0건이다(실측 2026-08-04). 관계 그래프를 그대로 순회하면 탐사 대상이
사실상 없다는 뜻이다. 대신 전수로 존재하는 **영문 효과 문구 16,117줄**에서 조건
subject를 결정적으로 유도한다 — 사람이 엣지를 달지 않아도 전수가 대상이 된다.

두 방향으로 나눈다:

  · **요구(demand)** — 그 조건이 참일 때 효과를 얻는다 ("against Chilled Enemies")
  · **공급(supply)** — 그 조건을 성립시킨다 ("20% increased chance to Chill")

시너지의 결정적 정의는 이 둘의 맞물림이다: A가 공급하는 subject를 B가 요구하면
AxB는 **후보**다. 후보일 뿐 판단이 아니다(AD-3) — 문구 패턴 매칭은 원리상
불완전하므로 추출물은 전부 미검증이고, 선별은 게이트(learning/hypothesis)가 한다.
그래서 모든 술어는 근거 문구를 **원문 그대로** 달고 다닌다(AD-8 반프록시).

패턴은 실제 정본 문구를 읽고 만들었다(추측 금지). 거짓 양성이 많으면 게이트가
무의미해지므로 **보수적**으로 — 확실한 표지만 잡고 애매하면 놓친다. 예를 들어
"20% increased Magnitude of Shock you inflict"는 감전을 *스케일*할 뿐 *공급*하지
않으므로 공급으로 세지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── 상태이상 어휘 (vocab enemy.status.values) ─────────────────────────
# 동사형(공급 문구) → 상태형(vocab 값). 두 표기를 잇는 표는 여기 하나뿐이다.
_STATUS_VERBS = {
    "Shock": "shocked",
    "Ignite": "ignited",
    "Chill": "chilled",
    "Freeze": "frozen",
    "Electrocute": "electrocuted",
    "Poison": "poisoned",
    "Stun": "stunned",
    # Bleed 누락으로 "출혈 요구 15건 · 공급 0" 이라는 거짓 갭이 났었다(2026-08-04)
    "Bleed": "bleeding",
}
_STATUS_ADJS = {
    "Shocked": "shocked",
    "Ignited": "ignited",
    "Chilled": "chilled",
    "Frozen": "frozen",
    "Electrocuted": "electrocuted",
    "Poisoned": "poisoned",
    "Bleeding": "bleeding",
    "Stunned": "stunned",
}

_CHARGES = {
    "Power": "self.charge.power",
    "Frenzy": "self.charge.frenzy",
    "Endurance": "self.charge.endurance",
}


@dataclass(frozen=True)
class Predicate:
    """레코드가 요구하거나 공급하는 조건 하나.

    subject/value 는 통제 어휘(KD-2)를 따르고, evidence 는 판정 근거가 될
    **원문 문구 그대로**다 — 게이트가 이 문구만 보고도 참·거짓을 가릴 수 있어야 한다.
    """

    subject: str
    direction: str  # "demand" | "supply"
    evidence: str
    value: str | None = None  # set/enum subject의 값 (예: enemy.status → "chilled")

    @property
    def key(self) -> str:
        """맞물림 판정의 키 — subject와 값이 같아야 요구·공급이 이어진다."""
        return f"{self.subject}={self.value}" if self.value else self.subject


# ── 요구 패턴 ────────────────────────────────────────────────────────
# (정규식, subject, value 그룹명 또는 None). 실제 문구로 검증한 표지만 싣는다.

_DEMAND_PATTERNS: list[tuple[re.Pattern[str], str, str | None]] = [
    # "against Chilled Enemies" · "+250 to Accuracy against Bleeding Enemies"
    (re.compile(r"\bagainst\s+(?P<v>\w+)\s+Enem", re.I), "enemy.status", "v"),
    # "if you have Shocked an Enemy Recently" — 과거분사형 상태 유지 확인
    (re.compile(r"\byou have\s+(?P<v>\w+)\s+an?\s+Enemy Recently", re.I), "enemy.status", "v"),
    # "Damage against Enemies that are Chilled" 계열
    (re.compile(r"\bEnemies (?:that are|which are)\s+(?P<v>\w+)", re.I), "enemy.status", "v"),
    (re.compile(r"\b(?:while|when)(?:\s+you are)?\s+on Low Life\b", re.I), "self.life.low", None),
    (re.compile(r"\b(?:while|when)(?:\s+you are)?\s+on Full Life\b", re.I), "self.life.full", None),
    (re.compile(r"\bwhile Dual Wielding\b", re.I), "gear.dual-wielding", None),
    (
        re.compile(r"\b(?:while holding|while wielding|with)\s+a\s+Shield\b", re.I),
        "gear.shield.equipped",
        None,
    ),
    (re.compile(r"\bwhile (?:you are )?(?:Moving|Dodge Rolling)\b", re.I), "self.moving", None),
    (re.compile(r"\bwhile (?:you are )?[Ss]tationary\b", re.I), "self.stationary", None),
    (re.compile(r"\bwhile (?:you are )?Channelling\b", re.I), "self.channelling", None),
    (re.compile(r"\bwhile (?:you are )?Leeching\b", re.I), "self.leeching", None),
    (re.compile(r"\b(?:if )?you've Killed Recently\b", re.I), "event.kill.recent", None),
    (
        re.compile(r"\b(?:if )?you've (?:dealt a )?Critical(?:ly)?[\w\s]*Recently\b", re.I),
        "event.crit.recent",
        None,
    ),
    (re.compile(r"\b(?:if )?you've been Hit Recently\b", re.I), "event.hit-taken.recent", None),
    (re.compile(r"\b(?:if )?you've Blocked Recently\b", re.I), "event.block.recent", None),
    (re.compile(r"\bper Nearby Enemy\b", re.I), "env.nearby-enemies.count", None),
    (re.compile(r"\bagainst Rare (?:or|and) Unique\b", re.I), "enemy.rarity", None),
    # 충전 소비·보유 요구: "per Power Charge" · "while you have Frenzy Charges" ·
    # "Consumes a Power Charge". 획득(gain)은 공급이므로 여기서 제외한다.
    *[
        (
            re.compile(
                rf"\b(?:per|while you have|if you have|[Cc]onsume[sd]?\s+(?:a|all)?\s*)"
                rf"[\w\s]{{0,12}}{name} Charge",
                re.I,
            ),
            subj,
            None,
        )
        for name, subj in _CHARGES.items()
    ],
]

# ── 공급 패턴 ────────────────────────────────────────────────────────

_SUPPLY_PATTERNS: list[tuple[re.Pattern[str], str, str | None]] = [
    # "20% increased chance to Chill" · "Always Freeze" · "chance to Ignite"
    (
        re.compile(rf"\bchance to\s+(?P<v>{'|'.join(_STATUS_VERBS)})\b", re.I),
        "enemy.status",
        "v",
    ),
    (
        re.compile(rf"\bAlways\s+(?P<v>{'|'.join(_STATUS_VERBS)})\b", re.I),
        "enemy.status",
        "v",
    ),
    # "Poison inflicted by this Skill" 계열 — 스킬 자체가 상태를 건다
    (
        re.compile(rf"\b(?P<v>{'|'.join(_STATUS_VERBS)})s? (?:Enemies|inflicted by this)\b", re.I),
        "enemy.status",
        "v",
    ),
    # "10% chance to inflict Bleeding on Hit" — 정본에서 가장 흔한 유발 표현인데
    # 위의 동사형 패턴이 못 잡아 "출혈 공급 1건"이라는 거짓 갭이 났다(2026-08-04).
    # `cannot inflict`(피격 방어 문구)는 유발이 아니므로 배제한다.
    (
        re.compile(
            rf"\b(?<!cannot )inflict(?:s|ing)?\s+(?P<v>{'|'.join(_STATUS_ADJS)})\b",
            re.I,
        ),
        "enemy.status",
        "v",
    ),
    # "Enemies you Electrocute have 20% increased Damage taken" — 유발 주체가 나다
    (
        re.compile(rf"\bEnemies you\s+(?P<v>{'|'.join(_STATUS_VERBS)})\b", re.I),
        "enemy.status",
        "v",
    ),
    # 충전 부여: "Gain a Power Charge" · "gain Frenzy Charges"
    *[
        (
            re.compile(rf"\b[Gg]ain(?:ing)?\s+(?:a|an|up to)?\s*[\w\s]{{0,8}}{name} Charge", re.I),
            subj,
            None,
        )
        for name, subj in _CHARGES.items()
    ],
    # ── 생명력 점유 → 로우라이프 성립 경로 ────────────────────────────
    # **점유(reserve)만 공급이다. 소모(cost·lose)는 아니다** (사용자 판정 2026-08-04).
    # 점유는 최대 생명력의 일부를 묶어 잔여를 영구히 낮추지만, 소모는 쓰고 나면
    # 회복으로 돌아오므로 로우라이프를 *유지*하지 못한다. 그래서 아탈루이의 사혈·
    # 생명력 전환("Mana cost into a Life cost")과 자해("Lose N% of maximum Life")는
    # 여기 걸리지 않아야 한다.
    #
    # 또한 **내 생명력**이어야 한다 — "Targets Cursed by you have at least 15% of
    # Life Reserved"는 적을 점유시키는 것이라 내 로우라이프와 무관하다.
    (
        re.compile(r"\bReserves\s+\d+%\s+of\s+(?:Maximum\s+)?Life\b", re.I),
        "self.life.low",
        None,
    ),
    # "Reserve Life instead of Spirit" — 앗지리의 성찬식(v6의 핵심 경로)과
    # "Socketed Gems Cost and Reserve Life instead of Mana" 계열. 수치가 붙지 않아
    # 위의 %패턴이 통째로 놓쳤었다(2026-08-04).
    (re.compile(r"\bReserve\s+Life\s+instead\s+of\b", re.I), "self.life.low", None),
    # 받는 피해를 점유로 돌리는 경로
    (
        re.compile(r"\bLife that would be lost\b[\w\s]*\bis instead Reserved\b", re.I),
        "self.life.low",
        None,
    ),
]


# 공급 패턴이 실제로 커버하는 축. **갭 주장의 사정거리**다 — 이 밖의 축에서
# "공급 0"이 나오는 건 발견이 아니라 이 파일이 그 축의 공급을 볼 줄 모른다는 뜻이다.
#
# 빠진 축들(self.moving·self.channelling·gear.shield.equipped·event.* 등)은 대개
# **플레이어의 행동이나 장비 선택**이지 무언가가 만들어 주는 것이 아니라서 공급
# 개념 자체가 성립하지 않는다. 그 구분을 코드가 안 하면 "이동을 요구하는 효과가
# 47건인데 공급이 0" 같은 거짓 갭이 쏟아진다(실측 2026-08-04).
SUPPLIABLE_SUBJECTS: frozenset[str] = frozenset(
    {
        "enemy.status",
        "self.charge.power",
        "self.charge.frenzy",
        "self.charge.endurance",
        "self.life.low",
    }
)


def _canon_status(word: str) -> str | None:
    """공급 동사형·요구 형용사형을 vocab 값으로 정규화. 어휘 밖이면 버린다."""
    w = word.strip().title()
    return _STATUS_ADJS.get(w) or _STATUS_VERBS.get(w)


def _sentences(text: str) -> list[str]:
    """문구를 문장 단위로 쪼갠다.

    스킬 description은 한 필드에 여러 효과가 들어 있어서(예: "…Bleeding inflicted
    by this Skill… Poison Damage…") 필드 전체를 근거로 삼으면 엉뚱한 문장이 근거로
    붙는다. 실제로 그 방식은 상태이상 술어에 거짓 양성을 냈다(실측 2026-08-04).
    문장으로 좁혀야 게이트가 근거만 읽고 참·거짓을 가릴 수 있다.
    """
    parts = re.split(r"(?<=[.;])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def extract_predicates(texts: list[str], subjects: dict[str, Any]) -> tuple[Predicate, ...]:
    """효과 문구들에서 요구·공급 술어를 뽑는다 (결정적, 판단 없음).

    `subjects` = 통제 어휘(Store.subjects). 어휘에 없는 subject·값은 **버린다** —
    임의 문자열을 만들지 않는 게 KD-2의 계약이다.
    """
    found: dict[tuple[str, str, str | None], Predicate] = {}
    sentences = [s for raw in texts for s in _sentences(" ".join(str(raw).split()))]
    for text in sentences:
        for patterns, direction in ((_DEMAND_PATTERNS, "demand"), (_SUPPLY_PATTERNS, "supply")):
            for pattern, subject, group in patterns:
                for m in pattern.finditer(text):
                    value: str | None = None
                    if group:
                        value = _canon_status(m.group(group))
                        if value is None:
                            continue  # 어휘 밖 단어 — 거짓 양성으로 보고 버린다
                    spec = subjects.get(subject)
                    if spec is None:
                        continue
                    allowed = spec.get("values")
                    if value is not None and allowed and value not in allowed:
                        continue
                    key = (subject, direction, value)
                    found.setdefault(key, Predicate(subject, direction, text, value))
    return tuple(found.values())


def record_texts(raw: dict[str, Any]) -> list[str]:
    """레코드에서 영문 효과 문구를 모은다 — 타입별 필드 차이를 여기서 흡수한다."""
    data = raw.get("data") or {}
    texts: list[str] = []
    for field_name in ("stats_en", "texts"):
        texts.extend(str(s) for s in (data.get(field_name) or []))
    if data.get("description"):
        texts.append(str(data["description"]))
    return texts
