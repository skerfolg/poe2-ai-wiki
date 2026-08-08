"""상태이상·축적(buildup) 계열 전량 수록 — 백로그 B-9.

빌드 테스트 리포트(2026-08-04): 세션이 "출혈은 물리 피해에서만 스케일한다"를
**PoB 소스를 직접 읽어서** 얻었다. KB에 상태이상이 한 건도 없었기 때문이다 —
`Mechanic` 5건에 출혈·점화·감전 어느 것도 없었고, 패시브·모드에 "출혈 확률"은
있어도 **출혈이 무엇이고 무엇으로 스케일하는가**는 어디에도 없었다.

이건 KD-5가 말하는 "공개 데이터인데 수집이 안 된 것"이라 인사이트로 우회하면
안 된다. 그리고 **출혈 한 건만 넣는 것도 안 된다** — 그게 KD-5가 지적한 건 바이 건
실패다. PoB `Modules/Data.lua`에 계열 전체가 테이블로 있으므로 전량을 수집한다:

  data.ailmentTypeList            6종 (Bleed·Poison·Ignite·Chill·Freeze·Shock)
  data.defaultAilmentDamageTypes  ScalesFrom(스케일 근원)·DamageType(피해 속성)
  data.buildupTypes               4종 축적 (Electrocute·Freeze·HeavyStun·Pin)
  Data/Misc.lua gameConstants     기본 지속시간·배율·임계 상수

`ScalesFrom`이 핵심이다. "출혈은 Physical만"·"중독은 Physical+Chaos"·"점화는 Fire만"이
설계에서 곧바로 갈리는 판단이고, 이걸 모르면 원소 피해 증가로 출혈이 오를 것이라
착각한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir
from pok.kb.ingest.merge import POB_COMMIT
from pok.kb.pob_pin import pob_src_dir
from pok.kb.store import write_record

# name.ko — 인게임 한글 표기 (효과 문구 한글이 없는 영역이라 이름만이라도 붙인다)
_KO = {
    "Bleed": "출혈",
    "Poison": "중독",
    "Ignite": "점화",
    "Chill": "냉기",
    "Freeze": "빙결",
    "Shock": "감전",
    "Electrocute": "전기 충격",
    "HeavyStun": "강한 기절",
    "Pin": "고정",
}

_LIST_ITEM = re.compile(r'"([^"]+)"')
_CONST = re.compile(r'\["(\w+)"\]\s*=\s*([\d.]+)')
# ["Bleed"] = { ["ScalesFrom"] = { ["Physical"] = true, }, ["DamageType"] = "Physical", }
_ENTRY = re.compile(r'\["(\w+)"\]\s*=\s*\{')
_SCALES = re.compile(r'\["ScalesFrom"\]\s*=\s*\{(.*?)\}', re.S)
_DMG_TYPE = re.compile(r'\["DamageType"\]\s*=\s*"(\w+)"')


# `<Ailment>CanStack` 플래그를 **세우는** 출처를 찾는다. `ConfigOptions.lua`의
# `ifFlag` 조건은 "이미 세워졌을 때 보여줄지"라 세우는 게 아니다 — 그걸 세는 것으로
# 오해하면 "출혈도 중첩된다"는 반대 결론이 나온다(실측 2026-08-05).
_CAN_STACK_SETTER = r'(?:flag\("|name="){name}CanStack'
_STACK_SCAN_SUFFIXES = (".lua", ".txt")


def can_stack_sources(src: Path, name: str) -> list[str]:
    """이 상태이상의 중첩을 여는 모드가 PoB에 있는가 — 없으면 **중첩 불가**다.

    `CalcOffence.lua:5065`가 `maxStacks = 1`에서 시작하고 이 플래그가 있어야 늘린다.
    실측 0.5.4b: 중독 8·감전 3·점화 2·냉기 2회, **출혈과 빙결은 0회**.

    빌드 세션이 "출혈을 거는 스킬 6개"를 보고 "그래서 딜이 크다"고 결론냈는데,
    중첩이 안 되므로 그 6개는 **가동률·커버리지 장치**이지 곱셈이 아니다.
    """
    pattern = re.compile(_CAN_STACK_SETTER.format(name=re.escape(name)))
    out: list[str] = []
    for path in sorted(src.rglob("*")):
        if path.suffix not in _STACK_SCAN_SUFFIXES or "ConfigOptions" in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.search(text):
            out.append(str(path.relative_to(src)))
    return out


def pob_src(root: Path | None = None) -> Path:
    return pob_src_dir(root)


def _balanced(text: str, open_at: int) -> str:
    """`{` 위치에서 짝이 맞는 `}`까지. **정규식으로 자르면 중첩에서 어긋난다** —
    실측: non-greedy 매칭이 `nonDamagingAilment`를 삼켜 `Cold`·`Lightning` 같은
    ScalesFrom 키가 상태이상으로 잡혔다."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : i]
    raise ValueError("괄호가 닫히지 않았다")


