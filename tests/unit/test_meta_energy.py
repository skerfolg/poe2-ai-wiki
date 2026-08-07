"""B-9 메타 젬 에너지 규칙 — 문구는 전량, Power형만 구조화 (A안)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pok.kb.ingest.meta_energy import apply_meta_energy, parse_energy

RAW = Path("artifacts/ingest-raw/0.5.4b/poe2db/us")

# 원시 스냅샷(poe2db HTML)은 gitignore되는 파생물이라 CI에 없다 — 재수집은 네트워크가
# 필요하고 패치판에 묶여 있어 CI에서 확보할 수 없다. 없으면 skip한다(통합 테스트가
# LuaJIT·PoB 스냅샷에 쓰는 규약과 같은 방식). 실측 2026-08-07: 가드가 없어 CI에서
# FileNotFoundError로 터졌다.
pytestmark = pytest.mark.skipif(
    not RAW.is_dir(), reason="artifacts/ingest-raw 스냅샷 없음 (수집 후에만 검증 가능)"
)


def _html(name: str) -> str:
    return (RAW / f"{name}.html").read_text(encoding="utf-8", errors="replace")


def test_coefficient_differs_per_gem() -> None:
    """THOR 문서의 `3 x Power`는 틀렸다 — 젬마다 1·2·3·10·30이다."""
    assert parse_energy(_html("Cast_on_Ignite"))["energy_per_power"] == {"Ignite": 2.0}
    assert parse_energy(_html("Cast_on_Critical"))["energy_per_power"] == {"Critically": 1.0}
    ailment = parse_energy(_html("Cast_on_Elemental_Ailment"))["energy_per_power"]
    assert ailment == {"Freeze": 10.0, "Ignite": 1.0, "Shock": 1.0}


def test_max_energy_clause_is_captured_whole() -> None:
    """`0.1 seconds`의 소수점에서 잘리면 안 된다 — 마침표로 문장을 자른 실패."""
    parsed = parse_energy(_html("Cast_on_Ignite"))
    assert parsed["max_energy_per_100ms"] == 10.0
    assert any("0.1 seconds of base cast time" in s for s in parsed["energy_stats"]), (
        "문구가 소수점에서 잘렸다"
    )


def test_non_power_gems_keep_their_text_with_numbers() -> None:
    """구조화 못 해도 **정보는 남긴다** — A안의 요점.

    다만 수치 없는 요약("gains Energy when you Block")은 정보가 아니라 담지 않는다.
    """
    block = parse_energy(_html("Cast_on_Block"))
    assert "energy_per_power" not in block, "Power형이 아니다"
    assert any("Gains 25 Energy when you Block" in s for s in block["energy_stats"])
    assert all(any(c.isdigit() for c in s) for s in block["energy_stats"])

    feral = parse_energy(_html("Feral_Invocation"))
    assert feral["max_energy_flat"] == 500.0, "최대 에너지가 고정인 젬"


def test_coverage_report_exposes_what_is_not_structured() -> None:
    """커버리지를 드러낸다 — 이 수가 움직이면 형태가 바뀐 신호다.

    분모는 **태그 보유 젬**으로 고정한다. 파싱이 실패해 분모까지 줄면 커버리지가
    좋아 보이는 착시가 난다(0/0 = 100%가 되는 종류의 거짓말).
    """
    report = apply_meta_energy(Path("artifacts/ingest-raw/0.5.4b"), write=False)
    assert report["total_energy_gems"] > report["structured"] > 0
    assert report["unstructured"], "구조화 못 한 것을 조용히 숨기지 않는다"
    assert report["structured"] + len(report["unstructured"]) == report["total_energy_gems"]
