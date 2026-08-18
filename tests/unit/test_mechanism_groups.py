"""메커니즘 그룹 계약 (사용자 요구 2026-08-18).

노드 가치를 전 빌드로 뭉치면 조건부 노드가 0으로 희석된다. 「이 빌드가 무엇을 쓰나」로
갈라야 하는데, 그 목록이 **손으로 든 것이면 조용히 낡는다**.
"""

from __future__ import annotations

import json

from pok.common.paths import knowledge_dir
from pok.engine.mechanism_groups import OVERRIDES, derive, groups_of, load_overrides

_groups = derive()


def test_담체를_KB에서_파생한다() -> None:
    """⛔ 손으로 들지 않는다. 실측 2026-08-18: 손으로 든 `발동` 그룹에 젬이 **2종**
    이었는데 KB 태그로 뽑으니 **106종**이었다 — 치명타 시 시전·소환수 사망 시 시전이
    빠져 있었다. 사람이 드는 목록은 새 젬이 나올 때마다 조용히 낡는다."""
    trigger = _groups["발동"]
    assert len(trigger.gems) > 50, "태그 파생이 끊겼다"
    assert "Cast on Critical" in trigger.gems
    assert "Cast on Minion Death" in trigger.gems


def test_문구로만_잡히는_메커니즘도_있다() -> None:
    """충전 계열은 태그가 없다 — 효과 문구에 게임이 이름 붙인 고유명사로 잡는다."""
    for name in ("권능 충전", "격분 충전", "인내 충전"):
        assert _groups[name].gems, f"{name} 그룹이 비었다"


def test_빌드가_든_젬으로_그룹을_고른다() -> None:
    """조건을 고르는 자리 — 이게 되어야 「이 빌드에 이 노드가 의미 있나」를 판단한다."""
    got = groups_of(["Cast on Critical", "Despair"], _groups)
    assert "발동" in got and "저주" in got
    assert groups_of(["존재하지 않는 젬"], _groups) == set()


def test_예외_파일이_손질_지점이다() -> None:
    """「발견될 때마다 업데이트」가 일어나는 **유일한** 자리 — 파일이 있어야 한다."""
    path = knowledge_dir() / "ingest" / OVERRIDES
    assert path.exists(), "손질 지점이 없으면 갱신이 코드 수정이 된다"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert "groups" in doc and "why" in doc, "왜 있는지 없으면 전체 목록을 옮겨 적게 된다"
    assert isinstance(load_overrides(), dict)


def test_예외가_파생과_합쳐진다() -> None:
    """같은 이름이면 합쳐지고, 출처가 남는다 — 어디서 온 담체인지 되짚을 수 있어야 한다."""
    trigger = _groups["발동"]
    assert set(trigger.source) == set(trigger.gems)
    assert set(trigger.source.values()) <= {"태그", "문구", "예외"}
