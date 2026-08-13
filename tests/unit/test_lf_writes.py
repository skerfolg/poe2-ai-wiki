"""PoB로 넘기는 텍스트와 정본은 **LF로 쓴다** (2026-08-13, 윈도우 실패 추적).

파이썬 텍스트 모드는 윈도우에서 `\n`을 `\r\n`으로 바꾼다. 그런데 이 레포의 Lua
스크립트는 전부 `io.open(path, "rb")`(바이너리)로 읽어 **변환을 되돌리지 않는다** —
모드 줄 끝에 `\r`가 붙은 채 PoB `parseMod`에 들어간다.

실측: 윈도우에서 `tests/integration/test_item_parse_gaps.py`가 그 경로로 깨졌다.
파싱 실패가 늘어 「정본 표기가 낡았다」는 **가짜 경보**가 뜬다. 맥에서는 통과하므로
OS를 바꿔 보기 전까지 보이지 않는다.

정본(`knowledge/`)도 같다 — 윈도우에서 쓰면 전 파일이 CRLF가 되어 git diff가 번진다.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
# PoB에 넘기거나 정본을 쓰는 자리 — 여기서 CRLF가 새면 계산·정본이 갈린다.
_GUARDED = ("src/pok/pob", "src/pok/kb/store.py")
_WRITE = re.compile(r"""(?:write_text\(|\.open\(\s*["']w["']|fdopen\([^,]+,\s*["']w["'])""")


def _sources() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for target in _GUARDED:
        path = _ROOT / target
        out.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return out


def test_lua로_가는_텍스트는_LF로_쓴다() -> None:
    """`newline="\\n"` 없는 텍스트 쓰기를 막는다.

    ⚠ 호출이 여러 줄에 걸치므로 **줄 단위가 아니라 호출 단위**로 본다 — 줄만 보면
    `write_text(\\n    text,\\n    encoding=…)` 꼴을 통째로 놓친다.
    """
    offenders: list[str] = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for match in _WRITE.finditer(text):
            # 여는 괄호부터 짝이 맞는 닫는 괄호까지가 한 호출이다
            depth, end = 0, match.end()
            for i in range(text.index("(", match.start()), len(text)):
                depth += text[i] == "("
                depth -= text[i] == ")"
                if depth == 0:
                    end = i
                    break
            call = text[match.start() : end + 1]
            if "newline=" in call or "encoding=" not in call:
                continue  # 바이너리·비텍스트 쓰기는 대상이 아니다
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(_ROOT)}:{line}")
    assert not offenders, (
        '텍스트 모드 쓰기에 `newline="\\n"`가 없다 — 윈도우에서 CRLF가 섞여 PoB '
        "파싱과 정본이 갈린다:\n  " + "\n  ".join(offenders)
    )
