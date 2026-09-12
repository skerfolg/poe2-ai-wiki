"""`text=True`인 subprocess 호출은 **인코딩을 코드에서 고정한다** (#166).

`text=True`만 쓰면 파이썬은 **로케일 코드페이지**로 디코딩한다 — 한국어 Windows면
`cp949`다. `common/stdio.py`가 출력(encode) 쪽에 두고 있는 것과 **같은 함정의 입력
(decode) 쪽**이고, 같은 이유로 환경변수(`PYTHONUTF8`)로는 막을 수 없다: 인터프리터
기동 전에 정해져야 해서 프로세스 안에서 못 켜고, 세션 설정에 넣어도 그 설정을 읽는
호스트만 덮는다(사용자가 직접 친 명령·다른 호스트가 띄운 MCP 서버는 그대로 노출).

⛔ **이 계열은 조용하다**(형태 ①·⑩). 예외가 리더 스레드에서 터지므로 호출부는
`IndexError`만 보고, 대개 그 위에 있는 `except`가 그것을 **빈 값으로 삼킨다**.
실측 2026-09-12(한국어 Windows, `PYTHONUTF8` 없이): `mcp/server.py`의 `_git_head`가
커밋 제목(한글 + em dash)에서 깨져 `("", "")`를 냈고, `_LOADED_COMMIT`과
`source_commit`이 **둘 다 빈 문자열**이 되어 `stale`이 **영원히 False**가 됐다 —
「소스 고쳤으니 재시작하라」는 신호가 통째로 죽은 채 초록이었다.

⛔ **CI는 이것을 못 잡는다.** 러너(ubuntu·macOS)와 Windows 러너의 MSYS2 셸이 전부
UTF-8이라 같은 코드가 거기선 통과한다. 그래서 강제 지점을 **로케일과 무관한 정적
검사**로 둔다(철칙 5) — 이 시험은 실행 결과가 아니라 **호출의 모양**을 본다.

#120이 `pob/runner.py` 한 자리에 같은 고정을 넣었지만 규율이 문서·주석에만 있어
나머지 7자리는 그대로였다(형태 ⑦ — 관문을 자리마다 달면 안 단 자리가 뚫린다).
"""

from __future__ import annotations

import ast
from pathlib import Path

from pok.common.paths import project_root

# 이 레포는 subprocess를 `import subprocess` 후 `subprocess.run(...)` 형태로만 쓴다.
# `from subprocess import run`이 생기면 이 시험이 **조용히 놓치므로** 그것도 막는다.
_SPAWNERS = frozenset({"run", "Popen", "check_output", "call", "check_call"})
_TEXT_KWARGS = frozenset({"text", "universal_newlines"})
_SCANNED = ("src/pok", "tests", "scripts")


def _py_files(root: Path) -> list[Path]:
    return [p for base in _SCANNED for p in sorted((root / base).rglob("*.py"))]


def _is_subprocess_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr in _SPAWNERS
    )


def test_text_모드_호출은_전부_encoding을_명시한다() -> None:
    root = project_root()
    offenders: list[str] = []
    checked = 0

    for path in _py_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_subprocess_call(node):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            if not (kwargs & _TEXT_KWARGS):
                continue  # bytes 모드 — 디코딩이 없으니 로케일도 없다
            checked += 1
            if "encoding" not in kwargs:
                rel = path.relative_to(root).as_posix()
                offenders.append(f"{rel}:{node.lineno}")

    assert checked, "text=True인 subprocess 호출을 하나도 못 찾았다 — 이 시험이 낡았다"
    assert not offenders, (
        '로케일 코드페이지로 디코딩한다(#166). `encoding="utf-8"`을 명시할 것 — '
        f"근거는 이 파일의 docstring: {offenders}"
    )


def test_subprocess를_이름으로_직접_들여오지_않는다() -> None:
    """`from subprocess import run`이면 위 시험이 **조용히 통과한다**.

    검사를 우회하는 문법이 하나뿐이므로 그 문법 자체를 막는다 — 검사가 부정확하면
    우회를 부르고, 우회는 규율을 갉는다(BACKLOG §0 머리말).
    """
    root = project_root()
    offenders = [
        f"{path.relative_to(root).as_posix()}:{node.lineno}"
        for path in _py_files(root)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and node.module == "subprocess"
        and any(alias.name in _SPAWNERS for alias in node.names)
    ]
    assert not offenders, f"`import subprocess` 후 `subprocess.run(...)`으로 쓸 것: {offenders}"
