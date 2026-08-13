"""PoB가 **읽지 못하는 트리 문구**를 찾아 KB에 표시한다 (백로그 제안 D).

## 무엇을 막는가 — 조용한 0

PoB는 노드 문구를 줄 단위로 파싱하고, 잔여 텍스트가 남은 줄은 `node.extra`를 세운 뒤
`PassiveTree.lua:487`의 `if mod.list and not mod.extra`에서 **modList 편입을 건너뛴다.**
경고는 없다. 그래서 그 줄은 계산에 **0으로 기여**하고, 세션은 델타 0을 보고
"값어치 없는 노드"라는 **실측으로 오독한다**.

실제로 그렇게 됐다(백로그 #3): 원소 집정관 계열이 통째로 0으로 측정돼
`optimize_tree`가 한 노드도 뽑지 않았고, 빌드 세션은 "후보 반경 밖이라 못 봤다"로
오진했다. 반경이 아니라 **효과가 0으로 계산된 것**이었다.

## 왜 grep이 아니라 PoB에게 묻나

「10% increased Archon Buff duration」은 파서에 패턴이 **있다** — `Duration` INC를 잡고
대상 한정어 `Archon Buff`만 잔여로 남긴다(`Data/ModCache.lua`). 즉 키워드 유무로는
판정할 수 없고, `parseMod`의 **두 번째 반환값**을 봐야 한다.

그렇다고 그 절차를 밖에서 재현하면 안 된다. `PassiveTree.lua:436-486`은 줄바꿈 분해 →
실패 시 뒤 줄과 합쳐 재시도 → 플래그 확정의 3단이고, 이걸 우리가 다시 짜면 그게 곧
**계산 로직 재구현**이다(AD-1 금지). 스냅샷이 바뀌면 조용히 어긋난다.
그래서 `scripts/pob_parse_gaps.lua`는 **PoB가 로드하면서 이미 매겨 둔 플래그를 읽기만**
한다 — 재현도 drift도 없다.

## 왜 `pob_computable`이 아닌가

제안 D 원안은 `pob_computable: false` 백필이었다. **쓸 수 없다** — Passive에서 그 필드는
이미 다른 뜻이다: `tree_merge.py:88`이 **PoB 트리 데이터에 노드 자체가 없을 때** 세운다
(할당 자체가 불가). 여기서 다루는 건 "노드는 있고 할당도 되는데 일부 줄만 안 세는" 것이라
성격이 반대다. 두 가지를 한 불리언에 겹치면 소비자가 구분할 수 없고, `items.py:284`처럼
`pob_computable is False`를 후보 배제에 쓰는 경로가 있어 **과잉 배제**(#13의 재발)까지
낳는다. 그래서 기존 `pob_modeling` 계약(`pob_gaps.py`)에 `kind`를 하나 더 붙였다.

## 재적용 멱등

스냅샷이 바뀌면 판정도 바뀐다. 그래서 매번 **전량 재계산**하고, 이제 파싱되는 노드의
낡은 플래그는 `None` 패치로 지운다(`store.patch_records` 계약). 다른 `kind`의
`pob_modeling`(룬 슬롯 등)은 건드리지 않는다.

⚠ **패치 재수집·PoB 스냅샷 교체 뒤에는 다시 돌린다** (`--dry-run`이면 쓰지 않고 세기만):

    PYTHONPATH=src .venv/bin/python -m pok.pob.parse_gaps

`PYTHONPATH=src`는 이 저장소의 관례다 — editable 설치의 `.pth`가 무시되는 환경이 있다
(pyproject `[tool.pytest] pythonpath`가 같은 이유로 있다). 실측 2026-08-08(macOS):
`.pth`에 `com.apple.provenance` xattr가 붙어 `import pok`이 실패했다.

안 돌리면 낡은 판정이 남는다 — 그건 문서 규율이라 안 지켜질 수 있으므로
`tests/integration/test_pob_parse_gaps.py`가 정본 표기와 현재 PoB 판정을 대조해
**어긋나면 실패**한다(철칙 5).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.common.paths import project_root, var_dir
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_SCRIPT = "scripts/pob_parse_gaps.lua"
_KIND = "tree-line-unparsed"

# `extra`  = 부분 파싱 후 잔여 텍스트 — 패턴은 걸렸는데 대상 한정어를 못 읽었다
# `unknown`= 패턴 자체가 없다
# 둘 다 결과는 같다(계산에서 탈락). 구분해 두는 이유는 대체 조립 난이도가 달라서다:
# extra는 한정어를 뺀 등가 문구로 근사할 여지가 있고, unknown은 효과를 통째로 옮겨야 한다.
_KINDS = frozenset({"extra", "unknown"})


@dataclass(frozen=True)
class UnparsedLine:
    """PoB가 계산에 넣지 못한 문구 한 줄."""

    index: int  # PoB `node.sd` 안의 1-based 줄 번호
    text: str
    kind: str  # "extra" | "unknown"
    remainder: str  # 파서가 읽다 남긴 꼬리 — **extra일 때만** 의미가 있다

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"line": self.index, "text": self.text, "kind": self.kind}
        # unknown일 때 PoB가 들고 있는 `extra`는 **줄 합치기 재시도의 마지막 잔재**라
        # 뒤 줄들이 통째로 붙어 있다. 정보가 아니라 잡음이므로 싣지 않는다.
        if self.kind == "extra" and self.remainder:
            out["remainder"] = self.remainder
        return out


@dataclass(frozen=True)
class NodeParseGap:
    """노드 하나의 파싱 갭 — PoB 판정 그대로."""

    node_id: int
    name: str
    lines: tuple[UnparsedLine, ...]
    # 주얼 소켓 노드. 「Sinister Jewel Socket」류는 효과가 아니라 **구조 선언**이라
    # PoB가 문구로 안 읽는 게 정상이다(node.type == "Socket"으로 다룬다). 표기 대상이
    # 아니지만 **버렸다는 사실은 요약에 남긴다** — 조용한 절단이 곧 거짓 분모다.
    socket: bool = False


@dataclass(frozen=True)
class ParseGapDump:
    """PoB 1회 부팅 산출물. `scanned`는 분모 — 비율을 근거로 말할 수 있게 함께 낸다."""

    tree_version: str
    scanned: int
    snapshot: str
    gaps: dict[int, NodeParseGap]


class ParseGapError(RuntimeError):
    """덤프 스크립트가 POK_OK 없이 끝났다."""


def dump_tree_parse_gaps(
    *,
    snapshot: PobSnapshot | None = None,
    root: Path | None = None,
    timeout: float = 300.0,
) -> ParseGapDump:
    """PoB를 1회 부팅해 트리 전체의 줄 단위 파싱 갭을 받는다 (~수십 초)."""
    from pok.pob.buildxml import BuildSpec, to_xml
    from pok.pob.runner import _LUA_PATH

    base = root or project_root()
    snap = snapshot or resolve_snapshot(base)
    xml_file = var_dir(base) / "pob-cache" / "_parse-gaps-input.xml"
    xml_file.parent.mkdir(parents=True, exist_ok=True)
    # 트리만 있으면 되므로 최소 스펙 — 어느 클래스로 열어도 tree.nodes는 같다.
    xml_file.write_text(
        to_xml(BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", level=1)),
        encoding="utf-8",
        newline="\n",
    )
    try:
        proc = subprocess.run(
            [find_luajit(), str(base / _SCRIPT), str(xml_file)],
            cwd=snap.src_dir,
            env={**os.environ, "LUA_PATH": _LUA_PATH},
            input="",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        xml_file.unlink(missing_ok=True)
    return parse_dump_lines(proc.stdout.splitlines(), snapshot=snap.short, stderr=proc.stderr)


def parse_dump_lines(lines: list[str], *, snapshot: str = "", stderr: str = "") -> ParseGapDump:
    """POK_* 프로토콜 파서 — PoB 없이도 테스트할 수 있게 분리한다."""
    if "POK_OK" not in lines:
        tail = "\n".join(lines[-8:])
        raise ParseGapError(f"덤프가 POK_OK 없이 종료:\n{tail}\n{stderr[-1000:]}")
    header: dict[str, Any] = {}
    gaps: dict[int, NodeParseGap] = {}
    for line in lines:
        if line.startswith("POK_TREE:"):
            header = json.loads(line[len("POK_TREE:") :])
        elif line.startswith("POK_GAP:"):
            payload = json.loads(line[len("POK_GAP:") :])
            node_id = int(payload["id"])
            gaps[node_id] = NodeParseGap(
                node_id=node_id,
                name=str(payload.get("name") or ""),
                socket=bool(payload.get("socket")),
                lines=tuple(
                    UnparsedLine(
                        index=int(item["i"]),
                        text=str(item["text"]).strip(),
                        kind=str(item["status"]),
                        remainder=str(item.get("rest") or "").strip(),
                    )
                    for item in payload["lines"]
                    if str(item["status"]) in _KINDS
                ),
            )
    if not header:
        raise ParseGapError("POK_TREE 헤더 없음 — 분모를 모르면 비율을 말할 수 없다")
    return ParseGapDump(
        tree_version=str(header.get("version") or "?"),
        scanned=int(header.get("nodes") or 0),
        snapshot=snapshot,
        gaps=gaps,
    )


# 레코드에 넣는 문장은 **짧게** — 501건에 같은 문단을 복사하면 정본이 설명문으로 부푼다.
# 긴 배경(왜 탈락하는가·왜 grep이 아닌가)은 이 모듈 docstring에 한 벌만 둔다.
def _detail(gap: NodeParseGap, total_lines: int) -> str:
    kinds = "·".join(sorted({line.kind for line in gap.lines}))
    scope = "전 줄" if total_lines and len(gap.lines) >= total_lines else f"{total_lines}줄 중"
    return (
        f"PoB가 이 노드 문구 {scope} {len(gap.lines)}줄을 계산에 넣지 못한다({kinds}) — "
        "델타 0은 '값어치 없음'이 아니라 **'측정 안 됨'**이다."
    )


_WORKAROUND = (
    "등가 문구로 바꿔 아이템 텍스트에 주입하면 접사로 파싱된다(원문 그대로는 또 "
    "떨어진다 — 대상 한정어가 원인). 실측이 아니라 **추산**임을 산출물에 남길 것. "
    "배경: `pok.pob.parse_gaps`"
)


@dataclass(frozen=True)
class RecordParseGap:
    """KB 레코드에 이어붙인 갭 — 그대로 `pob_modeling` 값이 된다."""

    record_id: str
    gap: NodeParseGap
    total_lines: int  # 레코드의 `stats_en` 줄 수 — 부분/전량 구분의 분모

    def as_modeling(self, snapshot: str) -> dict[str, Any]:
        return {
            "supported": False,
            "kind": _KIND,
            "detail": _detail(self.gap, self.total_lines),
            "workaround": _WORKAROUND,
            "snapshot": snapshot,  # 판정은 이 PoB 커밋 기준 — 없으면 낡음을 알 수 없다
            "unparsed": [line.as_dict() for line in self.gap.lines],
        }


def scan_parse_gaps(
    root: Path | None = None, *, dump: ParseGapDump | None = None
) -> tuple[list[RecordParseGap], dict[str, Any]]:
    """PoB 판정을 KB Passive 레코드에 잇는다. 반환 = (갭 목록, 요약).

    요약에 **KB에 없는 노드**도 함께 낸다 — 조용히 버리면 "전부 표시했다"로 읽히는데,
    트리엔 KB가 의도적으로 미수록한 노드(DNT 등)가 있다.
    """
    from pok.kb.store import load as store_load

    data_dump = dump if dump is not None else dump_tree_parse_gaps(root=root)
    by_node: dict[int, tuple[str, dict[str, Any]]] = {}
    for record in store_load(root).records.values():
        if record.type != "Passive":
            continue
        data = record.raw.get("data") or {}
        node_id = data.get("node_id")
        if node_id is not None:
            by_node[int(node_id)] = (record.id, data)

    found: list[RecordParseGap] = []
    unmatched: list[int] = []
    sockets: list[int] = []
    for node_id, gap in sorted(data_dump.gaps.items()):
        if gap.socket:
            sockets.append(node_id)  # 구조 선언 — 미파싱이 손실이 아니다
            continue
        hit = by_node.get(node_id)
        if hit is None:
            unmatched.append(node_id)
            continue
        record_id, data = hit
        found.append(
            RecordParseGap(
                record_id=record_id,
                gap=gap,
                total_lines=len(data.get("stats_en") or ()),
            )
        )
    summary = {
        "tree_version": data_dump.tree_version,
        "snapshot": data_dump.snapshot,
        "scanned_nodes": data_dump.scanned,
        "gap_nodes": len(data_dump.gaps),
        "flagged_records": len(found),
        "unmatched_nodes": unmatched,  # KB 미수록 — 표시할 레코드가 없다
        "skipped_sockets": sockets,  # 소켓 구조 선언 — 표기 대상 아님
    }
    return found, summary


def apply_parse_flags(
    root: Path | None = None, *, write: bool = True, dump: ParseGapDump | None = None
) -> dict[str, Any]:
    """검출된 갭을 `pob_modeling`으로 표시하고, 이제 파싱되는 것은 지운다."""
    from pok.kb.store import load as store_load
    from pok.kb.store import patch_records

    found, summary = scan_parse_gaps(root, dump=dump)
    snapshot = str(summary["snapshot"])
    updates: dict[str, dict[str, Any]] = {
        item.record_id: {"pob_modeling": item.as_modeling(snapshot)} for item in found
    }
    flagged = set(updates)

    # 낡은 플래그 정리 — 스냅샷이 바뀌어 이제 파싱되는 노드는 표시를 지운다.
    # 다른 kind(룬 슬롯 등)는 이 감사의 소관이 아니므로 그대로 둔다.
    stale = sorted(
        record.id
        for record in store_load(root).records.values()
        if record.id not in flagged
        and ((record.raw.get("data") or {}).get("pob_modeling") or {}).get("kind") == _KIND
    )
    updates.update({record_id: {"pob_modeling": None} for record_id in stale})

    if write and updates:
        patch_records(updates, root=root)
    return {**summary, "flagged": sorted(flagged), "cleared": stale, "wrote": bool(write)}


if __name__ == "__main__":  # python -m pok.pob.parse_gaps [--dry-run]
    import sys

    dry = "--dry-run" in sys.argv
    report = apply_parse_flags(write=not dry)
    print(
        f"트리 {report['tree_version']} · PoB {report['snapshot']} · "
        f"노드 {report['scanned_nodes']}개 검사 → 갭 {report['gap_nodes']}개 / "
        f"표기 {len(report['flagged'])}건 · 해제 {len(report['cleared'])}건 · "
        f"소켓 제외 {len(report['skipped_sockets'])}건 · "
        f"KB 미수록 {len(report['unmatched_nodes'])}건" + (" (dry-run — 쓰지 않음)" if dry else "")
    )
