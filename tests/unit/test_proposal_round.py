"""M5 라운드 계약 — 배치가 사람 상한에 갇히지 않게 하는 강제 지점들.

사람이 루프의 동력이면 ①노가다 ②탐색이 사람 머릿속 상한에 갇힘 ③사용량에 기대면
빈약, 셋이 무너진다(사용자 지적 2026-08-20). 여기서 잠그는 것은 그 셋을 막는 규율:
유형 할당량(가로등 방지)·중복 제외(예산 재탕 방지)·갭 가시성.
"""

from __future__ import annotations

import json
from pathlib import Path

from pok.engine.proposal import UNVERIFIABLE, validate
from pok.engine.proposal_flow import expand, save
from pok.engine.proposal_round import TYPE_QUOTA, build_brief, digest
from pok.kb.store import load

_store = load()


def _saved(tmp: Path, title: str, mechanism: str, route: str, **extra) -> Path:
    doc = {
        "title": title,
        "mechanism": mechanism,
        "premise": ["X"],
        "route": route,
        "bundle": ["a"],
        **extra,
    }
    p = validate(doc)
    return save("9-9", p, expand(p, _store), proposed_by={"model": "t"}, base=tmp)


def test_브리프가_유형_할당량을_요구한다() -> None:
    """⛔ 할당량이 없으면 잴 수 있는 조각(스태킹)으로 쏠린다 — 창의의 중심 축이
    통째로 빠져도 아무도 모른다(가로등 밑 열쇠 찾기)."""
    brief = build_brief("9-9", base=Path("/nonexistent"))
    assert brief["quota"] == TYPE_QUOTA
    assert "트리거 연쇄" in brief["quota"] and "상태이상·DoT" in brief["quota"]
    assert "가로등" in brief["why_quota"]


def test_브리프가_이미_낸_제안을_제외_목록으로_준다(tmp_path: Path) -> None:
    """LLM은 이전 라운드를 모른다 — 안 주면 같은 제안이 다시 나와 예산을 재탕한다."""
    _saved(tmp_path, "이미 낸 것", "스태킹", "pob-delta")
    brief = build_brief("9-9", base=tmp_path)
    assert "이미 낸 것" in brief["already_proposed"]
    assert brief["prior_counts"]["스태킹"] == 1


def test_다이제스트가_할당_미달을_밝힌다(tmp_path: Path) -> None:
    """안 밝히면 「고르게 봤다」로 읽힌다."""
    _saved(tmp_path, "스태킹 하나", "스태킹", "pob-delta")
    got = digest("9-9", base=tmp_path)
    assert got["quota_shortfall"]["트리거 연쇄"] == TYPE_QUOTA["트리거 연쇄"]
    assert got["quota_shortfall"]["스태킹"] == TYPE_QUOTA["스태킹"] - 1


def test_갭은_순위가_아니라_갭_목록으로_간다(tmp_path: Path) -> None:
    """측정 못 한 제안이 순위에서 조용히 빠지면 「없던 제안」이 된다 —
    갭 라벨의 누적이 다음 측정기의 우선순위 데이터다."""
    _saved(
        tmp_path,
        "못 재는 것",
        "상태이상·DoT",
        UNVERIFIABLE,
        route_gap="상태이상 중첩을 잴 도구가 없다",
    )
    got = digest("9-9", base=tmp_path)
    assert got["tool_gaps"] and got["tool_gaps"][0]["title"] == "못 재는 것"
    assert all(r["title"] != "못 재는 것" for r in got["ranked"])


def test_다이제스트는_채택_권고가_아니라고_말한다(tmp_path: Path) -> None:
    """⛔ 순위는 측정값이다 — 인게임 성립·조작 난이도는 PoB가 못 잰다(철칙 4)."""
    got = digest("9-9", base=tmp_path)
    assert "채택 권고가 아니다" in got["note"]


def test_측정된_제안은_다시_안_잰다(tmp_path: Path) -> None:
    """재개 가능해야 배치가 성립한다(M3 캠페인과 같은 규약)."""
    from pok.engine.proposal_flow import record_measurement

    path = _saved(tmp_path, "측정됨", "스태킹", "pob-delta")
    record_measurement(path, {"bundle": 0, "deltas": {"CombinedDPS": 5.0}, "pob_commit": "x"})
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert len(doc["measurements"]) == 1
    got = digest("9-9", base=tmp_path)
    assert got["ranked"][0]["best_dps_delta"] == 5.0
