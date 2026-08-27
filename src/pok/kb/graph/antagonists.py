"""적대 조합 — **A가 만드는 것을 B가 금지한다** (#131).

기존 그래프는 **생산·소비**를 본다: A가 X를 만들고 B가 X를 쓰는 관계다
(`scan_supply_edges`·`scan_state_edges`·`scan_synergies`). 여기는 축이 다르다 —
A가 X를 만드는데 B가 **X 자체를 금지**한다. 지금 어느 도구도 이 축을 안 낸다.

실측 계기(2026-08-27): `Xoph's Pyre`(*"Gain 40% of **Fire** Damage as Extra **Chaos**"*)와
불의 화신(*"Deal no **Non-Fire** Damage"*)이 정면 적대한다. 찍는 순간 그 젬이 **완전히
무효**가 되는데(두 구성의 최종 DPS가 1,556,109로 동일) **아무 신호도 없다**. 사용자가
인게임에서 발견했다.

⛔ **거부가 아니라 신고다.** 적대라도 **의도한 선택**일 수 있다(대가를 알고 쓴다).
거부하면 #117·#118과 같은 거짓 거부가 된다 — 판정은 호출자 몫(AD-3).

§0 ⑧의 **역방향**이다: 「관계가 문구에 있는데 도구가 안 읽어 **없는 공백**을 보고한다」의
반대로, 여기서는 **「있는 충돌」을 못 본다**.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pok.kb.store import Store

#: 피해 타입 축. 금지·생산 양쪽이 이 어휘로 정규화된다.
DAMAGE_TYPES: tuple[str, ...] = ("Physical", "Fire", "Cold", "Lightning", "Chaos")

# 금지: `Deal no Fire Damage` / `Deal no Non-Fire Damage` / `Cannot deal Non-Elemental Damage`
#
# ⚠ **어휘가 둘이다.** `Cannot deal`만 쓰는 담체가 있다 — `mechanic.elemental-archon`
# (어센던시)이 *"Cannot deal Non-Elemental Damage with Spells"*로 물리·카오스 주문을
# 통째로 죽인다. `Deal no`만 봤을 때 이 담체가 **전부 빠져 있었다**(형태 ⑭).
#
# ⚠ **조건은 모델링하지 않는다.** *"**with Spells**"* · *"**Attacks** deal no Physical"* ·
# *"**Movement Skills** deal no Physical"*처럼 적용 범위가 좁은 금지가 실재한다. 신고는
# 문구 전문을 `evidence`로 실어 호출자가 범위를 읽게 한다 — 조건을 무시하고 **거부**했다면
# 거짓 거부가 됐을 것이다(AD-3, 그래서 신고다).
#
# ⛔ **`No Physical Damage`(무기 로컬 속성)는 금지가 아니다** — 「이 무기에 물리 피해가
# 없다」이지 「물리를 못 낸다」가 아니다. 캐릭터는 다른 출처로 물리를 낸다. 정본 6건
# (`uniquelocalnoweaponphysicaldamage1~4` · `Skysliver` · `The Sentry`)이 여기 걸린다.
_BAN = re.compile(r"\b(?:Deal no|Cannot deal)\s+(Non-)?([A-Za-z]+)\s+Damage", re.I)
# 생산: `… as Extra Chaos Damage` (Gain/Converted 계열이 공통으로 쓰는 꼬리)
#
# ⚠ **범위는 「추가 피해」 문구다** — 무기 기본 물리처럼 문구 없이 존재하는 피해는 안
# 잡는다. 그건 정본 문구가 아니라 아이템 수치라 이 층에서 판정할 수 없다(오라클 몫).
# 여기서 잡는 것은 **담체 한 칸이 통째로 죽는** 경우다 — 젬·접사가 만드는 것을 금지가
# 0으로 만들면 그 칸의 기여가 전부 사라지는데, 그게 신호 없이 지나가던 자리다.
_GAIN = re.compile(r"as Extra ([A-Za-z]+) Damage", re.I)


#: 묶음 어휘 -> 실제 피해 타입. **정본은 묶음으로도 금지한다.**
#:
#: ⚠ 실측 2026-08-27: 처음엔 `DAMAGE_TYPES`에 없는 축을 전부 버렸고, 그래서
#: `Deal no Elemental Damage`(정본 7건)가 **조용히 사라졌다** — Brutality I~III가
#: 카오스만 죽이는 것으로 보고됐지만 실제로는 **화염·냉기·번개도 죽인다**.
#: 「비-타입 금지를 뺀다」는 규칙이 「묶음 금지도 뺀다」로 새어 나간 자리다.
DAMAGE_GROUPS: dict[str, tuple[str, ...]] = {
    "Elemental": ("Fire", "Cold", "Lightning"),
}


def _expand(subject: str) -> tuple[str, ...]:
    """금지·생산의 축 하나를 실제 피해 타입으로 편다. 축이 아니면 빈 튜플."""
    if subject in DAMAGE_GROUPS:
        return DAMAGE_GROUPS[subject]
    return (subject,) if subject in DAMAGE_TYPES else ()


def _texts(raw: dict[str, Any]) -> list[str]:
    """이 레코드의 효과 문구 전량.

    ⚠ `predicates.record_texts`는 `stats_en`·`texts`·`description`만 본다.
    금지 문구는 **패시브의 `stats_en`**과 **보조젬의 `stats`**, 룬의 `per_slot`에
    흩어져 있어 여기서 따로 모은다 — #106에서 `per_slot` 미독으로 룬 1,116줄이
    통째로 스캔 밖이었던 것과 같은 자리다.
    """
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


@dataclass(frozen=True)
class Prohibition:
    """「이 타입 피해를 못 낸다」를 거는 담체 하나."""

    carrier_id: str
    carrier_name: str
    carrier_type: str
    #: 금지가 **살려 두는** 타입(`Non-` 형태) 또는 **죽이는** 타입
    subject: str
    #: True면 `Deal no Non-X` — X **외 전부**를 죽인다
    is_exclusive: bool
    evidence: str

    @property
    def killed_types(self) -> tuple[str, ...]:
        """이 금지가 실제로 죽이는 피해 타입.

        `Non-` 형태는 **살려 두는 것의 여집합**이다 — `Deal no Non-Elemental`은
        원소를 남기고 물리·카오스를 죽인다.
        """
        spared = _expand(self.subject)
        if not spared:
            return ()
        if self.is_exclusive:
            return tuple(t for t in DAMAGE_TYPES if t not in spared)
        return spared


@dataclass(frozen=True)
class AntagonistPair:
    """금지 하나 ↔ 그것이 무효화하는 생산 담체 하나."""

    prohibition: Prohibition
    producer_id: str
    producer_name: str
    producer_type: str
    #: 생산되는 타입 — 금지에 걸려 **0이 된다**
    damage_type: str
    evidence: str


def scan_prohibitions(store: Store) -> list[Prohibition]:
    """정본 전수에서 **피해 타입 금지** 문구를 뽑는다.

    실측 2026-08-27: 담체 **14종** / 문구 행 **17건**. 적은데 **파급이 크다** —
    Brutality I~III가 각각 생산 담체 **233종**을, 불의 화신이 **188종**을 죽인다.
    「몇 건인가」가 아니라 **「무엇을 죽이는가」**로 잰다.
    """
    out: list[Prohibition] = []
    for record in store.records.values():
        for text in _texts(record.raw):
            for m in _BAN.finditer(text):
                subject = m.group(2).title()
                is_excl = bool(m.group(1))
                if not _expand(subject):
                    # `Deal no Spell/Melee/Projectile Damage`는 **타입 금지가 아니다**.
                    # ⚠ 묶음(`Elemental`)은 타입이 아니지만 **펴면 타입이다** — 버리지 않는다.
                    continue
                out.append(
                    Prohibition(
                        carrier_id=record.id,
                        carrier_name=record.name_en,
                        carrier_type=record.type,
                        subject=subject,
                        is_exclusive=is_excl,
                        evidence=text.strip(),
                    )
                )
    return out


def scan_antagonists(store: Store, *, carrier_ids: set[str] | None = None) -> list[AntagonistPair]:
    """금지 ↔ 생산의 적대 짝 전량.

    `carrier_ids`를 주면 **그 빌드가 실제로 든 것**만 본다 — 전수는 「무엇이 적대할 수
    있나」이고, 좁히면 「지금 내 빌드에서 무엇이 죽고 있나」다.

    ⛔ **거부가 아니라 신고다** — 대가를 알고 쓰는 선택일 수 있다(AD-3).
    """
    producers: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for record in store.records.values():
        if carrier_ids is not None and record.id not in carrier_ids:
            continue
        for text in _texts(record.raw):
            for m in _GAIN.finditer(text):
                for dtype in _expand(m.group(1).title()):
                    producers[dtype].append((record.id, record.name_en, record.type, text.strip()))

    out: list[AntagonistPair] = []
    seen: set[tuple[str, str, str]] = set()
    for ban in scan_prohibitions(store):
        if carrier_ids is not None and ban.carrier_id not in carrier_ids:
            continue
        for dtype in ban.killed_types:
            for pid, pname, ptype, ptext in producers.get(dtype, ()):
                if pid == ban.carrier_id:
                    continue  # 자기 자신은 적대가 아니다
                key = (ban.carrier_id, pid, dtype)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    AntagonistPair(
                        prohibition=ban,
                        producer_id=pid,
                        producer_name=pname,
                        producer_type=ptype,
                        damage_type=dtype,
                        evidence=ptext,
                    )
                )
    return out


def _node_index(store: Store) -> dict[int, Any]:
    """PoB **숫자 노드 id** -> 정본 Passive 레코드.

    ⚠ 스펙의 `tree_nodes`는 `passive.avatar-of-fire`가 아니라 `8975` 같은 **정수**다.
    id 규약이 다르다는 걸 놓치면 신고가 **조용히 0건**이 된다 — 실측 2026-08-27:
    `passive.{nid}`로 조회하도록 짰더니 131개 노드 중 **0개**가 맞았고, 계기가 된
    불의 화신이 바로 트리 키스톤이라 정작 그 사고를 못 잡을 뻔했다.
    """
    out: dict[int, Any] = {}
    for record in store.records.values():
        if record.type != "Passive":
            continue
        nid = (record.raw.get("data") or {}).get("node_id")
        if nid is not None:
            out[int(nid)] = record
    return out


def report_for_spec(store: Store, spec: dict[str, Any]) -> list[dict[str, str]]:
    """빌드 스펙 하나에서 **지금 죽고 있는 것**을 신고 형태로 낸다 (#131).

    스펙은 담체 id를 안 들고 있고 **문구를 들고 있다**(아이템 텍스트·젬 이름). 그래서
    id로 좁히는 대신 **스펙 문구 자체**에서 금지·생산을 뽑아 맞춘다 — 정본에 없는
    손으로 쓴 줄도 그대로 걸린다.

    ⛔ **거부가 아니라 신고다.** 적대라도 **의도한 선택**일 수 있다(대가를 알고 쓴다).
    거부하면 #117·#118과 같은 거짓 거부가 된다 — 판정은 호출자 몫(AD-3).
    """
    lines: list[str] = []
    for item in spec.get("items") or ():
        lines.extend(str(item.get("text") or "").splitlines())
    for jewel in spec.get("jewels") or ():
        lines.extend(str(jewel.get("text") or "").splitlines())
    gem_names = {
        str(g.get("name") or "").lower()
        for group in spec.get("skills") or ()
        for g in (group.get("gems") or ())
    }
    for record in store.records.values():
        if record.name_en.lower() in gem_names:
            lines.extend(_texts(record.raw))
    node_index = _node_index(store)
    for nid in spec.get("tree_nodes") or ():
        rec = node_index.get(int(nid))
        if rec is not None:
            lines.extend(_texts(rec.raw))
    blob = "\n".join(lines)

    bans: list[Prohibition] = []
    for m in _BAN.finditer(blob):
        subject = m.group(2).title()
        # ⚠ `_expand`로 거른다 — `DAMAGE_TYPES`만 보면 묶음(`Elemental`)이 조용히
        # 빠진다. 위 스캔에서 고친 누수가 **여기서 한 번 더** 났다: 고쳐야 할 자리가
        # 둘인데 하나만 고치면 정작 출고 경로가 죽어 있다(형태 ⑭).
        if _expand(subject):
            bans.append(
                Prohibition("spec", "(스펙)", "BuildSpec", subject, bool(m.group(1)), m.group(0))
            )
    if not bans:
        return []
    made = {t for m in _GAIN.finditer(blob) for t in _expand(m.group(1).title())}
    out: list[dict[str, str]] = []
    for ban in bans:
        for dtype in ban.killed_types:
            if dtype in made:
                out.append(
                    {
                        "prohibition": ban.evidence,
                        "kills": dtype,
                        "why": (
                            f"이 스펙이 {dtype} 피해를 만드는데 「{ban.evidence}」가 그것을 "
                            f"**0으로 만든다** — 그 담체는 기여가 통째로 사라진다. "
                            f"의도한 선택이면 무시할 것(판정은 호출자 몫)"
                        ),
                    }
                )
    return out
