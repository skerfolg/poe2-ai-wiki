"""P1b: fetch-plan 파싱 + fetcher 체크포인트·멱등·실패 기록 (네트워크 없음)."""

from __future__ import annotations

from pathlib import Path

import httpx

from pok.kb.ingest.fetch import load_status, run_fetch, status_report
from pok.kb.ingest.plan import build_plan, extract_items, extract_listed_count

LISTING_HTML = """
<html><body>
<h3>Skill Gems /3</h3>
<table>
 <tr><td><a href="/us/Spark" data-hover="/us/hover">Spark</a></td></tr>
 <tr><td><a href="/us/Fireball" data-hover="/us/hover">Fireball</a></td></tr>
 <tr><td><a href="/us/Nav_Page">개수 안 셈 (hover 없음)</a></td></tr>
</table>
<table>
 <tr><td><a href="/us/Ice_Nova" data-hover="/us/hover">Ice Nova</a></td></tr>
 <tr><td><a href="/us/Spark" data-hover="/us/hover">중복</a></td></tr>
</table>
<a href="/us/Outside_Table" data-hover="/us/hover">테이블 밖 — 제외</a>
</body></html>
"""


def test_extract_items_and_count() -> None:
    items = extract_items(LISTING_HTML)
    assert items == ["Fireball", "Ice_Nova", "Spark"], "hover+테이블 내부만, 중복 제거, 정렬"
    assert extract_listed_count(LISTING_HTML, "Skill Gems") == 3


def _mock_client(pages: dict[str, str | int]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        body = pages.get(request.url.path, 404)
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(200, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_plan_build_and_immutable(tmp_path: Path) -> None:
    client = _mock_client({"/us/Skill_Gems": LISTING_HTML})
    plan = build_plan("t", tmp_path, ["skill-gems"], client=client)
    assert plan["categories"]["skill-gems"]["planned_count"] == 3
    assert plan["categories"]["skill-gems"]["listed_count"] == 3
    assert (tmp_path / "poe2db/us/_listing_skill-gems.html").exists(), "목록 원시 = 증거 저장"

    # 확정된 plan은 불변 — 다시 호출해도 재수집하지 않고 그대로 반환
    plan2 = build_plan("t", tmp_path, ["skill-gems"], client=_mock_client({}))
    assert plan2 == plan


def _tiny_plan() -> dict[str, object]:
    return {
        "patch": "t",
        "source": "poe2db",
        "langs": ["us", "kr"],
        "categories": {"skill-gems": {"items": ["Spark", "Broken"]}},
    }


def test_fetch_checkpoint_idempotent_and_failure(tmp_path: Path) -> None:
    pages: dict[str, str | int] = {
        "/us/Spark": "<html>spark us</html>",
        "/kr/Spark": "<html>스파크</html>",
        "/us/Broken": 500,
        "/kr/Broken": 500,
    }
    plan = _tiny_plan()
    s1 = run_fetch(plan, tmp_path, rate_seconds=0, client=_mock_client(pages))
    assert (s1.fetched, s1.failed) == (2, 2)
    assert (tmp_path / "poe2db/us/Spark.html").exists()
    assert (tmp_path / "poe2db/kr/Spark.html").exists()
    st = load_status(tmp_path)
    assert st["us/Spark"]["state"] == "fetched" and st["us/Broken"]["state"] == "failed"

    # 재실행: fetched는 스킵(멱등), failed는 재시도 → 이번엔 성공하는 서버
    pages["/us/Broken"] = "<html>fixed</html>"
    pages["/kr/Broken"] = "<html>고침</html>"
    s2 = run_fetch(plan, tmp_path, rate_seconds=0, client=_mock_client(pages))
    assert (s2.fetched, s2.skipped, s2.failed) == (2, 2, 0)

    c = status_report(plan, tmp_path)
    assert c == {"planned": 4, "fetched": 4, "failed": 0, "pending": 0}


def test_fetch_limit_leaves_pending(tmp_path: Path) -> None:
    """--limit 중단 후 재실행이 이어서 수집 (PC 이동/분담 시나리오)."""
    pages: dict[str, str | int] = {
        f"/{lang}/{n}": f"<html>{lang}/{n}</html>"
        for lang in ("us", "kr")
        for n in ("Spark", "Broken")
    }
    plan = _tiny_plan()
    s1 = run_fetch(plan, tmp_path, rate_seconds=0, limit=1, client=_mock_client(pages))
    assert s1.fetched == 1 and s1.remaining == 3
    s2 = run_fetch(plan, tmp_path, rate_seconds=0, client=_mock_client(pages))
    assert s2.fetched == 3 and s2.skipped == 1
