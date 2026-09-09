"""표기 수치의 **유지 비용** — 「이 딜을 내려면 팩마다 무엇을 하나」.

`config_relevance`(#36)의 **거울**이다. 저쪽은 *관련 있는데 꺼진 것*을 찾아 "델타 0을
효과 없음으로 읽지 마라"를 막고, 이쪽은 *켜 둔 것의 대가*를 찾아 **"이 수치가 실전에서
나오나"**를 묻는다.

## 왜 필요한가 (실측 2026-09-04)

레퍼런스로 들여온 힘스태킹 녹아내린 폭발 젬링(래더 코드)의 config가 **조건 13종을
전부 참**으로 두고 있었다. 하나씩 끄고 재 보니:

    점화·빙결·출혈·실명·최근 워크라이·최근 치명타   각 Δ 0.0%   ← 켤 이유조차 없다
    화염/번개/냉기 노출                          끄면 +3.0 / +1.5 / +0.6%   ← **마이너스**
    전쟁 깃발 설치                               -20.3%
    격노 30                                      -23.3%
    세팅 없이 팩 진입(마크까지 해제)                 표기의 **52.6%**

딜을 실제로 만드는 둘(깃발·격노)은 각각 **영광 200 축적 + 반경 6m 유지**와 전투 중
누적을 요구하고, 마크 2종은 `Limit 1 Marked targets`라 **팩에서 한 마리에만** 걸린다.
즉 표기 수치는 「몹팩마다 여섯 종을 다 걸고 그 안에 서 있을 때」의 값이었다.

`compute_pob`은 config를 그대로 받아 계산할 뿐 **누구도 그 조건의 대가를 묻지 않았다.**
자원 관문·대상 한계·반경·횟수는 전부 KB 효과 문구에 있어 기계로 감지된다 —
철칙 5(감지되면 문서가 아니라 도구에 넣는다)에 해당한다.

## 추론하지 않는다 — 문구가 근거다

⛔ **「이 조건의 공급원이 빌드에 없다」는 내지 않는다.** 첫 판(2026-09-04)이 그걸
냈다가 11건 중 6건이 오탐이었다. 두 방향 다 틀렸다:

- 재의 전령이 점화를 거는데 `conditionEnemyIgnited`가 「공급원 없음」으로 나왔다 —
  문구가 `Ignite surrounding enemies`라서 키워드 `Ignited`에 안 걸린다
- `bannerValour`의 PoB 관련성 조건은 `ifSkill "Unbound Avatar"`다 — 전쟁 깃발과
  **무관한 스킬**이라 무엇을 껴도 「공급원 없음」이 뜬다

그래서 여기서 내는 것은 **빌드에 실제로 들어 있는 스킬의 문구에서 읽은 대가**뿐이다.
"없다"는 판정은 `audit_config_upkeep(measure=True)`의 **실측 델타**가 대신한다 —
그쪽은 켠 조건을 하나씩 꺼서 재므로 문구 매칭에 기대지 않는다.

## 판단하지 않는다 (AD-3)

`scan_antagonists`와 같은 성격이다 — **거부가 아니라 신고다.** 보스 하나를 오래 잡는
구도라면 전부 거는 게 맞고, 그때 이 수치는 정직하다. "팩에서는 이 값이 안 선다"까지만
내고 판정은 호출자 몫이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.engine.constraints.config_relevance import matching_sources

# ── 유지 비용의 근거 문구 ────────────────────────────────────────────────
# 전부 게임 데이터(KB `stats`)의 실제 표기다. 추측한 문구는 넣지 않는다 —
# 안 걸리면 경고가 안 나올 뿐이지만, 잘못 걸리면 없는 결함을 조사하게 만든다.

# 마크·저주의 대상 한계. 「Limit 1 Marked targets」(저격수의 징표·전도성 징표)
_SINGLE_TARGET = re.compile(r"\bLimit\s+(\d+)\s+(?:Marked\s+)?targets?\b", re.I)
# 자원 관문. 「Requires 200 Glory to use」(전쟁 깃발) / 「Requires 100 Glory」(선대의 함성)
_RESOURCE_GATE = re.compile(r"\bRequires\s+\d+\s+[A-Za-z]+\s+to\s+use\b", re.I)
# 횟수 소진. 「Empowers 4 Attacks」(얼음촉 화살)
_LIMITED_USES = re.compile(r"\bEmpowers\s+\d+\s+\w+\b", re.I)
# 위치 구속. 「Banner Aura radius is 6 metres」·「Warcry radius is 4 metres」
_RADIUS = re.compile(r"\b(?:Aura|Warcry|Presence)\s+radius\s+is\s+(\d+(?:\.\d+)?)\s+met", re.I)
# 지속시간. 「Warcry duration is 8 seconds」·「Maximum Mark duration is 8 seconds」
_DURATION = re.compile(r"\bduration\s+is\s+(\d+(?:\.\d+)?)\s+seconds?\b", re.I)

#: 지속시간이 이보다 길면 팩 사이에 유지된다고 보고 세지 않는다. 60초는 PoE2의 장기
#: 버프(전령·오라 류) 경계로 잡은 **보수적** 값이다 — 짧게 잡으면 상시 버프가 전부
#: 경고로 나와 신호가 묻힌다.
_LONG_DURATION_S = 60.0

#: 조건 연동과 **무관하게** 내는 종류. 「한 대상에만」·「자원을 먼저 벌어야」·
#: 「횟수를 쓰면 끝」·「반경 안에 있어야」는 그 자체로 팩당 대가다.
_ALWAYS = frozenset({"single_target", "resource_gate", "limited_uses", "positional"})


@dataclass(frozen=True)
class UpkeepCost:
    """유지 비용 하나 — 어느 스킬의 어느 문구가 무엇을 요구하는가."""

    source: str  # 젬 id·`passive.N`·`item:슬롯`
    kind: str  # single_target | resource_gate | limited_uses | positional | recast
    evidence: str  # 근거 문구 **원문** (반박 가능하게)
    note: str
    config_vars: tuple[str, ...] = ()  # 이 출처에 걸린, 켜 둔 config 키들


def _is_on(value: Any) -> bool:
    """이 값이 「켜 둔 조건」인가. bool을 int로 먼저 걸러야 False가 0으로 새지 않는다."""
    if isinstance(value, bool):
        return value
    return isinstance(value, (int, float)) and value > 0


def truthy_conditions(configured: Mapping[str, Any]) -> dict[str, Any]:
    """참으로 켜 둔 config만. 문자열(퀘스트 보상)·0·False는 조건이 아니다."""
    return {str(key): value for key, value in configured.items() if _is_on(value)}


def _markers(lines: list[str], cooldown_s: float | None) -> list[tuple[str, str, str]]:
    """효과 문구 한 뭉치에서 읽히는 (종류, 근거 원문, 설명)."""
    found: list[tuple[str, str, str]] = []
    for line in lines:
        text = line.strip()
        if (m := _SINGLE_TARGET.search(text)) is not None:
            found.append(("single_target", text, f"팩에서 {m.group(1)}마리에만 걸린다"))
        if _RESOURCE_GATE.search(text) is not None:
            found.append(("resource_gate", text, "쓰기 전에 자원을 먼저 벌어야 한다"))
        if _LIMITED_USES.search(text) is not None:
            found.append(("limited_uses", text, "횟수를 쓰면 다시 걸어야 한다"))
        if (m := _RADIUS.search(text)) is not None:
            found.append(("positional", text, f"반경 {m.group(1)}m 안에 있어야 효과가 있다"))
        if (m := _DURATION.search(text)) is not None and float(m.group(1)) < _LONG_DURATION_S:
            found.append(("recast", text, "지속이 끝나면 다시 걸어야 한다"))
    if cooldown_s and cooldown_s > 0:
        found.append(("recast", f"쿨다운 {cooldown_s:g}초", "팩마다 다시 돌려야 한다"))
    return found


def find_upkeep_costs(
    build_stats_text: Mapping[str, list[str]],
    configured: Mapping[str, Any],
    *,
    cooldowns: Mapping[str, float] | None = None,
    root: Path | None = None,
) -> tuple[UpkeepCost, ...]:
    """빌드에 든 것들의 문구에서 **팩당 대가**를 읽는다.

    `build_stats_text` = {출처(젬 id·`passive.N`·`item:슬롯`): 효과 문구 줄들} —
    `config_relevance.find_unset_options`와 **같은 입력**이다.
    `cooldowns` = {같은 출처 키: 쿨다운 초}. KB `data.cooldown_s`를 그대로 넣으면 된다.

    `configured`는 **거르는 데만** 쓴다 — 쿨다운·지속처럼 흔한 표시는 그 출처가
    켜 둔 조건에 걸릴 때만 낸다(안 그러면 빌드의 모든 스킬이 신고된다). 대상 한계·
    자원 관문·횟수·반경은 조건과 무관하게 낸다.
    """
    from pok.pob.catalog import config_options

    on = truthy_conditions(configured)
    # 출처 → 그 출처에 걸린 「켜 둔」 config 키들. 관련성 판정은 PoB 자신의 조건이다.
    linked: dict[str, list[str]] = {}
    if on:
        for option in config_options(root):
            if option.var not in on or not option.conditions:
                continue
            for source, _ in matching_sources(option, build_stats_text):
                linked.setdefault(source, []).append(option.var)

    out: list[UpkeepCost] = []
    cds = dict(cooldowns or {})
    for source, lines in build_stats_text.items():
        variables = tuple(dict.fromkeys(linked.get(source, ())))
        for kind, evidence, note in _markers(list(lines), cds.get(source)):
            if kind not in _ALWAYS and not variables:
                continue
            out.append(
                UpkeepCost(
                    source=source,
                    kind=kind,
                    evidence=evidence,
                    note=note,
                    config_vars=variables,
                )
            )
    return tuple(out)
