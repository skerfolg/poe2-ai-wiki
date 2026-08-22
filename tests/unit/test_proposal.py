"""M5 제안 계약 (확정 설계 2026-08-20).

세 필드(메커니즘·전제·검증 경로)를 **검증기로** 강제한다 — 문서에 적으면 안
지켜진다(철칙 5). 특히 「검증 경로 없음」을 조용한 배제가 아니라 **라벨**로 남기는
것이 이 계약의 존재 이유다: 창의의 중심 축(트리거·DoT·플레이 패턴)이 측정 커버리지
밖일 때, 배제하면 잴 수 있는 조각으로 제안이 쏠린다(가로등 밑 열쇠 찾기).
"""

from __future__ import annotations

import pytest

from pok.engine.proposal import (
    UNVERIFIABLE,
    VERIFICATION_ROUTES,
    ProposalError,
    validate,
)

_BASE = {
    "title": "저주 이중화",
    "mechanism": "저주",
    "premise": ["Whispers of Doom", "Despair"],
    "route": "pob-delta",
    "bundle": ["Whispers of Doom 채택", "Despair 젬 추가"],
}


def test_세_필드가_빠지면_문장으로_거부한다() -> None:
    """LLM이 읽고 고칠 수 있어야 한다 — 필드명만 던지면 같은 실수가 반복된다."""
    for key in ("mechanism", "premise", "route", "bundle"):
        doc = {**_BASE, key: None}
        with pytest.raises(ProposalError, match="계약"):
            validate(doc)


def test_모르는_경로는_가짜_검증이라_거부한다() -> None:
    with pytest.raises(ProposalError, match="가짜 경로"):
        validate({**_BASE, "route": "vibes"})


def test_갭은_거부가_아니라_라벨이다() -> None:
    """⛔ 검증 못 하는 창의를 버리면 안 된다 — 라벨 누적이 다음 측정기의 우선순위
    데이터다(형태 ①의 반대)."""
    got = validate(
        {
            **_BASE,
            "route": UNVERIFIABLE,
            "route_gap": "상태이상 중첩 상호작용을 잴 도구가 없다",
        }
    )
    assert not got.verifiable
    assert any("도구 갭" in n for n in got.notes)
    assert any("측정 없이 채택될 수 없다" in n for n in got.notes)


def test_갭_사유_없는_unverifiable은_거부한다() -> None:
    """사유 없는 갭 라벨은 조용한 갭과 같다."""
    with pytest.raises(ProposalError, match="route_gap"):
        validate({**_BASE, "route": UNVERIFIABLE})


def test_통과한_제안에는_검증_한계가_붙는다() -> None:
    """도구 이름만 들면 측정이 만능으로 읽힌다(철칙 4) — 한계가 같이 간다."""
    got = validate({**_BASE, "route": "dot-axes"})
    assert got.verifiable
    assert any("#44" in n for n in got.notes)


def test_등록부의_경로마다_한계가_있다() -> None:
    """한계 없는 경로 등록을 막는다 — 새 경로를 추가하는 세션이 걸리는 자리."""
    for name, spec in VERIFICATION_ROUTES.items():
        assert spec.get("measure"), f"{name}: 무엇으로 재는지 없다"
        assert spec.get("limits"), f"{name}: 알려진 한계가 없다 — 만능으로 읽힌다"
