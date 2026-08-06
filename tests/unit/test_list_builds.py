"""버전업/백지 관문의 재료 — 기존 빌드 열거 (사용자 지시 2026-08-06).

"매번 백지 상태로 작업하라고 지시하기 번거롭다 — 자료 조사 전에 작업 중인 빌드가
있으면 버전업할지 백지로 갈지 강제로 물어보게 하라." 이 도구가 그 질문의 재료이고,
강제는 SKILL.md 0단계가 한다.
"""

from __future__ import annotations

from pathlib import Path

from pok.artifacts.design import list_builds


def _make_build(root: Path, build_id: str, updated: str, status: str) -> None:
    d = root / "artifacts" / "builds" / build_id
    d.mkdir(parents=True)
    (d / "design.md").write_text(
        f"# 테스트\n\n- 갱신일: {updated}\n- 문서 버전: v1\n- 상태: {status}\n- 운용 목표: 1버튼\n",
        encoding="utf-8",
    )


def test_lists_builds_newest_first(tmp_path: Path) -> None:
    """최근 작업이 위에 와야 "이어받을 후보"가 바로 보인다."""
    _make_build(tmp_path, "20260801-old", "2026-08-01", "완료")
    _make_build(tmp_path, "20260806-new", "2026-08-06", "조립 전")
    builds = list_builds(root=tmp_path)
    assert [b.build_id for b in builds] == ["20260806-new", "20260801-old"]
    assert builds[0].status == "조립 전"


def test_dirs_without_design_are_listed_not_hidden(tmp_path: Path) -> None:
    """design.md 없는 산출물(티어 조립본)도 목록에는 나온다 — 숨기면 계보가 안 보인다."""
    _make_build(tmp_path, "20260806-with", "2026-08-06", "진행")
    (tmp_path / "artifacts" / "builds" / "20260805-tier-only").mkdir(parents=True)
    builds = list_builds(root=tmp_path)
    assert len(builds) == 2
    assert sum(1 for b in builds if b.has_design) == 1


def test_empty_dir_returns_empty(tmp_path: Path) -> None:
    """빌드가 없으면 빈 목록 — 관문은 "백지 신규로 진행"이 된다."""
    assert list_builds(root=tmp_path) == ()


def test_mcp_note_directs_the_gate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """note가 관문 지시를 담는다 — 도구 결과만 보고도 다음 행동이 정해지게."""
    import pok.artifacts.design as design_mod
    from pok.artifacts.design import BuildListing
    from pok.mcp.tools.constraints import list_builds as mcp_list

    one = BuildListing("20260806-x", "2026-08-06", "v1", "진행", "1버튼", True)
    monkeypatch.setattr(design_mod, "list_builds", lambda root=None: (one,))
    result = mcp_list()
    assert result["design_count"] == 1
    assert "묻기 전에는" in result["note"], "관문 지시가 note에 있어야 한다"

    monkeypatch.setattr(design_mod, "list_builds", lambda root=None: ())
    empty = mcp_list()
    assert empty["design_count"] == 0
    assert "백지 신규로 진행" in empty["note"], "빌드가 없으면 물을 필요가 없다"
