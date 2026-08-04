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
# 가설의 판정 조건 표지 — `주장 — 증명: 조건` / `주장 · 판정: 조건`
_PROOF = re.compile(r"\s*[—·\-]\s*(?:\*\*)?(?:증명|판정|검증)(?:\*\*)?\s*:\s*(.+)$")


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
class Hypothesis:
    """미검증 가설 하나 — 주장과 **무엇을 보면 판정되는가**.

    가설만 적고 판정 조건을 안 적으면 큐에 쌓이기만 하고 검증이 실행되지 않는다.
    실제로 v6·v7의 미검증 목록이 그 상태로 멈춰 있었다. 조건이 붙어야 가설이
    **실행 가능한 테스트**가 된다 (THOR 문서 §5에서 배움, 2026-08-04).

    본문 표기: `- 주장 — 증명: 무엇을 관측하면 참/거짓이 갈리는가`
    """

    claim: str
    proof: str = ""  # 비어 있으면 "실행 불가 가설" — 파서가 경고한다

    @property
    def actionable(self) -> bool:
        """다음 검증 단계가 정의됐는가 (= 열린 질문으로 큐에 올릴 수 있는가)."""
        return bool(self.proof.strip())


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
    unverified: tuple[Hypothesis, ...]  # `미검증` 섹션 = 가설 목록 (P5 입력, D29)
    queue: tuple[str, ...]  # `다음 결정 순서`/`검증 항목` 번호 목록
    gates: tuple[str, ...]  # `결정 관문` 번호 목록 — 하나라도 실패하면 컨셉 재검토
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
    unverified: list[Hypothesis] = []
    queue: list[str] = []
    gates: list[str] = []
    queue_heading = ""
    in_gates = False

    current = ""  # 현재 헤딩
    bucket: str | None = None  # 3구분 수집 대상 ("확정"|"잠정"|"미검증")
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
                bucket = "미검증"
            elif "확정" in current:
                bucket = "확정"
            elif "잠정" in current:
                bucket = "잠정"
            else:
                bucket = None
            # 결정 관문 — 하나라도 실패하면 컨셉을 계속 팔지 재검토한다
            in_gates = "결정 관문" in current or "계속 조건" in current
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
        if in_gates:
            gm = _NUMBERED.match(line)
            if gm:
                gates.append(gm.group(1).strip())
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
                text = bm.group(1).strip()
                if bucket == "미검증":
                    # 판정 조건을 주장에서 떼어낸다 — 조건이 없으면 proof=""
                    pm = _PROOF.search(text)
                    unverified.append(
                        Hypothesis(_PROOF.sub("", text).strip(), pm.group(1).strip() if pm else "")
                    )
                elif bucket == "확정":
                    confirmed.append(text)
                else:
                    tentative.append(text)
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
    # 판정 조건 없는 가설은 큐에 쌓이기만 하고 검증이 실행되지 않는다 (v6·v7이 그랬다)
    blind = [h.claim for h in unverified if not h.actionable]
    if blind:
        warnings.append(
            f"판정 조건 없는 가설 {len(blind)}건 — `— 증명: …`을 붙여야 검증이 실행 가능하다"
            f" (예: {blind[0][:40]})"
        )
    if not gates:
        warnings.append("`결정 관문` 없음 — 컨셉을 언제 접을지 기준이 없다 (BUILD_DESIGN §4-5)")
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
        gates=tuple(gates),
        formulas=tuple(formulas),
        tables=tuple(tables),
        warnings=tuple(warnings),
    )
