"""상주 PoB 프로세스 — 최적화 루프용 (scripts/pob_daemon.lua 관리).

기동(트리·데이터 로드 ~2초)을 1회로 상각하고 계산당 ~0.1초로 응답한다
(실측 2026-07-30: 계산 3회 합계 2.0초). 트리 탐색(P4)처럼 왕복이 수백 회인
루프에서만 쓰고, 단발 계산은 `runner.run_build`(캐시 포함)를 쓸 것.

명령은 잠금 대기부터 응답 완료까지 절대 기한을 적용한다. 소유한 명령의
응답 기한이 끝나면 해당 자식을 종료하고 다음 명령에서 새 프로세스를 시작한다.
"""

from __future__ import annotations

import atexit
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from functools import wraps
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, RLock, Thread
from time import monotonic
from types import FunctionType, TracebackType
from typing import Any, Concatenate
from uuid import uuid4

from pok.common.code_identity import code_sha256
from pok.common.execution import ExecutionStopped, checkpoint, current_execution, remaining_timeout
from pok.common.owned_process import spawn_owned, terminate_owned
from pok.common.paths import project_root, var_dir
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.execution_identity import observe_execution_inputs
from pok.pob.runner import (
    PobResult,
    PobRunError,
    find_dropped_items,
    native_mode_error_hint,
    parse_lines,
)
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_DAEMON = "scripts/pob_daemon.lua"
_LUA_PATH = "./?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;;"


class PobCommandTimeout(PobRunError, TimeoutError):
    """A command expired; direct-child termination is reported separately."""

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.termination = "not_owned" if phase == "lock_wait" else "not_attempted"
        super().__init__(f"PoB command deadline exceeded: {phase}")

    def __str__(self) -> str:
        return f"PoB command deadline exceeded: {self.phase}; termination={self.termination}"


class PobProcessStopped(PobRunError):
    """EOF before a complete native frame; this process cannot be reused."""


class _LineReader:
    """One reader per process; reads only when requested, never across frames."""

    def __init__(self, stream: Any) -> None:
        self.requests: Queue[Queue[tuple[str, Exception | None]] | None] = Queue()

        def pump() -> None:
            while (reply := self.requests.get()) is not None:
                try:
                    reply.put((str(stream.readline()), None))
                except Exception as exc:
                    reply.put(("", exc))

        Thread(target=pump, name="pok-pob-output", daemon=True).start()

    def read(self, deadline: float) -> str:
        checkpoint()
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PobCommandTimeout("native_response")
        reply: Queue[tuple[str, Exception | None]] = Queue(maxsize=1)
        self.requests.put(reply)
        while True:
            checkpoint()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise PobCommandTimeout("native_response")
            try:
                line, error = reply.get(timeout=min(remaining, 0.05))
                break
            except Empty:
                continue
        if error is not None:
            raise error
        if monotonic() >= deadline:
            raise PobCommandTimeout("native_response")
        return line

    def close(self) -> None:
        self.requests.put(None)


def _acquire_lock(lock: Any, timeout: float) -> bool:
    deadline = monotonic() + timeout
    while True:
        checkpoint()
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        if lock.acquire(timeout=min(remaining, 0.05)):
            return True


def _exclusive[**P, R](
    method: Callable[Concatenate[PobDaemon, P], R],
) -> Callable[Concatenate[PobDaemon, P], R]:
    """명령 전송부터 응답·상태 갱신까지 같은 요청이 스트림을 소유한다."""

    @wraps(method)
    def wrapped(self: PobDaemon, /, *args: P.args, **kwargs: P.kwargs) -> R:
        limit = remaining_timeout(self.command_timeout_s)
        deadline = monotonic() + limit
        if not _acquire_lock(self._lock, limit):
            checkpoint()
            raise PobCommandTimeout("lock_wait")
        if monotonic() >= deadline:
            self._lock.release()
            raise PobCommandTimeout("lock_wait")
        previous = self._deadline
        self._deadline = min(previous, deadline) if previous is not None else deadline
        try:
            if self._proc is not None and (scope := current_execution()) is not None:
                scope.acquire_resource(
                    f"pob-daemon:{id(self)}",
                    kind="pob_daemon_command",
                    identity=str(getattr(self._proc, "pid", "unavailable")),
                    handle=self._proc,
                )
            checkpoint()
            if monotonic() >= self._deadline:
                raise PobCommandTimeout("native_response")
            result = method(self, *args, **kwargs)
            checkpoint()
            if monotonic() >= self._deadline:
                raise PobCommandTimeout("native_response")
            return result
        except ExecutionStopped as exc:
            termination = self._abort_owned()
            if (scope := current_execution()) is not None:
                scope.release_resource(
                    f"pob-daemon:{id(self)}",
                    state="unconfirmed" if termination == "unconfirmed" else "terminated",
                )
            cleanup_scope = (self._last_cleanup or {}).get("scope", "no_process")
            exc.add_note(f"PoB native termination={termination}; scope={cleanup_scope}")
            raise
        except PobCommandTimeout as exc:
            if exc.phase != "lock_wait" and exc.termination == "not_attempted":
                exc.termination = self._abort_owned()
                if (scope := current_execution()) is not None:
                    scope.release_resource(
                        f"pob-daemon:{id(self)}",
                        state="unconfirmed" if exc.termination == "unconfirmed" else "terminated",
                    )
            raise
        except (OSError, PobProcessStopped) as exc:
            termination = self._abort_owned()
            exc.add_note(f"Interrupted native frame cleanup: {termination}")
            raise
        finally:
            if previous is None and (scope := current_execution()) is not None:
                scope.release_resource(f"pob-daemon:{id(self)}")
            if previous is None and self._reader is not None:
                # No pending read remains on a completed frame. Retire the idle
                # pump rather than leaking one thread per abandoned instance.
                self._reader.close()
                self._reader = None
                self._reader_proc = None
            self._deadline = previous
            self._lock.release()

    return wrapped


