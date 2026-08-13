"""스킬은 **등록되지 않으면 존재하지 않는다** (2026-08-13).

이 레포의 스킬은 두 파일이 한 쌍이다:

    skills/<name>/AGENTS.md            정본 절차 (사람·에이전트가 읽는 것)
    .claude/skills/<name>/SKILL.md     등록 shim (frontmatter의 name·description)

shim이 없으면 세션의 스킬 목록에 **뜨지 않는다** — 절차를 다 써 놓고도 아무도 못 쓴다.
실측 2026-08-13: `skills/ladder-corpus/`가 그 상태였다. 래더 수집 절차가 있는데도
목록에 없어서, 다른 PC에 수집을 지시할 때 절차를 **손으로 다시 적어야 했다**.

문서에 "shim도 만들 것"이라고 적는 방식은 이 레포에서 실패가 증명됐다(철칙 5) —
그래서 여기서 잠근다.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _skill_dirs() -> list[Path]:
    return sorted(p for p in (_ROOT / "skills").iterdir() if p.is_dir())


def test_모든_스킬이_등록_shim을_가진다() -> None:
    missing = [
        d.name
        for d in _skill_dirs()
        if not (_ROOT / ".claude" / "skills" / d.name / "SKILL.md").is_file()
    ]
    assert not missing, (
        f"등록 shim이 없는 스킬: {missing} — `.claude/skills/<name>/SKILL.md`를 만들 것. "
        "없으면 세션 목록에 뜨지 않아 절차가 있는데도 아무도 못 쓴다"
    )


def test_shim이_이름과_설명을_밝힌다() -> None:
    """`description`이 없으면 세션이 **언제 쓰는 스킬인지** 알 수 없어 안 부른다."""
    for d in _skill_dirs():
        shim = _ROOT / ".claude" / "skills" / d.name / "SKILL.md"
        text = shim.read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{d.name}: frontmatter가 없다"
        head = text.split("---", 2)[1]
        assert f"name: {d.name}" in head, f"{d.name}: frontmatter의 name이 디렉터리와 다르다"
        desc = next((ln for ln in head.splitlines() if ln.startswith("description:")), "")
        assert len(desc) > 40, f"{d.name}: description이 없거나 너무 짧다 — 호출 판단이 안 된다"


def test_shim이_정본_지침을_가리킨다() -> None:
    """shim에 절차를 복사해 두면 **두 개의 진실**이 생긴다 — 가리키기만 한다."""
    for d in _skill_dirs():
        shim = _ROOT / ".claude" / "skills" / d.name / "SKILL.md"
        body = shim.read_text(encoding="utf-8").split("---", 2)[2]
        assert f"skills/{d.name}/AGENTS.md" in body, (
            f"{d.name}: shim이 정본 AGENTS.md를 가리키지 않는다"
        )
