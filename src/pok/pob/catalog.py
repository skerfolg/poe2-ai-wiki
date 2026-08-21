"""PoB 카탈로그 — 유효한 `gem_id`·`config` 키 (이관 건 3, 2026-08-05).

**존재하지 않는 `gem_id`를 넣어도 오류가 나지 않았다.** PoB가 `nameSpec`(표시 이름)으로
대체 해석하기 때문인데, 이름까지 틀리거나 모호했다면 **젬이 소리 없이 사라지고**
세션은 낮은 숫자를 실측으로 받아 그걸 근거로 설계했을 것이다. 실제로 한 세션이
트리 62포인트를 잘못된 id로 최적화한 뒤에야 발견했다.

같은 계열의 결함이 한 세션에서 3건 나왔다 — 전부 "조용한 성능 저하, 명시적 실패 없음":

1. 없는 `gem_id` → 이름 폴백, 경고 없음
2. `multiplierIncisionStackCount` 기본 0 → 절개가 무가치해 보임(필수 젬을 뺄 뻔했다)
3. `conditionBleedAggravated` 기본 off → 상시 켜지는 축인데 출혈 수치가 절반

## 관련 config를 결정적으로 판정할 수 있다

`Modules/ConfigOptions.lua`의 각 항목은 **자기가 언제 관련되는지**를 들고 있다:

    { var = "multiplierIncisionStackCount", ifFlag = "Condition:CanInflictIncision", … }
    { var = "conditionBleedAggravated",     ifMod  = "BleedChance", … }

PoB가 UI에 표시할지 정할 때 쓰는 조건이다. 우리는 그 조건 문자열을 **빌드의 젬 효과
문구(KB `stats`, 2026-08-05 수록)와 대조**해 "관련 있는데 미설정"을 낸다. 추측이
아니라 PoB 자신의 관련성 정의를 쓰는 것이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pok.kb.pob_pin import pob_src_dir

_GEM_ID = re.compile(r'\["(Metadata/Items/Gems/[^"]+)"\]')
# PoB 항목은 **id를 둘** 갖는다: 테이블 키(PoB 내부 id)와 `gameId`(게임 쪽 id).
# poe.ninja가 내보내는 PoB 코드는 **gameId를 쓴다** — 그래서 키만 색인하면 래더
# 코드의 젬이 전부 "PoB에 없다"로 거부된다(실측 2026-08-12: 마셜 아티스트 10벌
# 전량 복원 실패, 거부 501건). 게임 id는 단수형 `Items/Gem/`도 쓴다(PoB 데이터에
# 498건) — poe.ninja 버그가 아니라 게임 표기다.
_GEM_BLOCK = re.compile(r'\["(Metadata/Items/Gems/[^"]+)"\]\s*=\s*\{(.*?)\n\t\}', re.S)
_GAME_ID = re.compile(r'gameId\s*=\s*"(Metadata/Items/Gems?/[^"]+)"')
_NAME_SPEC = re.compile(r'name\s*=\s*"([^"]+)"')
# 항목 시작만 잡고 **다음 항목 시작 직전까지**를 본문으로 삼는다. 블록을 정규식으로
# 닫으려 하면 중첩 `{}`(apply 함수 본문)에서 어긋나 절반을 놓친다 — 실측 2026-08-05:
# 1023개 중 542개만 잡혔다.
_CONFIG_START = re.compile(r'\{\s*var\s*=\s*"(\w+)"')
_COND_KEYS = ("ifFlag", "ifMod", "ifCond", "ifEnemyCond", "ifSkill", "ifSkillList", "ifMult")
_LABEL = re.compile(r'label\s*=\s*"([^"]*)"')
_TOOLTIP = re.compile(r'tooltip\s*=\s*"([^"]*)"')


def pob_src(root: Path | None = None) -> Path:
    return pob_src_dir(root)


@dataclass(frozen=True)
class ConfigOption:
    """PoB config 항목 하나 — 언제 관련되는지를 자기가 안다."""

    var: str
    label: str
    conditions: tuple[str, ...]  # ifFlag/ifMod/… 값들 (관련성 판정용)
    tooltip: str = ""
    # 각 조건이 **어느 키에서 왔는가**(`conditions`와 같은 순서). 종류마다 관련성의
    # 뜻이 다르다 — 특히 `ifMult`는 "그 승수를 **쓰는 접사가 빌드에 있을 때만**"
    # 의미가 있다(승수만 세워 두면 아무것도 안 변한다). 이 구분이 없어서
    # `multiplierFreezeShockIgniteOnEnemy`가 원소 작렬에 거짓 양성으로 붙었다
    # (실측 2026-08-21 — 그 힌트를 좇아 있지도 않은 PoB 버그를 조사했다).
    condition_kinds: tuple[str, ...] = ()

    @property
    def keywords(self) -> tuple[str, ...]:
        """조건 문자열에서 뽑은 매칭 키워드 — `Condition:CanInflictIncision` → `Incision`."""
        out: list[str] = []
        for cond in self.conditions:
            bare = cond.split(":")[-1]
            # 접두 기능어를 떼면 남는 게 실제 대상이다 — CanInflictIncision → Incision
            bare = re.sub(
                r"^(Can|Is|Are|Has|Have|Do|Using|While|Enemy|Your)+(Inflict|Be|Have)?", "", bare
            )
            # CamelCase를 단어로 — CanInflictIncision → Incision
            words = re.findall(r"[A-Z][a-z]{2,}", bare)
            out.extend(words or ([bare] if bare else []))
        return tuple(dict.fromkeys(out))


@lru_cache(maxsize=4)
def gem_aliases(root: Path | None = None) -> dict[str, str]:
    """게임 id(`gameId`) → PoB 내부 id.

    래더에서 받은 PoB 코드는 게임 id로 적혀 있다. 이 표가 없으면 코퍼스를 우리
    스펙으로 되돌릴 수 없다 — 실측 2026-08-12: 10벌 전량 실패.
    """
    text = (pob_src(root) / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for key, body in _GEM_BLOCK.findall(text):
        game = _GAME_ID.search(body)
        if game and game.group(1) != key:
            out.setdefault(game.group(1), key)
    return out


def canonical_gem_id(gem_id: str, root: Path | None = None) -> str:
    """게임 id면 PoB 내부 id로 바꾼다. 이미 내부 id면 그대로."""
    return gem_aliases(root).get(gem_id, gem_id)


@lru_cache(maxsize=4)
def gem_ids(root: Path | None = None) -> frozenset[str]:
    """PoB가 아는 `gem_id` 전량 (`Data/Gems.lua`) — 내부 id와 게임 id 둘 다."""
    text = (pob_src(root) / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    return frozenset(_GEM_ID.findall(text)) | frozenset(gem_aliases(root))


@lru_cache(maxsize=4)
def gem_names(root: Path | None = None) -> dict[str, str]:
    """표시 이름 → gem_id. 이름만 아는 호출자에게 정본 id를 알려주려는 것."""
    text = (pob_src(root) / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for match in re.finditer(r'\["(Metadata/Items/Gems/[^"]+)"\]\s*=\s*\{(.*?)\n\t\}', text, re.S):
        name = _NAME_SPEC.search(match.group(2))
        if name:
            out.setdefault(name.group(1), match.group(1))
    return out


@lru_cache(maxsize=4)
def config_options(root: Path | None = None) -> tuple[ConfigOption, ...]:
    """PoB config 항목 전량 (`Modules/ConfigOptions.lua`)."""
    text = (pob_src(root) / "Modules" / "ConfigOptions.lua").read_text(
        encoding="utf-8", errors="replace"
    )
    starts = list(_CONFIG_START.finditer(text))
    out: list[ConfigOption] = []
    for i, match in enumerate(starts):
        var = match.group(1)
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        body = text[match.end() : end]
        conditions: list[str] = []
        kinds: list[str] = []
        for key in _COND_KEYS:
            found = re.findall(rf'{key}\s*=\s*"([^"]+)"', body)
            conditions.extend(found)
            kinds.extend([key] * len(found))
        label = _LABEL.search(body)
        tooltip = _TOOLTIP.search(body)
        out.append(
            ConfigOption(
                var=var,
                label=label.group(1) if label else "",
                conditions=tuple(conditions),
                tooltip=tooltip.group(1) if tooltip else "",
                condition_kinds=tuple(kinds),
            )
        )
    return tuple(out)


@lru_cache(maxsize=4)
def quest_config_vars(root: Path | None = None) -> frozenset[str]:
    """퀘스트 보상 설정 키 — PoB가 **동적으로 만든다**.

    `ConfigOptions.lua`에는 리터럴로 없고 `"quest" .. Description .. Area .. Info`로
    조립된다(`data.questRewards` 순회). 그래서 리터럴만 훑던 카탈로그는 이 키들을
    모르고, 래더에서 받은 코드를 **정상인데 거부**했다(실측 2026-08-12: 코퍼스
    복원이 여기서 전량 막혔다 — BACKLOG 형태 ⑤ 「게이트가 정상을 막는다」).
    """
    text = (pob_src(root) / "Data" / "QuestRewards.lua").read_text(
        encoding="utf-8", errors="replace"
    )
    out: set[str] = set()
    for block in re.split(r"\n\t\},?", text):
        fields = dict(re.findall(r'\["(\w+)"\]\s*=\s*"([^"]*)"', block))
        if not fields.get("Description"):
            continue
        # `useConfig = false`인 항목은 PoB가 설정을 만들지 않는다(포인트 보상 등).
        if re.search(r'\["useConfig"\]\s*=\s*false', block):
            continue
        out.add("quest" + fields["Description"] + fields.get("Area", "") + fields.get("Info", ""))
    return frozenset(out)


@lru_cache(maxsize=4)
def config_vars(root: Path | None = None) -> frozenset[str]:
    return frozenset(o.var for o in config_options(root)) | quest_config_vars(root)


def _similar(name: str, pool: list[str], limit: int = 5) -> list[str]:
    """오타·표기 차이를 넘어 근접 후보 — 막다른 길 대신 다음 수를 준다."""
    import difflib

    return difflib.get_close_matches(name, pool, n=limit, cutoff=0.6)


def suggest_gem_ids(unknown: str, root: Path | None = None) -> list[str]:
    """미지의 gem_id에 대한 정본 후보. 이름으로 준 경우도 잡는다."""
    ids = gem_ids(root)
    by_name = gem_names(root)
    # "Heavy Swing" 처럼 표시 이름을 넣은 경우가 흔하다
    if unknown in by_name:
        return [by_name[unknown]]
    tail = unknown.rsplit("/", 1)[-1]
    hits = _similar(unknown, sorted(ids))
    if not hits:
        hits = [i for i in sorted(ids) if tail.lower() in i.lower()][:5]
    if not hits:
        name_hits = _similar(tail, sorted(by_name))
        hits = [by_name[n] for n in name_hits]
    return hits


def suggest_config_vars(unknown: str, root: Path | None = None) -> list[str]:
    return _similar(unknown, sorted(config_vars(root)))


# ── statSet·skillTypes 카탈로그는 여기 없다 (#63 P2) ─────────────────────
# 스킬 모드(statSets)·담체 판정식(require/exclude)은 **게임 사실**이라 KB가 정본이다:
# 수집은 `kb/ingest/skill_types.py`(패치 때), 런타임 읽기는 `kb/skill_facts.py`.
# 여기 남는 것은 "PoB에 실재하는가"라는 **계산기 계약 검증**(gem_ids·config_vars)뿐 —
# 그건 PoB가 옳은 권위다. 이 경계는 `tests/unit/test_pob_source_boundary.py`가 지킨다.
