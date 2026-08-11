"""PoB가 **읽지 못하는 아이템·룬 문구**를 찾아 KB에 표시한다 (제안 D 아이템 편).

트리 편(`pob.parse_gaps`)과 같은 결함, 다른 경로다. `Classes/Item.lua:2138`의
`if not modLine.extra`가 잔여 있는 줄을 아이템 모드 목록에서 빼므로, 그 접사는
**경고 없이 계산에 0으로 기여**한다. 세션은 그 델타를 "값어치 없음"으로 오독한다.

## 왜 문구만 떼어 `parseMod`에 넣으면 안 되나

KB 원문에는 `(35-42)%` 같은 값 범위가 있고 그 해석은 `Item.lua:947`의 `applyRange`가
한다. 문구만 파서에 직접 먹이면 **멀쩡한 모드가 파싱 실패로 잡힌다.** 그래서 레코드마다
**진짜 아이템을 세워** PoB에게 묻는다(`scripts/pob_item_parse_gaps.lua`).
레코드 단위로 나누는 이유는 줄 합치기 재시도가 **레코드 안에서만** 일어나야 하기
때문이다 — 한 아이템에 몰아넣으면 남의 줄과 합쳐져 없는 성공이 생긴다.

## 베이스를 여럿 시도하는 이유 — 오탐의 정체

접사는 아무 아이템에나 붙지 않는다. 「Recover (8-12) Life when Used」는 **차멤 접사**라
목걸이에 얹으면 파싱되지 않는데, 그건 PoB의 갭이 아니라 **우리가 자리를 잘못 준 것**이다.
실측 2026-08-08: 목걸이 한 종으로만 재면 차멤·플라스크 접사가 전부 갭으로 잡혔다.

그래서 **한 베이스라도 읽어 내면 갭이 아니다**로 판정한다. 주장은 이렇게 좁아진다 —
"PoB는 **어떤 아이템에 얹어도** 이 문구를 못 읽는다". 비용은 2단계로 줄인다:
① 대표 베이스 하나로 전량 → ② 거기서 실패한 것만 나머지 베이스 전부.

## 남는 한계 (주장하지 않는 것)

- 클래스 요구가 붙은 접사(`Requires Class …`)나 특정 베이스에만 붙는 특수 문구는
  베이스 목록 밖일 수 있다 — 그런 건 **갭으로 잡히되 실제로는 자리 문제**일 수 있다.
  그래서 표기에 "시도한 베이스"를 함께 남긴다
- 룬은 별개 결함이 하나 더 있다(슬롯 키 미매칭 — `kb.pob_gaps.scan_rune_slot_gaps`).
  여기서 보는 것은 **문구 파싱**이지 슬롯 매칭이 아니다
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.common.paths import project_root, var_dir
from pok.pob.runner import _LUA_PATH
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_SCRIPT = "scripts/pob_item_parse_gaps.lua"
_KIND = "item-line-unparsed"

# 1단계 대표 베이스 — 접사 대부분이 붙는 범용 자리.
_PRIMARY_BASE = "Amber Amulet"
# 2단계 — 1단계에서 실패한 것만 여기 전부에 얹어 본다. 클래스별 최저 레벨 베이스라
# 요구치 때문에 걸리지 않는다. 하나라도 읽으면 갭이 아니다.
_FALLBACK_BASES = (
    "Abyssal Signet",  # Ring
    "Double Belt",  # Belt
    "Abyssal Cuirass",  # Body Armour
    "Ancestral Tiara",  # Helmet
    "Adherent Cuffs",  # Gloves
    "Adherent Leggings",  # Boots
    "Akoyan Club",  # One Hand Mace
    "Aberrant Sledge",  # Two Hand Mace
    "Adherent Bow",  # Bow
    "Acrid Wand",  # Wand
    "Aromatic Sceptre",  # Sceptre
    "Aegis Quarterstaff",  # Quarterstaff
    "Aegis Buckler",  # Shield
    "Antler Focus",  # Focus
    "Blunt Quiver",  # Quiver
    "Amethyst Charm",  # Charm
    "Colossal Life Flask",  # Flask
    "Diamond",  # Jewel
    "Alpha Talisman",  # Talisman
)


@dataclass(frozen=True)
class UnparsedItemLine:
    """PoB가 아이템 모드 목록에 넣지 못한 문구 한 줄."""

    text: str
    kind: str  # "extra"(부분 파싱 후 잔여) | "unknown"(패턴 없음)
    remainder: str

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"text": self.text, "kind": self.kind}
        if self.kind == "extra" and self.remainder:
            out["remainder"] = self.remainder
        return out


class ItemParseGapError(RuntimeError):
    """덤프 스크립트가 POK_OK 없이 끝났다."""


def scannable_lines(data: dict[str, Any], name: str = "") -> list[str]:
    """판정 근거로 삼는 **영문** 줄 (`kb.pob_gaps.scannable_lines`와 같은 원칙).

    한글(`texts_ko`)은 PoB가 파싱하는 대상이 아니라 애초에 판정 축이 될 수 없다.

    ## ⚠ 유니크는 **PoB 원문**으로 시험한다 (백로그 #38)

    KB의 유니크 `explicits`에는 변형이 **플레이스홀더 한 줄**로 뭉쳐 있다:

        Can Allocate Passive Skills from the (Mercenary/Ranger/…)'s starting point

    PoB 패턴은 `"…from the (%a+)'s starting point"`(한 단어)라 슬래시가 든 이 줄은
    **안 맞는다.** 그래서 `item.split-personality`가 "PoB 미지원"으로 기록됐는데,
    변형을 확정한 줄(`…from the Warrior's…`)은 **정상 파싱된다.** 실측 2026-08-10:

        플레이스홀더    → unknown (갭으로 잡힘)
        변형-Warrior   → 정상 파싱

    즉 그건 PoB의 한계가 아니라 **우리 시험 문구 선택의 문제**였다. 다변형 유니크
    234건 중 98건이 `pob_gap` 표시를 달고 있어 같은 오판이 번져 있을 수 있다.
    PoB 원문(`Data/Uniques/*.lua`)에는 `{variant:N}`으로 변형별 줄이 있으므로
    **그걸 쓴다** — 정본은 PoB 소스다(AD-1).
    """
    lines: list[str] = []
    if name:
        from_source = _unique_source_lines(name)
        if from_source:
            return from_source
    for key in ("texts", "explicits", "implicits"):
        value = data.get(key)
        if isinstance(value, list):
            lines += [str(x) for x in value]
    per_slot = data.get("per_slot")
    if isinstance(per_slot, dict):
        for slot_lines in per_slot.values():
            if isinstance(slot_lines, list):
                lines += [str(x) for x in slot_lines]
    # 줄바꿈·탭은 프로토콜 구분자라 못 넘긴다. 빈 줄은 PoB가 아이템 구획으로 읽는다.
    return [" ".join(x.split()) for x in lines if x and x.strip()]


# PoB 원문의 **스펙 줄**(모드가 아니다). `Item.lua::ParseRaw`가 specName으로 읽는다 —
# `<이름>: <값>` 꼴이라 첫 콜론 앞이 한두 낱말이면 스펙 줄이다.
_UNIQUE_SPEC_LINE = re.compile(r"^[A-Z][A-Za-z ]{0,24}:", re.M)


def _unique_source_lines(name: str) -> list[str]:
    """PoB 원문의 **모드 줄만** — 스펙 줄(`Variant:`·`Selected …`)은 모드가 아니다.

    `{variant:N}`·`{range:R}` 같은 장식 접두는 그대로 둔다. PoB가 읽는 형태 그대로
    넘겨야 판정이 실물과 같아진다.
    """
    from pok.pob.uniques import unique_raw

    raw = unique_raw(name)
    if raw is None:
        return []
    out: list[str] = []
    for index, line in enumerate(raw.splitlines()):
        stripped = line.strip()
        if not stripped or index < 2:  # 첫 두 줄은 이름·베이스
            continue
        if not stripped.startswith("{") and _UNIQUE_SPEC_LINE.match(stripped):
            continue  # `Variant:`·`Limited to:`·`Source:`·`LevelReq:` … 스펙 줄
        out.append(" ".join(stripped.split()))
    return out


def _probe(
    batch: dict[str, list[str]], base: str, snap: PobSnapshot, timeout: float
) -> dict[str, list[UnparsedItemLine]]:
    """레코드 묶음을 한 베이스에 얹어 PoB 1회 부팅으로 판정."""
    if not batch:
        return {}
    payload = var_dir() / "pob-cache" / f"_item-gaps-{abs(hash(base)) % 10**8}.txt"
    payload.parent.mkdir(parents=True, exist_ok=True)
    with payload.open("w", encoding="utf-8") as fh:
        for rid, lines in batch.items():
            fh.write(f"#REC\t{rid}\t{base}\n")
            fh.writelines(f"{line}\n" for line in lines)
            fh.write("#END\n")
    try:
        proc = subprocess.run(
            [find_luajit(), str(project_root() / _SCRIPT), str(payload)],
            cwd=snap.src_dir,
            env={**os.environ, "LUA_PATH": _LUA_PATH},
            input="",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        payload.unlink(missing_ok=True)
    out = proc.stdout.splitlines()
    if "POK_OK" not in out:
        raise ItemParseGapError(
            f"베이스 {base!r} 판정이 POK_OK 없이 종료:\n"
            + "\n".join(out[-8:])
            + f"\n{proc.stderr[-800:]}"
        )
    found: dict[str, list[UnparsedItemLine]] = {}
    for line in out:
        if not line.startswith("POK_GAP:"):
            continue
        parts = line[len("POK_GAP:") :].split("\t")
        if len(parts) < 5:
            continue
        rid, _idx, kind, text, remainder = parts[0], parts[1], parts[2], parts[3], parts[4]
        found.setdefault(rid, []).append(
            UnparsedItemLine(text=text.strip(), kind=kind, remainder=remainder.strip())
        )
    return found


def dump_item_parse_gaps(
    root: Path | None = None,
    *,
    snapshot: PobSnapshot | None = None,
    timeout: float = 1800.0,
) -> tuple[dict[str, list[UnparsedItemLine]], dict[str, Any]]:
    """2단계 판정 — 어느 베이스에서도 안 읽힌 줄만 갭으로 남긴다."""
    from pok.kb.store import load as store_load

    snap = snapshot or resolve_snapshot(root)
    batch: dict[str, list[str]] = {}
    for record in store_load(root).records.values():
        if record.type not in ("Modifier", "Item"):
            continue
        name = str((record.raw.get("name") or {}).get("en") or "")
        is_unique = (record.raw.get("data") or {}).get("rarity") == "unique"
        lines = scannable_lines(record.raw.get("data") or {}, name if is_unique else "")
        if lines:
            batch[record.id] = lines

    first = _probe(batch, _PRIMARY_BASE, snap, timeout)
    # 1단계 실패분만 다른 자리에 얹어 본다 — 읽히면 갭이 아니라 **자리 문제**였다.
    survivors = {rid: batch[rid] for rid in first}
    rescued: dict[str, str] = {}
    for base in _FALLBACK_BASES:
        if not survivors:
            break
        still = _probe(survivors, base, snap, timeout)
        for rid in list(survivors):
            if rid not in still:
                rescued[rid] = base
                del survivors[rid]
        survivors = {rid: batch[rid] for rid in survivors}

    # PoB가 예외를 던진 레코드는 "조용한 0"이 아니라 **다른 결함**이다 — 섞지 않는다.
    errored = {rid for rid, ls in first.items() if any(x.kind == "error" for x in ls)}
    gaps = {rid: first[rid] for rid in survivors if rid not in errored}
    summary = {
        "snapshot": snap.short,
        "scanned_records": len(batch),
        "scanned_lines": sum(len(v) for v in batch.values()),
        "failed_on_primary": len(first),
        "rescued_by_other_base": len(rescued),
        "gap_records": len(gaps),
        # 파싱 중 예외 — 별개 결함이라 표기 대상에서 뺀다(백로그로)
        "parse_errors": sorted(errored),
        "bases_tried": [_PRIMARY_BASE, *_FALLBACK_BASES],
    }
    return gaps, summary


def apply_item_parse_flags(root: Path | None = None, *, write: bool = True) -> dict[str, Any]:
    """검출된 갭을 `pob_modeling`으로 표시하고, 이제 읽히는 것은 지운다."""
    from pok.kb.store import load as store_load
    from pok.kb.store import patch_records

    gaps, summary = dump_item_parse_gaps(root)
    snapshot = str(summary["snapshot"])
    store = store_load(root)
    # 이미 **다른 결함**으로 표시된 레코드는 덮지 않는다. 룬 슬롯 미매칭(3건)은 문구가
    # 아니라 슬롯 키가 원인이라 대체 조립 방법도 다르다 — 덮으면 그 안내가 사라진다.
    # 어느 쪽이든 소비자에게 가는 신호(`pob_gap`)는 같으므로 손실은 없고, 겹친 사실은
    # 요약에 남긴다.
    conflicts = sorted(
        rid
        for rid in gaps
        if ((store.records[rid].raw.get("data") or {}).get("pob_modeling") or {}).get("kind")
        not in (None, _KIND)
    )
    updates: dict[str, dict[str, Any]] = {}
    for record_id, lines in gaps.items():
        if record_id in conflicts:
            continue
        kinds = "·".join(sorted({line.kind for line in lines}))
        updates[record_id] = {
            "pob_modeling": {
                "supported": False,
                "kind": _KIND,
                "detail": (
                    f"PoB가 이 레코드 문구 {len(lines)}줄을 아이템 모드로 읽지 못한다({kinds}) "
                    f"— 베이스 {len(summary['bases_tried'])}종 전부에서 실패. "
                    "델타 0은 '값어치 없음'이 아니라 **'측정 안 됨'**이다."
                ),
                "workaround": (
                    "등가 문구로 바꿔 `ItemSpec.substitutes`에 넣어 **추산**으로 잰다"
                    "(원문 그대로는 또 떨어진다). 배경: `pok.pob.item_parse_gaps`"
                ),
                "snapshot": snapshot,
                "unparsed": [line.as_dict() for line in lines],
            }
        }
    flagged = set(updates)

    stale = sorted(
        record.id
        for record in store.records.values()
        if record.id not in flagged
        and ((record.raw.get("data") or {}).get("pob_modeling") or {}).get("kind") == _KIND
    )
    updates.update({record_id: {"pob_modeling": None} for record_id in stale})

    if write and updates:
        patch_records(updates, root=root)
    return {
        **summary,
        "flagged": sorted(flagged),
        "cleared": stale,
        "kept_other_kind": conflicts,
        "wrote": bool(write),
    }


if __name__ == "__main__":  # python -m pok.pob.item_parse_gaps [--dry-run]
    import sys

    dry = "--dry-run" in sys.argv
    report = apply_item_parse_flags(write=not dry)
    print(
        f"PoB {report['snapshot']} · 레코드 {report['scanned_records']}개"
        f"({report['scanned_lines']}줄) 검사 → 1차 실패 {report['failed_on_primary']} · "
        f"다른 베이스에서 해소 {report['rescued_by_other_base']} → "
        f"표기 {len(report['flagged'])}건 · 해제 {len(report['cleared'])}건 · "
        f"파싱 예외 {len(report['parse_errors'])}건 · "
        f"다른 kind 유지 {len(report['kept_other_kind'])}건"
        + (" (dry-run — 쓰지 않음)" if dry else "")
    )
