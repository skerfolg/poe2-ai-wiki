"""CI는 **통합까지** 돌아야 한다 (2026-08-13, 사용자 지시로 기본값을 좁힌 뒤).

개발 중 기본 경로(`pytest`)는 단위만 돌도록 `testpaths`를 좁혔다 — 통합은 PoB를
부팅해 파일당 수 분, 전량 30분~1시간이라 매 수정마다 돌릴 수 없다.

⛔ 그 대가로 **CI가 인자 없이 `pytest`를 부르면 통합이 조용히 사라진다.** 커버리지가
줄었는데 초록불이 뜨는 상태이고, 이 레포가 반복해 데인 「조용한 0」의 CI 판이다.
그래서 워크플로가 경로를 명시하는지 기계가 지킨다.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def test_ci가_경로를_명시해_pytest를_부른다() -> None:
    text = _CI.read_text(encoding="utf-8")
    calls = re.findall(r"^\s*run:\s*(pytest.*)$", text, re.M)
    assert calls, "CI에서 pytest 호출을 못 찾았다 — 워크플로가 바뀌었나"
    bare = [c for c in calls if c.strip() == "pytest"]
    assert not bare, (
        "CI가 인자 없이 `pytest`를 부른다 — pyproject의 testpaths가 단위로 좁혀져 있어 "
        "**통합이 조용히 빠진다**. `pytest tests`처럼 경로를 명시할 것"
    )
    assert any("tests" in c for c in calls), f"CI 호출이 tests를 안 가리킨다: {calls}"


def test_기본_testpaths는_단위다() -> None:
    """개발 기본이 느려지면 기능 개발이 매 수정마다 멎는다(사용자 지시 2026-08-13).

    이 값을 넓히려면 위 CI 시험과 **함께** 봐야 한다 — 둘은 한 쌍이다.
    """
    toml = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^testpaths\s*=\s*\[(.*?)\]", toml, re.M)
    assert match, "testpaths 설정이 사라졌다"
    assert "tests/unit" in match.group(1), f"기본이 단위가 아니다: {match.group(1)}"
    assert '"tests"' not in match.group(1), "기본에 전체 tests가 들어가면 개발이 느려진다"
