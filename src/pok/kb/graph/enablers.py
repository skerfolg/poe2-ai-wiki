"""조건 성립기 — **이 노드를 살리려면 무엇이 필요한가** (#125).

`scan_state_edges`(#92)의 54축은 전부 **가하거나 생성하는** 상태다(동결·점화·충전·주입).
조건부 노드가 요구하는 것은 **자신이 처한 상태**(낮은 생명력·포위·이동 중)로 **축이
다르다** — 실측 2026-08-27: `low_life`·`surrounded`·`moving` 중 어느 것도 그 54축에 없다.

⭑ **주체는 줄 단위다.** 한 레코드가 자신용과 적용을 **함께** 갖는다 — 실측: `Low Life`
문구에서 **6종**이 그렇고, `support.execute-iii`가 대표다:

    "deal 30% more Damage with Hits **while you are** on Low Life"            ← self
    "deal 30% more Damage with Hits **against Enemies that are** on Low Life" ← enemy

레코드 단위로 주체를 붙이면 이것이 통째로 「적 전용」으로 찍히고, 낮은 생명력 빌드가
**자기한테 맞는 젬을 후보에서 잃는다**(사용자 지적 2026-08-27).

⛔ **「무엇을 사야 하나」의 답이 범주마다 다르다.** 조건은 넷으로 갈리고 **둘은 살 것이
없다** — `equipment`는 슬롯을 보면 알고(링크 불필요), `behaviour`는 조작이라 구매 대상이
아니다. 그래서 `satisfy_by`를 축에 싣는다: 없는 답을 찾게 만들면 그것도 갭 보고다.

⛔ **거부가 아니라 신고다** — 전제가 없는 채로 찍는 것도 (그 아이템을 살 계획이라면)
선택일 수 있다. 판정은 호출자 몫(AD-3).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pok.kb.store import Store

#: 조건 축 — `(축 이름, 문구 표면형)`. **긴 표현을 먼저 둔다**(`low mana` ⊃ `mana`).
#: `mechanism.py::_OBJECT_AXES`와 같은 규약이다.
CONDITION_AXES: tuple[tuple[str, str], ...] = (
    ("low_life", r"[Ll]ow [Ll]ife"),
    ("full_life", r"[Ff]ull [Ll]ife"),
    ("low_mana", r"[Ll]ow [Mm]ana"),
    ("full_mana", r"[Ff]ull [Mm]ana"),
    ("surrounded", r"[Ss]urrounded"),
    ("shapeshifted", r"[Ss]hapeshifted|[Bb]ear [Ff]orm|[Ww]olf [Ff]orm"),
    ("dual_wielding", r"[Dd]ual [Ww]ield\w*"),
    ("holding_shield", r"[Hh]olding a [Ss]hield"),
    ("companion_present", r"[Cc]ompanion is in your [Pp]resence"),
    ("stationary", r"[Ss]tationary"),
    ("sprinting", r"[Ss]printing"),
    ("channelling", r"[Cc]hannelling"),
    ("parrying", r"[Pp]arrying"),
    ("leeching", r"[Ll]eeching"),
    ("moving", r"[Ww]hile [Mm]oving"),
)

#: 축 → **무엇으로 만족시키나**. 답의 성격이 달라 같은 표에 두면 오답이 나간다.
#: `equipment`·`behaviour`는 **살 것이 없다** — 「전제 아이템」을 찾으면 영원히 0건이다.
SATISFY_BY: dict[str, str] = {
    "low_life": "resource",
    "full_life": "resource",
    "low_mana": "resource",
    "full_mana": "resource",
    "surrounded": "situation",
    "shapeshifted": "form",
    "dual_wielding": "equipment",
    "holding_shield": "equipment",
    "companion_present": "equipment",
    "stationary": "behaviour",
    "sprinting": "behaviour",
    "channelling": "behaviour",
    "parrying": "behaviour",
    "leeching": "behaviour",
    "moving": "behaviour",
}

#: **기본 상태** — 아무것도 안 해도 그 상태다(피해를 안 입으면 만생명력).
#: 성립기가 0건인 것이 **정상**이라 갭 후보에서 뺀다. ⚠ 그렇다고 성립기가 없는
#: 것은 아니다 — `full_mana`는 문턱 재정의(90%)가 3건 있다.
DEFAULT_STATES: frozenset[str] = frozenset({"full_life", "full_mana"})

# 조건을 **요구하는** 문구인가. ⚠ 어휘가 넓다 — `while|if you|when you|during`만 보면
# 실측 2026-08-27에 **240줄(+14%)**을 놓쳤고, 가장 큰 누락(`on enemies` 124건)이
# 전부 적 쪽이라 **적 주체가 계통적으로 과소계상**됐다(형태 ⑭ — 어휘를 절반만 봄).
_REQUIRES = re.compile(
    r"\b(while|if you|when you|when on|during|that are|that have|against enemies on|"
    r"on enemies|unless|if it)\b",
    re.I,
)
# 주체 — **줄 단위로** 판정한다(위 docstring 참조)
_ENEMY = re.compile(r"\b(enem(?:y|ies)|monsters?)\b", re.I)
#: 「너」 표지 — **가까운 쪽 판정**에만 쓴다. 표지가 아예 없으면 자신이다
#: (정본은 적을 항상 `Enemies`로 명시한다).
_SELF_MARK = re.compile(r"\b(you are|you're|you have|your)\b", re.I)

#: 성립기 세 부류. 실측 2026-08-27: 전부 **한 자릿수~수십 종**이지만 파급이 크다.
_ENABLER_KINDS: tuple[tuple[str, str], ...] = (
    # 재정의 — 「무엇이 그 상태로 치나」를 바꾼다
    ("redefine", r"counts? as\b"),
    # 강제 — 그 상태에 **두어 버린다**
    ("force", r"cannot Recover Life to above|Reserves? \(?[\d\s-]+\)?% of"),
    # 완화 — 문턱을 낮춘다
    ("relax", r"[Rr]equire \(?[\d\s-]+\)? fewer"),
)


def _texts(raw: dict[str, Any]) -> list[str]:
    """이 레코드의 효과 문구 전량 (`antagonists._texts`와 같은 규약)."""
    data = raw.get("data") or {}
    out: list[str] = []
    for field in ("stats", "stats_en", "texts", "quality_stats", "explicits", "implicits"):
        out.extend(str(x) for x in (data.get(field) or ()))
    if data.get("description"):
        out.append(str(data["description"]))
    per_slot = data.get("per_slot")
    if isinstance(per_slot, dict):
        for lines in per_slot.values():
            out.extend(str(x) for x in (lines or ()))
    return out


def _axis_match(text: str) -> tuple[str, int] | None:
    """조건 축과 **그 문구가 시작하는 위치**. 위치가 있어야 주체를 정확히 잡는다."""
    for axis, pattern in CONDITION_AXES:
        m = re.search(pattern, text)
        if m:
            return axis, m.start()
    return None


def _axis_of(text: str) -> str | None:
    hit = _axis_match(text)
    return hit[0] if hit else None


#: 조건 문구 **바로 앞** 몇 글자를 주체 판정에 쓰나.
#: 줄 전체를 보면 *"Deal more Damage to **Enemies** while **you** are on Low Life"*가
#: `both`로 찍힌다 — 조건의 주체는 「너」인데 적은 피해 **대상**일 뿐이다.
_SUBJECT_WINDOW = 42


def _subject_of(text: str, at: int | None = None) -> str:
    """이 **줄**의 조건 주체. 조건 문구 바로 앞 창에서 가장 가까운 표지를 쓴다.

    ⭑ 레코드로 뭉개지 않는다 — 한 레코드가 자신용·적용을 함께 갖는다(위 docstring).
    ⚠ 표지가 없으면 **`self`다.** 정본은 적을 항상 `Enemies`로 **명시**하므로, 명시가
    없다는 것이 곧 「너」다 — 실측 2026-08-27: `unknown`으로 두면 `dual_wielding`
    44건이 전부 미분류가 돼 쓸 수 없었다.
    """
    window = text if at is None else text[max(0, at - _SUBJECT_WINDOW) : at]
    enemy = [m.start() for m in _ENEMY.finditer(window)]
    if not enemy:
        return "self"
    # ⚠ 둘 다 있으면 **조건 문구에 가까운 쪽**이 이긴다 — 먼 쪽은 대개 피해 **대상**이다
    # (*"Deal more Damage to Enemies while you are on Low Life"* → 조건 주체는 「너」).
    # 정본에는 지금 그런 줄이 0건이지만, 규칙이 옳아야 새 문구에서 안 틀린다.
    mine = [m.start() for m in _SELF_MARK.finditer(window)]
    return "enemy" if not mine or max(enemy) > max(mine) else "self"


#: 성립기의 주체는 **문장 주어**로 잡는다 — 창(window) 방식이 양방향으로 틀렸다.
#: 실측 2026-08-27:
#:   `Require (2-4) fewer enemies to be Surrounded` → 창에 `enemies`가 있어 적으로 찍혔지만
#:      포위되는 것은 **나**다(문턱 완화).
#:   `Enemies in your Presence count as being on Low Life` → `Enemies`가 창 **밖**으로
#:      밀려 자신으로 찍혔지만 낮은 생명력이 되는 것은 **적**이다.
#: 정본은 적이 주어일 때 문장을 `Enemies`/`Monsters`로 **시작**한다.
_ENEMY_SUBJECT = re.compile(r"^[\s•\-]*(enem(?:y|ies)|monsters?)\b", re.I)


def _enabler_subject(text: str) -> str:
    """성립기가 **누구를** 그 상태로 만드나."""
    return "enemy" if _ENEMY_SUBJECT.search(text) else "self"


@dataclass(frozen=True)
class ConditionUse:
    """조건이 성립할 때 **이득을 보는** 담체 한 줄."""

    carrier_id: str
    carrier_name: str
    carrier_type: str
    axis: str
    subject: str
    evidence: str


@dataclass(frozen=True)
class Enabler:
    """조건을 **성립시키는** 담체 한 줄 — 재정의·강제·완화."""

    carrier_id: str
    carrier_name: str
    carrier_type: str
    axis: str
    kind: str
    #: 이 성립기가 **누구를** 그 상태로 만드나. ⚠ 적 쪽 성립기가 실재한다 —
    #: `Enemies in your Presence count as being on Low Life`는 적을 낮은 생명력으로
    #: 만들어 **Execute I·II**(적 페이오프)를 켠다. 자신 페이오프와는 짝이 다르다.
    subject: str
    evidence: str


def scan_condition_uses(store: Store, *, axis: str | None = None) -> list[ConditionUse]:
    """조건을 **요구하는**(= 성립해야 이득인) 담체 전량."""
    out: list[ConditionUse] = []
    for record in store.records.values():
        for text in _texts(record.raw):
            if not _REQUIRES.search(text):
                continue
            hit = _axis_match(text)
            if hit is None or (axis is not None and hit[0] != axis):
                continue
            found, at = hit
            out.append(
                ConditionUse(
                    carrier_id=record.id,
                    carrier_name=record.name_en,
                    carrier_type=record.type,
                    axis=found,
                    subject=_subject_of(text, at),
                    evidence=text.strip(),
                )
            )
    return out


def scan_enablers(store: Store, *, axis: str | None = None) -> list[Enabler]:
    """조건을 **성립시키는** 담체 전량 — 「무엇을 사야 이 노드가 사나」.

    ⛔ `equipment`·`behaviour` 축에는 성립기가 없는 것이 **정상**이다(슬롯을 채우거나
    그렇게 움직이면 된다). 그 축에서 0건을 「수집 갭」으로 읽지 말 것.
    """
    out: list[Enabler] = []
    for record in store.records.values():
        for text in _texts(record.raw):
            hit = _axis_match(text)
            if hit is None or (axis is not None and hit[0] != axis):
                continue
            found = hit[0]
            for kind, pattern in _ENABLER_KINDS:
                if re.search(pattern, text, re.I):
                    out.append(
                        Enabler(
                            carrier_id=record.id,
                            carrier_name=record.name_en,
                            carrier_type=record.type,
                            axis=found,
                            kind=kind,
                            subject=_enabler_subject(text),
                            evidence=text.strip(),
                        )
                    )
                    break
    return out


def axis_report(store: Store) -> list[dict[str, Any]]:
    """축마다 「이득 보는 것 / 성립시키는 것」을 한 줄로.

    ⚠ `enablers`가 0인데 `satisfy_by`가 `resource`·`situation`이면 **진짜 갭 후보**다.
    `equipment`·`behaviour`면 갭이 아니다 — **살 것이 없는 것이 답**이다.
    """
    uses: dict[str, list[ConditionUse]] = defaultdict(list)
    for use in scan_condition_uses(store):
        uses[use.axis].append(use)
    enablers: dict[str, list[Enabler]] = defaultdict(list)
    for enabler in scan_enablers(store):
        enablers[enabler.axis].append(enabler)

    out: list[dict[str, Any]] = []
    for axis, _ in CONDITION_AXES:
        rows, made = uses.get(axis, []), enablers.get(axis, [])
        by_subject: dict[str, int] = defaultdict(int)
        for row in rows:
            by_subject[row.subject] += 1
        satisfy = SATISFY_BY.get(axis, "unknown")
        out.append(
            {
                "axis": axis,
                "satisfy_by": satisfy,
                "uses": len(rows),
                "by_subject": dict(by_subject),
                "enablers": len(made),
                "enabler_kinds": sorted({e.kind for e in made}),
                # 「살 것이 없다」와 「못 찾았다」를 구별한다 — 섞으면 없는 갭을 쫓는다
                "enabler_subjects": sorted({e.subject for e in made}),
                "gap_candidate": (
                    bool(rows)
                    and not made
                    and satisfy in ("resource", "situation")
                    and axis not in DEFAULT_STATES
                ),
            }
        )
    return out


def mixed_subject_carriers(store: Store) -> list[dict[str, Any]]:
    """자신용·적용을 **함께 갖는** 담체 — 레코드 단위 분류가 깨지는 자리.

    실측 2026-08-27(`low_life`): **6종**. `support.execute-iii`가 대표다. 사용자가
    인게임 지식으로 짚어 드러났다 — 레코드로 뭉갰으면 낮은 생명력 빌드가 자기한테
    맞는 젬을 후보에서 잃었다.
    """
    per: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    names: dict[str, str] = {}
    for use in scan_condition_uses(store):
        subjects = {use.subject}
        per[use.carrier_id][use.axis] |= subjects
        names[use.carrier_id] = use.carrier_name
    out: list[dict[str, Any]] = []
    for cid, axes in per.items():
        mixed = sorted(a for a, s in axes.items() if {"self", "enemy"} <= s)
        if mixed:
            out.append({"carrier_id": cid, "name": names.get(cid, ""), "axes": mixed})
    return sorted(out, key=lambda r: str(r["carrier_id"]))
