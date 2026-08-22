"""「X당 Y」 스케일러의 **크기 판정** — 담체 개수가 아니라 배율을 본다 (#97).

## 왜 만드나 — 같은 오독을 세 번 반복했다 (2026-08-22)

빌드 탐색에서 `per Power` 계열을 파다가 **연속 세 번** 과대평가했고, 원인이 전부 같았다.

1. **`per Power` 17종을 뽑고 "풍부한 광맥"이라 보고했다.** 실제로는 대부분 메타 젬
   **에너지 게이지**였고, 딜 계열은 담체가 없거나(id에 `unused`) 무기 배타였다.
2. **위세(Presence) 담체 48+45종을 "연쇄"라 보고했다.** 반경 확장은 페이오프가 아니다 —
   사용자 판정: *"접근 범위가 넓어진다! 그래서 뭐? 이런건 없는거나 마찬가지지"*.
3. **워크라이의 Power 카운트를 배율로 읽었다.** 실제로는 **상한 있는 횟수**(50~64)이고
   그 횟수에 붙는 페이오프가 `increased`(가산·희석)였다.

세 번 다 **「담체가 많다 · 숫자가 크다」를 「배율이 크다」로 착각**한 것이다. 도구가 문구를
문자열로만 뽑아 주고 **그게 곱연산인지 카운터인지 구분해 주지 않았기** 때문이다.
문서에 "주의하라"고 적는 방식은 이미 실패했다(철칙 5) — 그래서 **분해를 도구에 넣는다**.

## 네 축으로 분해한다

- **payoff_kind** — 무엇을 주는가
  `more`(곱연산·희석 없음) / `increased`(가산·희석) / `added`(추가 피해) /
  `counter`(횟수·중첩) / `resource`(에너지·격노 등 게이지) / `sustain`(회복·회수) /
  `reach`(반경·사정거리 — **페이오프가 아니다**) / `other`
- **cap** — `up to a maximum of N` · `counting up to N` 류 상한. 상한이 있으면 그 위로는
  투자해도 0이다(워크라이 50, 산의 가르침 30에서 실제로 걸렸다).
- **attribution** — `player`(「**네가** 명중/처치」) / `weapon`(「**이 무기로** 명중」) /
  `unattributed`. **프록시(공허의 형상·토템·소환수)에서 갈린다** — 인게임 실측 2026-08-22:
  가학자의 자비의 *"Hits with this Weapon"*은 공허의 형상 분신으로도 발동했지만,
  광기의 선구자의 *"Rare/Unique **you** Hit"*는 발동하지 않았다.
- **obtainable** — id에 `unused`가 붙었거나 `data.carrier_unknown`이면 **못 쓴다**.
  실측: 최고 후보였던 `(3-5)% increased Attack damage per Power of target`이
  `...1unused`였다. 담체 확인 없이 설계 근거로 쓸 뻔했다.

## 판단은 하지 않는다 (AD-3)

분해해서 늘어놓을 뿐 "이 빌드를 해라"는 답하지 않는다. 다만 **크기를 오독하기 어렵게**
만든다 — 그게 이 모듈의 전부다.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from pok.kb.store import Record, Store

# ── 입력 축 추출 ────────────────────────────────────────────────────────
# "per Power" · "per enemy Power" · "per Power of target" · "for every 5 Rage"
# ⚠ `Power Charge`는 플레이어 자원이지 몬스터 Power가 아니다 — 섞으면 판정이 무너진다.
_PER = re.compile(
    r"\bper\s+(?:(?P<num>\d+(?:\.\d+)?)\s+)?"
    r"(?:enemy\s+|the\s+target'?s?\s+|total\s+)?"
    r"(?P<axis>[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?|[a-z]+)",
)

# ── 페이오프 종류 ───────────────────────────────────────────────────────
# 순서가 곧 우선순위다. 위에서 걸리면 아래는 안 본다.
_KIND_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 곱연산 — 희석되지 않는 유일한 부류. **면적 배율도 여기 들어온다**(그건 경고로 가른다).
    ("more", re.compile(r"\bmore\b", re.I)),
    # 반경·사정거리는 **페이오프가 아니다**. `increased`보다 먼저 걸러야
    # "위세 반경 60% 증가"가 배율처럼 보이지 않는다.
    (
        "reach",
        re.compile(
            r"\b(?:radius|Area of Effect|further away|metres?|Presence)\b",
            re.I,
        ),
    ),
    # 추가 피해 — 가산이지만 별도 버킷이라 increased보다 낫다
    (
        "added",
        re.compile(
            r"\b(?:Adds?\s+\d|added\s+\w+\s+damage|as\s+[Ee]xtra\b|Gains?\s+\d+%\s+of\b)",
        ),
    ),
    # 회복·회수 — 방어·지속 축
    (
        "sustain",
        re.compile(r"\b(?:Recoup\w*|Regenerat\w+|Recover\w*|Leech\w*|Guard)\b", re.I),
    ),
    # 게이지 자원 — 그 자체로는 딜이 아니다. 무엇에 쓰이는지 **한 단계 더** 봐야 한다.
    (
        "resource",
        re.compile(
            r"\b(?:Energy|Rage|Glory|Runic Ward|Mana|Spirit|Darkness|Volatility)\b",
        ),
    ),
    # 횟수·중첩 — 상한에 걸리기 쉽다
    (
        "counter",
        re.compile(
            r"\b(?:Empowers?\s+one|Improves?\s+\d|\+\d+\s+\w+|gain\s+(?:a|an|\d+)\b"
            r"|stacks?|Charges?|Bolts?|Petals?|Remnants?|Boast|Teachings?)\b",
            re.I,
        ),
    ),
    # 가산 증가 — 다른 increased와 합산되어 희석된다
    ("increased", re.compile(r"\b(?:increased|reduced)\b", re.I)),
)

# ── 상한 ────────────────────────────────────────────────────────────────
_CAPS: tuple[re.Pattern[str], ...] = (
    re.compile(r"up to a maximum of\s+(\d+)", re.I),
    re.compile(r"counting up to\s+(\d+)", re.I),
    re.compile(r"\bMaximum\s+\w+\s+is\s+(\d+)", re.I),
    re.compile(r"\bmaximum of\s+(\d+)", re.I),
    re.compile(r"\bup to\s+(\d+)\s*%?", re.I),
    re.compile(r"\bLimit\s+(\d+)", re.I),
)

# ── 귀속 ────────────────────────────────────────────────────────────────
# 프록시(공허의 형상 분신·토템·소환수)가 수행한 공격에서 갈린다.
_ATTR_WEAPON = re.compile(r"\bwith this Weapon\b", re.I)
_ATTR_PLAYER = re.compile(
    r"\byou'?(?:ve)?\s+(?:Hit|kill|Freeze|Shock|Ignite|Critically|Cull|Immobilis)"
    r"|\benemies you\b|\btargets? you\b|\bKilled with\b"
    # 「이 스킬이 죽이면」·「처치한 대상의」도 결국 플레이어 귀속이다
    r"|\bwhen this [Ss]kill kills\b|\bof killed target\b|\btargets? [Kk]illed\b",
    re.I,
)


@dataclass(frozen=True)
class Scaler:
    """「X당 Y」 스케일러 1건을 **판정 가능한 형태로** 분해한 것. 근거는 원문 그대로(AD-8)."""

    input_axis: str  # 무엇을 세는가 ("Power", "Rage", "Combo"…)
    payoff_kind: str  # more | increased | added | counter | resource | sustain | reach | other
    cap: int | None  # 상한 (없으면 None)
    attribution: str  # player | weapon | unattributed
    obtainable: bool  # unused · carrier_unknown 이면 False
    pob_measurable: bool  # PoB가 읽는가 (pob_gap / pob_modeling.supported)
    carrier_id: str
    carrier_name: str
    carrier_type: str
    evidence: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScalerScan:
    scalers: tuple[Scaler, ...]
    by_kind: tuple[tuple[str, int], ...]
    # 제외된 것의 사유별 수 — 조용한 절단 금지(#21).
    excluded: tuple[tuple[str, int], ...]


def classify_payoff(text: str) -> str:
    """문구가 무엇을 주는지 분류한다 (결정적, 판단 없음)."""
    for kind, rx in _KIND_RULES:
        if rx.search(text):
            return kind
    return "other"


def find_cap(text: str) -> int | None:
    """상한을 뽑는다. 여럿이면 **가장 작은 것**이 실질 상한이다."""
    found = [int(m.group(1)) for rx in _CAPS for m in rx.finditer(text)]
    return min(found) if found else None


def classify_attribution(text: str, carrier_texts: Sequence[str] = ()) -> str:
    """프록시가 수행해도 발동하는가 — 「이 무기로」는 통과, 「네가」는 차단.

    인게임 실측 2026-08-22 (사용자): 공허의 형상 분신이 가학자의 자비로 때리면
    *"Hits with this Weapon inflict Gruelling Madness"*는 **정상 적용**(디버프 10/10 확인),
    반면 광기의 선구자의 *"Rare or Unique enemies **you** Hit"*는 **발동하지 않았다**.

    ⚠ **발동 조건은 배율과 다른 줄에 있는 경우가 많다.** 광기의 선구자가 그렇다 —
    배율 줄("Apparitions deal 5% more damage per Power")에는 「you」가 없고 조건은
    설명문에 있다. 그래서 담체 전체를 함께 본다. 이걸 안 하면 차단된 스케일러가
    `unattributed`로 나와 **쓸 수 있는 것처럼 보인다**.
    """
    if _ATTR_WEAPON.search(text):
        return "weapon"
    if _ATTR_PLAYER.search(text):
        return "player"
    blob = " ".join(carrier_texts)
    if _ATTR_PLAYER.search(blob):
        return "player"
    if _ATTR_WEAPON.search(blob):
        return "weapon"
    return "unattributed"


def _obtainable(record: Record) -> tuple[bool, str | None]:
    """획득 가능한가. **못 쓰는 것을 설계 근거로 올리지 않기 위한 관문**이다."""
    if "unused" in record.id.lower():
        return False, "unused-id"
    if (record.raw.get("data") or {}).get("carrier_unknown"):
        return False, "carrier-unknown"
    return True, None


def _pob_measurable(record: Record) -> bool:
    data = record.raw.get("data") or {}
    if record.raw.get("pob_gap") or data.get("pob_gap"):
        return False
    modeling = data.get("pob_modeling") or record.raw.get("pob_modeling") or {}
    return modeling.get("supported", True) is not False


def _join_continuations(lines: list[str]) -> list[str]:
    """개행으로 잘린 문장을 잇는다 — **소문자로 시작하는 줄은 앞줄의 연속**이다.

    이걸 안 하면 상한을 통째로 놓친다. 실측 2026-08-22: `Seismic Cry`가
    "Empowers one Slam per 10 enemy Power in" / "range, **counting up to 50** Power"
    두 줄이라 상한 50이 안 잡혔고, 그래서 "Power를 올리면 계속 늘어난다"고 오독했다.
    """
    joined: list[str] = []
    for line in lines:
        if joined and line[:1].islower():
            joined[-1] = f"{joined[-1]} {line}"
        else:
            joined.append(line)
    return joined


def _texts(record: Record) -> list[str]:
    data = record.raw.get("data") or {}
    out: list[str] = []
    for field_name in ("stats", "stats_en", "texts", "quality_stats", "energy_stats"):
        out.extend(_join_continuations([str(x) for x in (data.get(field_name) or ())]))
    for field_name in ("implicits", "explicits"):
        out.extend(_join_continuations([str(x) for x in (data.get(field_name) or ())]))
    if data.get("description"):
        out.append(str(data["description"]))
    return out


def _warnings(
    kind: str, cap: int | None, attribution: str, measurable: bool, text: str = ""
) -> tuple[str, ...]:
    """오독하기 쉬운 지점을 **결과에 붙여서** 낸다 — 문서가 아니라 반환값으로."""
    out: list[str] = []
    if (
        kind == "more"
        and re.search(r"Area of Effect|radius", text, re.I)
        and not re.search(r"\bDamage\b", text, re.I)
    ):
        out.append("**면적** 배율이지 피해 배율이 아니다 — 딜 환산 시 곱하지 말 것")
    if kind == "reach":
        out.append("반경·사정거리는 페이오프가 아니다 — 「멀리서 쌓인다」는 배율이 아니다")
    if kind == "increased":
        out.append("가산(increased)이라 다른 증가%와 **희석**된다")
    if kind in ("counter", "resource"):
        out.append(f"{kind}는 딜이 아니라 게이지다 — **무엇에 쓰이는지 한 단계 더** 봐야 한다")
    if cap is not None:
        out.append(f"상한 {cap} — 그 위로는 투자해도 0이다")
    if attribution == "player":
        out.append("「네가」 귀속 — 프록시(공허의 형상·토템·소환수)에서는 발동하지 않는다")
    if not measurable:
        out.append("PoB 미측정 — 델타 0은 '값어치 없음'이 아니라 '측정 안 됨'이다")
    return tuple(out)


def scan_scalers(store: Store, input_axis: str | None = None) -> ScalerScan:
    """정본 전수에서 「X당 Y」 스케일러를 뽑아 **네 축으로 분해**한다.

    `input_axis`를 주면 그 축만("Power", "Rage"…, 대소문자 무시).
    획득 불가(`unused`·`carrier_unknown`)는 **세어서 배제 사유로 보고**한다 — 조용히
    빼면 "없다"와 구분되지 않는다.
    """
    scalers: list[Scaler] = []
    excluded: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()

    for record in store.records.values():
        ok, reason = _obtainable(record)
        measurable = _pob_measurable(record)
        carrier_texts = _texts(record)
        for text in carrier_texts:
            for match in _PER.finditer(text):
                axis = match.group("axis")
                if not axis:
                    continue
                # Power Charge는 플레이어 자원이다 — 몬스터 Power와 섞지 않는다.
                tail = text[match.end() : match.end() + 8]
                if axis == "Power" and tail.lstrip().startswith("Charge"):
                    continue
                if input_axis and axis.lower() != input_axis.lower():
                    continue
                key = (record.id, text[:60])
                if key in seen:
                    continue
                seen.add(key)
                if not ok:
                    excluded[reason or "unknown"] += 1
                    continue
                kind = classify_payoff(text)
                cap = find_cap(text)
                attribution = classify_attribution(text, carrier_texts)
                scalers.append(
                    Scaler(
                        input_axis=axis,
                        payoff_kind=kind,
                        cap=cap,
                        attribution=attribution,
                        obtainable=True,
                        pob_measurable=measurable,
                        carrier_id=record.id,
                        carrier_name=record.name_en,
                        carrier_type=record.type,
                        evidence=text.strip()[:200],
                        warnings=_warnings(kind, cap, attribution, measurable, text),
                    )
                )

    kinds = Counter(s.payoff_kind for s in scalers)
    # 곱연산이 먼저 보이도록 — 크기 순서가 곧 판정 순서다.
    order = ["more", "added", "sustain", "increased", "counter", "resource", "reach", "other"]
    by_kind = tuple((k, kinds[k]) for k in order if kinds[k])
    return ScalerScan(
        scalers=tuple(scalers),
        by_kind=by_kind,
        excluded=tuple(sorted(excluded.items())),
    )