def _table(text: str, name: str) -> str:
    """`data.<이름> = { … }` 블록 본문 (없으면 빈 문자열)."""
    marker = re.search(rf"data\.{re.escape(name)}\s*=\s*\{{", text)
    return _balanced(text, marker.end() - 1) if marker else ""


def _entries(body: str) -> dict[str, str]:
    """블록 본문 → 최상위 `["이름"] = { … }` 항목 (중첩은 건너뛴다)."""
    out: dict[str, str] = {}
    pos = 0
    while (match := _ENTRY.search(body, pos)) is not None:
        inner = _balanced(body, match.end() - 1)
        out[match.group(1)] = inner
        pos = match.end() + len(inner) + 1
    return out


def _constants(misc_text: str) -> dict[str, float]:
    """Misc.lua의 `gameConstants` 수치 상수 전량."""
    out: dict[str, float] = {}
    for key, value in _CONST.findall(misc_text):
        num = float(value)
        out[key] = int(num) if num.is_integer() else num
    return out


def _scales_from(body: str) -> list[str]:
    match = _SCALES.search(body)
    return _LIST_ITEM.findall(match.group(1)) if match else []


def parse_ailments(src: Path) -> dict[str, dict[str, Any]]:
    """PoB 소스 → 상태이상/축적 이름별 데이터. 파일 접근만 하고 판단하지 않는다."""
    data_text = (src / "Modules" / "Data.lua").read_text(encoding="utf-8", errors="replace")
    misc_text = (src / "Data" / "Misc.lua").read_text(encoding="utf-8", errors="replace")
    consts = _constants(misc_text)

    def listed(name: str) -> list[str]:
        return _LIST_ITEM.findall(_table(data_text, name))

    ailments = listed("ailmentTypeList")
    elemental = set(listed("elementalAilmentTypeList"))
    non_damaging = set(listed("nonDamagingAilmentTypeList"))
    buildups = _entries(_table(data_text, "buildupTypes"))

    out: dict[str, dict[str, Any]] = {}
    for name in ailments:
        out[name] = {
            "kind": "ailment",
            "elemental": name in elemental,
            "damaging": name not in non_damaging,
        }
    for name in buildups:
        out.setdefault(name, {"kind": "buildup"})

    # ScalesFrom·DamageType — 설계 판단이 여기서 갈린다.
    # **계열 목록에 있는 이름만** 받는다 — 목록 밖 이름이 나오면 파싱이 어긋난 것이다.
    for name, body in _entries(_table(data_text, "defaultAilmentDamageTypes")).items():
        if name not in out:
            continue
        out[name]["scales_from"] = _scales_from(body)
        dmg = _DMG_TYPE.search(body)
        if dmg:
            out[name]["damage_type"] = dmg.group(1)
    for name, body in buildups.items():
        out[name]["scales_from"] = _scales_from(body)

    # 중첩 가능성 — "여러 번 걸면 곱해지는가"는 설계 판단을 크게 가른다
    for name, entry in out.items():
        if entry["kind"] != "ailment":
            continue
        sources = can_stack_sources(src, name)
        entry["can_stack"] = bool(sources)
        entry["max_stacks_default"] = 1
        if sources:
            entry["can_stack_sources"] = sources

    # 상수: 이름 앞머리가 상태이상 이름과 맞는 것만 붙인다 (Base*/*Duration/*Scale 등)
    for name, entry in out.items():
        picked = {
            key: value
            for key, value in consts.items()
            if name.lower() in key.lower() or (name == "Bleed" and "Bleeding" in key)
        }
        if picked:
            entry["constants"] = dict(sorted(picked.items()))
    return out


