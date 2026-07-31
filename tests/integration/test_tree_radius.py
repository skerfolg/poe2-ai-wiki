"""주얼 반경 판정 통합 — KB 좌표(data.position) vs PoB 스냅샷 nodesInRadius 실측 대조.

Time-Lost(오래된)·Against the Darkness 류 '반경 내 패시브' 주얼 전략의 기반 검증:
KB 트리 샤드에 수록한 노드 좌표가 PoB의 반경 판정과 **같은 좌표 공간**임을
전체 주얼 소켓 x Small(1000)·Very Large(1500) 반경으로 확인한다.

오라클 = scripts/pob_radius_dump.lua 가 노출하는 PoB의 실제 사전계산
(PassiveTree.lua:326-355, 거리² ≤ (outer*1.2)² — 1.2는 Misc.lua의
PassiveTreeJewelDistanceMultiplier). KB 좌표로 같은 부등식을 계산해 집합이
일치해야 한다. PoB는 KB가 의도적으로 미수록한 노드(DNT·클래스 시작·OnlyImage
등)도 반경에 담으므로, 비교는 KB 수록 노드로 한정한다(∩) — 그 방향의 누락은
KB 수록 판정(test_tree)의 몫이지 좌표 공간의 몫이 아니다.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache

import pytest

from pok.common.paths import project_root
from pok.kb.store import load as store_load
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.runner import _LUA_PATH
from pok.pob.versions import find_luajit, resolve_snapshot

# Data/Misc.lua gameConstants["PassiveTreeJewelDistanceMultiplier"]
_DISTANCE_MULT = 1.2
# Modules/Data.lua jewelRadii — outer가 이 값이고 inner=0인 정의를 인덱스로 해석
_RADII_UNDER_TEST = (1000, 1500)  # Small · Very Large


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


@lru_cache(maxsize=1)
def _pob_dump() -> tuple[list[dict[str, int]], dict[int, dict[int, set[int]]]]:
    """PoB를 1회 부팅해 (jewelRadius 정의, 소켓별 radiusIndex별 노드 집합)을 얻는다."""
    snap = resolve_snapshot()
    xml_file = project_root() / "var" / "pob-cache" / "_radius-dump-input.xml"
    xml_file.parent.mkdir(parents=True, exist_ok=True)
    xml_file.write_text(
        to_xml(BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", level=1)),
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            [find_luajit(), str(project_root() / "scripts" / "pob_radius_dump.lua"), str(xml_file)],
            cwd=snap.src_dir,
            env={**os.environ, "LUA_PATH": _LUA_PATH},
            input="",
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        xml_file.unlink(missing_ok=True)
    lines = proc.stdout.splitlines()
    assert "POK_OK" in lines, f"덤프 실패:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    radii = json.loads(next(x[len("POK_RADII:") :] for x in lines if x.startswith("POK_RADII:")))
    raw = json.loads(next(x[len("POK_RADIUS:") :] for x in lines if x.startswith("POK_RADIUS:")))
    by_socket = {
        int(sid): {int(idx): set(ids) for idx, ids in per.items()} for sid, per in raw.items()
    }
    return radii, by_socket


def test_kb_positions_reproduce_pob_jewel_radius() -> None:
    kb = store_load(project_root())
    positions: dict[int, tuple[float, float]] = {}
    sockets: list[int] = []
    for rec in kb.records.values():
        if rec.type != "Passive":
            continue
        data = rec.raw.get("data", {})
        pos = data.get("position")
        if pos is None:
            continue
        nid = int(data["node_id"])
        positions[nid] = (float(pos["x"]), float(pos["y"]))
        if data.get("kind") == "jewel-socket":
            sockets.append(nid)
    assert len(positions) > 4000, "트리 샤드 좌표가 비어 있다 — 재수록 필요"
    assert sockets, "jewel-socket 레코드 없음"

    radii, by_socket = _pob_dump()

    # noRadius 소켓(Sinister 계열)은 PoB가 반경 사전계산 자체를 건너뛴다
    # (PassiveTree.lua:330 — charm/containJewelSocket/noRadius 제외).
    tree_json = json.loads(
        (resolve_snapshot().src_dir / "TreeData" / "0_5" / "tree.json").read_text(encoding="utf-8")
    )
    no_radius = {
        int(nid)
        for nid, n in tree_json["nodes"].items()
        if isinstance(n, dict) and n.get("noRadius")
    }
    assert set(sockets) - by_socket.keys() <= no_radius, "noRadius 아닌 소켓이 PoB 판정에서 빠졌다"
    radius_sockets = [s for s in sockets if s in by_socket]
    assert radius_sockets, "반경 판정 대상 소켓 없음"

    compared = 0
    nonempty = 0
    for outer in _RADII_UNDER_TEST:
        radius_index = radii.index({"inner": 0, "outer": outer}) + 1  # Lua 1-based
        threshold_sq = (outer * _DISTANCE_MULT) ** 2
        for socket_id in radius_sockets:
            expected = by_socket[socket_id][radius_index] & positions.keys()
            sx, sy = positions[socket_id]
            got = {
                nid
                for nid, (x, y) in positions.items()
                if nid != socket_id and (x - sx) ** 2 + (y - sy) ** 2 <= threshold_sq
            }
            assert got == expected, (
                f"소켓 {socket_id} 반경 {outer}: KB만 {sorted(got - expected)[:10]} / "
                f"PoB만 {sorted(expected - got)[:10]}"
            )
            compared += 1
            if expected:
                nonempty += 1
    assert compared == len(radius_sockets) * len(_RADII_UNDER_TEST)
    assert nonempty, "모든 반경 집합이 비어 있다 — 좌표 공간이 어긋났을 가능성"
