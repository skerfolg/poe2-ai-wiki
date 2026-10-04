"""스킬은 **등록되지 않으면 존재하지 않는다** (2026-08-13).

이 레포의 스킬은 공통 절차와 클라이언트별 등록 진입점으로 구성한다:

    skills/<name>/AGENTS.md            정본 절차 (사람·에이전트가 읽는 것)
    .claude/skills/<name>/SKILL.md     등록 shim (frontmatter의 name·description)
    .agents/skills/<name>/SKILL.md     Codex 등록 shim (같은 정본 절차 참조)

shim이 없으면 세션의 스킬 목록에 **뜨지 않는다** — 절차를 다 써 놓고도 아무도 못 쓴다.
실측 2026-08-13: `skills/ladder-corpus/`가 그 상태였다. 래더 수집 절차가 있는데도
목록에 없어서, 다른 PC에 수집을 지시할 때 절차를 **손으로 다시 적어야 했다**.

문서에 "shim도 만들 것"이라고 적는 방식은 이 레포에서 실패가 증명됐다(철칙 5) —
그래서 여기서 잠근다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CLIENT_DIRS = (".claude", ".agents")


def _skill_dirs() -> list[Path]:
    return sorted(p for p in (_ROOT / "skills").iterdir() if p.is_dir())


@pytest.mark.parametrize("client_dir", _CLIENT_DIRS, ids=("claude", "codex"))
def test_모든_스킬이_등록_shim을_가진다(client_dir: str) -> None:
    missing = [
        d.name
        for d in _skill_dirs()
        if not (_ROOT / client_dir / "skills" / d.name / "SKILL.md").is_file()
    ]
    assert not missing, (
        f"등록 shim이 없는 스킬: {missing} — `{client_dir}/skills/<name>/SKILL.md`를 만들 것. "
        "없으면 세션 목록에 뜨지 않아 절차가 있는데도 아무도 못 쓴다"
    )


@pytest.mark.parametrize("client_dir", _CLIENT_DIRS, ids=("claude", "codex"))
def test_shim이_이름과_설명을_밝힌다(client_dir: str) -> None:
    """`description`이 없으면 세션이 **언제 쓰는 스킬인지** 알 수 없어 안 부른다."""
    for d in _skill_dirs():
        shim = _ROOT / client_dir / "skills" / d.name / "SKILL.md"
        text = shim.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{d.name}: frontmatter가 없다"
        head = text.split("---", 2)[1]
        name = re.search(r"^name: (.+)$", head, re.MULTILINE)
        assert name and name[1] == d.name, f"{d.name}: frontmatter의 name이 디렉터리와 다르다"
        desc = re.search(r"^description: (.+)$", head, re.MULTILINE)
        assert desc and len(desc[1]) > 40, (
            f"{d.name}: description이 없거나 너무 짧다 — 호출 판단이 안 된다"
        )


@pytest.mark.parametrize("client_dir", _CLIENT_DIRS, ids=("claude", "codex"))
def test_shim이_정본_지침을_가리킨다(client_dir: str) -> None:
    """shim에 절차를 복사해 두면 **두 개의 진실**이 생긴다 — 가리키기만 한다."""
    for d in _skill_dirs():
        shim = _ROOT / client_dir / "skills" / d.name / "SKILL.md"
        body = shim.read_text(encoding="utf-8").split("---", 2)[2]
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", body)
        targets = {(shim.parent / link).resolve() for link in links}
        assert (d / "AGENTS.md").resolve() in targets, (
            f"{d.name}: shim이 정본 AGENTS.md를 가리키지 않는다"
        )
        assert (_ROOT / "skills" / "AGENTS.md").resolve() in targets, (
            f"{d.name}: 공통 실행 환경으로 가는 참조가 없다"
        )
        assert all(target.is_file() for target in targets), f"{shim}: 깨진 문서 링크"
