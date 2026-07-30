"""상주 PoB 프로세스 — 최적화 루프용 (scripts/pob_daemon.lua 관리).

기동(트리·데이터 로드 ~2초)을 1회로 상각하고 계산당 ~0.1초로 응답한다
(실측 2026-07-30: 계산 3회 합계 2.0초). 트리 탐색(P4)처럼 왕복이 수백 회인
루프에서만 쓰고, 단발 계산은 `runner.run_build`(캐시 포함)를 쓸 것.

주의: 응답 대기는 블로킹이다 — PoB가 무한 루프에 빠지면 같이 멈춘다.
루프 상위(엔진)가 필요 시 close()로 강제 종료하고 새로 띄우는 것이 복구 전략.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from types import TracebackType

from pok.common.paths import project_root, var_dir
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.runner import PobResult, PobRunError, parse_lines
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_DAEMON = "scripts/pob_daemon.lua"
_LUA_PATH = "./?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;;"


class PobDaemon:
    """with PobDaemon() as d: d.compute_build(spec) — 프로세스 1개, 계산 N회."""

    def __init__(self, snapshot: PobSnapshot | None = None) -> None:
        self._snap = snapshot or resolve_snapshot()
        self._proc: subprocess.Popen[str] | None = None
        self._seq = 0

    def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            [find_luajit(), str(project_root() / _DAEMON)],
            cwd=self._snap.src_dir,
            env={**os.environ, "LUA_PATH": _LUA_PATH},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # PoB의 진행 로그(ConPrintf)는 버린다
            text=True,
            encoding="utf-8",
        )
        while True:
            line = self._readline()
            if not line:
                raise PobRunError("데몬이 POK_READY 없이 종료됨")
            if line.strip() == "POK_READY":
                return

    def compute(self, xml_text: str, *, requested_nodes: tuple[int, ...] = ()) -> PobResult:
        """XML 하나를 계산한다 (캐시 없음 — 루프는 항상 새 조합을 시도한다)."""
        self.start()
        assert self._proc is not None and self._proc.stdin is not None
        xml_file = self._xml_file(xml_text)
        xml_file.write_text(xml_text, encoding="utf-8")
        try:
            self._proc.stdin.write(str(xml_file) + "\n")
            self._proc.stdin.flush()
            lines: list[str] = []
            while True:
                line = self._readline()
                if not line:
                    raise PobRunError("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
                if line.rstrip("\n") == "POK_DONE":
                    break
                lines.append(line.rstrip("\n"))
        finally:
            xml_file.unlink(missing_ok=True)
        stats, meta, alloc = parse_lines(lines)
        pruned = tuple(sorted(set(requested_nodes) - set(alloc)))
        return PobResult(
            stats=stats, meta=meta, allocated_nodes=alloc, pruned_nodes=pruned, cached=False
        )

    def compute_build(self, spec: BuildSpec) -> PobResult:
        return self.compute(to_xml(spec), requested_nodes=spec.tree_nodes)

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.write("QUIT\n")
                self._proc.stdin.flush()
            self._proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()
        finally:
            self._proc = None

    def _readline(self) -> str:
        # 제너레이터로 감싸지 않는다 — `yield from 파일`을 중도 포기하면
        # close 위임으로 프로세스 stdout까지 닫힌다 (실측 함정).
        assert self._proc is not None and self._proc.stdout is not None
        return str(self._proc.stdout.readline())

    def _xml_file(self, xml_text: str) -> Path:
        self._seq += 1
        digest = hashlib.sha256(xml_text.encode()).hexdigest()[:8]
        d = var_dir() / "pob-cache"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"_daemon-{os.getpid()}-{self._seq}-{digest}.xml"

    def __enter__(self) -> PobDaemon:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