class PobDaemon:
    """with PobDaemon() as d: d.compute_build(spec) — 프로세스 1개, 계산 N회."""

    def __init__(
        self,
        snapshot: PobSnapshot | None = None,
        *,
        command_timeout_s: float = 180.0,
        adapter_root: Path | None = None,
        kb_diagnostics: bool = True,
    ) -> None:
        if not math.isfinite(command_timeout_s) or command_timeout_s <= 0:
            raise ValueError("command_timeout_s must be finite and positive")
        if not isinstance(kb_diagnostics, bool):
            raise ValueError("kb_diagnostics must be a boolean")
        self._kb_diagnostics = kb_diagnostics
        self.command_timeout_s = command_timeout_s
        self._adapter_root = adapter_root.resolve() if adapter_root is not None else None
        self._snap = snapshot or resolve_snapshot()
        self._proc: subprocess.Popen[str] | None = None
        self._lock = RLock()
        self._deadline: float | None = None
        self._reader: _LineReader | None = None
        self._reader_proc: subprocess.Popen[str] | None = None
        self._broken = False
        self._last_cleanup: dict[str, Any] | None = None
        self._startup_observation: dict[str, Any] | None = None
        self._startup_process_identity: int | None = None
        self._loaded_spec: BuildSpec | None = None
        # 마지막으로 계산한 XML — `compute_tree`는 트리만 갈아 끼우므로 **아이템은
        # 그때 올린 것 그대로**다. 버려진 아이템 신고(#135)를 트리 왕복에서도 유지한다.
        self._last_xml = ""

    @contextmanager
    def transaction(self) -> Iterator[PobDaemon]:
        """로드 상태 확인과 그 상태를 쓰는 여러 명령을 한 요청으로 묶는다."""
        if not _acquire_lock(self._lock, remaining_timeout(self.command_timeout_s)):
            checkpoint()
            raise PobCommandTimeout("lock_wait")
        try:
            yield self
        finally:
            self._lock.release()

    @_exclusive
    def start(self) -> None:
        if self._broken:
            raise PobRunError("Previous PoB process termination is unconfirmed; close before reuse")
        if self._proc is not None:
            poll = getattr(self._proc, "poll", None)
            if not callable(poll) or not isinstance(poll(), int):
                return
            if self._abort_owned() == "unconfirmed":
                raise PobRunError("Exited PoB process cleanup could not be confirmed")
        before = copy.deepcopy(self._observe_inputs())
        self._check_command_deadline()
        self._startup_process_identity = None
        self._last_cleanup = None
        try:
            self._proc = spawn_owned(
                [
                    str(Path(find_luajit()).resolve()),
                    str((self._adapter_root or project_root()) / _DAEMON),
                ],
                cwd=self._snap.src_dir,
                env={**os.environ, "LUA_PATH": _LUA_PATH},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # PoB의 진행 로그(ConPrintf)는 버린다
                text=True,
                encoding="utf-8",
            )
        except BaseException as exc:
            retained = getattr(exc, "owned_process", None)
            cleanup = getattr(exc, "owned_cleanup", None)
            self._last_cleanup = cleanup
            if retained is not None:
                if not cleanup or cleanup["status"] != "confirmed":
                    self._proc = retained
                    self._broken = True
                if (scope := current_execution()) is not None:
                    key = f"pob-daemon:{id(self)}"
                    scope.acquire_resource(
                        key, kind="pob_daemon_command", identity=str(retained.pid), handle=retained
                    )
                    scope.release_resource(
                        key,
                        state="terminated"
                        if cleanup and cleanup["status"] == "confirmed"
                        else "unconfirmed",
                        details=cleanup,
                    )
            if isinstance(exc, ExecutionStopped) and cleanup is not None:
                exc.details["native_spawn_cleanup"] = cleanup
            raise
        while True:
            line = self._readline()
            if not line:
                raise PobProcessStopped("데몬이 POK_READY 없이 종료됨")
            if line.strip() == "POK_READY":
                after = copy.deepcopy(self._observe_inputs())
                self._startup_observation = {
                    "before": before,
                    "after": after,
                    "status": "unavailable"
                    if before["status"] != "observed" or after["status"] != "observed"
                    else "stable_observation"
                    if before == after
                    else "changed_during_startup",
                    "process_id": getattr(self._proc, "pid", None),
                    "generation": uuid4().hex,
                }
                self._startup_process_identity = id(self._proc)
                return

    def _check_command_deadline(self) -> None:
        checkpoint()
        if self._deadline is not None and monotonic() >= self._deadline:
            raise PobCommandTimeout("native_response")

    def _observe_inputs(self) -> dict[str, Any]:
        self._check_command_deadline()
        try:
            digest = hashlib.sha256(sys.version.encode("utf-8"))
            methods: dict[str, Any] = {}
            for parent in reversed(type(self).__mro__):
                methods.update(vars(parent))
            for name, method in sorted(methods.items()):
                if not isinstance(method, FunctionType):
                    continue
                digest.update(name.encode("utf-8"))
                digest.update(code_sha256(method.__code__).encode("ascii"))
                digest.update(
                    code_sha256(getattr(method, "__wrapped__", method).__code__).encode("ascii")
                )
            observed = observe_execution_inputs(
                self._snap,
                adapter_root=self._adapter_root or project_root(),
                executable=Path(find_luajit()).resolve(),
                adapter_code_sha256=digest.hexdigest(),
                launch_config={
                    "driver": str(((self._adapter_root or project_root()) / _DAEMON).resolve()),
                    "lua_path": _LUA_PATH,
                },
            )
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            observed = {"status": "unavailable", "diagnostics": [{"reason": str(exc)}]}
        self._check_command_deadline()
        return observed

    def _execution_meta(self) -> dict[str, Any]:
        matched = self._proc is not None and id(self._proc) == self._startup_process_identity
        poll = getattr(self._proc, "poll", None)
        code = poll() if callable(poll) else None
        return {
            "format": "pok.daemon-startup-observation.v1",
            "status": "observed_startup"
            if matched
            else "stopped"
            if self._proc is None
            else "unobserved_process",
            "startup": copy.deepcopy(self._startup_observation) if matched else None,
            "process_id": getattr(self._proc, "pid", None),
            "process_state": "termination_unconfirmed"
            if self._broken
            else "stopped"
            if self._proc is None
            else "exited"
            if isinstance(code, int)
            else "running"
            if callable(poll)
            else "not_checked",
            **(
                {"last_startup": copy.deepcopy(self._startup_observation)}
                if self._proc is None and self._startup_observation is not None
                else {}
            ),
            "current_disk": "not_sampled",
            "loaded_native_modules": "not_verified",
            "last_cleanup": copy.deepcopy(self._last_cleanup),
        }

    @_exclusive
    def inspect_execution(self, *, observe_current: bool = False) -> dict[str, Any]:
        """Never start a process merely to inspect it or replace its startup evidence."""
        result = self._execution_meta()
        if observe_current:
            current = copy.deepcopy(self._observe_inputs())
            result["current_disk"] = current
            startup = result["startup"]
            result["current_matches_startup"] = (
                "not_checked"
                if startup is None
                or startup["status"] != "stable_observation"
                or current["status"] != "observed"
                else current["sha256"] == startup["after"]["sha256"]
            )
        return result

    @_exclusive
    def compute(self, xml_text: str, *, requested_nodes: tuple[int, ...] = ()) -> PobResult:
        """XML 하나를 계산한다 (캐시 없음 — 루프는 항상 새 조합을 시도한다)."""
        self.start()
        assert self._proc is not None and self._proc.stdin is not None
        xml_file = self._xml_file(xml_text)
        xml_file.write_text(xml_text, encoding="utf-8", newline="\n")
        try:
            # raw XML도 native 빌드를 교체한다. 이전 BuildSpec 표식을 남기면
            # TREE 최적화가 다른 장비의 빌드를 자기 토대로 오인한다.
            self._loaded_spec = None
            self._last_xml = ""
            self._proc.stdin.write(str(xml_file) + "\n")
            self._proc.stdin.flush()
            lines: list[str] = []
            while True:
                line = self._readline()
                if not line:
                    raise PobProcessStopped("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
                if line.rstrip("\n") == "POK_DONE":
                    break
                lines.append(line.rstrip("\n"))
        finally:
            xml_file.unlink(missing_ok=True)
        try:
            stats, meta, alloc = parse_lines(lines)
        except PobRunError as exc:
            hint = native_mode_error_hint(xml_text, str(exc)) if self._kb_diagnostics else None
            if hint:
                raise PobRunError(f"{hint}\nOriginal native error:\n{exc}") from exc
            raise
        meta["daemon_execution"] = self._execution_meta()
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

    @_exclusive
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
                raise PobProcessStopped("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
            if line.rstrip("\n") == "POK_DONE":
                break
            lines.append(line.rstrip("\n"))
        stats, meta, alloc = parse_lines(lines)
        meta["daemon_execution"] = self._execution_meta()
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

    @_exclusive
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
        for stat in stats:
            if stat.startswith("LateLootRarity"):
                raise PobRunError(
                    f"{stat} is unavailable in POWER; use full XML or TREE computation"
                )
        self.start()
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write("POWER\t" + ",".join(stats) + "\n")
        self._proc.stdin.flush()
        out: dict[int, dict[str, float]] = {}
        meta: dict[str, Any] = {}
        lines: list[str] = []
        while True:
            line = self._readline()
            if not line:
                raise PobProcessStopped("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
            s = line.rstrip("\n")
            if s == "POK_DONE":
                break
            lines.append(s)
        # 오류도 응답 프레임 끝까지 소비한 뒤 전파한다. 중간에 던지면 남은
        # POK_DONE을 다음 요청이 자기 응답 끝으로 읽어 정상 계산까지 실패한다.
        for s in lines:
            if s.startswith("POK_POWER:"):
                row = json.loads(s[len("POK_POWER:") :])
                out[int(row["node"])] = {k: float(v) for k, v in (row.get("d") or {}).items()}
            elif s.startswith("POK_POWERMETA:"):
                meta = json.loads(s[len("POK_POWERMETA:") :])
            elif s.startswith("POK_ERR:"):
                raise PobRunError(s[len("POK_ERR:") :])
        meta["daemon_execution"] = self._execution_meta()
        return out, meta

    @_exclusive
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
                    raise PobProcessStopped("데몬이 POK_DONE 전에 종료됨 (close 후 재기동 필요)")
                stripped = line.rstrip("\n")
                if stripped == "POK_DONE":
                    break
                if stripped.startswith("POK_RAW:"):
                    built = stripped[len("POK_RAW:") :].replace("\\n", "\n").replace("\\\\", "\\")
        finally:
            path.unlink(missing_ok=True)
        return built

    @_exclusive
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
        proc = self._proc
        if proc is None:
            return
        # 계산이 막혔을 때 close()로 중단하는 기존 계약을 지킨다. 계산 잠금을
        # 기다리면 무한 대기를 끊을 수 없으므로, 사용 중이면 이 자식만 종료한다.
        idle = self._lock.acquire(blocking=False)
        confirmed = False
        try:
            if idle and proc.stdin is not None:
                with suppress(OSError, subprocess.TimeoutExpired):
                    proc.stdin.write("QUIT\n")
                    proc.stdin.flush()
                    proc.wait(timeout=5)
            cleanup = terminate_owned(proc)
            self._last_cleanup = cleanup
            confirmed = cleanup["status"] == "confirmed"
            if not confirmed:
                if (scope := current_execution()) is not None:
                    key = f"pob-daemon:{id(self)}"
                    scope.acquire_resource(
                        key,
                        kind="pob_daemon_command",
                        identity=str(getattr(proc, "pid", "unavailable")),
                        handle=proc,
                    )
                    scope.release_resource(key, state="unconfirmed", details=cleanup)
                raise PobRunError(f"Native daemon cleanup unconfirmed: {cleanup}")
        finally:
            with self._lock:
                if self._proc is proc:
                    self._loaded_spec = None
                    self._last_xml = ""
                    self._broken = not confirmed
                    if confirmed:
                        self._proc = None
                        if self._reader is not None:
                            self._reader.close()
                        self._reader = None
                        self._reader_proc = None
            if idle:
                self._lock.release()

    def _readline(self) -> str:
        # 제너레이터로 감싸지 않는다 — `yield from 파일`을 중도 포기하면
        # close 위임으로 프로세스 stdout까지 닫힌다 (실측 함정).
        assert self._proc is not None and self._proc.stdout is not None
        if (scope := current_execution()) is not None:
            scope.acquire_resource(
                f"pob-daemon:{id(self)}",
                kind="pob_daemon_command",
                identity=str(getattr(self._proc, "pid", "unavailable")),
                handle=self._proc,
            )
        if self._reader_proc is not self._proc:
            if self._reader is not None:
                self._reader.close()
            self._reader = _LineReader(self._proc.stdout)
            self._reader_proc = self._proc
        assert self._reader is not None and self._deadline is not None
        return self._reader.read(self._deadline)

    def _abort_owned(self) -> str:
        """Called while owning the command lock; never kills a waiting caller's owner."""
        proc = self._proc
        if proc is None:
            return "no_process"
        cleanup = terminate_owned(proc)
        self._last_cleanup = cleanup
        if (scope := current_execution()) is not None:
            scope.release_resource(
                f"pob-daemon:{id(self)}",
                state="terminated" if cleanup["status"] == "confirmed" else "unconfirmed",
                details=cleanup,
            )
        if cleanup["status"] != "confirmed":
            self._broken = True
            self._loaded_spec = None
            self._last_xml = ""
            return "unconfirmed"
        if self._reader is not None:
            self._reader.close()
        self._reader = None
        self._reader_proc = None
        self._proc = None
        self._loaded_spec = None
        self._last_xml = ""
        self._broken = False
        return (
            "direct_child_confirmed"
            if cleanup["scope"] == "direct_child"
            else "owned_tree_confirmed"
        )

    def _xml_file(self, xml_text: str) -> Path:
        digest = hashlib.sha256(xml_text.encode()).hexdigest()[:8]
        d = var_dir() / "pob-cache"
        d.mkdir(parents=True, exist_ok=True)
        # 인스턴스별 seq는 같은 PID의 독립 데몬끼리 충돌한다. 요청별 소유권이다.
        return d / f"_daemon-{os.getpid()}-{uuid4().hex}-{digest}.xml"

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
_SHARED_LOCK = Lock()


def inspect_shared_execution(*, observe_current: bool = False) -> dict[str, Any]:
    """Read the existing shared daemon only; never initialize one for inspection."""
    if not _SHARED_LOCK.acquire(blocking=False):
        return {
            "status": "initializing_or_busy",
            "scope": "shared_daemon_only",
            "started_by_inspection": False,
        }
    try:
        daemon = _SHARED
    finally:
        _SHARED_LOCK.release()
    if not isinstance(daemon, PobDaemon):
        return {
            "status": "unavailable" if daemon is False else "not_started",
            "scope": "shared_daemon_only",
            "started_by_inspection": False,
        }
    if not daemon._lock.acquire(blocking=False):
        return {"status": "busy", "scope": "shared_daemon_only", "started_by_inspection": False}
    try:
        return {
            "status": "observed",
            "scope": "shared_daemon_only",
            "started_by_inspection": False,
            "observation": daemon.inspect_execution(observe_current=observe_current),
        }
    finally:
        daemon._lock.release()


def shared_daemon() -> PobDaemon | None:
    """프로세스당 하나의 상주 PoB. 못 띄우면 `None` — 호출자가 1회성 경로로 되돌아간다.

    ⚠ **상주 여부가 곧 쓸 수 있느냐를 가른다.** 1회성 경로는 호출마다 luajit을
    새로 띄워 **1.82초**가 들고, 데몬은 **0.173초**다(실측 2026-08-11, 동일 스펙
    20회 평균 — 10.5배). `optimize_items`는 8슬롯 2라운드에 606회를 재므로
    18.4분 대 1.75분이 된다. 실제로 한 세션이 29분 46초를 기다리다 **정지로 판단해
    강제 종료**했다(백로그 #61) — 느린 것과 죽은 것을 구분할 수 없었다.
    """
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            daemon = None
            try:
                daemon = PobDaemon()
                daemon.start()
            except PobCommandTimeout:
                # A deadline is not a permanent missing-runtime result. The
                # owning command already attempted termination and reports it.
                if daemon is not None and daemon._broken:
                    _SHARED = daemon
                    atexit.register(daemon.close)
                raise
            except Exception:  # 스냅샷 없음·기동 실패 — 조용히 죽지 않고 되돌아간다
                if daemon is not None:
                    daemon.close()
                _SHARED = False
            else:
                _SHARED = daemon
                atexit.register(daemon.close)
    return _SHARED if isinstance(_SHARED, PobDaemon) else None