def _topic(word: str) -> str:
    """받침에 맞는 주격 조사 — `출혈은(는)` 같은 표기는 읽는 쪽이 사람이라 거슬린다."""
    last = word[-1]
    if not ("\uac00" <= last <= "\ud7a3"):
        return f"{word}는"
    return f"{word}은" if (ord(last) - 0xAC00) % 28 else f"{word}는"


def _record(name: str, entry: dict[str, Any], patch: str) -> dict[str, Any]:
    slug = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    data: dict[str, Any] = {k: v for k, v in entry.items() if k != "kind"}
    data["kind"] = entry["kind"]
    if entry.get("kind") == "ailment" and entry.get("can_stack") is False:
        data["stacking_note"] = (
            f"**{_topic(_KO.get(name, name))} 중첩되지 않는다**(0.5.4b) — 최대 1중첩이고 "
            f"`{name}CanStack`을 여는 모드가 PoB 어디에도 없다. 여러 스킬로 걸어도 "
            f"딜이 곱해지지 않는다 — 그것들은 가동률·커버리지 장치다."
        )
    if scales := entry.get("scales_from"):
        data["note"] = (
            f"{_topic(_KO.get(name, name))} **{'·'.join(scales)} 피해에서만 스케일한다** — "
            f"다른 속성의 피해 증가는 반영되지 않는다"
        )
    elif entry.get("kind") == "buildup":
        data["note"] = (
            f"{_topic(_KO.get(name, name))} PoB `buildupTypes`에 스케일 근원이 "
            f"비어 있다 — 피해량으로 축적되지 않는 축이다"
        )
    return {
        "id": f"mechanic.{slug}",
        "type": "Mechanic",
        "name": {"ko": _KO.get(name, name), "en": name},
        "tags": ["mechanic", "ailment" if entry["kind"] == "ailment" else "buildup"],
        "data": data,
        "verification": "POB_CODE",
        "sources": [
            {
                "src": "pob",
                "ref": "Modules/Data.lua (ailmentTypeList·defaultAilmentDamageTypes·"
                "buildupTypes) · Data/Misc.lua (gameConstants)",
                "patch": patch,
                "pob": POB_COMMIT,
            }
        ],
    }


def ingest_ailments(
    patch: str = "0.5.4b",
    root: Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """상태이상·축적 전량을 `mechanics/`에 개별 JSON으로 쓴다 (KD-1 소량은 JSON)."""
    from pok.kb.store import load as store_load

    parsed = parse_ailments(pob_src(root))
    out_dir = knowledge_dir(root) / "game-data" / "mechanics"
    existing = store_load(root).records
    written: list[str] = []
    preserved: list[str] = []
    for name, entry in sorted(parsed.items()):
        rec = _record(name, entry, patch)
        written.append(rec["id"])
        prev = existing.get(rec["id"])
        if prev is not None:
            # **다른 경로가 붙인 필드를 지우지 않는다.** `write_record`는 전체 교체라
            # 그대로 쓰면 poe2db 키워드 정의(`keyword_stats`)가 날아간다 — 실측
            # 2026-08-05에 실제로 날렸다. B-7(부분 갱신이 값을 잃는 결함)이 다른
            # 경로에서 재발한 것이라, 여기서도 같은 계약을 지킨다.
            prev_data = prev.raw.get("data") or {}
            foreign = {k: v for k, v in prev_data.items() if k not in rec["data"]}
            if foreign:
                rec["data"] = {**foreign, **rec["data"]}
                preserved.append(rec["id"])
        if write:
            # 정본 쓰기는 store API로만 — 직접 write_text 금지(B-6, kb/AGENTS.md)
            write_record(out_dir / f"{rec['id'].split('.', 1)[1]}.json", rec, root=root)
    return {"written": written, "count": len(written), "preserved_foreign": sorted(preserved)}
