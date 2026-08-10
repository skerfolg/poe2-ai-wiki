"""임플리싯 후보 축 — 접사 풀에 **애초에 안 들어오는** 경로를 보이게 한다 (백로그 #22).

## 왜 안 보였나

`optimize_rare`는 접사(prefix/suffix) 풀만 열거한다. 그런데 사용자가 짚은 경로
(*"에센스로 최대 퀄리티 +20% → 기폭제로 40% → 옵션 교체"*)의 부품은 전부
**임플리싯**이다:

    item.breach-ring                              implicit "+20% to Maximum Quality"
    modifier.essencebreach                        prefix, Amulets·Rings
    modifier.ringimplicitmaximumquality{Additional1,Additional2,Override1}

접사 풀에 없으니 최적화가 **구조적으로 못 본다** — #18·#25와 같은 형태다.

## ⚠ PoB는 이 축을 못 잰다

실측 2026-08-09: `+20% to Maximum Quality`는 `pob_modeling.supported = false`다
(베이스 20종 전부에서 unknown). 즉 **열거해도 델타는 0으로 나온다.** 그래서 이
모듈은 값을 지어내지 않고 **경로와 측정 가능 여부를 함께** 낸다 — 「측정 안 됨」과
「값어치 없음」을 구분하는 것이 이 프로젝트의 반복 결함(§0 ③)이다.

## 슬롯 판정은 코드가 한다 (정본에 추론을 쓰지 않는다)

실측: 임플리싯 계열 Modifier **264건 전부** `applicable_pages`가 비어 있다.
근거는 `pob_key` 이름뿐이고(`RingImplicitMaximumQualityAdditional1`), 그건
**추론**이라 정본에 쓰면 사실과 섞인다(철칙 2). 여기서 결정적으로 파생하고,
못 가르면 `None`을 돌려 "모른다"를 남긴다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# pob_key에 실리는 아이템 클래스 토큰 → KB `category`.
# 긴 것부터 봐야 한다 — `BodyArmour`가 `Body`보다 먼저 걸려야 맞다.
_CLASS_TOKENS: tuple[tuple[str, str], ...] = (
    ("BodyArmour", "body"),
    ("OneHandSword", "sword"),
    ("TwoHandSword", "sword"),
    ("OneHandMace", "mace"),
    ("TwoHandMace", "mace"),
    ("OneHandAxe", "axe"),
    ("TwoHandAxe", "axe"),
    ("Crossbow", "crossbow"),
    ("Quarterstaff", "warstaff"),
    ("Sceptre", "sceptre"),
    ("Talisman", "talisman"),
    ("Amulet", "amulet"),
    ("Quiver", "quiver"),
    ("Buckler", "buckler"),
    ("Shield", "shield"),
    ("Helmet", "helmet"),
    ("Gloves", "gloves"),
    ("Boots", "boots"),
    ("Focus", "focus"),
    ("Charm", "charm"),
    ("Flask", "flask"),
    ("Jewel", "jewel"),
    ("Dagger", "dagger"),
    ("Flail", "flail"),
    ("Spear", "spear"),
    ("Staff", "staff"),
    ("Wand", "wand"),
    ("Claw", "claw"),
    ("Ring", "ring"),
    ("Belt", "belt"),
    ("Mace", "mace"),
    ("Axe", "axe"),
    ("Bow", "bow"),
)
_IMPLICIT_KEY = re.compile(r"implicit", re.I)


def implicit_category(pob_key: str) -> str | None:
    """`pob_key` → KB `category`. **가르지 못하면 None** — 지어내지 않는다.

    실측: 264건 전부 `applicable_pages`가 비어 있어 이 이름이 유일한 신호다.
    """
    for token, category in _CLASS_TOKENS:
        if token.lower() in pob_key.lower():
            return category
    return None


@dataclass(frozen=True)
class ImplicitOption:
    """이 베이스가 가질 수 있는 임플리싯 하나."""

    source: str  # "base" | "base-variant" | "modifier"
    label: str  # KB id 또는 베이스 이름
    lines: tuple[str, ...]
    # PoB가 이 문구를 읽는가. False면 **델타 0은 '측정 안 됨'이다**(§0 ③).
    pob_measurable: bool = True
    pob_gap: str = ""
    # 이 슬롯 것이 **확실한가**. `pob_key`에서 클래스를 갈라 베이스와 맞은 것만 True다.
    # 모르는 토큰(`…ImplicitWreath1`)은 빼지도 확실하다고도 하지 않는다 — 빼면 조용한
    # 누락이 되고(§0 ⑤ 게이트가 정상을 막는다), 섞으면 목록이 거짓 정밀해진다.
    slot_certain: bool = True


def _measurable(data: Mapping[str, Any]) -> tuple[bool, str]:
    modeling = data.get("pob_modeling") or {}
    if modeling.get("supported") is False:
        return False, str(modeling.get("detail") or "PoB가 이 문구를 읽지 못한다")
    return True, ""


def enumerate_implicits(
    base_name: str, records: Mapping[str, Mapping[str, Any]]
) -> list[ImplicitOption]:
    """베이스 이름 → 가질 수 있는 임플리싯 전량 (베이스 자신 + 변종 + 임플리싯 모드).

    `records`는 KB 원본 레코드 맵(id → raw)이다 — 이 모듈은 로드를 하지 않는다
    (엔진은 결정적 도구, 저장소 접근은 호출자 몫).
    """
    base = next(
        (
            r
            for r in records.values()
            if r.get("type") == "Item"
            and str((r.get("name") or {}).get("en", "")).lower() == base_name.lower()
            and (r.get("data") or {}).get("rarity") == "normal"
        ),
        None,
    )
    if base is None:
        return []
    data = base.get("data") or {}
    category = data.get("category")
    out: list[ImplicitOption] = []
    if data.get("implicit"):
        out.append(ImplicitOption("base", base_name, (str(data["implicit"]),)))
    # 동명 변종 — 인게임에서 **다른 아이템**이다(#32). 베이스 선택 자체가 축이다.
    for line in data.get("implicit_variants") or []:
        if not out or line != out[0].lines[0]:
            out.append(ImplicitOption("base-variant", base_name, (str(line),)))

    for rid, rec in sorted(records.items()):
        if rec.get("type") != "Modifier":
            continue
        mdata = rec.get("data") or {}
        key = str(mdata.get("pob_key") or "")
        if not _IMPLICIT_KEY.search(key):
            continue
        derived = implicit_category(key)
        if category is not None and derived is not None and derived != category:
            continue
        ok, gap = _measurable(mdata)
        out.append(
            ImplicitOption(
                source="modifier",
                label=rid,
                lines=tuple(str(t) for t in (mdata.get("texts") or [])),
                pob_measurable=ok,
                pob_gap=gap,
                slot_certain=derived is not None and derived == category,
            )
        )
    # 확실한 것부터 — 목록이 길어도 위쪽만 봐도 되게 한다
    return sorted((o for o in out if o.lines), key=lambda o: (not o.slot_certain, o.label))


def render_implicit(item_text: str, lines: Sequence[str]) -> str:
    """임플리싯 줄을 선언과 함께 박는다.

    ⚠ 실측 2026-08-09: 임플리싯은 **선언이 없어도 적용된다**(룬·반경과 다르다 — ES
    +50이 선언 유무와 무관하게 붙었다). 그래도 `Implicits: N`을 적는 이유는 **접사
    한도** 때문이다 — 선언이 없으면 검사기가 이 줄을 접사로 세어 한도를 터뜨린다.
    """
    body = [ln for ln in item_text.splitlines() if not ln.lower().startswith("implicits:")]
    head, rest = body[:4], body[4:]
    return "\n".join([*head, f"Implicits: {len(lines)}", *lines, *rest])


def uncertain_note(options: Sequence[ImplicitOption]) -> str:
    """슬롯이 확실하지 않은 후보 수 — 목록이 **거짓 정밀**해 보이지 않게 한다."""
    unsure = [o for o in options if not o.slot_certain and o.source == "modifier"]
    if not unsure:
        return ""
    return (
        f"⚠ 후보 {len(unsure)}건은 `pob_key`에서 아이템 클래스를 가르지 못해 **이 슬롯 것인지 "
        f"확실하지 않다**(임플리싯 Modifier 264건 전부 `applicable_pages`가 비어 있다). "
        f"빼지 않고 뒤로 미뤄 둔다 — 빼면 조용한 누락이 된다"
    )


def unmeasurable_note(options: Sequence[ImplicitOption]) -> str:
    """PoB가 못 재는 후보가 섞여 있으면 그 사실을 문장으로 — 조용히 0으로 두지 않는다."""
    blind = [o.label for o in options if not o.pob_measurable]
    if not blind:
        return ""
    return (
        f"⚠ 임플리싯 후보 {len(blind)}건은 **PoB가 문구를 못 읽는다** — 델타 0은 "
        f"'값어치 없음'이 아니라 '측정 안 됨'이다. 등가 문구 대리 측정은 "
        f"`ItemSpec.substitutes`로 (예: {', '.join(blind[:3])})"
    )


def load_records(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """편의 로더 — 호출자가 KB를 직접 들고 있지 않을 때만 쓴다."""
    from pok.kb.store import load as store_load

    return {rid: rec.raw for rid, rec in store_load(root).records.items()}
