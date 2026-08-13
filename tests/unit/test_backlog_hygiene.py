"""백로그 규율의 **강제 지점** — 문서에만 있던 규칙을 여기서 잠근다 (철칙 5).

v0.3에서 백로그에 넣은 규칙들(번호는 이 파일이 발급 · `(이 PR)` 금지 · 해결분 본문
삭제 · 큐 표 갱신)이 전부 **문서 규율**이었다. 이 프로젝트는 문서 규율이 **인용까지
하고도 어겨진** 기록을 갖고 있다(61배 격차 · 룬 소켓 6칸 공란 · 4회 반복 위반).
그래서 감지 가능한 것만 골라 테스트로 옮긴다 — 감지 불가한 것은 §0에서 **「없음
(문서뿐)」이라고 밝히게** 하고, 그 표시 자체를 이 테스트가 강제한다.

여기서 잡는 것은 **형식**이지 내용이 아니다. "실측을 적었는가"는 기계가 못 읽지만
"상태 줄이 있는가 · 번호가 겹치는가 · 큐 표와 본문이 어긋나는가"는 읽는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_DOC = Path(__file__).resolve().parents[2] / "docs" / "BACKLOG.md"
_ROOT = _DOC.parents[1]


@pytest.fixture(scope="module")
def text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str | None) -> str:
    body = text.split(start, 1)[1]
    return body.split(end, 1)[0] if end else body


def _entry_ids(section: str) -> list[str]:
    return re.findall(r"(?m)^### (#[\w-]+)", section)


def test_ids_are_unique(text: str) -> None:
    """같은 번호가 두 항목에 붙으면 **참조가 깨진다** — 실제로 `#17`이 그랬다."""
    ids = _entry_ids(text)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"번호 중복: {dupes} — 나중 것을 재발급할 것"


def test_next_number_is_ahead_of_every_used_number(text: str) -> None:
    """다음 발급 번호가 뒤쳐지면 **다음 세션이 겹치는 번호를 뽑는다.**"""
    nxt = int(re.search(r"다음 발급 번호는 \*\*#(\d+)\*\*", text).group(1))  # type: ignore[union-attr]
    # 본문의 `#53`은 PR 번호일 수 있다 — **항목 번호만** 센다(제목 · 표 첫 칸).
    used = [int(n) for n in re.findall(r"(?m)^(?:### |\| \*{0,2})#(\d+)", text)]
    assert nxt > max(used), f"다음 발급 #{nxt} <= 이미 쓰인 최대 #{max(used)}"


def test_pr_numbers_are_never_written_as_this_pr(text: str) -> None:
    """「(이 PR)」은 머지되면 **무엇을 가리키는지 알 수 없다**(v0.2에서 17곳 정정)."""
    stray = [
        line.strip()
        for line in text.splitlines()
        # 금지 규칙 문장 자신은 「」로 인용하므로 제외한다
        if "(이 PR)" in line and "「(이 PR)」" not in line
    ]
    assert not stray, f"PR 번호를 실제 번호로 되돌려 적을 것: {stray}"


def test_open_entries_carry_a_status_line(text: str) -> None:
    """상태가 없으면 다음 세션이 **처음부터 다시 조사한다**(기재 규약)."""
    section = _section(text, "## 1. 열린 결함", "## 2. ")
    missing = [
        block.splitlines()[0][4:]
        for block in re.split(r"(?m)^(?=### )", section)[1:]
        if "- **상태**" not in block
    ]
    assert not missing, f"상태 줄 없는 항목: {missing}"


def test_resolved_entries_are_not_left_in_the_open_section(text: str) -> None:
    """해결·기각분 **본문**은 지운다 — 이력은 §4 한 줄과 git·PR에 있다.

    안 지우면 큐가 이력으로 부푼다(실측: 1,228줄 중 열린 항목은 11건이었다).
    """
    section = _section(text, "## 1. 열린 결함", "## 2. ")
    stale = re.findall(r"(?m)^### (#[\w-]+)[^\n]*\n- \*\*상태\*\*: \*\*?(?:해결|기각)", section)
    assert not stale, f"§4로 옮기고 본문을 지울 것: {stale}"


def test_queue_table_matches_the_open_entries(text: str) -> None:
    """큐 표와 본문이 어긋나면 **이미 고친 것을 다시 파거나** 낡은 정보로 판단한다.

    이 파일의 존재 이유가 「어느 세션이든 이 파일 하나로 이어받는다」이므로, 표만 보고
    판단하는 세션이 정상이다 — 표가 본문과 다르면 그 세션이 틀린 결정을 한다.
    """
    # ⚠ 끝 표식을 `---`로 두면 **표 구분줄(`|---|`)에서 잘린다** — 만들다 걸린 함정이다
    queue = _section(text, "### 현재 열려 있는 것", "## 기재 규약")
    # ⚠ **표 행의 첫 칸만** 센다. 절 전체를 훑으면 산문의 참조("#59는 판정받아 반영했다")도
    # 항목으로 오인해 실패한다 — 실제로 두 번 걸렸고 그때마다 문서 쪽을 비틀어 피했다.
    # 검사가 부정확하면 우회를 부르고, 우회는 규율을 갉는다.
    listed = {
        f"#{m.group(1)}"
        for line in queue.splitlines()
        if line.startswith("|")
        for cell in [line.split("|")[1] if len(line.split("|")) > 1 else ""]
        if (m := re.search(r"#(\d+(?:-[a-z])?)", cell))
    }
    entries = set(_entry_ids(_section(text, "## 1. 열린 결함", "## 2. ")))
    assert not (entries - listed), f"본문에 있는데 큐 표에 없다: {sorted(entries - listed)}"
    assert not (listed - entries), f"큐 표에 있는데 본문이 없다: {sorted(listed - entries)}"


def test_overturned_report_count_matches_the_table(text: str) -> None:
    """「N건이 틀렸다」와 표 행 수는 **손으로 맞춰야 해서 어긋난다** — 3번 고쳤다."""
    section = _section(text, "## 3. 검증으로 뒤집힌 보고", "## 4. ")
    claimed = int(re.search(r"보고 (\d+)건이 틀렸다", section).group(1))  # type: ignore[union-attr]
    rows = [ln for ln in section.splitlines() if ln.startswith("|")]
    assert claimed == len(rows) - 2, f"주장 {claimed}건 vs 표 {len(rows) - 2}행"


def test_every_recurring_pattern_names_its_enforcement_point(text: str) -> None:
    """§0의 각 형태는 **어디서 강제되는가**를 밝힌다 (철칙 5의 자기적용).

    형태를 적어 두는 것만으로는 다음 세션이 그걸 대조하리라는 보장이 없다. 강제 지점을
    적게 하면 ①있는 것은 심볼이 사라질 때 이 테스트가 깨지고 ②없는 것은 **「문서뿐」
    이라고 눈에 보이게** 남는다 — 강제가 있다고 착각하지 않는 것이 절반이다.
    """
    section = _section(text, "## 0. 반복되는 형태", "## 1. 열린 결함")
    blocks = re.split(r"(?m)^(?=### )", section)[1:]
    assert len(blocks) >= 6, "형태가 사라졌다"
    for block in blocks:
        head = block.splitlines()[0][4:]
        line = re.search(r"(?m)^\*\*강제\*\*: (.+)$", block)
        assert line, f"「{head}」에 **강제**: 줄이 없다 — 도구로 갈지 문서뿐인지 밝힐 것"
        body = "\n".join(block.split("**강제**: ", 1)[1].split("\n\n", 1)[0].splitlines())
        refs = re.findall(r"`([\w/.]+\.py)(?:::(\w+))?`", body)
        if not refs:
            assert "없음(문서뿐)" in body, f"「{head}」의 강제 표기를 못 읽었다: {body}"
            continue
        for path, symbol in refs:
            target = _ROOT / path
            # 경로만 적힌 것도 검사한다 — 실제로 없는 테스트 파일을 가리키고 있었다
            assert target.exists(), f"「{head}」가 가리키는 {path}가 없다"
            if not symbol:
                continue
            source = target.read_text(encoding="utf-8")
            assert re.search(rf"(?m)^\s*(?:def|class) {symbol}\b|^{symbol}\b", source), (
                f"「{head}」의 강제 지점 {path}::{symbol}이 사라졌다 — 규율이 비었다"
            )


def test_정본_문서가_빌드_산출물_인스턴스를_근거로_걸지_않는다() -> None:
    """`artifacts/builds/`는 gitignore이고 **보존 대상도 아니다**(사용자 판정 2026-08-13:
    "빌드 산출물은 프로젝트 차원에서 가져가야 할 정보가 아니다. 문서가 산출물을 정확히
    링크하고 있으면 그게 문제다").

    특정 인스턴스를 근거 경로로 걸면 그 PC를 떠나는 순간 **근거가 사라진다** — 실제로
    53회분이 어느 repo에도 없는 채로 문서 4곳이 그것을 가리키고 있었다. 근거는 **값을
    본문에 옮겨** 적는다. 구조 설명(`<id>` 플레이스홀더)은 허용한다.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    pattern = re.compile(r"artifacts/builds/(?!<)([^\s`)/]+)")
    offenders: list[str] = []
    for folder in ("docs", "skills", ".claude/skills"):
        for path in (root / folder).rglob("*.md"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in pattern.finditer(line):
                    # 디렉터리 자체를 가리키는 것(`artifacts/builds/` 뒤 경로 없음)은 구조 설명이다
                    offenders.append(f"{path.relative_to(root)}:{lineno} → {match.group(0)}")
    assert not offenders, (
        "정본 문서가 빌드 산출물 **인스턴스**를 근거로 걸었다 — 그 PC를 떠나면 근거가 "
        "사라진다. 값을 본문에 옮겨 적을 것:\n  " + "\n  ".join(offenders)
    )
