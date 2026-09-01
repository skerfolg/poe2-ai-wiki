"""상주 PoB 프로세스 — 최적화 루프용 (scripts/pob_daemon.lua 관리).

기동(트리·데이터 로드 ~2초)을 1회로 상각하고 계산당 ~0.1초로 응답한다
(실측 2026-07-30: 계산 3회 합계 2.0초). 트리 탐색(P4)처럼 왕복이 수백 회인
루프에서만 쓰고, 단발 계산은 `runner.run_build`(캐시 포함)를 쓸 것.

주의: 응답 대기는 블로킹이다 — PoB가 무한 루프에 빠지면 같이 멈춘다.
루프 상위(엔진)가 필요 시 close()로 강제 종료하고 새로 띄우는 것이 복구 전략.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import TracebackType
from typing import Any

from pok.common.paths import project_root, var_dir
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.runner import PobResult, PobRunError, find_dropped_items, parse_lines
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_DAEMON = "scripts/pob_daemon.lua"
_LUA_PATH = "./?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;;"


class PobDaemon:
    """with PobDaemon() as d: d.compute_build(spec) — 프로세스 1개, 계산 N회."""

    def __init__(self, snapshot: PobSnapshot | None = None) -> None:
        self._snap = snapshot or resolve_snapshot()
        self._proc: subprocess.Popen[str] | None = None
        self._seq = 0
        self._loaded_spec: BuildSpec | None = None
        # 마지막으로 계산한 XML — `compute_tree`는 트리만 갈아 끼우므로 **아이템은
        # 그때 올린 것 그대로**다. 버려진 아이템 신고(#135)를 트리 왕복에서도 유지한다.
        self._last_xml = ""

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
        xml_file.write_text(xml_text, encoding="utf-8", newline="\n")
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
        self._last_xml = xml_text
        return PobResult(
            stats=stats,
            meta=meta,
            allocated_nodes=alloc,
            pruned_nodes=pruned,
            cached=False,
            dropped_items=find_dropped_items(xml_text, meta),
        )

    def compute_tree(self, nodes: tuple[int, ...]) -> PobResult:
        """**로드된 빌드의 트리만** 갈아 끼워 재계산한다 (#70 후속).

        최적화 루프는 노드만 바꾸는데 `compute_build`은 매번 빌드를 통째로 다시
        로드한다. 실측 2026-08-13(블러드 메이지, 장비 15·스킬 9그룹·젬 32개):
        최소 **0.38초** · 장비까지 **0.60초** · 스킬까지 **3.68초** — 장비는 +0.22초인데
        **스킬이 +3.16초**다. 스킬은 루프에서 한 번도 안 바뀌므로 통째로 낭비였다.

        ⚠ **먼저 `compute_build`으로 빌드를 한 번 올려 둬야 한다.** 안 그러면 데몬이
        「로드된 빌드가 없다」로 거부한다 — 조용히 빈 빌드를 계산하지 않는다.
        """
        self.start()
        assert self._proc is not None and self._proc.stdin is not None
        payload = ",".join(str(n) for n in nodes)
        self._proc.stdin.write(f"TREE\t{payload}\n")
        self._proc.stdin.flush()
        lines: list[str] = []
        while True:
            line = self._readline()
            if not line:
                raise PobRunError("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
            if line.rstrip("\n") == "POK_DONE":
                break
            lines.append(line.rstrip("\n"))
        stats, meta, alloc = parse_lines(lines)
        return PobResult(
            stats=stats,
            meta=meta,
            allocated_nodes=alloc,
            pruned_nodes=tuple(sorted(set(nodes) - set(alloc))),
            cached=False,
            # 트리만 갈아 끼워도 **아이템은 그대로** 올라가 있다 — 신고가 여기서
            # 끊기면 최적화 루프 전체가 버려진 장비를 못 보고 돈다.
            dropped_items=find_dropped_items(self._last_xml, meta),
        )

    def node_power(
        self, stats: tuple[str, ...] = ()
    ) -> tuple[dict[int, dict[str, float]], dict[str, Any]]:
        """**미할당 노드 전량**을 하나씩 더했을 때의 델타 (추가 방향, #73 스파이크).

        우리 측정은 「이미 찍은 노드를 빼면?」만 답한다. 「안 찍은 노드를 찍으면?」은
        후보마다 전체 재계산을 가정해 전수가 46일로 잡혀 있었는데, PoB에는 전용
        빠른 경로가 있다(`calcs.getMiscCalculator` — 기준 계산 1회 뒤 환경·DB를
        재사용하는 클로저). PoB 자신의 트리 색칠이 이 경로를 쓴다.

        ⚠ **경로 비용이 빠져 있다.** 노드 하나만 더한 값이라 「거기까지 잇는 데 몇
        포인트가 드나」가 없다. PoB 자신도 "Estimate"라 부르고 조합 효과도 무시한다
        (단독 델타 0인 둘이 함께 1.44배인 사례). **후보를 좁히는 신호**로만 쓸 것.

        ⚠ 먼저 `compute_build`으로 빌드를 올려 둬야 한다(`compute_tree`와 같다).
        """
        self.start()
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write("POWER\t" + ",".join(stats) + "\n")
        self._proc.stdin.flush()
        out: dict[int, dict[str, float]] = {}
        meta: dict[str, Any] = {}
        while True:
            line = self._readline()
            if not line:
                raise PobRunError("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
            s = line.rstrip("\n")
            if s == "POK_DONE":
                break
            if s.startswith("POK_POWER:"):
                row = json.loads(s[len("POK_POWER:") :])
                out[int(row["node"])] = {k: float(v) for k, v in (row.get("d") or {}).items()}
            elif s.startswith("POK_POWERMETA:"):
                meta = json.loads(s[len("POK_POWERMETA:") :])
            elif s.startswith("POK_ERR:"):
                raise PobRunError(s[len("POK_ERR:") :])
        return out, meta

    def build_item(self, spec_text: str) -> str:
        """아이템 **명세 → PoB 정본 텍스트** (#34). 실패하면 빈 문자열.

        별도 프로세스로 띄우면 **호출마다 9.8초**가 든다(실측 2026-08-09: `optimize_rare`
        전체 9.8초 중 9.8초가 부팅이었다). 데몬에 붙여 그 비용을 1회로 상각한다.
        """
        self.start()
        assert self._proc is not None and self._proc.stdin is not None
        path = self._xml_file(spec_text).with_suffix(".item")
        path.write_text(spec_text, encoding="utf-8", newline="\n")
        try:
            self._proc.stdin.write(f"ITEM\t{path}\n")
            self._proc.stdin.flush()
            built = ""
            while True:
                line = self._readline()
                if not line:
                    raise PobRunError("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
                stripped = line.rstrip("\n")
                if stripped == "POK_DONE":
                    break
                if stripped.startswith("POK_RAW:"):
                    built = stripped[len("POK_RAW:") :].replace("\\n", "\n").replace("\\\\", "\\")
        finally:
            path.unlink(missing_ok=True)
        return built

    def compute_build(self, spec: BuildSpec) -> PobResult:
        result = self.compute(to_xml(spec), requested_nodes=spec.tree_nodes)
        self._loaded_spec = spec
        return result

    @property
    def loaded_spec(self) -> BuildSpec | None:
        """마지막으로 **통째로 올린** 스펙. `compute_tree`의 토대가 무엇인지 알려 준다.

        ⚠ 이걸 데몬이 들고 있어야 하는 이유: 호출자가 여러 겹이면(예:
        `evaluate_bundles` → `evaluate_node_deltas`) **바깥 호출자는 안쪽이 다른
        빌드를 올린 것을 모른다.** 그 상태로 `compute_tree`를 부르면 엉뚱한 토대
        위에서 재는데, 값이 그럴듯해서 조용히 틀린다. 상태를 아는 것은 데몬뿐이다.
        """
        return self._loaded_spec

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
            # 프로세스가 죽으면 올라가 있던 빌드도 사라진다 — 안 지우면 재기동 뒤
            # `compute_tree`가 **빈 데몬 위에서** 도는데 그건 조용히 틀린다.
            self._loaded_spec = None

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


_SHARED: PobDaemon | bool | None = None


def shared_daemon() -> PobDaemon | None:
    """프로세스당 하나의 상주 PoB. 못 띄우면 `None` — 호출자가 1회성 경로로 되돌아간다.

    ⚠ **상주 여부가 곧 쓸 수 있느냐를 가른다.** 1회성 경로는 호출마다 luajit을
    새로 띄워 **1.82초**가 들고, 데몬은 **0.173초**다(실측 2026-08-11, 동일 스펙
    20회 평균 — 10.5배). `optimize_items`는 8슬롯 2라운드에 606회를 재므로
    18.4분 대 1.75분이 된다. 실제로 한 세션이 29분 46초를 기다리다 **정지로 판단해
    강제 종료**했다(백로그 #61) — 느린 것과 죽은 것을 구분할 수 없었다.
    """
    global _SHARED
    if _SHARED is None:
        try:
            daemon = PobDaemon()
            daemon.start()
        except Exception:  # 스냅샷 없음·기동 실패 — 조용히 죽지 않고 되돌아간다
            _SHARED = False
        else:
            _SHARED = daemon
            atexit.register(daemon.close)
    return _SHARED if isinstance(_SHARED, PobDaemon) else None
