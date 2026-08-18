"""전직 식별자 내보내기 — 신형식만 내면 전직이 빈칸으로 읽힌다.

실측 사고 2026-08-18: `to_xml`이 `classInternalId`+`ascendancyInternalId`만 써서
PoB가 전직을 못 잡았다. 전직 9노드가 **일반 패시브로 세어져** 123짜리 트리가
132/123으로 떴고 `parse_pob`도 `ascendancy=""`를 냈다. 표시 계층은 구형식만
읽는다(`BuildListHelpers.lua:53`) — PoB 자신은 저장할 때 다섯을 전부 쓴다
(`PassiveSpec.lua:253-264`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pok.pob.buildxml import (
    ASCENDANCY_ID,
    CLASS_INTERNAL_ID,
    CLASS_LEGACY_ID,
    BuildSpec,
    to_xml,
)

POB_TREE = Path("external/pob/5d173cb/src/TreeData/0_5/tree.lua")


def _spec(class_name: str = "Witch", ascendancy: str = "Witch2") -> BuildSpec:
    return BuildSpec(class_name=class_name, ascendancy=ascendancy, level=97, tree_nodes=(8415,))


def test_emits_both_formats() -> None:
    xml = to_xml(_spec())
    build = re.search(r"<Build [^>]*>", xml)
    spec = re.search(r"<Spec [^>]*", xml)
    assert build and spec
    assert 'ascendClassName="Blood Mage"' in build.group(0)
    for attr in ("classId=", "ascendClassId=", "classInternalId=", "ascendancyInternalId="):
        assert attr in spec.group(0), f"{attr} 누락 — 구·신 형식을 모두 내야 한다"
    assert 'ascendClassId="2"' in spec.group(0)
    assert 'classId="6"' in spec.group(0)  # Witch의 구형식 id는 6 (integerId 1과 다르다)


def test_legacy_and_internal_ids_differ_for_witch() -> None:
    """둘을 같은 수로 착각하면 조용히 다른 클래스가 된다."""
    assert CLASS_LEGACY_ID["Witch"] == 6
    assert CLASS_INTERNAL_ID["Witch"] == 1


def test_unknown_ascendancy_rejected() -> None:
    with pytest.raises(ValueError, match="알 수 없는 전직 코드"):
        to_xml(_spec(ascendancy="Witch9"))


def test_trailing_digit_is_not_the_id() -> None:
    """ "Witch3b"는 4번이다 — 끝자리 유추를 막는 회귀 표식."""
    assert ASCENDANCY_ID["Witch3b"][0] == 4
    assert ASCENDANCY_ID["Witch3"][0] == 3


@pytest.mark.skipif(not POB_TREE.exists(), reason="고정 PoB 트리 데이터 없음")
def test_table_matches_pinned_tree_data() -> None:
    """표가 트리 데이터와 어긋나면 여기서 막힌다 (문서가 아니라 강제 지점)."""
    text = POB_TREE.read_text(encoding="utf-8", errors="replace")
    seen: dict[str, tuple[int, str]] = {}
    classes: dict[str, int] = {}
    for cm in re.finditer(r"\[(\d+)\]=\{\n\t\t\tascendancies=\{", text):
        tail = text[cm.end() : cm.end() + 20000]
        im = re.search(r'\n\t\t\tintegerId=(\d+),\n\t\t\tname="([^"]+)"', tail)
        if not im:
            continue
        classes[im.group(2)] = int(cm.group(1))
        for m in re.finditer(
            r'\[(\d+)\]=\{.*?internalId="([^"]+)",\n\t\t\t\t\tname="([^"]+)"',
            tail[: im.start()],
            re.S,
        ):
            seen[m.group(2)] = (int(m.group(1)), m.group(3))
    assert seen, "트리 데이터에서 전직을 하나도 못 읽었다 — 파싱 가정이 깨졌다"
    assert seen == ASCENDANCY_ID
    assert classes == CLASS_LEGACY_ID
