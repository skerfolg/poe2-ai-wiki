"""설계 문서(design.md) 기계 가독 파서 — BUILD_DESIGN §4의 최소 계약 (D26).

파이프라인이 기대는 것은 §4가 전부다: 헤더 4줄, 고정 섹션 제목(포함 매칭),
수식 = 코드 블록, 장부 = 표, 번호 목록 = 순서 있는 큐. **이 이상의 스키마화
금지** — 설계 문서는 사람과 에이전트가 대화하며 쓰는 마크다운이다.

파서는 관대(lenient)하다: 섹션이 빠지면 실패가 아니라 `warnings`에 누락 경고를
남기고 해당 추출을 생략한다. 제약 검사기(D27)로의 전사(轉寫)는 에이전트 몫 —
여기는 원료(수식 블록·표·목록)를 위치 맥락과 함께 꺼내줄 뿐이다(AD-3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADER_KEYS = ("갱신일", "문서 버전", "상태", "운용 목표")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HEADER_LINE = re.compile(r"^[-*]\s*(갱신일|문서 버전|상태|운용 목표)\s*:\s*(.+)$")
_NUMBERED = re.compile(r"^\s*\d+\.\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


@dataclass(frozen=True)
class Table:
    """마크다운 표 하나 — 직전 헤딩이 위치 맥락."""

    heading: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Formula:
    """```text 코드 블록 하나(수식·작업식) — 직전 헤딩이 위치 맥락."""

    heading: str
    text: str


@dataclass(frozen=True)
class DesignDoc:
    updated: str | None
    version: str | None
    status: str | None
    goal: str | None
    headings: tuple[str, ...]
    has_constraints: bool  # `제약` 포함 제목 존재 여부 (없으면 warning)
    confirmed: tuple[str, ...]  # `확정` 섹션의 불릿
    tentative: tuple[str, ...]  # `잠정` 섹션의 불릿
    unverified: tuple[str, ...]  # `미검증` 섹션의 불릿 = 가설 목록 (P5 입력, D29)
    queue: tuple[str, ...]  # `다음 결정 순서`/`검증 항목` 번호 목록
    formulas: tuple[Formula, ...]
    tables: tuple[Table, ...]
    warnings: tuple[str, ...] = field(default=())


def _cells(line: str) -> tuple[str, ...]:
    m = _TABLE_ROW.match(line)
    return tuple(c.strip() for c in m.group(1).split("|")) if m else ()


def parse_design(text: str) -> DesignDoc:
    """design.md 원문 → DesignDoc. 실패 없음 — 누락은 warnings로."""
    lines = text.splitlines()
    header: dict[str, str] = {}
    headings: list[str] = []
    formulas: list[Formula] = []
    tables: list[Table] = []
    confirmed: list[str] = []
    tentative: list[str] = []
    unverified: list[str] = []
    queue: list[str] = []
    queue_heading = ""

    current = ""  # 현재 헤딩
    bucket: list[str] | None = None  # 3구분 수집 대상
    in_code = False
    code_buf: list[str] = []
    table_buf: list[tuple[str, ...]] = []

    def flush_table() -> None:
        nonlocal table_buf
        if len(table_buf) >= 2:
            tables.append(Table(heading=current, header=table_buf[0], rows=tuple(table_buf[2:])))
        table_buf = []

    for line in lines:
        if in_code:
            if line.strip().startswith("```"):
                in_code = False
                formulas.append(Formula(heading=current, text="\n".join(code_buf)))
                code_buf = []
            else:
                code_buf.append(line)
            continue
        if line.strip().startswith("```"):
            flush_table()
            in_code = True
            continue
        if _TABLE_ROW.match(line):
            if not (_TABLE_SEP.match(line) and not table_buf):
                table_buf.append(() if _TABLE_SEP.match(line) else _cells(line))
            continue
        flush_table()
        m = _HEADING.match(line)
        if m:
            current = m.group(2).strip()
            headings.append(current)
            # 3구분 버킷 전환 (포함 매칭 — 수준 무관, BUILD_DESIGN §4-2)
            if "미검증" in current:
                bucket = unverified
            elif "확정" in current:
                bucket = confirmed
            elif "잠정" in current:
                bucket = tentative
            else:
                bucket = None
            # 큐 섹션: `다음 결정 순서` 우선, 없으면 첫 `검증 항목`
            if "다음 결정 순서" in current or (
                "검증 항목" in current and queue_heading != "다음 결정 순서"
            ):
                if "다음 결정 순서" in current and "다음 결정 순서" not in queue_heading:
                    queue.clear()
                    queue_heading = "다음 결정 순서"
                elif not queue_heading:
                    queue_heading = current
            continue
        hm = _HEADER_LINE.match(line)
        if hm and hm.group(1) not in header:
            header[hm.group(1)] = hm.group(2).strip()
            continue
        if queue_heading and (
            ("다음 결정 순서" in current and queue_heading == "다음 결정 순서")
            or current == queue_heading
        ):
            nm = _NUMBERED.match(line)
            if nm:
                queue.append(nm.group(1).strip())
        if bucket is not None:
            bm = _BULLET.match(line)
            if bm:
                bucket.append(bm.group(1).strip())
    flush_table()

    warnings = [f"헤더 '{k}:' 누락" for k in _HEADER_KEYS if k not in header]
    has_constraints = any("제약" in h for h in headings)
    if not has_constraints:
        warnings.append("`제약` 섹션 없음 — 제약 검사 원료 없음 (BUILD_DESIGN §4-2 경고)")
    for name, got in (("확정", confirmed), ("잠정", tentative), ("미검증", unverified)):
        if not got:
            warnings.append(f"`{name}` 목록 없음 (3구분 미비, D29)")
    if not queue:
        warnings.append("`다음 결정 순서`/`검증 항목` 큐 없음")
    return DesignDoc(
        updated=header.get("갱신일"),
        version=header.get("문서 버전"),
        status=header.get("상태"),
        goal=header.get("운용 목표"),
        headings=tuple(headings),
        has_constraints=has_constraints,
        confirmed=tuple(confirmed),
        tentative=tuple(tentative),
        unverified=tuple(unverified),
        queue=tuple(queue),
        formulas=tuple(formulas),
        tables=tuple(tables),
        warnings=tuple(warnings),
    )
