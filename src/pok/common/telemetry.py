"""도구 호출 이력 — 결함을 사람이 옮겨 적지 않아도 되게 (무개입 테스트 보조).

무개입 빌드 테스트에서는 구조 세션이 생성 과정을 지켜볼 수 없다. 그러면 "무엇이
막혔나"를 사람이 손으로 옮겨 적어야 하는데, 그건 확장되지 않고 빠뜨리기도 쉽다.
도구가 스스로 남기면 결과 통보가 스크린샷이 아니라 데이터가 된다.

**세 가지를 남긴다.** 예외만 남기면 정작 값진 것을 놓친다:

  · `error`  — 예외가 났다. 대개 진짜 버그다.
  · `failed` — 도구가 `ok: False`를 돌려줬다(입력 부족·파일 없음 등).
  · `empty`  — **성공했는데 결과가 비었다.** 이게 가장 값지다.

`empty`가 값진 이유: 조회 0건은 실패가 아니라 **신호**다. KB 갭일 수도, 표기
오류일 수도 있는데 둘은 대응이 정반대다. 실제로 B-1이 그 사례였다 — `+N to
Spirit`을 `+N to maximum Spirit`으로 조회해 0건이 났고, 그걸 KB 갭으로 단정했다가
아니었음이 드러났다. 0건이 쌓이면 그 패턴이 보인다.

출력은 `var/tool-calls.ndjson`(파생물·gitignore). 기록 실패가 도구를 망가뜨리지
않도록 **모든 오류를 삼킨다** — 관측이 본 작업을 방해하면 안 된다.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pok.common.paths import var_dir

_MAX_ARG = 120  # 인자 요약 길이 — 재현에 필요한 만큼만


def log_path(root: Path | None = None) -> Path:
    return var_dir(root) / "tool-calls.ndjson"


def _brief(value: Any) -> Any:
    """인자를 재현 가능한 선에서 줄인다 (원문 전체는 필요 없다)."""
    if isinstance(value, str):
        return value if len(value) <= _MAX_ARG else value[:_MAX_ARG] + "…"
    if isinstance(value, list):
        return [_brief(v) for v in value[:5]] + (["…"] if len(value) > 5 else [])
    if isinstance(value, dict):
        return {k: _brief(v) for k, v in list(value.items())[:8]}
    return value


def classify(result: Any) -> str:
    """반환값에서 결과 종류를 읽는다 — 판단이 아니라 형태 판별이다."""
    if isinstance(result, list):
        return "empty" if not result else "ok"
    if isinstance(result, dict):
        if result.get("ok") is False:
            return "failed"
        # 히트 목록을 담는 도구들: 목록이 전부 비면 조회 0건이다
        buckets = [v for k, v in result.items() if isinstance(v, list) and k != "warnings"]
        if buckets and all(not v for v in buckets):
            return "empty"
    return "ok"


def record(
    tool: str,
    args: dict[str, Any],
    *,
    outcome: str,
    detail: str = "",
    root: Path | None = None,
) -> None:
    """호출 1건을 append 한다. **절대 예외를 밖으로 내지 않는다.**"""
    if os.environ.get("POK_TELEMETRY") == "off":
        return
    try:
        path = log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": tool,
            "outcome": outcome,
            "args": _brief({k: v for k, v in args.items() if v is not None}),
        }
        if detail:
            row["detail"] = detail[:400]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # 관측이 본 작업을 방해하면 안 된다 — 모든 오류를 삼킨다
        pass


def read(root: Path | None = None) -> list[dict[str, Any]]:
    path = log_path(root)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def summarize(root: Path | None = None) -> str:
    """결과 통보에 붙일 요약 — 도구별 성적표."""
    rows = read(root)
    if not rows:
        return "도구 호출 이력 없음"
    by_tool: dict[str, Counter[str]] = {}
    for r in rows:
        by_tool.setdefault(str(r.get("tool")), Counter())[str(r.get("outcome"))] += 1

    lines = [f"도구 호출 {len(rows)}건 ({rows[0].get('at', '?')} ~ {rows[-1].get('at', '?')})", ""]
    lines.append(f"{'도구':24s} {'ok':>5s} {'empty':>6s} {'failed':>7s} {'error':>6s}")
    for tool, counts in sorted(by_tool.items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(
            f"{tool[:24]:24s} {counts['ok']:5d} {counts['empty']:6d}"
            f" {counts['failed']:7d} {counts['error']:6d}"
        )
    problems = [r for r in rows if r.get("outcome") != "ok"]
    if problems:
        lines += ["", f"— 문제 호출 {len(problems)}건 (최근 12) —"]
        for r in problems[-12:]:
            args = json.dumps(r.get("args", {}), ensure_ascii=False)[:70]
            lines.append(f"  [{r.get('outcome'):6s}] {r.get('tool')} {args}")
            if r.get("detail"):
                lines.append(f"           {str(r['detail'])[:80]}")
    return "\n".join(lines)


if __name__ == "__main__":  # python -m pok.common.telemetry
    print(summarize())
