"""스킬 타입·모드 수집 — 구조화 사실이 KB를 건너뛰지 않게 한다 (#63 P1).

## 왜 이 수집기인가

담체 판정(`require`/`exclude`) 591건 · 스킬 모드(`statSets`) 140건이 **KB에 없고
PoB 소스에만** 있어서, `hosting.py`·statSet 게이트가 런타임에 gitignore된 파생물
(`external/pob`)을 직독했다 — 철칙 2 위반이고, `search_kb`로도 닿지 못했다.
다른 PoB 유래 데이터(트리·상태이상·마법사의 유산)는 전부 여기(`kb/ingest/`)를
거쳐 KB에 들어간다. **읽는 것이 문제가 아니라 읽는 시점이 런타임인 것이 문제다.**

## 무엇을 수록하나

`Data/Skills/*.lua`의 스킬 블록에서 담체 판정·모드 선택에 필요한 전부를
KB Skill·Support 레코드의 `data.pob`에 넣는다:

- `skillTypes`·`minionSkillTypes` — 이 스킬이 무엇인가 (담체 판정의 피연산자)
- `requireSkillTypes`·`excludeSkillTypes`·`addSkillTypes` — 담체가 거는 조건.
  ⚠ **후위(RPN) 식이라 순서가 의미다** — `{Spell, Totemable, AND}`는 "둘 다",
  `{Spell, Totemable}`는 "둘 중 하나". 정렬하지 말 것.
- `statSets` 라벨 — 모드가 2개 이상이면 지정 없이 PoB가 조용히 1번을 쓴다(#52)
- `fromItem`/`cannotBeSupported`/`supportGemsOnly`/`ignoreMinionTypes` 플래그

메타 젬은 **반쪽이 둘**이다(주문 토템: 소환 스킬 + 보조 판정 스킬) — `effects`
배열이 그 구조를 그대로 담는다(첫 항목 = `grantedEffectId`, 이후 = additional).

## 매칭

KB 레코드 ↔ PoB는 **표시 이름(en)**으로 잇는다(젬 966건 중 911건 일치 실측).
젬이 아닌 스킬(아이템 부여·기본 공격)은 플레이어 파일(`act_*`·`sup_*`·`other`)의
스킬 블록 이름으로 잇는다 — `spectre.lua`(몬스터)는 후보에서 뺀다(동명 오염 방지).
못 이은 것은 **양방향 모두 리포트로 낸다**(KI-7 완전성) — 조용한 누락 금지.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from pathlib import Path
from typing import Any

from pok.kb.pob_pin import POB_COMMIT, pob_src_dir
from pok.kb.store import load as store_load
from pok.kb.store import write_record, write_shard

_SOURCE_REF = "Data/Skills (skillTypes·statSets·require/exclude·fromItem)"

# ── Lua 파싱 (pob/catalog.py에서 이관 — #63 P2로 그쪽은 계산기 계약만 남는다) ──
_SKILL_BLOCK = re.compile(r'^skills\["([^"]+)"\]\s*=\s*\{', re.M)
_GEM_BLOCK = re.compile(r'\["(Metadata/Items/Gems/[^"]+)"\]\s*=\s*\{')
_NAME = re.compile(r'\bname\s*=\s*"([^"]*)"')
_GRANTED_EFFECT_ID = re.compile(r'grantedEffectId\s*=\s*"([^"]+)"')
_ADDITIONAL_EFFECT_ID = re.compile(r'additionalGrantedEffectId\d+\s*=\s*"([^"]+)"')
# `minionSkillTypes`를 잡지 않도록 부정 후방탐색 — PoB는 요구 판정에만 이걸 함께 본다
_SKILL_TYPES = re.compile(r"(?<!minion)\bskillTypes\s*=\s*\{")
_MINION_TYPES = re.compile(r"\bminionSkillTypes\s*=\s*\{")
_REQUIRE_TYPES = re.compile(r"\brequireSkillTypes\s*=\s*\{")
_EXCLUDE_TYPES = re.compile(r"\bexcludeSkillTypes\s*=\s*\{")
_ADD_TYPES = re.compile(r"\baddSkillTypes\s*=\s*\{")
_TYPE_REF = re.compile(r"SkillType\.(\w+)")
_STAT_SETS = re.compile(r"\bstatSets\s*=\s*\{")
_LABEL = re.compile(r'label\s*=\s*"([^"]*)"')
_FLAGS = {
    "ignore_minion_types": re.compile(r"\bignoreMinionTypes\s*=\s*true"),
    "from_item": re.compile(r"\bfromItem\s*=\s*true"),
    "cannot_be_supported": re.compile(r"\bcannotBeSupported\s*=\s*true"),
    "support_gems_only": re.compile(r"\bsupportGemsOnly\s*=\s*true"),
    "support": re.compile(r"\bsupport\s*=\s*true"),
}

# 젬 아닌 스킬의 이름 매칭 허용 파일 — 몬스터(`spectre`)·소환수 자체 스킬(`minion`)은
# 플레이어 레코드와 동명이 있어도 다른 스킬이다
_PLAYER_FILES = ("act_str", "act_dex", "act_int", "sup_str", "sup_dex", "sup_int", "other")


def _fold(name: str) -> str:
    """이름 매칭 키 — 대소문자에 더해 **발음 구별 기호를 뭉갠다**.

    poe2db는 `Mórrigan's Insight`·`Oisín's Oath`처럼 원문 표기를 쓰고 PoB는
    ASCII(`Morrigan's`)다 — casefold만으로는 실존 젬 4건이 고아가 됐다(실측).
    """
    decomposed = unicodedata.normalize("NFKD", name.replace("’", "'"))  # noqa: RUF001
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _match_brace(text: str, start: int) -> int:
    """`text[start]`의 `{`에 대응하는 `}` 인덱스. 문자열·주석 안의 괄호는 세지 않는다."""
    depth, i, n = 0, start, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "-" and text.startswith("--", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _block_types(text: str, pattern: re.Pattern[str], start: int, end: int) -> list[str]:
    found = pattern.search(text, start, end)
    if found is None:
        return []
    close = _match_brace(text, found.end() - 1)
    if close < 0:
        return []
    return [m.group(1) for m in _TYPE_REF.finditer(text, found.end(), close)]


def _stat_set_labels(text: str, start: int, end: int) -> list[str]:
    """`statSets = { {…}, {…} }` 직속 자식마다 `label` (없으면 빈 문자열).

    ⚠ `Data/Gems.lua`의 `additionalStatSet1/2`로 세지 않는다 — exporter 전용이라
    PoB 계산엔 소비처가 없다. 색인의 유효 범위를 정하는 것은 `statSets`다.
    """
    sets = _STAT_SETS.search(text, start, end)
    if sets is None:
        return []
    sets_end = _match_brace(text, sets.end() - 1)
    if sets_end < 0:
        return []
    labels: list[str] = []
    i = sets.end()
    while i < sets_end:
        if text[i] == "{":
            child_end = _match_brace(text, i)
            if child_end < 0:
                break
            found = _LABEL.search(text, i, child_end)
            labels.append(found.group(1) if found else "")
            i = child_end + 1
            continue
        i += 1
    return labels


def parse_skill_effects(src: Path) -> dict[str, dict[str, Any]]:
    """`Data/Skills/*.lua` 전량 → `effect_id` → 담체 판정 재료 dict.

    dict의 필드는 KB `data.pob.effects[]` 항목과 같은 꼴이다(빈 값 생략).
    `_file` 키는 매칭 필터용 내부 정보 — KB에는 쓰지 않는다.
    """
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((src / "Data" / "Skills").glob("*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _SKILL_BLOCK.finditer(text):
            end = _match_brace(text, match.end() - 1)
            if end < 0:
                continue
            head = match.end()
            name = _NAME.search(text, head, end)
            entry: dict[str, Any] = {
                "id": match.group(1),
                "_file": path.stem,
                "_name": name.group(1) if name else match.group(1),
            }
            for key, flag in _FLAGS.items():
                if flag.search(text, head, end):
                    entry[key] = True
            # 집합 의미인 것은 정렬(안정 diff), 식·라벨은 **순서 보존**
            if types := sorted(_block_types(text, _SKILL_TYPES, head, end)):
                entry["types"] = types
            if minion := sorted(_block_types(text, _MINION_TYPES, head, end)):
                entry["minion_types"] = minion
            if require := _block_types(text, _REQUIRE_TYPES, head, end):
                entry["require"] = require
            if exclude := _block_types(text, _EXCLUDE_TYPES, head, end):
                entry["exclude"] = exclude
            if adds := _block_types(text, _ADD_TYPES, head, end):
                entry["adds"] = adds
            if labels := _stat_set_labels(text, head, end):
                entry["stat_sets"] = labels
            out[match.group(1)] = entry
    return out


def parse_gems(src: Path) -> dict[str, dict[str, Any]]:
    """`Data/Gems.lua` → `gem_id` → {name, effects(주 + additional)}.

    ⚠ 메타 젬은 반쪽이 둘이다 — 주 id만 보면 "주문 토템은 보조가 아니다"가 된다.
    """
    text = (src / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    out: dict[str, dict[str, Any]] = {}
    for match in _GEM_BLOCK.finditer(text):
        end = _match_brace(text, match.end() - 1)
        stop = end if end > 0 else len(text)
        name = _NAME.search(text, match.end(), stop)
        ids: list[str] = []
        primary = _GRANTED_EFFECT_ID.search(text, match.end(), stop)
        if primary:
            ids.append(primary.group(1))
        ids.extend(m.group(1) for m in _ADDITIONAL_EFFECT_ID.finditer(text, match.end(), stop))
        if ids:
            out[match.group(1)] = {"name": name.group(1) if name else "", "effects": ids}
    return out


def _strip_internal(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def _pob_block(
    record_type: str,
    name_en: str,
    gems_by_name: dict[str, list[str]],
    gems: dict[str, dict[str, Any]],
    effects: dict[str, dict[str, Any]],
    player_by_name: dict[str, list[str]],
) -> dict[str, Any] | None:
    """레코드 하나의 `data.pob` — 젬 이름 매칭 우선, 다음이 플레이어 스킬 이름."""
    key = _fold(name_en)
    candidates = gems_by_name.get(key, [])
    if len(candidates) > 1:
        # 동명 젬이면 레코드 타입으로 가른다 — Skill 레코드엔 주 효과가 비보조인 젬
        want_support = record_type == "Support"
        typed = [
            g
            for g in candidates
            if effects.get(gems[g]["effects"][0], {}).get("support", False) is want_support
        ]
        candidates = typed or candidates
    if candidates:
        gem_id = candidates[0]
        rows = [_strip_internal(effects[e]) for e in gems[gem_id]["effects"] if e in effects]
        if rows:
            return {"gem_id": gem_id, "effects": rows}
        return None
    rows = [_strip_internal(effects[e]) for e in player_by_name.get(key, [])]
    if rows:
        return {"effects": rows}
    return None


def _with_source(record: dict[str, Any], patch: str) -> dict[str, Any]:
    """`sources[]`에 pob 항목을 붙인다(있으면 갱신 — 재실행 멱등)."""
    entry = {"src": "pob", "ref": _SOURCE_REF, "patch": patch, "pob": POB_COMMIT}
    sources = [
        s
        for s in record.get("sources", [])
        if not (s.get("src") == "pob" and s.get("ref") == _SOURCE_REF)
    ]
    sources.append(entry)
    return {**record, "sources": sources}


def apply_skill_types(
    root: Path | None = None,
    *,
    patch: str = "0.5.4b",
    write: bool = True,
) -> dict[str, Any]:
    """KB Skill·Support 전량에 `data.pob`를 수록하고 커버리지를 리포트로 낸다.

    누락을 조용히 넘기지 않는다 — `kb_unmatched`(KB에 있는데 PoB에서 못 찾음)와
    `pob_only_gems`(PoB 젬인데 KB 레코드 없음)는 **파서 갭이거나 수록 갭**이다.
    후자의 수록 여부 판정은 게임 지식이므로 사용자 몫이다(KI-7).
    """
    src = pob_src_dir(root)
    effects = parse_skill_effects(src)
    gems = parse_gems(src)

    gems_by_name: dict[str, list[str]] = {}
    for gem_id, gem in gems.items():
        if gem["name"]:
            gems_by_name.setdefault(_fold(gem["name"]), []).append(gem_id)
    player_by_name: dict[str, list[str]] = {}
    for eid, entry in effects.items():
        if entry["_file"] in _PLAYER_FILES and entry["_name"]:
            player_by_name.setdefault(_fold(entry["_name"]), []).append(eid)

    store = store_load(root)
    matched_gem = matched_skill = 0
    kb_unmatched: list[str] = []
    updated: dict[str, dict[str, Any]] = {}  # id → 갱신된 raw 레코드
    used_gem_names: set[str] = set()

    for record in store.records.values():
        if record.type not in ("Skill", "Support"):
            continue
        name_en = str(record.raw.get("name", {}).get("en", ""))
        block = _pob_block(record.type, name_en, gems_by_name, gems, effects, player_by_name)
        if block is None:
            kb_unmatched.append(record.id)
            continue
        if "gem_id" in block:
            matched_gem += 1
            used_gem_names.add(_fold(name_en))
        else:
            matched_skill += 1
        raw = copy.deepcopy(record.raw)
        raw.setdefault("data", {})["pob"] = block
        updated[record.id] = _with_source(raw, patch)

    if write and updated:
        by_path: dict[Path, list[str]] = {}
        for rid in updated:
            by_path.setdefault(store.records[rid].path, []).append(rid)
        for path, ids in sorted(by_path.items()):
            if path.suffix == ".ndjson":
                # 샤드는 전량 다시 쓴다 — 순서는 기존 파일 순서를 보존해 diff를 좁힌다
                rows = [updated.get(r.id, r.raw) for r in store.records.values() if r.path == path]
                write_shard(path, rows, root=root, validate=False)
            else:
                write_record(path, updated[ids[0]], root=root, validate=False)
        store_load(root)  # 안전장치: 전체 재검증 (파일별 재검증 비용 회피)

    pob_only = sorted(
        gem["name"] for gem in gems.values() if _fold(gem["name"]) not in used_gem_names
    )
    multi_mode = sum(1 for e in effects.values() if len(e.get("stat_sets", [])) > 1)
    gated = sum(1 for e in effects.values() if e.get("require") or e.get("exclude"))
    report = {
        "kb_gem_records": matched_gem + matched_skill + len(kb_unmatched),
        "matched_via_gem": matched_gem,
        "matched_via_skill_name": matched_skill,
        "kb_unmatched": sorted(kb_unmatched),
        "pob_only_gems": pob_only,
        "pob_effects_total": len(effects),
        "pob_effects_multi_mode": multi_mode,
        "pob_effects_gated": gated,
        "note": (
            "kb_unmatched=KB에 있는데 PoB에서 못 찾은 것(표기 차이 의심), "
            "pob_only_gems=PoB 젬인데 KB 레코드가 없는 것 — 수록 여부는 게임 지식"
            " 판정이라 사용자 몫이다(KI-7)"
        ),
    }
    return report
