"""근거 없는 가정 검사 — "빌드에 없는 파워를 켜 놓았는가" (사용자 실증 2026-08-06).

인게임 구현 중 발견된 결함이다. 생성본의 출혈 효과 강도가 **x15.81**인데 같은
컨셉의 실제 캐릭터는 **x5.72**였고(출혈 DPS 706,661 vs 239,936), 차액의 정체는
계산 탭에 `100% more Base`·`30% more Skill: Incision`으로 찍혀 있었다 — **아이템도
패시브도 아닌 config**다. 사용자 지적: "패시브 노드나 아이템에서는 절대 알 수 없는
수치들이 들어가있어."

전수 조사 결과 일회성이 아니었다: 산출물 11건에 config Input이 있었고, 그중 9건이
`conditionBleedAggravated`·`multiplierIncisionStackCount`(오늘자 8건은 중첩 **10**)
같은 최상 조건 가정을 상시 참으로 깔고 있었다.

## 왜 아무도 못 잡았나 — 검사의 방향 편향

엔진의 자동 검사는 전부 **한 방향**이었다. `config_relevance`는 "관련 있는데 **안
켜진**" config를, `axes`는 "**비어 있는**" 축을 찾는다 — 둘 다 "너 파워를 빠뜨렸다"만
본다. **"너가 없는 파워를 가정했다"를 보는 검사가 없었다.** 그래서 근거 없는 가정은
조용히 통과해 3배를 부풀렸다.

## 판정

`config_relevance`가 쓰는 **PoB 자신의 관련성 조건**(`ConfigOptions.lua`의 ifFlag·
ifMod·ifCond)을 반대로 쓴다: 설정된 config의 조건 키워드가 빌드 문구(아이템·젬·
패시브) 어디에도 없으면 **근거 없음**이다.

    neutral    적·퀘스트·표시 설정 — 플레이어 파워가 아니다 (감사 대상 아님)
    grounded   빌드에 공급원이 있다 — 단 **가정**임은 남긴다(상시 참이 아닐 수 있다)
    ungrounded 공급원이 전무하다 — 이 측정은 빌드를 왜곡한다

`ungrounded`는 조립을 **막는다**(탐침 게이트와 같은 성격). 빌드 품질을 판정하는 게
아니라(AD-3), 빌드를 왜곡하는 측정치의 생산을 거부하는 것이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 플레이어 파워가 아니라 **상황**을 기술하는 설정 — 감사 대상이 아니다.
# (적 스펙·보스 여부·거리는 측정 시나리오이고, 퀘스트 보상은 실제로 받은 것이다.)
_NEUTRAL_PREFIXES = ("quest", "misc_", "skill_", "enemy", "custom")
_NEUTRAL_EXACT = frozenset(
    {"ChanceToIgnoreEnemyPhysicalDamageReductionMode", "detonateDeadCorpseLife"}
)
# 꺼져 있거나 0인 값은 파워를 만들지 않는다
_OFF_VALUES = frozenset({"false", "nil", "0", "", "none"})


@dataclass(frozen=True)
class ConfigVerdict:
    var: str
    value: str
    status: str  # grounded | ungrounded | neutral
    label: str = ""
    reason: str = ""
    matched_in: str = ""  # 근거를 찾은 출처 (grounded일 때)


@dataclass(frozen=True)
class LockedNode:
    node_id: int
    name: str
    locked_to: str  # 이 노드를 해금할 수 있는 어센던시 실명 ("" = 전직 제약 아님)
    stats: tuple[str, ...] = ()
    # 선행 노드 요구형에서 **아직 안 찍은** 노드들. locked_to가 ""면 이쪽이 사유다.
    missing_nodes: tuple[int, ...] = ()

    @property
    def why(self) -> str:
        if self.locked_to:
            return f"{self.locked_to} 전용"
        return f"선행 노드 {', '.join(str(n) for n in self.missing_nodes)} 미할당"


@dataclass(frozen=True)
class AssumptionReport:
    verdicts: tuple[ConfigVerdict, ...]
    ascendancy_error: str = ""
    locked_nodes: tuple[LockedNode, ...] = ()

    @property
    def ungrounded(self) -> tuple[ConfigVerdict, ...]:
        return tuple(v for v in self.verdicts if v.status == "ungrounded")

    @property
    def grounded(self) -> tuple[ConfigVerdict, ...]:
        return tuple(v for v in self.verdicts if v.status == "grounded")

    @property
    def blocking(self) -> tuple[str, ...]:
        """조립을 막아야 하는 사유들 — 측정이 빌드를 왜곡한다."""
        out = [
            f"config `{v.var}`={v.value} — 빌드에 공급원이 없다. {v.reason}"
            for v in self.ungrounded
        ]
        if self.ascendancy_error:
            out.append(self.ascendancy_error)
        if self.locked_nodes:
            detail = ", ".join(f"{n.node_id}({n.name}→{n.why})" for n in self.locked_nodes[:6])
            out.append(
                f"해금 불가 노드 {len(self.locked_nodes)}개를 찍었다: {detail}"
                f"{'…' if len(self.locked_nodes) > 6 else ''} — 다른 어센던시에서만 열리거나 "
                f"선행 노드를 요구하는 노드다. **PoB 계산기는 이 제약을 검사하지 않아 스탯을 "
                f"그대로 더하고**, 트리 화면엔 그리지 않으며, 인게임에선 찍을 수 없다"
            )
        return tuple(out)

    @property
    def notes(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.grounded:
            out.append(
                f"⚠ 상시 참으로 가정한 config {len(self.grounded)}건 — 공급원은 있으나 "
                f"**항상 켜져 있지는 않다**. 유지율(가동 조건)을 design.md에 적고, 상시가 "
                f"아니면 끄고 다시 재라: "
                + ", ".join(f"{v.var}={v.value}({v.matched_in})" for v in self.grounded)
            )
        return tuple(out)


# 요구절 표지 — 그 조건이 **참일 때** 효과를 얻는다는 문형. 이 안에 등장한 단어는
# 그 조건을 **공급**하지 않는다. 어휘(KD-2)에 없는 축까지 덮는 문장 층위의 일반화다
# (사용자 지시 2026-08-06: "특정 상태를 요구하는 기재가 공급하지는 않는다").
_DEMAND_MARKER = re.compile(
    r"\b(?:against|while|when(?:ever)?|if|during|per\b|that are|which are"
    r"|on\s+\w+\s+targets?|have been|you have\s+\w+ed)\b",
    re.I,
)
# 조건 단어 **바로 앞**에 붙는 요구 표지 (사이에 관사·수식어 2개까지 허용)
_DEMAND_HEAD = re.compile(
    r"\b(?:against|on|while|when(?:ever)?|if|during|per|that are|which are|versus|vs)\s+"
    r"(?:\w+\s+){0,2}$",
    re.I,
)


def _is_demand_only(lines: Sequence[str], patterns: Sequence[re.Pattern[str]]) -> bool:
    """이 출처가 그 조건을 **요구만** 하는가 (공급하지 않는가).

    실측 2026-08-06: 피 가시의 "Bleeding you inflict **on Cursed targets** is
    Aggravated"는 저주를 요구할 뿐인데, 단어가 있다는 이유로 저주 공급원으로 오인돼
    `conditionEnemyCursed`가 통과했다. 그 오판이 `100% more Base`(출혈 악화)를
    성립시켜 출혈 강도를 x2.76 부풀렸다.

    문장 단위로 본다 — 조건 단어가 든 문장이 **전부** 요구절이고 공급절 표지가 하나도
    없으면 요구 전용이다. 하나라도 공급절이면 근거로 인정한다(보수적 — 오탐으로 정상
    빌드를 막으면 게이트 자체가 우회 대상이 된다).
    """
    occurrences: list[bool] = []
    for line in lines:
        text = str(line)
        for match in patterns[0].finditer(text):
            # 표지는 **그 단어 바로 앞**을 봐야 한다 — 문장 어딘가에 공급 동사가 있어도
            # 다른 대상에 걸린 것일 수 있다. "Bleeding you **inflict** on Cursed targets"의
            # inflict는 출혈에 걸린 것이지 저주를 공급하지 않는다(실측 오판 사례).
            prefix = text[max(0, match.start() - 24) : match.start()]
            occurrences.append(bool(_DEMAND_HEAD.search(prefix)))
    return bool(occurrences) and all(occurrences)


def _stem_pattern(keyword: str) -> re.Pattern[str]:
    """어미 변화를 흡수한 매칭 — 'Aggravated' 설정이 'Aggravate Bleeding' 문구에
    걸려야 한다. 접미 2자를 떼고 `\\w*`로 여는 방식(실측: 룬 문구가 동사형이다)."""
    stem = keyword[:-2] if len(keyword) > 6 else keyword
    return re.compile(rf"\b{re.escape(stem)}\w*", re.I)


def build_text_sources(
    build_spec: Mapping[str, Any], *, root: Path | None = None
) -> dict[str, list[str]]:
    """빌드가 실제로 가진 효과 문구 — 아이템 텍스트 + 젬·패시브의 KB stats.

    config의 근거는 여기 있어야 한다. 여기 없으면 그 파워는 빌드에 없는 것이다.
    """
    from pok.kb.store import load as store_load

    sources: dict[str, list[str]] = {}
    for item in build_spec.get("items") or []:
        lines = str(item.get("text", "")).splitlines()
        if lines:
            name = lines[1] if len(lines) > 1 else str(item.get("slot", "item"))
            sources[f"아이템:{name}"] = lines
    for jewel in build_spec.get("jewels") or []:
        lines = str(jewel.get("text", "")).splitlines()
        if lines:
            sources[f"주얼:{lines[1] if len(lines) > 1 else '?'}"] = lines

    records = store_load(root).records
    by_name = {}
    by_node = {}
    for rid, rec in records.items():
        data = rec.raw.get("data") or {}
        if rec.type in ("Skill", "Support"):
            by_name[str((rec.raw.get("name") or {}).get("en") or "").lower()] = (rid, data)
        elif rec.type == "Passive" and data.get("node_id") is not None:
            by_node[int(data["node_id"])] = (rid, data)

    for group in build_spec.get("skills") or []:
        for gem in group.get("gems") or []:
            hit = by_name.get(str(gem.get("name", "")).lower())
            if hit:
                rid, data = hit
                stats = [str(s) for s in (data.get("stats") or [])]
                if data.get("description"):
                    stats.append(str(data["description"]))
                if stats:
                    sources[f"젬:{gem.get('name')}"] = stats
    for node in build_spec.get("tree_nodes") or ():
        hit = by_node.get(int(node))
        if hit:
            rid, data = hit
            stats = [str(s) for s in (data.get("stats_en") or data.get("stats") or [])]
            if stats:
                sources[f"노드:{rid}"] = stats
    return sources


_ENEMY_STATUS_VAR = re.compile(r"^conditionEnemy([A-Z]\w+)$")


def _status_grounding(
    var: str, sources: Mapping[str, list[str]], *, root: Path | None
) -> ConfigVerdict | None:
    """적 상태이상 config는 **공급 술어**로 판정한다 (일반형, 사용자 지시 2026-08-06).

    문구에 단어가 있기만 하면 근거로 인정하던 방식은 **요구와 공급을 구분하지 못한다**.
    실측: `conditionEnemyCursed`를 켠 근거로 피 가시 노드가 잡혔는데, 그 노드 문구는
    "Bleeding you inflict **on Cursed targets** is Aggravated" — 저주를 *요구*하지
    공급하지 않는다. 빌드에 저주 스킬이 없었고, 그 오판이 `100% more Base`(출혈 악화)를
    성립시켜 출혈 강도를 x2.76 부풀렸다.

    그래서 KB의 요구·공급 추출기(KD-2 통제 어휘)를 쓴다 — 공급이 하나라도 있어야
    근거로 인정하고, **요구만 있으면 근거 없음**이다.
    """
    m = _ENEMY_STATUS_VAR.match(var)
    if m is None:
        return None
    from pok.kb.graph.predicates import extract_predicates
    from pok.kb.store import load as store_load

    subjects = store_load(root).subjects
    status = m.group(1).lower()
    if status not in (subjects.get("enemy.status", {}).get("values") or []):
        return None  # 어휘 밖 상태 — 기계로 못 가린다. 키워드 경로에 맡긴다
    key = f"enemy.status={status}"
    demanded_in = ""
    for source, lines in sources.items():
        for predicate in extract_predicates(list(lines), subjects):
            if predicate.key != key:
                continue
            if predicate.direction == "supply":
                return ConfigVerdict(
                    var, "", "grounded",
                    reason=f"공급 술어 확인({key})", matched_in=source,
                )  # fmt: skip
            demanded_in = demanded_in or source
    reason = (
        f"'{status}'를 **공급**하는 문구가 빌드에 없다"
        + (
            f" — {demanded_in}은 그 상태를 *요구*할 뿐 공급하지 않는다"
            if demanded_in
            else " (요구·공급 어느 쪽도 없다)"
        )
        + ". 공급원이 없으면 이 조건은 인게임에서 참이 되지 않는다"
    )
    return ConfigVerdict(var, "", "ungrounded", reason=reason)


def audit_config(
    build_spec: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> tuple[ConfigVerdict, ...]:
    """설정된 config가 빌드에 근거를 갖는지 판정한다 — 없으면 근거 없음.

    적 상태이상(`conditionEnemy*`)은 **공급 술어**로, 나머지는 PoB 관련성 키워드로
    판정한다. 전자가 일반형이고 후자는 아직 단어 존재만 보는 근사다.
    """
    from pok.pob.catalog import config_options

    from .config_relevance import _keywords_of

    config = dict(build_spec.get("config") or {})
    if not config:
        return ()
    options = {o.var: o for o in config_options(root)}
    sources = build_text_sources(build_spec, root=root)

    verdicts: list[ConfigVerdict] = []
    for var, raw_value in config.items():
        value = str(raw_value)
        if var.startswith(_NEUTRAL_PREFIXES) or var in _NEUTRAL_EXACT:
            verdicts.append(ConfigVerdict(var, value, "neutral", reason="측정 시나리오 설정"))
            continue
        if value.lower() in _OFF_VALUES:
            verdicts.append(
                ConfigVerdict(var, value, "neutral", reason="꺼짐 — 파워를 만들지 않는다")
            )
            continue
        # 적 상태이상은 **공급 술어**로 판정한다 (요구/공급 구분 — 일반형)
        status_verdict = _status_grounding(var, sources, root=root)
        if status_verdict is not None:
            verdicts.append(
                ConfigVerdict(
                    var, value, status_verdict.status,
                    reason=status_verdict.reason, matched_in=status_verdict.matched_in,
                )
            )  # fmt: skip
            continue
        option = options.get(var)
        keywords = _keywords_of(option.keywords) if option else []
        if not keywords:
            verdicts.append(
                ConfigVerdict(
                    var, value, "neutral",
                    reason="PoB에 관련성 조건이 없어 근거를 기계로 못 가린다 — 사람이 볼 것",
                )
            )  # fmt: skip
            continue
        patterns = [_stem_pattern(k) for k in keywords]
        found = ""
        demand_only_in = ""
        for source, lines in sources.items():
            blob = " ".join(lines)
            if not all(p.search(blob) for p in patterns):
                continue
            # 단어가 있다고 공급이 아니다 — 요구 전용 출처는 근거로 세지 않는다
            if _is_demand_only(lines, patterns):
                demand_only_in = demand_only_in or source
                continue
            found = source
            break
        if found:
            verdicts.append(
                ConfigVerdict(
                    var, value, "grounded",
                    label=option.label if option else "",
                    reason=f"공급원 있음({' + '.join(keywords)})",
                    matched_in=found,
                )
            )  # fmt: skip
        elif demand_only_in:
            verdicts.append(
                ConfigVerdict(
                    var, value, "ungrounded",
                    label=option.label if option else "",
                    reason=(
                        f"{demand_only_in}은 '{' + '.join(keywords)}'를 **요구**할 뿐 "
                        f"공급하지 않는다 — 이 조건을 성립시키는 기재가 빌드에 따로 있어야 한다"
                    ),
                )
            )  # fmt: skip
        else:
            verdicts.append(
                ConfigVerdict(
                    var, value, "ungrounded",
                    label=option.label if option else "",
                    reason=(
                        f"'{' + '.join(keywords)}'를 주는 아이템·젬·노드가 스펙에 없다 — "
                        f"이 설정이 만든 배율은 인게임에서 나오지 않는다"
                    ),
                )
            )  # fmt: skip
    return tuple(verdicts)


def check_ascendancy_entry(tree_nodes: Sequence[int], *, root: Path | None = None) -> str:
    """어센던시 노드를 찍었으면 **시작 노드**도 찍혀 있어야 한다.

    실측 2026-08-06: 생성본이 혈액술·피 가시 등 어센던시 9개를 찍고 시작 노드
    (59822 블러드 메이지)를 빠뜨렸다. PoB는 예산을 `allocAscendancy=8`로 세어
    **합법 통과**시키고 효과까지 반영했지만(`LifePerSecondCost` 105.16 = 혈액술),
    인게임에서는 시작 노드 없이 어센던시를 찍을 수 없다.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.graph import TreeGraph

    graph = TreeGraph(knowledge_dir(root))
    allocated = {int(n) for n in tree_nodes}
    used: dict[str, list[int]] = {}
    starts: dict[str, int] = {}
    for node_id, node in graph.nodes.items():
        if not node.ascendancy:
            continue
        if node.kind == "ascendancy-start":
            starts[node.ascendancy] = node_id
        if node_id in allocated:
            used.setdefault(node.ascendancy, []).append(node_id)
    for ascendancy, nodes in used.items():
        start = starts.get(ascendancy)
        if start is None or start in allocated:
            continue
        if len(nodes) == 1 and nodes[0] == start:
            continue
        return (
            f"어센던시 노드 {len(nodes)}개를 찍었는데 **시작 노드 {start}**"
            f"({ascendancy})가 없다 — 인게임에서는 시작 노드를 거치지 않으면 어센던시를 "
            f"찍을 수 없다. PoB는 예산만 세고 통과시키므로 이 측정은 실현 불가능한 트리다"
        )
    return ""


