"""스펙 자체의 설계 무결성 — **적법성과 별개 축** (백로그 #58 ①, 2026-08-11).

지금까지의 강제 지점은 전부 "이 스펙이 **지금 적법한가**"를 봤다(`items_legal` ·
`req_shortfall` · `pruned_nodes` · statSet 선언 · 룬 표기 · 색 원장). 전부 잘
동작했는데도 한 세션이 **같은 실패를 3연속**했고 세 번 다 도구가 통과시켰다 —
빌드가 「적법」한데 **애초에 빌드가 아니었기** 때문이다.

실측 2026-08-11(이관 5차): 주력기가 스펙에 없는 채로 3회차가 돌았고
`CombinedDPS`가 2,562였다. 주력기를 넣자 **24,436** — 10배가 조용히 빠져 있었다.
`items_legal ✅` · `pruned []`였다.

여기 있는 것은 **결정적 구조 검사**뿐이다(AD-3): 무엇을 만들지는 판단하지 않고,
"딜을 낼 수 있는 구성인가"라는 기계적 질문만 한다. 거부하지 않는다 — 낡은/부분
구성으로 A/B를 재는 것이 정상 작업이고, 막으면 게이트가 정상을 죽인다(§0 ⑤).
대신 **매 반환에 싣는다**: 1회성 경고는 문서와 동급이라 사라진다(#29).
"""

from __future__ import annotations

import functools
from typing import Any

# 메타/트리거 젬은 **스스로 딜을 내지 않는다** — 무엇을 발동시킬지가 있어야 한다.
# 판정 근거는 KB 태그(GAME_DATA)이지 이름 매칭이 아니다.
_META_TAGS = frozenset({"meta", "trigger"})


@functools.lru_cache(maxsize=1)
def _skill_tags() -> dict[str, frozenset[str]]:
    """스킬 표시명(소문자) → 태그. 액티브 스킬 판별과 메타 젬 판별에 함께 쓴다."""
    from pok.kb.store import load as store_load

    out: dict[str, frozenset[str]] = {}
    for record in store_load().records.values():
        if record.type != "Skill":
            continue
        tags = record.raw.get("tags") or []
        out[record.name_en.lower()] = frozenset(str(x).lower() for x in tags)
    return out


def _is_support(gem: dict[str, Any]) -> bool:
    """보조 젬인가 — PoB gemId가 정본이다(`…Support`)."""
    return str(gem.get("gem_id", "")).endswith("Support")


def _classify(gem: dict[str, Any]) -> str:
    """`support` | `meta` | `active` | `unknown`."""
    if _is_support(gem):
        return "support"
    tags = _skill_tags().get(str(gem.get("name", "")).strip().lower())
    if tags is None:
        return "unknown"
    return "meta" if tags & _META_TAGS else "active"


def spec_integrity(spec_data: dict[str, Any]) -> tuple[str, ...]:
    """스펙의 구조적 결함 — 적법성이 아니라 **설계가 성립하는가**.

    돌려주는 것은 사람이 읽을 문장이다. 어느 그룹의 몇 번째인지까지 짚어야
    호출자가 고칠 수 있다(#29: 어디를 고칠지 모르는 경고는 안 고쳐진다).
    """
    problems: list[str] = []
    groups = list(spec_data.get("skills") or [])
    if not groups:
        return ("스킬 그룹이 하나도 없다 — 딜을 낼 수 있는 구성이 아니다",)

    kinds = [[_classify(g) for g in (grp.get("gems") or [])] for grp in groups]

    # ① 주력기 부재 — `main_socket_group`이 가리키는 곳에 딜을 낼 스킬이 없다.
    #    실측: `CombinedDPS` 2,562(주력기 없음) → 24,436(투입). **10배**.
    main_index = int(spec_data.get("main_socket_group") or 1)
    if not 1 <= main_index <= len(groups):
        problems.append(
            f"main_socket_group={main_index}인데 스킬 그룹은 {len(groups)}개다 — "
            f"PoB가 다른 그룹을 주력으로 잡는다"
        )
    else:
        main = groups[main_index - 1]
        main_kinds = kinds[main_index - 1]
        active_at = [i for i, k in enumerate(main_kinds) if k == "active"]
        if not active_at:
            gems = [str(g.get("name", "?")) for g in (main.get("gems") or [])]
            problems.append(
                f"skills[{main_index - 1}]는 **주력 그룹인데 딜을 낼 스킬이 없다** "
                f"(젬: {gems or '(비어 있음)'}) — 메타 젬·보조만으로는 딜이 나오지 않는다. "
                f"실측 2026-08-11: 이 상태로 3회차가 돌았고 `CombinedDPS` 2,562 vs "
                f"주력기 투입 시 24,436(**10배**)"
            )
        else:
            # ② 주력 스킬 지정 — PoB의 `mainActiveSkill`은 그룹 안 **순번**이다.
            #    메타 젬을 가리키면 그 그룹의 딜이 통째로 안 잡힌다.
            pointer = int(main.get("main_active_skill") or 1)
            if 1 <= pointer <= len(main_kinds) and main_kinds[pointer - 1] != "active":
                names = [str(g.get("name", "?")) for g in (main.get("gems") or [])]
                suggest = ", ".join(f"{i + 1}={names[i]!r}" for i in active_at)
                problems.append(
                    f"skills[{main_index - 1}].main_active_skill={pointer}가 "
                    f"{names[pointer - 1]!r}(딜을 내지 않는 젬)를 가리킨다 — "
                    f"딜을 낼 젬은 {suggest}"
                )

    # ③ 트리거 미연결 — 메타 젬이 있는데 **발동될 스킬**이 같은 그룹에 없다.
    #    PoB는 오류를 내지 않는다. 조립도 성공이고 젬도 `enabled="true"`다.
    for gi, (grp, kind_list) in enumerate(zip(groups, kinds, strict=True)):
        metas = [
            str(g.get("name", "?"))
            for g, k in zip(grp.get("gems") or [], kind_list, strict=True)
            if k == "meta"
        ]
        if metas and "active" not in kind_list:
            problems.append(
                f"skills[{gi}]: 트리거 젬 {metas}이 있는데 **발동될 스킬이 없다** — "
                f"그 그룹은 정신력만 점유하고 아무것도 하지 않는다. 같은 그룹에 "
                f"발동시킬 액티브 스킬을 넣을 것"
            )
    return tuple(problems)
