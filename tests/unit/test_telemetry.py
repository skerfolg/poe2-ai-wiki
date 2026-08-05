"""도구 호출 이력 — 무개입 테스트에서 결함 보고가 사람 기억에 의존하지 않게.

관측 장치의 제1원칙: **본 작업을 절대 방해하지 않는다.** 이 파일의 절반은 그걸 지킨다.
"""

from __future__ import annotations

from pathlib import Path

from pok.common import telemetry


def test_빈_목록은_조회_0건_신호다() -> None:
    """0건은 실패가 아니라 신호다 — KB 갭이거나 표기 오류(B-1 실측)."""
    assert telemetry.classify([]) == "empty"
    assert telemetry.classify([{"id": "x"}]) == "ok"


def test_명시적_실패_신호를_읽는다() -> None:
    assert telemetry.classify({"ok": False, "reason": "설계 문서 없음"}) == "failed"
    assert telemetry.classify({"ok": True}) == "ok"


def test_목록이_전부_빈_dict도_조회_0건이다() -> None:
    """search류는 dict 안에 목록을 담는다 — 겉이 dict라고 ok가 아니다."""
    assert telemetry.classify({"hypotheses": [], "pairs": []}) == "empty"
    assert telemetry.classify({"pairs": [], "summary": [{"x": 1}]}) == "ok"


def test_경고만_있는_결과는_빈_것이_아니다() -> None:
    """warnings는 진단 부산물이지 조회 결과가 아니다."""
    assert telemetry.classify({"warnings": [], "version": "v6"}) == "ok"


def test_기록과_요약(tmp_path: Path) -> None:
    telemetry.record("search_kb", {"query": "없는것"}, outcome="empty", root=tmp_path)
    telemetry.record("get_entry", {"id": "x"}, outcome="error", detail="KeyError", root=tmp_path)
    rows = telemetry.read(tmp_path)
    assert [r["tool"] for r in rows] == ["search_kb", "get_entry"]
    assert rows[0]["args"] == {"query": "없는것"}
    summary = telemetry.summarize(tmp_path)
    assert "search_kb" in summary and "KeyError" in summary


def test_긴_인자는_줄여_기록한다(tmp_path: Path) -> None:
    """빌드 코드 같은 거대 인자로 로그가 부풀면 안 된다."""
    telemetry.record("parse_pob", {"code": "x" * 5000}, outcome="error", root=tmp_path)
    assert len(telemetry.read(tmp_path)[0]["args"]["code"]) < 200


def test_None_인자는_기록하지_않는다(tmp_path: Path) -> None:
    telemetry.record("search_kb", {"query": "a", "tags": None}, outcome="empty", root=tmp_path)
    assert telemetry.read(tmp_path)[0]["args"] == {"query": "a"}


def test_기록_실패가_본_작업을_막지_않는다(tmp_path: Path) -> None:
    """디스크가 막혀도 도구는 돌아야 한다 — 관측이 본 작업을 방해하면 안 된다."""
    blocked = tmp_path / "blocked"
    blocked.write_text("파일이라 디렉터리를 못 만든다", encoding="utf-8")
    telemetry.record("search_kb", {"q": "x"}, outcome="empty", root=blocked)  # 예외 없이 통과


def test_이력_없으면_그렇게_말한다(tmp_path: Path) -> None:
    assert "없음" in telemetry.summarize(tmp_path)


def test_비어있는게_정상인_필드를_0건으로_보지_않는다() -> None:
    """`pruned_nodes`가 비었다는 건 **좋은 소식**이지 조회 실패가 아니다.

    실측 2026-08-05: compute_pob 성공 6건이 전부 "empty"로 기록됐다 — 반환 dict의
    유일한 목록이 `pruned_nodes`(비연결 노드)였고 그게 비어 있었기 때문이다.
    빈 목록을 세는 대신 **내용이 하나라도 채워졌는가**로 본다.
    """
    computed = {"stats": {"CombinedDPS": 1200.0}, "tree_legal": True, "pruned_nodes": []}
    assert telemetry.classify(computed) == "ok"
    assert telemetry.classify({"legal": True, "errors": [], "lines": []}) == "ok"
    # 반대로 내용이 통째로 비면 여전히 0건이다
    assert telemetry.classify({"stats": {}, "pruned_nodes": []}) == "empty"


def test_실패_사유를_기록한다() -> None:
    """도구는 사유를 돌려주는데 기록하는 쪽이 버리면 원인이 사라진다."""
    assert telemetry.detail_of({"ok": False, "reason": "젬 티어 범위 초과"}) == "젬 티어 범위 초과"
    assert "접사" in telemetry.detail_of({"legal": False, "errors": ["접사 수 초과"]})
    assert telemetry.detail_of([{"empty": True, "why": ["한글 질의"]}]) == "한글 질의"
    assert telemetry.detail_of({"stats": {}}) == ""