def check_locked_nodes(
    tree_nodes: Sequence[int], ascendancy: str | None, *, root: Path | None = None
) -> tuple[LockedNode, ...]:
    """다른 어센던시 전용 **해금 노드**를 찍었는지 (실측 2026-08-06 인게임 대조).

    PoB 트리 데이터의 `unlockConstraint`는 "이 어센던시에서만 열린다"를 명시하는데,
    **PoB 계산기는 이걸 검사하지 않는다** — allocNodes에 있으면 스탯을 그대로 더한다.
    트리 화면에는 그리지 않으므로 두 빌드를 비교해도 차이가 보이지 않는다. 그래서
    블러드 메이지 빌드에 오라클 전용 7개(피의 향기·출혈 지속시간 x2·힘과 주문 피해
    x3·강력한 시전)가 섞여 출혈 지속시간이 1.50 → 1.90으로 부풀었다.

    `ascendancy`는 실명("Blood Mage") 또는 코드("Witch2") 어느 쪽이든 받는다.

    **전용 해금 외에 선행 노드 요구형도 잡는다** — `unlock_constraint`에 `ascendancy`
    없이 `nodes`만 있는 꼴(실측 2026-08-07: 3건). 전직 대조만 하던 이전 판은 이걸
    그냥 통과시켰다: 「탈주자의 길」은 노터블 3개를 먼저 찍어야 열리는데, 안 찍고
    할당해도 PoB는 카오스 저항 +8%를 그대로 더해 준다.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.graph import TreeGraph

    graph = TreeGraph(knowledge_dir(root))
    # 코드(Witch2) → 실명(Blood Mage) 해소 — unlock_constraint는 실명으로 적혀 있다
    allowed = {str(ascendancy or ""), str(graph.resolve_ascendancy(ascendancy) or "")}
    allocated_ids = {int(n) for n in tree_nodes}
    out: list[LockedNode] = []
    for node_id in allocated_ids:
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        locked_to = node.locked_to
        missing = tuple(sorted(set(node.requires_nodes) - allocated_ids))
        if (locked_to is None or locked_to in allowed) and not missing:
            continue
        out.append(
            LockedNode(
                node_id=node_id,
                name=node.name_ko or node.name_en,
                locked_to=locked_to or "",
                stats=node.stats_en,
                missing_nodes=missing,
            )
        )
    return tuple(sorted(out, key=lambda n: n.node_id))


def check_assumptions(
    build_spec: Mapping[str, Any], *, root: Path | None = None
) -> AssumptionReport:
    """근거 없는 가정 전량 — config 감사 + 어센던시 진입 + 해금 불가 노드."""
    nodes = build_spec.get("tree_nodes") or ()
    return AssumptionReport(
        verdicts=audit_config(build_spec, root=root),
        ascendancy_error=check_ascendancy_entry(nodes, root=root),
        locked_nodes=check_locked_nodes(
            nodes, str(build_spec.get("ascendancy") or "") or None, root=root
        ),
    )
