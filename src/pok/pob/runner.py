"""headless PoB 실행 — XML을 넣고 스탯을 받는 왕복 (scripts/pob_driver.lua 프로토콜).

한 번 실행 = LuaJIT 프로세스 1회 (~2초, 트리·데이터 로드가 지배적).
동일 (XML, PoB 커밋) 결과는 `var/pob-cache/`에 캐시 — 파생물이므로 삭제 무해.
최적화 루프용 상주 프로세스(daemon)는 P3 Phase 2에서 별도로 다룬다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pok.common.paths import project_root, var_dir
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_DRIVER = "scripts/pob_driver.lua"
_LUA_PATH = "./?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;;"


@dataclass(frozen=True)
class PobResult:
    """PoB 계산 결과 + 적법성 신호."""

    stats: dict[str, float]  # mainOutput의 유한 숫자 전부
    meta: dict[str, object]  # class/ascendancy/level/alloc* — 드라이버 POK_META
    allocated_nodes: tuple[int, ...]  # 실제 할당된 트리 노드 (시작점 제외)
    pruned_nodes: tuple[int, ...]  # 요청했지만 PoB가 해제한 노드 (비연결 등)
    cached: bool

    @property
    def is_tree_legal(self) -> bool:
        """요청한 노드가 전부 반영됐는가 — 비연결 노드는 PoB가 소리 없이 잘라낸다."""
        return not self.pruned_nodes


class PobRunError(RuntimeError):
    """드라이버가 POK_OK 없이 끝났다 — stderr/stdout 꼬리를 담는다."""


def _cache_path(xml_text: str, commit: str) -> Path:
    digest = hashlib.sha256(f"{commit}\n{xml_text}".encode()).hexdigest()[:32]
    return var_dir() / "pob-cache" / f"{digest}.json"


def parse_lines(
    lines: list[str],
) -> tuple[dict[str, float], dict[str, object], tuple[int, ...]]:
    """POK_* 프로토콜 공통 파서 (driver·daemon 동일 계약). POK_ERR는 예외로 승격."""
    meta: dict[str, object] = {}
    stats: dict[str, float] = {}
    alloc: tuple[int, ...] = ()
    for line in lines:
        if line.startswith("POK_META:"):
            meta = json.loads(line[len("POK_META:") :])
        elif line.startswith("POK_ALLOC:"):
            alloc = tuple(json.loads(line[len("POK_ALLOC:") :]))
        elif line.startswith("POK_JSON:"):
            stats = {k: float(v) for k, v in json.loads(line[len("POK_JSON:") :]).items()}
        elif line.startswith("POK_ERR:"):
            raise PobRunError(line[len("POK_ERR:") :])
    if not stats or not meta:
        tail = "\n".join(lines[-8:])
        raise PobRunError(f"POK_META/POK_JSON 누락:\n{tail}")
    return stats, meta, alloc


def _parse(stdout: str) -> tuple[dict[str, float], dict[str, object], tuple[int, ...]]:
    lines = stdout.splitlines()
    result = parse_lines(lines)  # POK_ERR 사유가 있으면 여기서 먼저 예외로 승격
    if "POK_OK" not in lines:
        raise PobRunError("드라이버가 POK_OK 없이 종료:\n" + "\n".join(lines[-8:]))
    return result


def run_xml(
    xml_text: str,
    *,
    requested_nodes: tuple[int, ...] = (),
    snapshot: PobSnapshot | None = None,
    use_cache: bool = True,
    timeout: float = 120.0,
) -> PobResult:
    """XML 하나를 PoB로 계산한다. requested_nodes를 주면 잘린 노드를 판정."""
    snap = snapshot or resolve_snapshot()
    cache = _cache_path(xml_text, snap.commit)
    hit = use_cache and cache.exists()
    if hit:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        payload = _run_driver(xml_text, snap, timeout)
        if use_cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )
    allocated = tuple(int(n) for n in payload["alloc"])
    pruned = tuple(sorted(set(requested_nodes) - set(allocated)))
    return PobResult(
        stats=dict(payload["stats"]),
        meta=dict(payload["meta"]),
        allocated_nodes=allocated,
        pruned_nodes=pruned,
        cached=hit,
    )


def run_build(spec: BuildSpec, **kwargs: object) -> PobResult:
    """BuildSpec → XML 직렬화 → 계산. 트리 적법성 판정까지 한 번에."""
    return run_xml(to_xml(spec), requested_nodes=spec.tree_nodes, **kwargs)  # type: ignore[arg-type]


def _run_driver(xml_text: str, snap: PobSnapshot, timeout: float) -> dict[str, object]:
    driver = project_root() / _DRIVER
    digest = hashlib.sha256(xml_text.encode()).hexdigest()[:16]
    xml_file = var_dir() / "pob-cache" / f"_input-{digest}.xml"  # 해시명 = 동시 실행 안전
    xml_file.parent.mkdir(parents=True, exist_ok=True)
    xml_file.write_text(xml_text, encoding="utf-8", newline="\n")
    env = {**os.environ, "LUA_PATH": _LUA_PATH}
    try:
        proc = subprocess.run(
            [find_luajit(), str(driver), str(xml_file)],
            cwd=snap.src_dir,
            env=env,
            input="",  # PoB가 stdin을 읽는 경로 차단 (스파이크에서 echo "" 파이프와 동일)
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        xml_file.unlink(missing_ok=True)
    if proc.returncode != 0 and "POK_" not in proc.stdout:
        raise PobRunError(f"luajit 종료 코드 {proc.returncode}:\n{proc.stderr[-2000:]}")
    stats, meta, alloc = _parse(proc.stdout)
    return {"stats": stats, "meta": meta, "alloc": list(alloc)}
