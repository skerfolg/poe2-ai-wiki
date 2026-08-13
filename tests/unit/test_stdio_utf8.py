"""진입점의 stdout UTF-8 고정을 잠근다 (Windows cp949 대응).

이건 「글자가 깨진다」는 미관 문제가 아니라 **죽는** 문제다. Windows 기본
stdout은 cp949인데 이 레포는 em dash(`—`)를 사용자 출력과 레코드에 상시 쓴다
— `engine/ladder_aggregate.py`가 `sample.basis`에 무조건 넣고, 그 레코드가
CLI stdout으로 나간다. cp949는 `—`를 인코딩하지 못한다(실측 2026-08-13).

환경변수(`PYTHONUTF8`)로는 못 막는다 — 인터프리터 기동 전에 정해져야 해서
프로세스 안에서 켤 수 없고, 세션 설정에 넣어도 그 설정을 읽는 호스트만 덮는다.
그래서 강제 지점을 코드에 뒀고(철칙 5), **그게 조용히 빠지는 것**을 여기서 막는다.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from pok.common.paths import project_root
from pok.common.stdio import force_utf8_stdio


def _entry_points() -> list[Path]:
    """`python -m ...`으로 직접 실행되는 모듈 전부.

    목록을 박지 않고 훑는다 — 박아 두면 **새 진입점이 추가될 때 조용히 빠진다**.
    """
    src = project_root() / "src" / "pok"
    found = set(src.rglob("__main__.py"))
    for path in src.rglob("*.py"):
        if '__name__ == "__main__"' in path.read_text(encoding="utf-8"):
            found.add(path)
    return sorted(found)


def test_진입점을_하나라도_찾는다() -> None:
    """훑기가 망가지면 아래 시험이 **공집합을 통과**해 버린다."""
    assert len(_entry_points()) >= 8


def test_모든_진입점이_stdio를_고정한다() -> None:
    """새 CLI를 추가하면서 이 호출을 빠뜨리면 여기서 걸린다."""
    missing = [
        p.relative_to(project_root()).as_posix()
        for p in _entry_points()
        if "force_utf8_stdio" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, f"진입점이 stdout을 고정하지 않는다 — Windows에서 죽는다: {missing}"


def test_cp949_스트림이_utf8로_바뀐다(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="cp949"))
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp949"))

    force_utf8_stdio()

    assert sys.stdout.encoding == "utf-8"
    assert sys.stderr.encoding == "utf-8"
    # 실제로 터졌던 문자열 그대로
    sys.stdout.write("poe.ninja 래더 PoB 실측 — 0-5/class-Blood_Mage 10벌")
    sys.stdout.flush()
    assert "—" in buf.getvalue().decode("utf-8")


def test_고정하지_않으면_실제로_죽는다() -> None:
    """이 시험이 없으면 위 시험이 무엇을 막고 있는지 알 수 없다."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    with pytest.raises(UnicodeEncodeError):
        stream.write("실측 — em dash")
        stream.flush()


def test_reconfigure가_없는_스트림에서도_죽지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytest capture 등 TextIOWrapper가 아닌 스트림이 실제로 들어온다."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    force_utf8_stdio()  # 예외 없이 통과하면 된다


def test_두_번_불러도_같다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp949"))
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp949"))
    force_utf8_stdio()
    force_utf8_stdio()
    assert sys.stdout.encoding == "utf-8"
